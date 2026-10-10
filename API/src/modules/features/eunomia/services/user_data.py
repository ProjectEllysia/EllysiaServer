"""
Lo que Eunomia hace con los datos de un usuario que se da de baja o pide su exportación.

Se da de alta en ``users.UserDataRegistry`` desde ``eunomia/__init__.py``.
"""

from src.modules.infrastructure import UnitOfWork

from ..repositories import EunomiaFrameworkAdoptionRepository


def purge_eunomia_data(uow: UnitOfWork, user_id: int) -> dict[str, int]:
    """Borra lo que Eunomia guarda de un usuario.

    Al borrarse una cuenta de dueño, su organización se disuelve y sus datos de cumplimiento
    desaparecen con ella; los de un miembro que fueron suyos antes de entrar también.

    Args:
        uow: Unidad de trabajo de la baja, con la sesión abierta.
        user_id: Usuario cuya cuenta se borra.

    Returns:
        dict[str, int]: Filas borradas por tabla.
    """
    return {"EunomiaFrameworkAdoption": EunomiaFrameworkAdoptionRepository(uow).delete_for_owner(user_id)}
