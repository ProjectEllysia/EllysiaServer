"""Enriquecer hallazgos con lo que la KB local sabe de sus CVEs.

Descripción, CWEs y —lo más accionable de todo— la versión en la que el
problema está corregido. Nada de esto se inventa: sale del registro NVD
replicado localmente, y `fixed_version` sólo se rellena cuando la propia NVD
declara una cota superior en la regla de aplicabilidad que casó con el producto
del hallazgo.

Vivía dentro del constructor del PDF (``FindingsPrintingStrategy``), así que
era exclusivo del informe: la interfaz no podía decir «actualiza a 2.4.58 o
superior» ni aunque quisiera, porque ese dato nunca llegaba a la API. Aquí
queda a mano de los dos. No está en ``lybra/``, que es la capa pura, porque
consulta la base de datos.
"""

from __future__ import annotations

from typing import Optional

from src.modules.infrastructure.session import build_repository

from ..lybra import parse_cpe23, version_in_range
from ..repositories import KbRepository


def _load_primary_cve_entries(findings: list) -> dict:
    """Carga en bloque el ``CveEntry`` (con sus ``cpe_matches``) de cada hallazgo.

    Una consulta para todos los CVEs del escaneo, nunca una por hallazgo: un
    host con 150 hallazgos es lo normal, y ahí la diferencia entre una
    consulta y ciento cincuenta es la diferencia entre una vista que abre y
    una que no. Compartida por :func:`enrich_with_cve_context` (contexto
    completo, de lectura) y :func:`resolve_fixed_versions` (sólo la versión
    corregida, de escritura).
    """
    cve_ids = sorted({cve for finding in findings for cve in (finding.get("cve_ids") or [])})
    if not cve_ids:
        return {}
    return {
        cve_entry.cve_id: cve_entry
        for cve_entry in build_repository(KbRepository).get_cves_with_matches(cve_ids)
    }


def enrich_with_cve_context(findings: list) -> None:
    """Añadir ``description``, ``cwe_ids`` y ``fixed_version`` a cada hallazgo.

    Modifica los dicts en el sitio. Para la vista de informe/API — trae
    campos (``description``, ``cwe_ids``) que no son columnas de ``Finding``,
    así que esta función no debe usarse para preparar un dict antes de
    persistirlo (ver :func:`resolve_fixed_versions`, que sí lo es).
    """
    entries = _load_primary_cve_entries(findings)
    if not entries:
        return
    for finding in findings:
        ids = finding.get("cve_ids") or []
        if not ids:
            continue
        entry = entries.get(ids[0])
        if entry is None:
            continue
        finding["description"] = entry.description
        finding["cwe_ids"] = entry.cwe_ids or []
        finding["fixed_version"] = find_fixed_version(entry, finding.get("cpe"))


def resolve_fixed_versions(findings: list) -> None:
    """Añadir sólo ``fixed_version`` a cada hallazgo. Modifica los dicts en el sitio.

    Se llama antes de persistir (``ScanRepository.persist_findings``), para
    que la versión corregida quede en la fila del ``Finding`` — consultable y
    ordenable por SQL — en vez de recalcularse cada vez que alguien pide un
    informe. A diferencia de :func:`enrich_with_cve_context`, sólo toca
    ``fixed_version`` porque es la única de las tres claves que tiene columna
    propia en ``Finding``; ``description`` y ``cwe_ids`` sólo tienen sentido
    en la vista de informe, con el CVE completo delante.
    """
    entries = _load_primary_cve_entries(findings)
    if not entries:
        return
    for finding in findings:
        ids = finding.get("cve_ids") or []
        if not ids:
            continue
        entry = entries.get(ids[0])
        if entry is not None:
            finding["fixed_version"] = find_fixed_version(entry, finding.get("cpe"))


def find_fixed_version(entry, cpe: Optional[str]) -> Optional[str]:
    """La cota "corregido en" de la NVD para el producto y la versión de este hallazgo.

    Una CVE puede declarar varias reglas de aplicabilidad para el mismo
    producto, cada una con su rango: una regresión trae el rango donde el fallo
    apareció por primera vez y el rango donde volvió a aparecer. La cota que
    sirve es la de la regla **cuyo rango contiene la versión detectada**; la de
    otra regla manda actualizar a una versión que no corrige nada (regreSSHion
    sobre un 9.6p1 decía «4.4», la corrección del fallo de 2006, en vez de
    «9.8p1»).

    Args:
        entry: El ``CveEntry`` con sus ``cpe_matches`` cargados.
        cpe: El CPE del hallazgo, en forma 2.2 o 2.3, o ``None``.

    Returns:
        Optional[str]: La versión corregida de la regla que contiene la versión
            del CPE. Si el CPE no trae versión (``*``, ``-`` o vacía), la de la
            primera regla del producto con cota superior, porque no hay con qué
            elegir. ``None`` cuando no hay CPE, cuando ninguna regla del
            producto declara cota superior, o cuando el CPE trae versión y
            ninguna regla la contiene: una versión de destino inventada es peor
            que ninguna, porque se actúa sobre ella.
    """
    if not cpe:
        return None
    parsed = parse_cpe23(cpe)
    if not parsed:
        return None
    version = parsed.get("version")
    has_version = bool(version) and version not in ("*", "-")
    for cpe_match in entry.cpe_matches:
        if cpe_match.vendor != parsed["vendor"] or cpe_match.product != parsed["product"]:
            continue
        if has_version and not version_in_range(version, cpe_match):
            continue
        upper_bound = cpe_match.version_end_excluding or cpe_match.version_end_including
        if upper_bound:
            return upper_bound
    return None
