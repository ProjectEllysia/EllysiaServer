"""
Acceso a datos del módulo accounts.

Regla del proyecto, igual que en el resto de módulos: ``Repo(uow)`` para el
camino de escritura (dentro de un ``with UnitOfWork()``) y
``build_repository(Repo)`` para el de lectura.
"""

from typing import List, Optional

from src.modules.infrastructure import BaseRepository

from .model import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Plan,
    PlanLimit,
    Subscription,
)


class PlanRepository(BaseRepository[Plan]):
    """Acceso a datos del catálogo de planes."""

    _MODEL = Plan

    def get_by_code(self, code: str) -> Optional[Plan]:
        """El plan con ese código estable, o ``None`` si no existe.

        Args:
            code: Identificador estable del plan ("freemium", "bronze"...), no
                el id numérico.

        Returns:
            Optional[Plan]: El plan, o ``None`` si ningún plan lo usa.
        """
        return self.get_by_field("code", code)

    def get_default(self) -> Optional[Plan]:
        """El plan que reciben las cuentas sin suscripción vigente.

        Devuelve ``None`` si el catálogo no se ha sembrado; quien llama decide
        si eso es un ``DefaultPlanMissingError``. Un índice único parcial
        garantiza que no haya dos.
        """
        return (
            self._session.query(Plan)
            .filter(Plan.is_default.is_(True))
            .one_or_none()
        )

    def get_all_ordered(self) -> List[Plan]:
        """Todos los planes, ocultos incluidos, del más barato al más caro."""
        return self._session.query(Plan).order_by(Plan.rank.asc()).all()

    def get_public(self) -> List[Plan]:
        """Catálogo visible en la web, del más barato al más caro."""
        return (
            self._session.query(Plan)
            .filter(Plan.is_public.is_(True))
            .order_by(Plan.rank.asc())
            .all()
        )


class PlanLimitRepository(BaseRepository[PlanLimit]):
    """Acceso a datos de los topes de un plan."""

    _MODEL = PlanLimit

    def get_by_plan(self, plan_id: int) -> List[PlanLimit]:
        """Todos los topes declarados por un plan, en cualquier ámbito."""
        return self.get_children("plan_id", plan_id)

    def get_by_plan_and_scope(self, plan_id: int, scope: str) -> List[PlanLimit]:
        """Los topes de un plan restringidos a un ámbito concreto.

        Args:
            plan_id: Primary key del plan.
            scope: Ámbito del tope (p. ej. "user" u "organization").

        Returns:
            List[PlanLimit]: Los topes del plan que declaran ese ámbito;
                lista vacía si no hay ninguno.
        """
        return (
            self._session.query(PlanLimit)
            .filter(PlanLimit.plan_id == plan_id, PlanLimit.scope == scope)
            .all()
        )

    def get_one(self, plan_id: int, limit_key: str, scope: str) -> Optional[PlanLimit]:
        """Un tope concreto, o ``None`` si el plan no lo declara.

        ``None`` no significa "ilimitado": quien llama lo lee como 0 (no
        incluido). Es el fallo cerrado del catálogo.
        """
        return (
            self._session.query(PlanLimit)
            .filter(
                PlanLimit.plan_id == plan_id,
                PlanLimit.limit_key == limit_key,
                PlanLimit.scope == scope,
            )
            .one_or_none()
        )


