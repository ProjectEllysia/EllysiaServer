"""
Lo que las evaluaciones de controles aportan a una adopción: su recuento y su purga.

Se registra en ``AdoptionDataRegistry`` desde ``eunomia/__init__.py``, de modo que quitar un
marco cuente y borre sus evaluaciones sin que la adopción conozca la tabla.
"""

from src.modules.infrastructure import UnitOfWork

from ..repositories import EunomiaControlAssessmentRepository


def count_assessments(uow: UnitOfWork, owner_user_id: int, framework_key: str) -> dict[str, int]:
    """Cuenta las evaluaciones de un marco que ya no están «pendientes».

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        owner_user_id: Dueño efectivo de los datos.
        framework_key: Clave del marco.

    Returns:
        dict[str, int]: ``{"assessments": n}``.
    """
    return {"assessments": EunomiaControlAssessmentRepository(uow).count_not_pending(owner_user_id, framework_key)}


def purge_assessments(uow: UnitOfWork, owner_user_id: int, framework_key: str) -> dict[str, int]:
    """Borra las evaluaciones de un marco de un dueño.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        owner_user_id: Dueño efectivo de los datos.
        framework_key: Clave del marco.

    Returns:
        dict[str, int]: ``{"EunomiaControlAssessment": filas borradas}``.
    """
    return {"EunomiaControlAssessment": EunomiaControlAssessmentRepository(uow).delete_for_framework(
        owner_user_id, framework_key)}
