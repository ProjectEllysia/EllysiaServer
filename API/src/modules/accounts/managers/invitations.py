"""
Invitaciones a una organización.

Dos caminos, y la diferencia entre ellos es de consentimiento:

- **El correo ya tiene cuenta en Ellysia** → invitación pendiente y un enlace.
  Hasta que acepta no cambia absolutamente nada: ni organización, ni plan, ni
  derechos. Un tercero no puede cambiarle a alguien su contexto sin permiso.
- **El correo no tiene cuenta** → se crea, con contraseña aleatoria, y entra
  directa. Aquí no hay consentimiento que pedir porque no había nadie a quien
  pedírselo; el dueño de la organización responde por esa dirección.

Aceptar una invitación **nunca cambia el plan personal** de quien acepta. Los
derechos de la organización se suman a los suyos por ``max()``; si tenía un
Bronze pagado, sigue teniéndolo, y se lo lleva intacto si algún día se va.
"""

import logging
import secrets
from datetime import timedelta

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import utcnow_naive
from src.modules.tools.herald import EmailMessage, build_mailer, render_email

from ..exceptions import (
    AlreadyInOrganizationError,
    InvitationInvalidError,
    OrganizationNotAllowedError,
)
from ..model import Organization, OrganizationInvitation, OrganizationMember
from ..repositories import (
    OrganizationInvitationRepository,
    OrganizationMemberRepository,
    SubscriptionRepository,
)
from ..services.entitlements import is_effective
from ..services.limits import LimitKey
from ..services.ownership import get_owned_organization
from ..services.quotas import QuotaManager


logger = logging.getLogger(__name__)


def _assert_owner_can_grow(owner_user_id: int) -> None:
    """Exige que el dueño pueda sumar gente a su organización.

    Hace falta una suscripción vigente con la opción de organización activada.
    Sin ella, lo que la organización ya tiene sigue en pie, pero no crece.

    Args:
        owner_user_id: Primary key del usuario dueño de la organización.

    Raises:
        OrganizationNotAllowedError: la suscripción no está vigente o no
            incluye organizaciones.
    """
    subscription = build_repository(SubscriptionRepository).get_by_user(owner_user_id)
    if not is_effective(subscription, utcnow_naive()) or not subscription.organization_enabled:
        raise OrganizationNotAllowedError()

def _assert_not_in_any_organization(user_id: int) -> None:
    """Exige que el usuario no pertenezca todavía a ninguna organización.

    La comprobación es contra *cualquier* organización, no solo la que invita:
    ``OrganizationMember.user_id`` es ``UNIQUE``, así que un usuario que ya es
    miembro de otra haría fallar la inserción con un error de integridad en
    vez de con un error de dominio.

    Args:
        user_id: Primary key del usuario invitado.

    Raises:
        AlreadyInOrganizationError: el usuario ya es miembro de una organización.
    """
    if build_repository(OrganizationMemberRepository).get_by_user(user_id) is not None:
        raise AlreadyInOrganizationError()

def _send_invitation_email(
    email: str,
    name: str,
    organization_name: str,
    token: str,
    ttl_hours: int,
) -> None:
    """Envía el correo con el enlace para aceptar una invitación pendiente.

    Un fallo de envío se registra y no se propaga: la invitación ya está
    guardada y el dueño puede revocarla y volver a emitirla.

    Args:
        email: Dirección del destinatario.
        name: Nombre con el que se saluda al destinatario.
        organization_name: Nombre de la organización que invita.
        token: Token opaco en claro que viaja en el enlace de aceptación.
        ttl_hours: Horas de validez del enlace, que se muestran en el correo.
    """
    accept_url = f"{CR.general_config().public_url}/invitacion?token={token}"
    try:
        html, text = render_email(
            "org_invitation",
            recipient_name=name,
            organization_name=organization_name,
            accept_url=accept_url,
            ttl_hours=ttl_hours,
        )
        build_mailer("accounts").send(EmailMessage(
            to=email, to_name=name,
            subject=f"Te han invitado a {organization_name} en Ellysia",
            html_body=html, text_body=text,
        ))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(f"No se pudo enviar la invitacion a {email}: {exc}")

