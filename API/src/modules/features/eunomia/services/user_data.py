"""
Lo que Eunomia hace con los datos de un usuario que se da de baja o pide su exportación.

Se da de alta en ``users.UserDataRegistry`` desde ``eunomia/__init__.py``.
"""

from src.modules.infrastructure import UnitOfWork

from .evidence_data import purge_owner_evidence
from ..repositories import (
    EunomiaAssessmentEventRepository,
    EunomiaEvidenceRepository,
    EunomiaControlAssessmentRepository,
    EunomiaFrameworkAdoptionRepository,
    EunomiaRecordEventRepository,
    EunomiaRecordRepository,
    EunomiaTemplateDraftRepository,
)


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
    events = EunomiaAssessmentEventRepository(uow)
    # El historial de otro dueño conserva el cambio y el nombre de quien se va, sin su cuenta.
    events.clear_actor(user_id)
    # Quién subió o enlazó una evidencia de otro dueño: rastro de otra persona, no datos de quien se va.
    EunomiaEvidenceRepository(uow).clear_user_references(user_id)
    assessments = EunomiaControlAssessmentRepository(uow)
    # Responsable y último editor son rastro de otra persona: se anulan, no se borra la fila.
    assessments.clear_user_references(user_id)
    drafts = EunomiaTemplateDraftRepository(uow)
    drafts.clear_user_references(user_id)
    record_events = EunomiaRecordEventRepository(uow)
    record_events.clear_actor(user_id)
    records = EunomiaRecordRepository(uow)
    records.clear_user_references(user_id)
    return {
        **purge_owner_evidence(uow, user_id),
        "EunomiaAssessmentEvent": events.delete_for_owner(user_id),
        "EunomiaControlAssessment": assessments.delete_for_owner(user_id),
        "EunomiaTemplateDraft": drafts.delete_for_owner(user_id),
        "EunomiaRecordEvent": record_events.delete_for_owner(user_id),
        "EunomiaRecord": records.delete_for_owner(user_id),
        "EunomiaFrameworkAdoption": EunomiaFrameworkAdoptionRepository(uow).delete_for_owner(user_id),
    }


def export_evidence_files(session, user_id: int):
    """Va dando los ficheros de evidencia del usuario, descifrados, para la exportación.

    Solo las evidencias de las que es dueño efectivo: las de la organización a la que
    pertenece son de su dueño y las exporta él.

    Args:
        session: Sesión abierta con la que leer.
        user_id: El usuario que exporta sus datos.

    Yields:
        tuple[str, bytes]: ``(ruta dentro de files/eunomia/, contenido)``.
    """
    for evidence, content in EunomiaEvidenceRepository(session=session).iter_files_for_owner(user_id):
        yield f"evidence/{evidence.id}-{evidence.filename}", content
