"""
Lo que el módulo de cuentas hace con los datos de un usuario que se da de baja
o que pide su exportación.

Se da de alta en ``users.UserDataRegistry`` desde ``accounts/__init__.py``: así
es ``accounts`` —que conoce sus tablas— quien declara qué se borra, qué se
cuenta en el aviso previo y qué se exporta, y ``users`` no escribe SQL sobre
ellas.
"""

from src.modules.infrastructure import UnitOfWork

from ..repositories import (
    CompanyProfileRepository,
    OrganizationInvitationRepository,
    OrganizationMemberRepository,
    OrganizationRepository,
    SubscriptionRepository,
)


def purge_accounts_data(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Borra la suscripción, la pertenencia, el perfil de empresa y el rastro en invitaciones de un usuario.

    La **organización de la que es dueño se disuelve entera**: sus miembros se
    quedan sin ella. Es lo que hay que avisarle antes de pulsar el botón, y por
    eso ``UserManager.preview_deletion`` lo cuenta.

    Las referencias de «quién invitó» o «quién asignó el plan» se ponen a
    ``NULL`` en vez de borrar la fila: son rastro histórico de otra persona, no
    datos de quien se va. El orden importa (primero la organización con sus
    invitaciones y miembros, después las referencias sueltas y por último las
    filas propias) y es el que tenía el borrado antes de moverse aquí.

    Args:
        uow: Unidad de trabajo de la baja, con la sesión abierta.
        user_id: Usuario cuya cuenta se borra.

    Returns:
        dict[str, int]: Filas borradas por tabla (``OrganizationInvitation``,
            ``OrganizationMember``, ``Organization``, ``Subscription``,
            ``CompanyProfile``). Puede
            incluir ceros; quien suma los descarta.
    """
    organizations = OrganizationRepository(uow)
    invitations = OrganizationInvitationRepository(uow)
    members = OrganizationMemberRepository(uow)
    subscriptions = SubscriptionRepository(uow)

    counts = organizations.dissolve_owned_by(user_id)

    invitations.release_user(user_id)
    members.clear_inviter(user_id)
    subscriptions.clear_assigner(user_id)

    counts["OrganizationMember"] = members.delete_by_user(user_id)
    counts["Subscription"] = subscriptions.delete_by_user(user_id)
    counts["CompanyProfile"] = CompanyProfileRepository(uow).delete_by_user(user_id)
    return counts
