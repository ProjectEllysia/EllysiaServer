"""Riesgo de movimiento lateral entre los hosts de un grupo.

El motor razona host a host: cada escaneo es un activo y cada hallazgo
pertenece a un puerto. Eso deja fuera la pregunta que de verdad se hace un
defensor: **¿cómo se mueve un atacante por mi red una vez que entra?** Este
módulo mira a la vez los hallazgos de todos los hosts de un grupo y busca las
cuatro formas en que un fallo en un host se convierte en un problema de varios:

- ``exposed-service``: un servicio de administración remota (SMB, RDP, WinRM)
  con un problema grave, en un host que comparte segmento de red con otros. Un
  atacante que lo compromete llega, desde ahí, a los demás.
- ``shared-vulnerability``: la misma vulnerabilidad grave en varios hosts. Si
  es explotable en uno, lo es en todos con la misma configuración: se propaga
  por igual.
- ``multi-homed``: un host con direcciones en varios segmentos, que es el puente
  entre ellos.
- ``shared-credentials``: unas mismas credenciales por defecto que funcionan en
  varios hosts.

Cada riesgo es **explicable en una frase** que nombra a los hosts implicados.
Un grafo con un número sin explicación sería justo la «lista plana con más
pasos» que el motor rehúye, así que ninguna regla produce un riesgo cuyo
porqué no quepa en el ``title``. Y las reglas son deliberadamente
conservadoras: sin un problema grave, o sin nadie más a quien alcanzar, no hay
hallazgo.

Es la capa pura, como ``correlation.py``: recibe valores simples (los hosts del
grupo con sus hallazgos y direcciones) y devuelve hallazgos como diccionarios.
No toca la red ni el ORM. Quien lee los hosts y sus escaneos es el manager.

**Un hallazgo de red no pertenece a un host.** Sale con ``host_id=None`` y
``port=None``, y su identidad —lo que lo distingue de otro riesgo de la misma
red y lo mantiene estable entre escaneos— viaja en ``service``:
``<grupo>|<regla>|<discriminante>``, donde el discriminante es lo que el riesgo
*es* (un servicio de un host, una CVE, un check) y no el conjunto de hosts que
hoy lo sufren. Si la identidad dependiera de ese conjunto, cada host nuevo
convertiría el riesgo en otro y el anterior se daría por corregido.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .correlation import compute_dedup_key

# La versión de las reglas, para el ``feed_version`` de los hallazgos: sube
# cuando cambia lo que una regla considera un riesgo.
LATERAL_RULES_VERSION = "lybra-lateral-1"

# Los servicios por los que un atacante se mueve entre equipos: recursos
# compartidos de Windows, escritorio remoto y administración remota. Se
# reconocen por puerto o por el nombre con que los identifica el motor.
_LATERAL_PORTS: Dict[int, str] = {445: "SMB", 139: "SMB", 3389: "RDP", 5985: "WinRM", 5986: "WinRM"}
_LATERAL_NAMES: Dict[str, str] = {
    "smb": "SMB", "microsoft-ds": "SMB", "netbios-ssn": "SMB",
    "rdp": "RDP", "ms-wbt-server": "RDP",
    "winrm": "WinRM", "wsman": "WinRM",
}

# Cuánto pesa cada severidad cuando el hallazgo no trae puntuación CVSS (un
# fallo de configuración no la tiene).
_SEVERITY_SCORE: Dict[str, float] = {"CRITICAL": 9.5, "HIGH": 8.0, "MEDIUM": 5.5, "LOW": 3.0, "INFO": 0.0}

# Un hallazgo es «grave» para el movimiento lateral a partir de esta puntuación
# (o si está en KEV); uno de configuración, a partir de la mitad de la escala.
_SERIOUS_SCORE = 7.0
_SERIOUS_CONFIGURATION_SCORE = 5.0
_CONFIGURATION_CATEGORIES = ("network_config", "default_credentials", "exposed_service")

# Estados en los que un hallazgo cuenta como riesgo abierto.
_OPEN_STATES = (None, "open", "regressed")

# El factor de propagación: cada host alcanzado suma este porcentaje a la
# puntuación base, hasta ``_MAX_COUNTED_REACH`` hosts. Con cinco o más hosts
# alcanzados la puntuación llega a una vez y media la base. El tope evita que
# una red grande convierta cualquier hallazgo medio en crítico por volumen.
_PROPAGATION_STEP = 0.1
_MAX_COUNTED_REACH = 5

# La puntuación base de un host que une segmentos sin más problema: es un
# riesgo estructural, no una vulnerabilidad.
_MULTI_HOMED_BASE_SCORE = 5.0

# Cuántos nombres de host se listan en la frase antes de resumir el resto.
_NAMES_IN_SENTENCE = 5


@dataclass(frozen=True)
class GroupHost:
    """Un host del grupo, con lo que se sabe de él.

    Attributes:
        host_id: Identificador del host.
        name: Cómo se nombra al host en las frases: su nombre o su IP.
        addresses: Las direcciones IP del host. Con más de una en segmentos
            distintos el host es multi-homed. Puede traer una sola.
        findings: Sus hallazgos del último escaneo, como diccionarios con las
            claves de ``Finding.snapshot`` (``port``, ``service``, ``severity``,
            ``cvss_score``, ``in_kev``, ``cve_ids``, ``category``, ``check_id``,
            ``title``) y ``state``.
    """
    host_id: int
    name: str
    addresses: Tuple[str, ...]
    findings: Tuple[dict, ...]


def segment_of(address: str) -> Optional[str]:
    """El segmento de red al que pertenece una dirección.

    Un /24 para IPv4 y un /64 para IPv6: el tamaño con el que se reparten
    normalmente las redes de una organización. Dos hosts en el mismo segmento se
    alcanzan sin pasar por un router.

    Args:
        address: Una dirección IP en texto.

    Returns:
        Optional[str]: La red en forma canónica (``"10.0.0.0/24"``), o ``None``
            si el texto no es una dirección IP.
    """
    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError:
        return None
    prefix = 24 if parsed.version == 4 else 64
    return str(ipaddress.ip_network(f"{parsed}/{prefix}", strict=False))


def _segments(host: GroupHost) -> Set[str]:
    """Los segmentos en los que tiene dirección un host.

    Args:
        host: El host.

    Returns:
        Set[str]: Los segmentos, sin repetir; vacío si ninguna dirección es válida.
    """
    return {segment for segment in (segment_of(address) for address in host.addresses)
            if segment is not None}


def _score(finding: dict) -> float:
    """La puntuación de un hallazgo: su CVSS o, sin él, la que toca a su severidad.

    Args:
        finding: El hallazgo.

    Returns:
        float: Entre 0.0 y 10.0.
    """
    cvss = finding.get("cvss_score")
    if cvss:
        return float(cvss)
    return _SEVERITY_SCORE.get(str(finding.get("severity") or "").upper(), 0.0)


def _is_serious(finding: dict) -> bool:
    """Si un hallazgo es lo bastante grave como para alimentar un riesgo lateral.

    Args:
        finding: El hallazgo.

    Returns:
        bool: ``True`` si está abierto y (su puntuación llega al umbral o está
            en KEV), o si es un fallo de configuración de puntuación media o
            más. Los hallazgos informativos (puertos abiertos, huellas) nunca.
    """
    if finding.get("state") not in _OPEN_STATES:
        return False
    if finding.get("category") in ("open_port", "surface_change", "fingerprint"):
        return False
    score = _score(finding)
    if finding.get("in_kev") or score >= _SERIOUS_SCORE:
        return True
    return finding.get("category") in _CONFIGURATION_CATEGORIES and score >= _SERIOUS_CONFIGURATION_SCORE


def _lateral_service(finding: dict) -> Optional[str]:
    """El servicio de movimiento lateral al que pertenece un hallazgo, si lo hay.

    Args:
        finding: El hallazgo.

    Returns:
        Optional[str]: ``"SMB"``, ``"RDP"`` o ``"WinRM"``; ``None`` si el hallazgo
            no es de uno de ellos.
    """
    by_port = _LATERAL_PORTS.get(finding.get("port"))
    if by_port:
        return by_port
    return _LATERAL_NAMES.get(str(finding.get("service") or "").lower())


def _band(score: float) -> str:
    """La severidad que le corresponde a una puntuación.

    Args:
        score: De 0.0 a 10.0.

    Returns:
        str: ``"CRITICAL"`` desde 9.0, ``"HIGH"`` desde 7.0, ``"MEDIUM"`` desde
            4.0 y ``"LOW"`` por debajo.
    """
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"


def propagation_score(base_score: float, reach: int) -> float:
    """Combina la puntuación base con cuántos hosts alcanza el riesgo.

    ``base × (1 + 0,1 × hosts alcanzados)``, contando como mucho cinco hosts y
    con techo en 10. Es lo que hace que el mismo fallo puntúe más en una red
    donde llega a doce equipos que en una donde llega a uno.

    Args:
        base_score: La puntuación del hallazgo que origina el riesgo, de 0.0 a 10.0.
        reach: A cuántos otros hosts del grupo alcanza. Los negativos cuentan como 0.

    Returns:
        float: La puntuación combinada, con un decimal, entre 0.0 y 10.0.
    """
    counted = min(max(reach, 0), _MAX_COUNTED_REACH)
    return round(min(10.0, base_score * (1 + _PROPAGATION_STEP * counted)), 1)


def _names(hosts: Iterable[GroupHost]) -> str:
    """Los nombres de unos hosts, para una frase: los primeros y cuántos más.

    Args:
        hosts: Los hosts a nombrar.

    Returns:
        str: ``"a, b y c"``, o ``"a, b, c, d, e y 3 más"`` si pasan del tope.
    """
    names = sorted(host.name for host in hosts)
    if len(names) > _NAMES_IN_SENTENCE:
        listed = ", ".join(names[:_NAMES_IN_SENTENCE])
        return f"{listed} y {len(names) - _NAMES_IN_SENTENCE} más"
    if len(names) > 1:
        return f"{', '.join(names[:-1])} y {names[-1]}"
    return names[0] if names else ""


def _risk(group_key: str, rule: str, discriminator: str, sentence: str, base_score: float,
          origin: Sequence[GroupHost], reached: Sequence[GroupHost]) -> dict:
    """Construye el hallazgo de un riesgo lateral.

    Args:
        group_key: La clave del grupo (identifica la red analizada).
        rule: La regla que lo detectó (``"exposed-service"``…).
        discriminator: Lo que el riesgo *es*, estable entre escaneos.
        sentence: La explicación en una frase; es el título del hallazgo.
        base_score: La puntuación del hallazgo que lo origina.
        origin: Los hosts donde nace el riesgo.
        reached: Los hosts a los que llega, sin contar los de origen.

    Returns:
        dict: El hallazgo con la forma que entiende el resto del motor, más
            ``risk_score``, ``reach``, ``rule`` y ``hosts`` (origen y alcanzados
            con su id y nombre).
    """
    score = propagation_score(base_score, len(reached))
    finding = {
        "title": sentence, "category": "lateral_risk", "severity": _band(score),
        "host_id": None, "port": None, "protocol": "tcp", "source": "lybra",
        "service": f"{group_key}|{rule}|{discriminator}",
        "check_id": f"lybra:lateral-{rule}@1", "feed_version": LATERAL_RULES_VERSION,
        # Es una inferencia sobre la topología, no una prueba: no se confirma.
        "qod": 60, "confirmed": False, "state": "open",
        "risk_score": score, "reach": len(reached), "rule": rule,
        "hosts": [{"hostId": host.host_id, "name": host.name}
                  for host in sorted({item.host_id: item for item in (*origin, *reached)}.values(),
                                     key=lambda item: item.name)],
    }
    finding["dedup_key"] = compute_dedup_key(finding)
    return finding


def _exposed_service_risks(group_key: str, hosts: Sequence[GroupHost]) -> List[dict]:
    """SMB, RDP o WinRM con un problema grave, alcanzable desde otros hosts del segmento.

    Args:
        group_key: La clave del grupo.
        hosts: Los hosts del grupo.

    Returns:
        List[dict]: Un riesgo por cada (host, servicio) con problema y al menos
            otro host en su segmento.
    """
    risks: List[dict] = []
    for host in hosts:
        reached = [other for other in hosts
                   if other is not host and _segments(host) & _segments(other)]
        if not reached:
            continue
        by_service: Dict[str, List[dict]] = {}
        for finding in host.findings:
            service = _lateral_service(finding)
            if service and _is_serious(finding):
                by_service.setdefault(service, []).append(finding)
        for service, findings in by_service.items():
            worst = max(findings, key=_score)
            sentence = (f"{host.name} expone {service} con un problema grave ({worst.get('title')}) "
                        f"y puede alcanzar a otros {len(reached)} hosts de su mismo segmento: "
                        f"{_names(reached)}.")
            risks.append(_risk(group_key, "exposed-service", f"{host.host_id}:{service}",
                               sentence, _score(worst), [host], reached))
    return risks


def _shared_vulnerability_risks(group_key: str, hosts: Sequence[GroupHost]) -> List[dict]:
    """La misma vulnerabilidad grave en varios hosts.

    Args:
        group_key: La clave del grupo.
        hosts: Los hosts del grupo.

    Returns:
        List[dict]: Un riesgo por cada CVE grave presente en dos hosts o más.
    """
    affected: Dict[str, List[Tuple[GroupHost, dict]]] = {}
    for host in hosts:
        for finding in host.findings:
            if not _is_serious(finding):
                continue
            for cve in finding.get("cve_ids") or ():
                affected.setdefault(cve, []).append((host, finding))
    risks: List[dict] = []
    for cve, pairs in sorted(affected.items()):
        distinct = {host.host_id: host for host, _ in pairs}
        if len(distinct) < 2:
            continue
        involved = sorted(distinct.values(), key=lambda item: item.name)
        sentence = (f"La vulnerabilidad {cve} afecta a {len(involved)} hosts con la misma "
                    f"configuración ({_names(involved)}): si es explotable en uno, lo es en todos.")
        base = max(_score(finding) for _, finding in pairs)
        risks.append(_risk(group_key, "shared-vulnerability", cve, sentence, base,
                           involved[:1], involved[1:]))
    return risks


def _multi_homed_risks(group_key: str, hosts: Sequence[GroupHost]) -> List[dict]:
    """Un host con direcciones en varios segmentos, que es el puente entre ellos.

    Sólo cuenta si en **cada** segmento del host hay algún otro host del grupo:
    un puente que no une nada no mueve a nadie.

    Args:
        group_key: La clave del grupo.
        hosts: Los hosts del grupo.

    Returns:
        List[dict]: Un riesgo por cada host multi-homed que une a otros.
    """
    risks: List[dict] = []
    for host in hosts:
        segments = sorted(_segments(host))
        if len(segments) < 2:
            continue
        others = [other for other in hosts if other is not host]
        if not all(any(segment in _segments(other) for other in others) for segment in segments):
            continue
        reached = [other for other in others if _segments(other) & set(segments)]
        sentence = (f"{host.name} tiene direcciones en {len(segments)} segmentos "
                    f"({', '.join(segments)}) y une a {len(reached)} hosts de la red "
                    f"({_names(reached)}): si cae, un atacante pasa de un segmento al otro.")
        risks.append(_risk(group_key, "multi-homed", str(host.host_id), sentence,
                           _MULTI_HOMED_BASE_SCORE, [host], reached))
    return risks


def _shared_credentials_risks(group_key: str, hosts: Sequence[GroupHost]) -> List[dict]:
    """Las mismas credenciales por defecto funcionando en varios hosts.

    Args:
        group_key: La clave del grupo.
        hosts: Los hosts del grupo.

    Returns:
        List[dict]: Un riesgo por cada check de credenciales por defecto que
            dispara en dos hosts o más.
    """
    affected: Dict[str, List[Tuple[GroupHost, dict]]] = {}
    for host in hosts:
        for finding in host.findings:
            if (finding.get("category") == "default_credentials" and finding.get("check_id")
                    and finding.get("state") in _OPEN_STATES):
                affected.setdefault(finding["check_id"], []).append((host, finding))
    risks: List[dict] = []
    for check_id, pairs in sorted(affected.items()):
        distinct = {host.host_id: host for host, _ in pairs}
        if len(distinct) < 2:
            continue
        involved = sorted(distinct.values(), key=lambda item: item.name)
        title = pairs[0][1].get("title")
        sentence = (f"Las credenciales por defecto de «{title}» funcionan en {len(involved)} hosts "
                    f"({_names(involved)}): quien las conozca de uno las reutiliza en todos.")
        base = max(_score(finding) for _, finding in pairs)
        risks.append(_risk(group_key, "shared-credentials", check_id, sentence, base,
                           involved[:1], involved[1:]))
    return risks


def assess_lateral_risk(group_key: str, hosts: Sequence[GroupHost]) -> List[dict]:
    """Los riesgos de movimiento lateral de un grupo de hosts.

    Un grupo de menos de dos hosts no tiene por dónde moverse: no produce nada.

    Args:
        group_key: Identifica la red analizada (``"group:3"``, ``"scan:120"``);
            entra en la identidad de cada hallazgo, para que dos redes con el
            mismo riesgo no se fundan.
        hosts: Los hosts del grupo con sus direcciones y hallazgos.

    Returns:
        List[dict]: Los hallazgos ``lateral_risk``, de mayor a menor
            ``risk_score`` (y por título a igualdad); vacía si no hay riesgo.
    """
    ordered = sorted(hosts, key=lambda item: item.name)
    if len(ordered) < 2:
        return []
    risks = (_exposed_service_risks(group_key, ordered)
             + _shared_vulnerability_risks(group_key, ordered)
             + _multi_homed_risks(group_key, ordered)
             + _shared_credentials_risks(group_key, ordered))
    return sorted(risks, key=lambda risk: (-risk["risk_score"], risk["title"]))
