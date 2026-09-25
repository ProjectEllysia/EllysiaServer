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
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .correlation import DEFAULT_SITE_VHOST
from .engine import QOD_OPEN_PORT

#: Las categorías de hallazgo que describen la web servida (su certificado,
#: sus cabeceras) y no la máquina. Sobre el sitio por defecto de una IP que
#: aloja otras webs se reclasifican (ver :func:`mark_default_site_findings`).
DEFAULT_SITE_CATEGORIES = ("tls", "security_header")

#: Lo que un sitio sirve en un puerto web: ``(estado HTTP, huella del cuerpo,
#: identidad del certificado)``. Cualquiera de los tres es ``None`` si no se
#: pudo obtener. Lo construye la parte de red; aquí sólo se compara.
SiteView = Tuple[Optional[int], Optional[str], Optional[tuple]]

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


def is_alias_of_default_site(default_views: Dict[int, SiteView], site_views: Dict[int, SiteView]) -> bool:
    """Si un sitio con nombre sirve exactamente lo mismo que la IP sin nombre.

    Es el caso típico del nombre que da el DNS inverso de un proveedor de
    hosting (``ip203-0-113-10.proveedor.test``): resuelve a la IP, pero el
    servidor no lo conoce y contesta con su página por defecto. Auditarlo
    aparte repetiría, con otro nombre, los hallazgos del sitio por defecto.

    Se exige coincidencia completa en todos los puertos web, y que al menos
    uno haya contestado: ante la duda (una página con contenido dinámico, un
    puerto que no respondió) el sitio se audita como uno más.

    Args:
        default_views: Lo que sirve la IP sin nombre, por puerto.
        site_views: Lo que sirve el sitio con nombre, por puerto.

    Returns:
        bool: ``True`` si los dos sirven lo mismo en todos los puertos y hubo
            alguna respuesta; ``False`` en cualquier otro caso.
    """
    if default_views != site_views:
        return False
    return any(status is not None for status, _digest, _certificate in site_views.values())


def site_finding(name: str, origin: str, serves_default_site: bool = False) -> dict:
    """El aviso de que la IP sirve un sitio con nombre, y de dónde salió.

    Categoría ``virtual_host``, que el ciclo de vida trata como evento y el
    informe lista aparte, en «Sitios detectados en esta IP».

    Args:
        name: El nombre del sitio.
        origin: De dónde se sacó el nombre.
        serves_default_site: Si el nombre sólo sirve el sitio por defecto de la
            IP (ver :func:`is_alias_of_default_site`). Se dice en el título y no
            se audita aparte. Por defecto ``False``.

    Returns:
        dict: El hallazgo, listo para persistir. La clave de trabajo
            ``_serves_default_site`` (que no se persiste) repite
            ``serves_default_site`` para quien decide si la IP aloja otras
            webs.
    """
    suffix = "; sirve el sitio por defecto de la IP" if serves_default_site else ""
    return {
        "title":        f"{name} (origen: {origin}{suffix})",
        "_serves_default_site": serves_default_site,
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


def mark_alias_fixes(findings: List[dict]) -> None:
    """Anota, en sitio, los «corregidos» que sólo son un sitio que resultó alias.

    Cuando un nombre pasa a reconocerse como alias del sitio por defecto
    (:func:`is_alias_of_default_site`), deja de auditarse aparte y sus avisos
    del escaneo anterior dejan de aparecer con ese nombre. El ciclo de vida los
    da por corregidos, pero el servidor no ha cambiado: los mismos avisos salen
    ahora con el sitio por defecto. Se marcan con ``fixed_reason="alias"`` para
    que el informe no se los atribuya al cliente.

    Args:
        findings: Los hallazgos del escaneo, ya con el ciclo de vida aplicado:
            los avisos ``virtual_host`` de este escaneo (con su clave de
            trabajo ``_serves_default_site``) y los ``fixed`` que arrastra del
            anterior. Se modifican en sitio.
    """
    alias_names = {finding["vhost"] for finding in findings
                   if finding.get("category") == "virtual_host"
                   and finding.get("_serves_default_site")}
    for finding in findings:
        if (finding.get("state") == "fixed" and not finding.get("fixed_reason")
                and finding.get("vhost") in alias_names):
            finding["fixed_reason"] = "alias"


def mark_default_site_findings(findings: List[dict]) -> None:
    """Etiqueta los hallazgos web del sitio por defecto, en sitio.

    Cuando la IP aloja otras webs, lo que sirve a quien entra sin nombre (sin
    SNI ni ``Host``) es su sitio por defecto: en un hosting, la página
    genérica del panel con su certificado de fábrica. Lo que se dice de su
    certificado y de sus cabeceras es cierto para quien conecta así, y no se
    borra, pero no es lo que ve ningún visitante: se marca con
    :data:`DEFAULT_SITE_VHOST`, que lo deja en LOW y lo nombra como tal en el
    informe.

    Args:
        findings: Los hallazgos del escaneo por IP. Se modifican en sitio; sólo
            se tocan los de :data:`DEFAULT_SITE_CATEGORIES` sin sitio.
    """
    for finding in findings:
        if finding.get("category") in DEFAULT_SITE_CATEGORIES and not finding.get("vhost"):
            finding["vhost"] = DEFAULT_SITE_VHOST


def has_own_named_sites(findings: List[dict]) -> bool:
    """Si la IP aloja webs con nombre propio, además de su sitio por defecto.

    Args:
        findings: Los hallazgos de la auditoría de sitios con nombre, con sus
            avisos ``virtual_host``.

    Returns:
        bool: ``True`` si algún sitio con nombre sirve algo distinto del sitio
            por defecto; ``False`` si no hay sitios o todos son alias suyos.
    """
    return any(finding.get("category") == "virtual_host" and not finding.get("_serves_default_site")
               for finding in findings)


def _is_ip(name: str) -> bool:
    """Si ``name`` es una IP escrita tal cual."""
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False
