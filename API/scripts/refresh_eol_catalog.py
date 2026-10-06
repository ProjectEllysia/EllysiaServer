"""Refresca el catálogo de fin de soporte del fabricante (L114).

``lybra/end_of_life.py`` lee ``lybra/feeds/eol_catalog.json``, una instantánea
curada en vez de una tabla con su propia sincronización: las fechas de fin de
soporte casi no cambian, así que no justifican una migración ni un scheduler
propio. Este script es cómo se actualiza esa instantánea, a mano, contra la
API pública de ``endoflife.date``.

**Qué productos entran.** Sólo los que ya tienen un alias curado en
``feeds/product_aliases.json`` (vendor/producto exactos, el mismo CPE que usa
la correlación de CVEs) o cuyo par vendor/producto de la NVD es sobradamente
conocido (``redis:redis``, ``mongodb:mongodb``). Un producto que Lybra sólo
resuelve por el índice automático de la base de conocimiento (las APIs de
administración: Docker, Elasticsearch, Kubernetes…) se queda fuera hasta que
alguien confirme a mano cuál es su CPE real — meter una clave adivinada
produciría un catálogo que silenciosamente no cruza con nada, el mismo riesgo
que ``CPE_PRODUCT_OVERRIDES`` ya evita para las CVEs.

Uso, desde ``API/``:

    python scripts/refresh_eol_catalog.py

Reescribe el fichero entero: no hay forma de "sólo añadir uno", porque
``endoflife.date`` tampoco versiona sus respuestas — cada vez se pide el
catálogo completo de cada producto y se vuelve a filtrar. Revisa el diff antes
de commitear: una rama que desaparece del todo (``endoflife.date`` retira un
producto muy antiguo) se queda también sin aviso para esa rama, que es lo
correcto.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List

_API_DIR = Path(__file__).resolve().parent.parent
_CATALOG_PATH = (_API_DIR / "src" / "modules" / "features" / "themis" / "lybra"
                / "feeds" / "eol_catalog.json")

# slug de endoflife.date -> "vendor:product" (la misma clave que
# feeds/cve_applicability.json y feeds/product_aliases.json ya usan).
_PRODUCTS: Dict[str, str] = {
    "nginx": "nginx:nginx",
    "mysql": "mysql:mysql",
    "mariadb": "mariadb:mariadb",
    "postgresql": "postgresql:postgresql",
    "postfix": "postfix:postfix",
    "dovecot": "dovecot:dovecot",
    "exim": "exim:exim",
    "proftpd": "proftpd:proftpd",
    "memcached": "memcached:memcached",
    "zookeeper": "apache:zookeeper",
    "wordpress": "wordpress:wordpress",
    "drupal": "drupal:drupal",
    "joomla": "joomla:joomla\\!",
    "mssqlserver": "microsoft:sql_server",
    "redis": "redis:redis",
    "mongodb": "mongodb:mongodb",
}

_API_BASE = "https://endoflife.date/api"
_TIMEOUT_SECONDS = 15


def fetch_cycles(slug: str) -> List[dict]:
    """Pide el catálogo de ramas de un producto a ``endoflife.date``.

    Args:
        slug: El identificador del producto en esa API (``"nginx"``).

    Returns:
        list[dict]: Una entrada por rama, tal cual la devuelve la API.

    Raises:
        urllib.error.URLError: Si la petición falla (red, 404, timeout...).
    """
    with urllib.request.urlopen(f"{_API_BASE}/{slug}.json", timeout=_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def to_catalog_branches(cycles: List[dict]) -> List[dict]:
    """Queda sólo con lo que ``end_of_life.py`` necesita de cada rama.

    Args:
        cycles: Las entradas tal cual las devuelve ``endoflife.date``.

    Returns:
        list[dict]: ``{"cycle": str, "eol": str | False}``, en el mismo orden.
    """
    return [{"cycle": str(cycle["cycle"]), "eol": cycle.get("eol", False)} for cycle in cycles]


def main() -> int:
    """Pide cada producto y reescribe el catálogo entero.

    Returns:
        int: ``0`` si todos los productos se obtuvieron; ``1`` si alguno
        falló (el fichero no se toca en ese caso: mejor conservar la
        instantánea anterior que escribir una a medias).
    """
    products: Dict[str, List[dict]] = {}
    for slug, key in _PRODUCTS.items():
        try:
            products[key] = to_catalog_branches(fetch_cycles(slug))
        except (urllib.error.URLError, ValueError, KeyError) as err:
            print(f"refresh_eol_catalog: fallo con {slug!r} ({key}): {err}", file=sys.stderr)
            return 1
        print(f"refresh_eol_catalog: {key} -> {len(products[key])} ramas")

    catalog = {
        "_comment": ("Instantánea curada de endoflife.date; se refresca a mano con "
                    "scripts/refresh_eol_catalog.py. Ver lybra/end_of_life.py."),
        "feedVersion": "lybra-eol-1",
        "products": products,
    }
    _CATALOG_PATH.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"refresh_eol_catalog: escrito {_CATALOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
