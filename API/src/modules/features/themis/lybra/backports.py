"""Preguntarle al proveedor si esa vulnerabilidad ya está corregida.

Un *backport* es una distribución arreglando un fallo sin subir el número de
versión visible: Debian parchea ``apache2``, el banner sigue diciendo
``2.4.49``, y el motor emite una CVE que ya no existe. Es la causa número uno
de falsos positivos de toda la detección por versión — se ha medido en
**0,42**: cuatro de cada diez CVEs reportados contra un Debian o un Ubuntu ya
estaban corregidos.

Hasta ahora la mitigación era un paliativo declarado (``qod=70``,
``confirmed=false``) que le dice al lector que *puede* ser falso pero no cuál lo
es, que es justo lo que quería saber. Y la verdad no hay que ir a buscarla
dentro del host: Debian, Ubuntu y Red Hat publican exactamente qué paquete
quedó corregido y en qué versión.

Este módulo es la aplicación de esa verdad sobre los hallazgos ya producidos.
Es puro —recibe una función de consulta y devuelve veredictos— para que el
paquete siga libre de ORM.

**Nunca se adivina.** Si no consta de qué distribución es el paquete
(:mod:`~.distro`), o si el proveedor no se ha pronunciado sobre esa CVE, el
hallazgo se queda exactamente como estaba. Bajar un hallazgo por una
suposición sería cambiar falsos positivos por falsos negativos, que en un
escáner es el peor negocio posible.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from .distro import DistroRelease, infer_distro_release
from .kb import parse_cpe23, version_compare

#: Lo que responde una consulta al espejo de avisos: el estado que el proveedor
#: declara y, si lo corrigió, en qué versión.
PackageStatus = tuple  # (status: str, fixed_in: Optional[str])

#: El check con el que se firma un hallazgo que el proveedor desmintió o
#: confirmó. Se estampa para que un hallazgo sepa decir por qué cambió de
#: estado, y para que el desmentido caduque solo si este check cambia de
#: versión (ver ``apply_lifecycle``).
BACKPORT_CHECK_ID = "lybra:oval-backport@1"

#: Producto NVD → paquete fuente de la distribución, sólo donde difieren. Donde
#: coinciden (``openssh``, ``openssl``, ``nginx``…) el nombre del CPE ya es el
#: del paquete y no hace falta entrada.
_DISTRO_PACKAGE_FOR_PRODUCT = {
    "http_server": "apache2",
    "bind": "bind9",
    "postgresql": "postgresql-common",
    "mysql": "mysql-8.0",
    "exim": "exim4",
    "tomcat": "tomcat10",
}

#: Qué release de la distribución tiene un paquete, dada su versión exacta:
#: ``(vendor, package, version) -> release`` o ``None``. Inyectada porque
#: consulta la base de datos.
ReleaseLookup = Callable[[str, str, str], Optional[str]]


def is_unverified_distro_package(finding: dict) -> bool:
    """Si un hallazgo por versión es de un paquete de distribución que nadie contrastó.

    Es el caso en que la versión visible no demuestra nada: la distribución
    puede haber corregido la CVE sin cambiar el número (un *backport*), y la
    verificación con su feed no llegó a pronunciarse —porque el feed falta,
    está caducado o no reconoce la release—. Si se hubiera pronunciado, el
    hallazgo ya no estaría así: sería ``fixed`` o estaría confirmado.

    Se decide con lo que el hallazgo guarda (su CPE, su versión instalada o su
    título), así que sirve igual al puntuar un escaneo recién hecho que al
    leerlo meses después.

    Args:
        finding: Un hallazgo, recién producido o leído de la base de datos.

    Returns:
        bool: ``True`` si es un ``outdated_software`` con CVE, sin confirmar,
            no resuelto por un backport, y cuya versión lleva la firma de una
            distribución. ``False`` en cualquier otro caso, incluido un binario
            compilado a mano (sin distribución, la versión sí es la que se ve).
    """
    if finding.get("category") != "outdated_software" or not finding.get("cve_ids"):
        return False
    if finding.get("confirmed") or finding.get("state") == "fixed":
        return False
    if finding.get("check_id") == BACKPORT_CHECK_ID:
        return False
    parsed = parse_cpe23(finding.get("cpe") or "") or {}
    version = finding.get("_installed_version") or parsed.get("version") or ""
    return infer_distro_release(version, finding.get("title") or "") is not None


def apply_backport_verdicts(
    findings: List[dict],
    status_lookup: Callable[[str, Optional[str], str, str], Optional[PackageStatus]],
    release_lookup: Optional[ReleaseLookup] = None,
) -> List[dict]:
    """Contrastar cada hallazgo por versión con lo que dice su distribución.

    Tres desenlaces, y sólo dos cambian algo:

    - **El proveedor ya lo corrigió** en una versión menor o igual que la
      instalada → el hallazgo pasa a ``state="fixed"`` y ``confirmed=False``.
      No es que se haya remediado ahora: es que nunca estuvo, y el motor lo
      había deducido de un número de versión que miente.
    - **El proveedor dice que sigue vulnerable** → asciende a
      ``confirmed=True`` con ``qod=90``. Dos fuentes independientes —la versión
      y el propio empaquetador— coinciden, que es una evidencia mucho más
      fuerte que la deducción sola.
    - **No consta** —ni la distribución ni el pronunciamiento— → no se toca.

    Args:
        findings: Los hallazgos del escaneo. Sólo se miran los de categoría
            ``outdated_software`` con CVE: son los únicos que nacen de una
            comparación de versiones y, por tanto, los únicos que un backport
            puede desmentir.
        status_lookup: ``(vendor, release, package, cve_id)`` → ``(status,
            fixed_in)`` o ``None``. Inyectada porque consulta la base de datos
            y este paquete no la toca.
        release_lookup: Deduce la release de la distribución cuando la
            revisión del paquete no la escribe (Ubuntu firma
            ``3ubuntu13.19``, sin «24.04»). Por defecto ``None``: sin ella,
            sólo se pregunta por avisos que no dependen de release.

    Returns:
        La misma lista, con los hallazgos que cambiaron ya modificados.
    """
    for finding in findings:
        if finding.get("category") != "outdated_software":
            continue
        cve_ids = finding.get("cve_ids") or []
        if not cve_ids:
            continue

        release = _release_for(finding)
        if release is None:
            continue          # sin distribución no hay a quién preguntar

        package = _package_name(finding)
        if not package:
            continue

        release_name = release.release
        installed = finding.get("_installed_version") or ""
        if release_name is None and release_lookup is not None and installed:
            release_name = release_lookup(release.vendor, package, installed)

        status = status_lookup(release.vendor, release_name, package, cve_ids[0])
        if status is None:
            continue          # el proveedor no se ha pronunciado

        _apply(finding, status, finding.get("_installed_version") or "")
    return findings


def _apply(finding: dict, status: PackageStatus, installed: str) -> None:
    """Traducir el pronunciamiento del proveedor a un cambio en el hallazgo."""
    state, fixed_in = status

    if state == "fixed" and fixed_in:
        # La versión instalada tiene que estar **a la altura** del arreglo: que
        # Debian lo haya corregido en 2.4.49-1~deb11u2 no dice nada bueno de un
        # host que sigue en 2.4.49-1~deb11u1. Sin esta comparación, la
        # verificación desmentiría hallazgos legítimos, que es peor que no
        # tenerla.
        if installed and version_compare(installed, fixed_in) < 0:
            return
        finding["state"] = "fixed"
        finding["fixed_reason"] = "backport"
        finding["confirmed"] = False
        finding["check_id"] = BACKPORT_CHECK_ID
        return

    if state == "vulnerable":
        finding["confirmed"] = True
        finding["qod"] = 90
        finding["check_id"] = BACKPORT_CHECK_ID


def _release_for(finding: dict) -> Optional[DistroRelease]:
    """De qué distribución es el paquete de este hallazgo, si consta."""
    return infer_distro_release(
        finding.get("_installed_version") or "",
        finding.get("title") or "",
    )


def _package_name(finding: dict) -> Optional[str]:
    """El nombre con el que la distribución llama a este paquete.

    Por orden: el que trae el hallazgo si lo trae (el inventario de Hygeia ya
    lo sabe), el producto de su CPE traducido con
    :data:`_DISTRO_PACKAGE_FOR_PRODUCT` donde la NVD y la distribución no
    coinciden, y en último término el nombre del servicio. El CPE va antes que
    el servicio porque el servicio de un OpenSSH se llama ``ssh``, y la
    distribución lo publica como ``openssh``: preguntar por ``ssh`` no
    encontraba nunca nada.

    Cuando ningún nombre coincide con el del feed, la consulta no encuentra
    nada y el hallazgo se queda como estaba, que es el comportamiento seguro.

    Args:
        finding: El hallazgo por versión.

    Returns:
        Optional[str]: El nombre del paquete en minúsculas, o ``None`` si no
            hay ninguno que probar.
    """
    if finding.get("_package_name"):
        return finding["_package_name"].strip().lower() or None
    parsed = parse_cpe23(finding.get("cpe") or "")
    if parsed and parsed.get("product"):
        product = parsed["product"].lower()
        return _DISTRO_PACKAGE_FOR_PRODUCT.get(product, product)
    package = finding.get("service") or ""
    return package.strip().lower() or None
