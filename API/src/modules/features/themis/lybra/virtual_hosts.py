"""Los sitios con nombre que sirve una misma IP.

Un servidor compartido puede alojar decenas de webs detrás de una IP y un
puerto, y decide cuál responde por el nombre que el cliente dice (SNI en TLS,
``Host`` en HTTP). Escanear la IP a secas audita sólo el sitio por defecto.

El propio servidor delata los otros nombres: los certificados que sirve los
llevan en el SAN, y el DNS inverso de la IP suele nombrar la máquina. Este
módulo decide cuáles de esos candidatos se auditan y cómo se reportan; la
red (el handshake, la resolución) la pone quien llama.
"""

from __future__ import annotations

import ipaddress
from typing import Callable, Iterable, List, Tuple

from .correlation import DEFAULT_SITE_VHOST
from .engine import QOD_OPEN_PORT

#: Los checks cuyo hallazgo describe el certificado servido. Sobre el sitio
#: por defecto de una IP con sitios con nombre se reclasifican (ver
#: :func:`mark_default_site_certificates`).
DEFAULT_SITE_CERTIFICATE_CHECKS = ("tls-self-signed-cert", "tls-expired-cert")

#: Las categorías que describen la máquina y no el sitio. Una configuración de
#: red —las marcas de tiempo TCP, por ejemplo— la fija el sistema operativo
#: para todas las conexiones, se pida el nombre que se pida.
MACHINE_LEVEL_CATEGORIES = ("network_config",)


def depends_on_site(finding: dict) -> bool:
    """Indica si un hallazgo cambia según el sitio que se pide a la IP.

    La auditoría de un sitio con nombre repite los checks de los servicios web
    de la IP, y algunos de esos checks no miran la web sino la máquina que hay
    debajo. Su hallazgo ya salió en el escaneo por IP: repetirlo en cada sitio
    presentaría un único problema una vez por sitio, y lo contaría otras
    tantas en los totales.

    Args:
        finding: El hallazgo producido al auditar un sitio. Se lee su
            ``category``; si falta, se considera que depende del sitio.

    Returns:
        bool: ``True`` si el hallazgo es del sitio y debe conservarse con su
            nombre; ``False`` si es de la máquina (categoría en
            :data:`MACHINE_LEVEL_CATEGORIES`) y ya lo cubre el escaneo por IP.
    """
    return finding.get("category") not in MACHINE_LEVEL_CATEGORIES


def select_site_names(
    candidates: Iterable[Tuple[str, str]],
    resolves_to_target: Callable[[str], bool],
    limit: int,
) -> List[Tuple[str, str]]:
    """Filtra los nombres candidatos a los que de verdad sirve la IP escaneada.

    Se descartan los comodines (``*.ejemplo.test`` no nombra ningún sitio
    concreto), las IPs escritas como nombre, los nombres sin punto y los
    repetidos. De lo que queda, sólo pasa un nombre que resuelve a la IP
    escaneada: uno que apunta a otra máquina no está autorizado por el
    escaneo de ésta.

    Args:
        candidates: Pares ``(nombre, origen)``, en orden de preferencia. El
            origen es texto para el informe («certificado TLS de 443/tcp»).
        resolves_to_target: Dice si un nombre resuelve a la IP escaneada.
        limit: Máximo de nombres que se devuelven; a cero, ninguno.

    Returns:
        list: Los pares aceptados, en minúsculas y sin punto final, en el
            orden de ``candidates``; cada nombre con el primer origen en que
            apareció.
    """
    selected: List[Tuple[str, str]] = []
    seen = set()
    for raw_name, origin in candidates:
        if len(selected) >= limit:
            break
        name = (raw_name or "").strip().lower().rstrip(".")
        if not name or name in seen or name.startswith("*") or "." not in name or _is_ip(name):
            continue
        seen.add(name)
        if resolves_to_target(name):
            selected.append((name, origin))
    return selected


def site_finding(name: str, origin: str) -> dict:
    """El aviso de que la IP sirve un sitio con nombre, y de dónde salió.

    Categoría ``virtual_host``, que el ciclo de vida trata como evento y el
    informe lista aparte, en «Sitios detectados en esta IP».

    Args:
        name: El nombre del sitio.
        origin: De dónde se sacó el nombre.

    Returns:
        dict: El hallazgo, listo para persistir.
    """
    return {
        "title":        f"{name} (origen: {origin})",
        "category":     "virtual_host",
        "port":         None,
        "service":      name,
        "protocol":     "tcp",
        "vhost":        name,
        "source":       "lybra",
        "check_id":     "lybra:virtual-host@1",
        "feed_version": "lybra-vhosts-1",
        "qod":          QOD_OPEN_PORT,
        "confirmed":    False,
        "state":        "open",
    }


def mark_default_site_certificates(findings: List[dict]) -> None:
    """Etiqueta los hallazgos de certificado del sitio por defecto, en sitio.

    Cuando la IP aloja sitios con nombre, el certificado que sirve sin SNI es
    el de su sitio por defecto (a menudo el del panel, autofirmado). Es
    cierto para quien conecta sin nombre, así que no se borra, pero no es el
    que ve ningún visitante: se marca con :data:`DEFAULT_SITE_VHOST`, que lo
    deja en LOW y lo nombra como tal en el informe.

    Args:
        findings: Los hallazgos del escaneo por IP. Se modifican en sitio; sólo
            se tocan los de :data:`DEFAULT_SITE_CERTIFICATE_CHECKS` sin sitio.
    """
    for finding in findings:
        check_id = str(finding.get("check_id") or "").split(":", 1)[-1].split("@", 1)[0]
        if check_id in DEFAULT_SITE_CERTIFICATE_CHECKS and not finding.get("vhost"):
            finding["vhost"] = DEFAULT_SITE_VHOST


def _is_ip(name: str) -> bool:
    """Si ``name`` es una IP escrita tal cual."""
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False