class OrganizationRepository(BaseRepository[Organization]):
    """Acceso a datos de las organizaciones."""

    _MODEL = Organization

    def get_by_owner(self, user_id: int) -> Optional[Organization]:
        """La organización de la que ``user_id`` es dueño, o ``None``.

        Args:
            user_id: Primary key del usuario a comprobar como dueño.

        Returns:
            Optional[Organization]: La organización, o ``None`` si el usuario
                no posee ninguna. ``owner_user_id`` es ``UNIQUE``, así que a lo
                sumo hay una.
        """
        return self.get_by_field("owner_user_id", user_id)

    def get_by_slug(self, slug: str) -> Optional[Organization]:
        """La organización con ese slug, o ``None`` si no existe.

        Args:
            slug: Identificador legible y único de la organización.

        Returns:
            Optional[Organization]: La organización, o ``None`` si el slug no
                está en uso.
        """
        return self.get_by_field("slug", slug)

    def slug_exists(self, slug: str) -> bool:
        """Indica si el slug ya está en uso por alguna organización.

        Args:
            slug: Slug a comprobar.

        Returns:
            bool: ``True`` si ya existe una organización con ese slug.
        """
        return self.exists("slug", slug)

    def is_owned_by(self, organization_id: int, user_id: int) -> bool:
        """Indica si ``user_id`` es el dueño de la organización ``organization_id``.

        Comprobación ligera de propiedad: solo consulta si la fila existe con
        ese dueño, sin cargarla entera. A diferencia de
        ``ownership.get_owned_organization`` (que devuelve la organización o
        lanza ``OrganizationNotFoundError``), esta es para el caso en que solo
        hace falta el booleano. Espejo de
        ``OrganizationMemberRepository.is_member``, que hace la misma
        comprobación para la pertenencia en vez de para la propiedad.

        Args:
            organization_id: Primary key de la organización.
            user_id: Primary key del usuario a comprobar como dueño.

        Returns:
            bool: ``True`` si la organización existe y su dueño es
                ``user_id``; ``False`` en cualquier otro caso, incluida una
                organización inexistente.
        """
        return (
            self._session.query(Organization.id)
            .filter(
                Organization.id == organization_id,
                Organization.owner_user_id == user_id,
            )
            .first()
            is not None
        )

    def dissolve_owned_by(self, user_id: int) -> dict[str, int]:
        """Disuelve la organización de la que ``user_id`` es dueño, con sus miembros e invitaciones.

        Se borran primero las invitaciones y las filas de pertenencia, y al final
        la organización: las dos primeras tienen clave ajena hacia ella. Los
        usuarios que eran miembros conservan su cuenta y sus datos; solo pierden
        la pertenencia.

        Args:
            user_id: Usuario dueño de la organización que se disuelve.

        Returns:
            dict[str, int]: Filas borradas, con las claves ``OrganizationInvitation``,
                ``OrganizationMember`` y ``Organization``. Vacío si no es dueño de
                ninguna.
        """
        organization = self.get_by_owner(user_id)
        if organization is None:
            return {}

        counts = {
            "OrganizationInvitation": self._session.query(OrganizationInvitation).filter(
                OrganizationInvitation.organization_id == organization.id
            ).delete(synchronize_session=False),
            "OrganizationMember": self._session.query(OrganizationMember).filter(
                OrganizationMember.organization_id == organization.id
            ).delete(synchronize_session=False),
        }
        self._session.delete(organization)
        counts["Organization"] = 1
        return counts