def _send_credentials_email(
    email: str,
    organization_name: str,
    username: str,
    password: str,
) -> None:
    """Envía las credenciales de una cuenta creada al invitar a un correo nuevo.

    Un fallo de envío se registra y no se propaga: la cuenta ya existe y su
    titular puede recuperar el acceso restableciendo la contraseña.

    Args:
        email: Dirección de la cuenta recién creada.
        organization_name: Nombre de la organización a la que se ha unido.
        username: Nombre de usuario asignado.
        password: Contraseña aleatoria en claro; se exige cambiarla al entrar.
    """
    login_url = f"{CR.general_config().public_url}/login"
    try:
        html, text = render_email(
            "org_credentials",
            organization_name=organization_name,
            username=username,
            password=password,
            login_url=login_url,
        )
        build_mailer("accounts").send(EmailMessage(
            to=email,
            subject=f"Tu cuenta en Ellysia ({organization_name})",
            html_body=html, text_body=text,
        ))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(f"No se pudieron enviar las credenciales a {email}: {exc}")

def _build_available_username(email: str) -> str:
    """Construye un nombre de usuario libre a partir de la parte local del correo.

    Se queda con los caracteres alfanuméricos en minúscula de lo que hay antes
    de la ``@`` y, si ese nombre ya está cogido, añade el primer sufijo
    numérico libre empezando por ``2``.

    Args:
        email: Dirección de correo de la que se deriva el nombre.

    Returns:
        str: Un nombre de usuario que no existe todavía; ``"usuario"`` (o
            ``"usuario<n>"``) si la parte local no tiene ningún carácter
            alfanumérico.
    """
    from src.modules.users.repositories import UserRepository

    base = "".join(char for char in email.split("@")[0].lower() if char.isalnum()) or "usuario"
    repo = build_repository(UserRepository)
    if not repo.username_exists(base):
        return base
    suffix = 2
    while repo.username_exists(f"{base}{suffix}"):
        suffix += 1
    return f"{base}{suffix}"

def _invite_existing_account(
    organization: Organization,
    owner_user_id: int,
    email: str,
    user_first_name: str,
) -> dict:
    """Emite una invitación pendiente para un correo que ya tiene cuenta.

    No cambia nada de la cuenta invitada hasta que acepta: solo guarda la
    invitación con el hash del token y envía el enlace.

    Args:
        organization: Organización que invita.
        owner_user_id: Primary key del dueño que emite la invitación.
        email: Correo invitado, ya normalizado.
        user_first_name: Nombre de la cuenta invitada, para el saludo del correo.

    Returns:
        dict: La invitación serializada con ``OrganizationInvitation.to_dict``.
    """
    from src.modules.users.services.secrets import generate_opaque_token, hash_opaque_token

    token = generate_opaque_token()
    ttl_hours = CR.registration_config().invitation_ttl_hours

    with UnitOfWork() as uow:
        invitation = OrganizationInvitationRepository(uow).save(OrganizationInvitation(
            organization_id=organization.id,
            email=email,
            token_hash=hash_opaque_token(token),
            status="pending",
            invited_by_user_id=owner_user_id,
            expires_at=utcnow_naive() + timedelta(hours=ttl_hours),
        ))
        payload = invitation.to_dict()

    _send_invitation_email(email, user_first_name, organization.name, token, ttl_hours)
    logger.info(f"Invitacion enviada a {email} para la organizacion {organization.id}")
    return payload

def _invite_new_account(
    organization: Organization,
    owner_user_id: int,
    email: str,
) -> dict:
    """Crea una cuenta para un correo sin registrar y la mete directamente en la organización.

    El correo se da por verificado: responde de él quien invita. La contraseña
    es aleatoria y se marca ``must_change_password``, porque ha viajado por
    correo y no sirve como secreto a largo plazo. La invitación se guarda ya
    aceptada, como registro de quién trajo la cuenta.

    Args:
        organization: Organización que invita.
        owner_user_id: Primary key del dueño que emite la invitación.
        email: Correo invitado, ya normalizado.

    Returns:
        dict: La invitación serializada con ``OrganizationInvitation.to_dict``.
    """
    from src.modules.users.managers import UserManager
    from src.modules.users.repositories import UserRepository
    from src.modules.users.services.secrets import hash_opaque_token

    password = secrets.token_urlsafe(12)
    username = _build_available_username(email)

    user = UserManager().sign_in_user(
        username=username,
        email=email,
        first_name=email.split("@")[0],
        last_name="",
        password=password,
        email_verified=True,
    )

    with UnitOfWork() as uow:
        user_repo = UserRepository(uow)
        created_user = user_repo.get_by_id(user.id)
        created_user.must_change_password = True
        user_repo.update(created_user)

        OrganizationMemberRepository(uow).save(OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            member_role="member",
            invited_by_user_id=owner_user_id,
        ))
        invitation = OrganizationInvitationRepository(uow).save(OrganizationInvitation(
            organization_id=organization.id,
            email=email,
            # No hay enlace que emitir: la cuenta ya está dentro. Se guarda
            # un hash irrepetible solo porque la columna es NOT NULL y
            # UNIQUE; no corresponde a ningún token vivo.
            token_hash=hash_opaque_token(secrets.token_urlsafe(32)),
            status="accepted",
            invited_by_user_id=owner_user_id,
            created_user_id=user.id,
            expires_at=utcnow_naive(),
            accepted_at=utcnow_naive(),
        ))
        payload = invitation.to_dict()

    _send_credentials_email(email, organization.name, username, password)
    logger.info(f"Cuenta creada por invitacion para {email} (organizacion {organization.id})")
    return payload


