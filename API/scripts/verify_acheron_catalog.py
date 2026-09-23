"""Comprueba que la copia del catálogo de Acheron sigue al original.

El catálogo de tipos de la bóveda —qué campos tiene una cuenta, cuáles son
sensibles— vive en ``schema/schema.json`` del repositorio ``AcheronCore``. Esta
API no puede leerlo de ahí en tiempo de test, porque la suite está sellada
contra la red, así que lleva una copia en ``API/tests/unit/acheron-schema.json``.

Y ahí está el agujero que este script tapa. ``test_acheron_schema_contract.py``
compara ``storable_specs.py`` **contra la copia**, pero nadie comprobaba que la
copia siguiera al original. Una copia congelada y un registro congelado
coinciden perfectamente entre sí: el test da verde mientras la copia envejece,
y lo que certifica es la coherencia con un documento obsoleto.

No es hipotético. El 2026-09-18 esta copia iba una marca por detrás
(``identityKey``) y la de AcheronMobile iba dos, con las suites en verde todo el
tiempo.

**Qué versión se compara.** La que fija el SPA en ``web/app/package.json``, que
es el único sitio donde esta casa declara qué catálogo usa. No hay un fichero
nuevo que mantener al día: si el SPA sube de versión y nadie actualiza la copia,
esto falla, que es exactamente lo que se busca.

    python API/scripts/verify_acheron_catalog.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
COPIA = RAIZ / "API" / "tests" / "unit" / "acheron-schema.json"
PACKAGE_JSON = RAIZ / "web" / "app" / "package.json"
PAQUETE = "@projectellysia/acheron-core-js"
ORIGEN = "https://raw.githubusercontent.com/ProjectEllysia/AcheronCore/{tag}/schema/schema.json"


def version_fijada() -> str:
    """Lee del SPA qué versión del motor —y por tanto del catálogo— se usa."""
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    version = package.get("dependencies", {}).get(PAQUETE)
    if not version:
        raise SystemExit(f"{PACKAGE_JSON} no declara {PAQUETE}")
    # Sin rangos: el motor se fija a una version exacta a proposito, y de ahi
    # sale el tag. Un '^2.4.0' no identificaria un catalogo concreto.
    if not version[0].isdigit():
        raise SystemExit(
            f"{PAQUETE} esta fijado como '{version}', que no es una version exacta. "
            "El catalogo se compara contra un tag, y un rango no senala ninguno."
        )
    return f"v{version}"


def catalogo_original(tag: str) -> dict:
    url = ORIGEN.format(tag=tag)
    try:
        with urllib.request.urlopen(url, timeout=30) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise SystemExit(
                f"No existe el tag {tag} en AcheronCore, o no tiene schema/schema.json.\n"
                f"  {url}"
            ) from error
        raise


def main() -> int:
    tag = version_fijada()
    original = catalogo_original(tag)
    copia = json.loads(COPIA.read_text(encoding="utf-8"))

    if copia == original:
        tipos = len(original.get("types", []))
        print(f"OK: la copia coincide con AcheronCore {tag} ({tipos} tipos).")
        return 0

    # El mensaje tiene que decir QUE hacer, no solo que algo falla: quien lo lea
    # estara mirando un job rojo en un repositorio que no ha tocado el catalogo.
    print(f"La copia del catalogo NO coincide con AcheronCore {tag}.\n", file=sys.stderr)
    print(f"  copia:   {COPIA.relative_to(RAIZ).as_posix()}", file=sys.stderr)
    print(f"  original: {ORIGEN.format(tag=tag)}\n", file=sys.stderr)

    for linea in diferencias(copia, original):
        print(f"  {linea}", file=sys.stderr)

    print(
        "\nPara arreglarlo, copia el original encima de la copia y ejecuta la suite:\n"
        f"  curl -sL {ORIGEN.format(tag=tag)} -o {COPIA.relative_to(RAIZ)}\n"
        "  pytest API/tests/unit/test_acheron_schema_contract.py",
        file=sys.stderr,
    )
    return 1


def diferencias(copia: dict, original: dict) -> list[str]:
    """Resume en que se separan, tipo a tipo, en vez de volcar dos JSON enteros."""
    lineas: list[str] = []

    if copia.get("schemaVersion") != original.get("schemaVersion"):
        lineas.append(
            f"schemaVersion: copia={copia.get('schemaVersion')} "
            f"original={original.get('schemaVersion')}"
        )

    por_kind = lambda doc: {t.get("kind"): t for t in doc.get("types", [])}  # noqa: E731
    en_copia, en_original = por_kind(copia), por_kind(original)

    for kind in sorted(set(en_original) - set(en_copia)):
        lineas.append(f"falta el tipo '{kind}', que el original si trae")
    for kind in sorted(set(en_copia) - set(en_original)):
        lineas.append(f"sobra el tipo '{kind}', que el original ya no trae")

    for kind in sorted(set(en_copia) & set(en_original)):
        if en_copia[kind] != en_original[kind]:
            lineas.append(f"el tipo '{kind}' difiere:")
            lineas.append(f"    copia:    {json.dumps(en_copia[kind], sort_keys=True)}")
            lineas.append(f"    original: {json.dumps(en_original[kind], sort_keys=True)}")

    return lineas


if __name__ == "__main__":
    sys.exit(main())