class OrganizationMemberRepository(BaseRepository[OrganizationMember]):
    """Acceso a datos de la pertenencia a una organización."""

    _MODEL = OrganizationMember

    def get_by_user(self, user_id: int) -> Optional[OrganizationMember]:
        """La pertenencia de un usuario, o ``None``.

        Devuelve una y no una lista porque ``user_id`` es ``UNIQUE``: un
        usuario pertenece a lo sumo a una organización, y lo impone la base de
        datos.
        """
        return self.get_by_field("user_id", user_id)

    def get_by_organization(self, organization_id: int) -> List[OrganizationMember]:
        """Todos los miembros de la organización, del más antiguo al más reciente."""
        return (
            self._session.query(OrganizationMember)
            .filter(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.joined_at.asc())
            .all()
        )

    def user_ids_of(self, organization_id: int) -> List[int]:
        """Ids de los miembros. Es lo que necesitan los contadores de la bolsa
        común, que suman las existencias de todos."""
        rows = (
            self._session.query(OrganizationMember.user_id)
            .filter(OrganizationMember.organization_id == organization_id)
            .all()
        )
        return [row[0] for row in rows]

    def count_members(self, organization_id: int) -> int:
        """Número de miembros de la organización, dueño incluido."""
        return (
            self._session.query(OrganizationMember)
            .filter(OrganizationMember.organization_id == organization_id)
            .count()
        )

    def is_member(self, organization_id: int, user_id: int) -> bool:
        """Indica si ``user_id`` pertenece a la organización ``organization_id``.

        El dueño es miembro de su propia organización con
        ``member_role='owner'`` (ver ``OrganizationMember``), así que esta
        comprobación también es ``True`` para él sin necesitar un caso
        especial. Espejo de ``OrganizationRepository.is_owned_by``, que hace
        la misma comprobación ligera para la propiedad en vez de para la
        pertenencia.

        Args:
            organization_id: Primary key de la organización.
            user_id: Primary key del usuario a comprobar como miembro.

        Returns:
            bool: ``True`` si existe una fila de pertenencia para ese par;
                ``False`` en caso contrario.
        """
        return (
            self._session.query(OrganizationMember.user_id)
            .filter(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
            .first()
            is not None
        )

    def clear_inviter(self, user_id: int) -> None:
        """Quita a ``user_id`` como invitador de las filas de pertenencia que lo citan.

        Es rastro histórico de otra persona, no un dato de quien se va: la fila
        se conserva con ``invited_by_user_id`` a ``NULL``.

        Args:
            user_id: Usuario que dejó de existir como invitador.
        """
        self._session.query(OrganizationMember).filter(
            OrganizationMember.invited_by_user_id == user_id
        ).update({"invited_by_user_id": None}, synchronize_session=False)

    def delete_by_user(self, user_id: int) -> int:
        """Borra la pertenencia del usuario a una organización.

        Args:
            user_id: Usuario cuya fila de pertenencia se borra.

        Returns:
            int: Filas borradas (``0`` o ``1``: un usuario pertenece a lo sumo a una).
        """
        return self._session.query(OrganizationMember).filter(
            OrganizationMember.user_id == user_id
        ).delete(synchronize_session=False)


class OrganizationInvitationRepository(BaseRepository[OrganizationInvitation]):
    """Acceso a datos de las invitaciones."""

    _MODEL = OrganizationInvitation

    def get_by_token_hash(self, token_hash: str) -> Optional[OrganizationInvitation]:
        """La invitación cuyo token (ya hasheado) coincide, o ``None``.

        Args:
            token_hash: Hash del token de invitación, tal como se guarda en
                la columna (nunca el token en claro).

        Returns:
            Optional[OrganizationInvitation]: La invitación, o ``None`` si
                ningún hash coincide.
        """
        return self.get_by_field("token_hash", token_hash)

    def get_by_organization(self, organization_id: int) -> List[OrganizationInvitation]:
        """Todas las invitaciones de la organización, de la más reciente a la más antigua."""
        return (
            self._session.query(OrganizationInvitation)
            .filter(OrganizationInvitation.organization_id == organization_id)
            .order_by(OrganizationInvitation.created_at.desc())
            .all()
        )

    def get_pending_for_email(self, organization_id: int, email: str) -> Optional[OrganizationInvitation]:
        """La invitación pendiente de ese email en la organización, o ``None``.

        Args:
            organization_id: Primary key de la organización.
            email: Correo del invitado, tal como se guardó al invitar.

        Returns:
            Optional[OrganizationInvitation]: La invitación con
                ``status == "pending"`` para ese email, o ``None`` si no hay
                ninguna (ya respondida, expirada, o nunca invitado).
        """
        return (
            self._session.query(OrganizationInvitation)
            .filter(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email == email,
                OrganizationInvitation.status == "pending",
            )
            .first()
        )

    def count_pending(self, organization_id: int) -> int:
        """Invitaciones sin responder.

        Cuentan para el tope de miembros: si no, se invitaría a 300 personas
        con un plan de 20 y el tope no serviría de nada.
        """
        return (
            self._session.query(OrganizationInvitation)
            .filter(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.status == "pending",
            )
            .count()
        )

    def release_user(self, user_id: int) -> None:
        """Quita a un usuario de las invitaciones que lo citan, al borrar su cuenta.

        Las invitaciones que emitió se borran con él; en las que crearon su
        cuenta (``created_user_id``) la referencia pasa a ``NULL`` y la fila se
        conserva, porque es rastro de quien invitó.

        Args:
            user_id: Usuario que se da de baja.
        """
        self._session.query(OrganizationInvitation).filter(
            OrganizationInvitation.created_user_id == user_id
        ).update({"created_user_id": None}, synchronize_session=False)
        self._session.query(OrganizationInvitation).filter(
            OrganizationInvitation.invited_by_user_id == user_id
        ).delete(synchronize_session=False)


class SubscriptionRepository(BaseRepository[Subscription]):
    """Acceso a datos de las suscripciones."""

    _MODEL = Subscription

    def get_by_user(self, user_id: int) -> Optional[Subscription]:
        """La suscripción de un usuario, o ``None``.

        ``None`` es un resultado normal y frecuente, no un error: quien no
        tiene fila está en el plan por defecto.
        """
        return self.get_by_field("user_id", user_id)

    def clear_assigner(self, user_id: int) -> None:
        """Quita a ``user_id`` como quien asignó el plan de otras suscripciones.

        Es rastro histórico de otra persona: la suscripción se conserva con
        ``assigned_by_user_id`` a ``NULL``.

        Args:
            user_id: Usuario (un administrador) que dejó de existir.
        """
        self._session.query(Subscription).filter(
            Subscription.assigned_by_user_id == user_id
        ).update({"assigned_by_user_id": None}, synchronize_session=False)

    def delete_by_user(self, user_id: int) -> int:
        """Borra la suscripción de un usuario.

        Args:
            user_id: Usuario cuya suscripción se borra.

        Returns:
            int: Filas borradas (``0`` o ``1``).
        """
        return self._session.query(Subscription).filter(
            Subscription.user_id == user_id
        ).delete(synchronize_session=False)