class InvitationManager:
    """Emisión, aceptación y revocación de invitaciones."""

    # ------------------------------------------------------------- emisión

    def invite(self, organization_id: int, owner_user_id: int, email: str) -> dict:
        """Invita a ``email`` a la organización.

        Raises:
            OrganizationNotAllowedError: la suscripción del dueño no está
                vigente o perdió el toggle. Mientras no paga no puede crecer
                — lo que ya tiene sigue en pie, pero no suma gente.
            AlreadyInOrganizationError: esa persona ya está en una organización.
            QuotaExceededError: se alcanzó el tope de miembros del plan.
        """
        # Import diferido: users → acheron → accounts cerraría un ciclo si se
        # importara al cargar el módulo.
        from src.modules.users.managers import UserManager

        organization = get_owned_organization(owner_user_id, organization_id)
        _assert_owner_can_grow(organization.owner_user_id)

        email = email.strip().lower()
        user = UserManager().get_user_by_email(email)

        if user is not None:
            _assert_not_in_any_organization(user.id)

        # El tope cuenta miembros MÁS invitaciones pendientes: si solo contara
        # miembros, se invitaría a 300 personas con un plan de 20 y bastaría con
        # que fueran aceptando.
        QuotaManager().consume(owner_user_id, LimitKey.ORGANIZATION_MEMBERS)

        if user is None:
            return _invite_new_account(organization, owner_user_id, email)
        return _invite_existing_account(organization, owner_user_id, email, user.first_name)

    def list_invitations(self, organization_id: int, owner_user_id: int) -> list[dict]:
        get_owned_organization(owner_user_id, organization_id)
        repo = build_repository(OrganizationInvitationRepository)
        return [invitation.to_dict() for invitation in repo.get_by_organization(organization_id)]

    def revoke(self, invitation_id: int, owner_user_id: int) -> None:
        """Retira una invitación sin responder. El enlace deja de valer."""
        with UnitOfWork() as uow:
            repo = OrganizationInvitationRepository(uow)
            invitation = repo.get_by_id(invitation_id)
            if invitation is None:
                raise InvitationInvalidError()
            get_owned_organization(owner_user_id, invitation.organization_id)

            # El hash se queda: la columna es NOT NULL y no hace falta borrarlo
            # para invalidar el enlace — accept() exige status == 'pending', que
            # es la única puerta.
            invitation.status = "revoked"
            repo.update(invitation)

    # ---------------------------------------------------------- aceptación

    def accept(self, token: str) -> dict:
        """Acepta una invitación y crea la pertenencia.

        Público: el token es la única identidad, igual que en el quiz de Aegis
        o en la verificación de correo. Quien pulsa el enlace puede no tener la
        sesión abierta.

        Lo que **no** hace: tocar el plan personal de quien acepta. Los derechos
        de la organización se resuelven al leer, sumándose por ``max()``.
        """
        from src.modules.users.managers import UserManager
        from src.modules.users.services.secrets import hash_opaque_token

        with UnitOfWork() as uow:
            repo = OrganizationInvitationRepository(uow)
            invitation = repo.get_by_token_hash(hash_opaque_token(token))

            if invitation is None or invitation.status != "pending":
                raise InvitationInvalidError()
            if utcnow_naive() >= invitation.expires_at:
                invitation.status = "expired"
                repo.update(invitation)
                raise InvitationInvalidError()

            user = UserManager().get_user_by_email(invitation.email)
            if user is None:
                raise InvitationInvalidError()
            # El id se copia ya: la entidad viene de la sesión de lectura, no
            # de la de este UnitOfWork.
            user_id = user.id
            _assert_not_in_any_organization(user_id)

            OrganizationMemberRepository(uow).save(OrganizationMember(
                organization_id=invitation.organization_id,
                user_id=user_id,
                member_role="member",
                invited_by_user_id=invitation.invited_by_user_id,
            ))
            invitation.status = "accepted"
            invitation.accepted_at = utcnow_naive()
            repo.update(invitation)

            logger.info(
                f"Usuario {user_id} acepto la invitacion a la organizacion "
                f"{invitation.organization_id}"
            )
            return {"organizationId": invitation.organization_id, "userId": user_id}
