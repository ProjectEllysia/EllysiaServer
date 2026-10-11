"""La lámina de concordancias de Eunomia se graba con datos reales del catálogo.

``web/app/src/components/decor/concordance.json`` es la instantánea con la que el SPA pinta la
escena del hub de Eunomia (``scenes/EunomiaScene.vue``): cuántos requisitos evaluables tiene cada
marco y qué requisito corresponde con cuál en otro marco. El SPA no puede leer el catálogo, que vive
en ``API/``, así que lleva una copia; este test es lo que impide que esa copia se quede vieja en
silencio —la escena seguiría pintándose, pero con un catálogo que ya no existe—.

Si falla porque el catálogo cambió, regenera la instantánea y revisa el diff::

    UPDATE_CONCORDANCE=1 pytest tests/unit/test_eunomia_scene_data.py
"""

import json
import os
from pathlib import Path

import pytest

from src.modules.features.eunomia.services.catalog import load_index, load_version
from src.modules.features.eunomia.services.crosswalks import COVERAGE_FULL, load_crosswalks

pytestmark = pytest.mark.unit

_SNAPSHOT = Path(__file__).resolve().parents[3] / "web" / "app" / "src" / "components" / "decor" / "concordance.json"

#: Orden de los marcos sobre la regla de la escena. Es una decisión de dibujo, no del catálogo:
#: deja contiguos los dos cruces con más enlaces (NIS2 con ISO 27001 y NIS2 con el ENS).
_RULER_ORDER = ("iso27001", "nis2", "ens", "rgpd")


def _build_snapshot() -> dict:
    """Reconstruye la instantánea a partir del catálogo.

    Solo entran las versiones vigentes de cada marco: el índice de un requisito es su posición entre
    los evaluables de esa versión, así que un cruce entre versiones antiguas no se puede situar.

    Returns:
        dict: ``{"order": [clave], "frameworks": {clave: {"label", "count"}}, "links": [[marco de
            origen, índice, marco de destino, índice, 1 si la cobertura es total y 0 si parcial]]}``.
            Los marcos salen en ``_RULER_ORDER`` (los que no figuren en él, detrás, en el orden del
            índice) y los enlaces en el orden de los ficheros de cruces.
    """
    current = {framework["key"]: framework["current"] for framework in load_index()["frameworks"]}
    versions = {key: load_version(key, version) for key, version in current.items()}
    order = sorted(current, key=lambda key: _RULER_ORDER.index(key) if key in _RULER_ORDER else len(_RULER_ORDER))
    positions = {
        key: {node.identifier: index for index, node in enumerate(version.assessable_nodes())}
        for key, version in versions.items()
    }
    links = [
        [crosswalk.a_framework, positions[crosswalk.a_framework][origin],
         crosswalk.b_framework, positions[crosswalk.b_framework][to], int(coverage == COVERAGE_FULL)]
        for crosswalk in load_crosswalks()
        if current.get(crosswalk.a_framework) == crosswalk.a_version
        and current.get(crosswalk.b_framework) == crosswalk.b_version
        for origin, to, coverage in crosswalk.links
    ]
    return {
        "order": order,
        "frameworks": {
            key: {"label": versions[key].short_name, "count": len(positions[key])} for key in order
        },
        "links": links,
    }


def _render(snapshot: dict) -> str:
    """Escribe la instantánea con un enlace por línea, para que el diff de un cambio se lea.

    Args:
        snapshot: Lo que devuelve ``_build_snapshot``.

    Returns:
        str: El JSON, terminado en salto de línea.
    """
    frameworks = ",\n".join(f'    "{key}": {json.dumps(value, ensure_ascii=False)}'
                            for key, value in snapshot["frameworks"].items())
    links = ",\n".join(f"    {json.dumps(link)}" for link in snapshot["links"])
    return (
        "{\n"
        f'  "order": {json.dumps(snapshot["order"])},\n'
        f'  "frameworks": {{\n{frameworks}\n  }},\n'
        f'  "links": [\n{links}\n  ]\n'
        "}\n"
    )


def test_the_scene_snapshot_matches_the_catalog():
    """La instantánea del SPA es la que sale hoy del catálogo (con ``UPDATE_CONCORDANCE=1`` la reescribe)."""
    expected = _build_snapshot()
    if os.environ.get("UPDATE_CONCORDANCE") == "1":
        _SNAPSHOT.write_text(_render(expected), encoding="utf-8")
    assert json.loads(_SNAPSHOT.read_text(encoding="utf-8")) == expected, (
        "concordance.json no coincide con el catálogo de Eunomia; regenérala con "
        "UPDATE_CONCORDANCE=1 pytest tests/unit/test_eunomia_scene_data.py"
    )
