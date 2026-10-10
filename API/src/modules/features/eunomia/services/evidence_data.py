"""
Lo que las evidencias aportan a una adopción: su recuento y su purga.

Quitar un marco **no borra las evidencias que sirven a otro marco adoptado**: una evidencia
enlazada con NIS2 y con ENS sigue ahí cuando se purga NIS2, solo pierde ese enlace. Se borra
únicamente la que solo demostraba controles del marco que se va.
"""

from src.modules.infrastructure import UnitOfWork

from ..repositories import EunomiaEvidenceLinkRepository, EunomiaEvidenceRepository


def _split(uow: UnitOfWork, owner_user_id: int, framework_key: str) -> tuple[set[int], set[int]]:
    """Reparte las evidencias enlazadas con un marco en exclusivas y compartidas.

    Returns:
        tuple[set[int], set[int]]: ``(exclusivas, compartidas)``: ids de las evidencias que solo
            demuestran controles de ese marco, y de las que además demuestran otro.
    """
    links = EunomiaEvidenceLinkRepository(uow)
    ids = {link.evidence_id for link in links.list_for_framework(owner_user_id, framework_key)}
    if not ids:
        return set(), set()
    other = links.evidence_ids_linked_elsewhere(ids, framework_key)
    return ids - other, ids & other


def count_evidence(uow: UnitOfWork, owner_user_id: int, framework_key: str) -> dict[str, int]:
    """Cuenta las evidencias que se borrarían y las que se conservarían al quitar un marco.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        owner_user_id: Dueño efectivo de los datos.
        framework_key: Clave del marco.

    Returns:
        dict[str, int]: ``{"evidenceDeleted": n, "evidenceKept": m}``.
    """
    exclusive, shared = _split(uow, owner_user_id, framework_key)
    return {"evidenceDeleted": len(exclusive), "evidenceKept": len(shared)}


def purge_evidence(uow: UnitOfWork, owner_user_id: int, framework_key: str) -> dict[str, int]:
    """Borra los enlaces de un marco y las evidencias que solo servían a ese marco.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        owner_user_id: Dueño efectivo de los datos.
        framework_key: Clave del marco.

    Returns:
        dict[str, int]: Filas borradas por tabla.
    """
    exclusive, _ = _split(uow, owner_user_id, framework_key)
    removed_links = EunomiaEvidenceLinkRepository(uow).delete_for_framework(owner_user_id, framework_key)
    repo = EunomiaEvidenceRepository(uow)
    for evidence_id in exclusive:
        repo.delete_with_dependents(evidence_id)
    return {"EunomiaEvidenceLink": removed_links, "EunomiaEvidence": len(exclusive)}


def purge_owner_evidence(uow: UnitOfWork, owner_user_id: int) -> dict[str, int]:
    """Borra todas las evidencias de un dueño con su contenido y sus enlaces.

    Args:
        uow: Unidad de trabajo con la sesión abierta.
        owner_user_id: Dueño cuya cuenta se borra.

    Returns:
        dict[str, int]: ``{"EunomiaEvidence": n}``.
    """
    repo = EunomiaEvidenceRepository(uow)
    ids = repo.ids_for_owner(owner_user_id)
    for evidence_id in ids:
        repo.delete_with_dependents(evidence_id)
    return {"EunomiaEvidence": len(ids)}
