"""NetworkRiskManager — grupos de activos y riesgo de movimiento lateral.

La decisión de qué es un riesgo lateral vive en la capa pura
(``themis/lybra/lateral.py``); aquí está lo que esa capa no puede tener: leer de
la base de datos los hosts de una red con sus últimos hallazgos, resolver sus
nombres a direcciones y administrar los grupos de activos del usuario.

Un análisis de red mira un **conjunto de hosts que ya se escanearon**; nunca
toca la red. Por eso no pasa por el registro de objetivos autorizados: no manda
ningún paquete, sólo razona sobre lo que ya se sabe. El conjunto sale de una de
dos fuentes:

- Un **grupo de activos**: los hosts que el usuario ha escaneado y cuya
  dirección cae en el rango del grupo, cada uno con su último escaneo terminado.
- Un **escaneo de red**: los hosts hijo de un escaneo lanzado sobre un CIDR o
  una lista de objetivos.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Callable, List, Optional, Sequence, Tuple

from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from src.modules.shared import assert_owned, isoformat_utc
from src.modules.shared._exceptions import ValidationError

from ...exceptions import AssetGroupNotFoundError, DuplicateAssetGroupError, ScanNotFoundError
from ...lybra import GroupHost, assess_lateral_risk
from ...model import AssetGroup
from ...repositories import AssetGroupRepository, ScanRepository
from ...services.parsing import is_hostname

logger = logging.getLogger(__name__)

#: Máximo de hosts que un análisis de red considera. El análisis compara hosts
#: entre sí, así que su coste crece con el cuadrado del grupo; el tope evita que
#: un rango enorme lo convierta en un cálculo interminable.
MAX_HOSTS_PER_ANALYSIS = 500

#: Estados en los que un hallazgo se sigue contando como riesgo. Los demás
#: (corregido, aceptado, falso positivo) ya no son un problema abierto.
_OPEN_STATES = ("open", "regressed")


def _resolve_addresses(name: str) -> Tuple[str, ...]:
    """Las direcciones IP a las que resuelve un nombre, según el sistema.

    Es lo que permite reconocer un host multi-homed: un nombre que resuelve a
    direcciones de varios segmentos.

    Args:
        name: El nombre de host.

    Returns:
        Tuple[str, ...]: Las direcciones sin repetir, en el orden en que llegan;
            vacía si el nombre no resuelve.
    """
    try:
        return tuple(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(name, None)))
    except OSError:
        return ()


def _canonical_cidr(cidr: str) -> str:
    """Valida un rango y lo devuelve en forma canónica.

    Args:
        cidr: El rango tal como lo escribió el usuario.

    Returns:
        str: La red canónica (``"10.0.0.0/24"``).

    Raises:
        ValidationError: Si no es una red IPv4 o IPv6 válida.
    """
    try:
        return str(ipaddress.ip_network(cidr.strip(), strict=False))
    except ValueError as error:
        raise ValidationError(
            f"Rango no válido: {cidr!r}", field="cidr", value=cidr,
            user_message=f"«{cidr}» no es un rango de red válido (por ejemplo 10.0.0.0/24).",
        ) from error


def _format_group(group: AssetGroup) -> dict:
    """Un grupo de activos en la forma de la API.

    Args:
        group: El grupo.

    Returns:
        dict: ``groupId``, ``name``, ``cidr`` y ``createdAt``.
    """
    return {"groupId": group.id, "name": group.name, "cidr": group.cidr,
            "createdAt": isoformat_utc(group.created_at)}


def _format_risk(risk: dict) -> dict:
    """Un riesgo lateral en la forma de la API, en camelCase.

    Args:
        risk: El hallazgo tal como lo produce ``assess_lateral_risk``.

    Returns:
        dict: ``title`` (la explicación en una frase), ``severity``,
            ``riskScore``, ``reach``, ``rule``, ``checkId``, ``dedupKey`` y
            ``hosts`` (los implicados, con ``hostId`` y ``name``).
    """
    return {
        "title": risk["title"], "severity": risk["severity"], "riskScore": risk["risk_score"],
        "reach": risk["reach"], "rule": risk["rule"], "checkId": risk["check_id"],
        "dedupKey": risk["dedup_key"], "hosts": risk["hosts"],
    }


class NetworkRiskManager:
    """Administra los grupos de activos y analiza el riesgo de movimiento lateral.

    Args:
        resolve_addresses: ``nombre -> tupla de IPs``: cómo se resuelve el nombre
            de un host para reconocer los multi-homed. Por defecto, el resolutor
            del sistema; los tests inyectan una tabla.
    """

    def __init__(self, resolve_addresses: Optional[Callable[[str], Sequence[str]]] = None) -> None:
        self._resolve_addresses = resolve_addresses or _resolve_addresses

    # ------------------------------------------------------------------ grupos

    def create_group(self, user_id: int, name: str, cidr: str) -> AssetGroup:
        """Crea un grupo de activos.

        Args:
            user_id: Dueño del grupo.
            name: Nombre legible, de 1 a 100 caracteres, único por usuario.
            cidr: El rango que define la red del grupo.

        Returns:
            AssetGroup: El grupo ya guardado.

        Raises:
            ValidationError: Si el nombre está vacío o el rango no es válido.
            DuplicateAssetGroupError: Si el usuario ya tiene un grupo con ese nombre.
        """
        clean_name = (name or "").strip()
        if not clean_name or len(clean_name) > 100:
            raise ValidationError(
                "Nombre de grupo no válido", field="name", value=name,
                user_message="El nombre del grupo debe tener entre 1 y 100 caracteres.")
        canonical = _canonical_cidr(cidr)
        with UnitOfWork() as uow:
            repository = AssetGroupRepository(uow)
            if repository.get_by_name_and_user(clean_name, user_id):
                raise DuplicateAssetGroupError(clean_name)
            group = repository.save(AssetGroup(user_id=user_id, name=clean_name, cidr=canonical))
        logger.info("Grupo de activos '%s' (%s) creado por usuario %s", clean_name, canonical, user_id)
        return group

    def list_groups(self, user_id: int) -> List[dict]:
        """Los grupos de activos del usuario.

        Args:
            user_id: Dueño.

        Returns:
            List[dict]: Uno por grupo, por nombre (ver ``_format_group``).
        """
        return [_format_group(group)
                for group in build_repository(AssetGroupRepository).get_by_user(user_id)]

    def delete_group(self, group_id: int, user_id: int) -> str:
        """Borra un grupo de activos, verificando propiedad.

        Args:
            group_id: Clave primaria del grupo.
            user_id: Usuario que lo pide.

        Returns:
            str: El nombre del grupo borrado.

        Raises:
            AssetGroupNotFoundError: Si no existe o es de otro usuario.
        """
        with UnitOfWork() as uow:
            repository = AssetGroupRepository(uow)
            group = repository.get_by_id_and_user(group_id, user_id)
            if group is None:
                raise AssetGroupNotFoundError(group_id)
            name = group.name
            repository.delete(group)
        return name

    # ---------------------------------------------------------------- análisis

    def assess_group(self, user_id: int, group_id: int) -> dict:
        """El riesgo de movimiento lateral de los hosts de un grupo.

        Args:
            user_id: Dueño del grupo.
            group_id: Clave primaria del grupo.

        Returns:
            dict: ``scope`` (``type``, ``id``, ``name``, ``cidr``), ``hostCount``
                y ``risks`` (ver ``_format_risk``), de mayor a menor puntuación.

        Raises:
            AssetGroupNotFoundError: Si el grupo no existe o es de otro usuario.
        """
        with UnitOfWork() as uow:
            group = AssetGroupRepository(uow).get_by_id_and_user(group_id, user_id)
            if group is None:
                raise AssetGroupNotFoundError(group_id)
            network = ipaddress.ip_network(group.cidr, strict=False)
            repository = ScanRepository(uow)
            scans = repository.get_latest_finished_scans_by_host(user_id)
            hosts = {host.id: host for host in repository.get_hosts_by_ids([scan.host_id for scan in scans])}
            members = [(scan, hosts[scan.host_id]) for scan in scans
                       if scan.host_id in hosts and _is_inside(hosts[scan.host_id].ip_address, network)]
            group_hosts = _group_hosts(repository, members, self._resolve_addresses)
            scope = {"type": "group", "id": group.id, "name": group.name, "cidr": group.cidr}
        return _result(scope, f"group:{group_id}", group_hosts)

    def assess_scan(self, user_id: int, scan_id: int) -> dict:
        """El riesgo de movimiento lateral de los hosts de un escaneo de red.

        Un escaneo de red es el padre de un escaneo por host; se analiza el
        último estado de cada uno. Un escaneo de un solo host no tiene por dónde
        moverse y no produce riesgos.

        Args:
            user_id: Dueño del escaneo.
            scan_id: Clave primaria del escaneo de red (el padre).

        Returns:
            dict: ``scope`` (``type``, ``id``, ``target``), ``hostCount`` y
                ``risks`` (ver ``_format_risk``).

        Raises:
            ScanNotFoundError: Si el escaneo no existe o es de otro usuario.
        """
        with UnitOfWork() as uow:
            assert_owned(ScanRepository, scan_id, user_id, ScanNotFoundError, uow=uow)
            repository = ScanRepository(uow)
            scan = repository.get_by_id(scan_id)
            children = [child for child in repository.get_child_scans(scan_id)
                        if child.host_id is not None]
            hosts = {host.id: host for host in repository.get_hosts_by_ids(
                [child.host_id for child in children])}
            members = [(child, hosts[child.host_id]) for child in children if child.host_id in hosts]
            group_hosts = _group_hosts(repository, members, self._resolve_addresses)
            scope = {"type": "scan", "id": scan.id, "target": scan.target}
        return _result(scope, f"scan:{scan_id}", group_hosts)


def _is_inside(address: str, network) -> bool:
    """Si una dirección cae dentro de una red.

    Args:
        address: La IP en texto.
        network: La red (``ipaddress.ip_network``).

    Returns:
        bool: ``True`` si es una IP válida de la misma versión y está dentro.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.version == network.version and parsed in network


def _group_hosts(repository: ScanRepository, members: list,
                 resolve_addresses: Callable[[str], Sequence[str]]) -> List[GroupHost]:
    """Los hosts de un análisis, con sus direcciones y sus hallazgos abiertos.

    Args:
        repository: El repositorio de escaneos de la transacción en curso.
        members: Pares ``(escaneo, host)``: el último escaneo de cada host.

    Returns:
        List[GroupHost]: Como mucho :data:`MAX_HOSTS_PER_ANALYSIS`, ordenados
            por nombre.
    """
    group_hosts: List[GroupHost] = []
    for scan, host in sorted(members, key=lambda pair: pair[1].hostname)[:MAX_HOSTS_PER_ANALYSIS]:
        addresses = [host.ip_address]
        if is_hostname(host.hostname):
            addresses += [address for address in resolve_addresses(host.hostname)
                          if address not in addresses]
        findings = []
        for finding in repository.get_findings_by_scan(scan.id):
            if finding.state not in _OPEN_STATES:
                continue
            view = finding.snapshot
            view["state"] = finding.state
            findings.append(view)
        group_hosts.append(GroupHost(host.id, host.hostname, tuple(addresses), tuple(findings)))
    return group_hosts

def _result(scope: dict, group_key: str, group_hosts: List[GroupHost]) -> dict:
    """Ejecuta el análisis puro y le da la forma de la API.

    Args:
        scope: Qué se analizó, para la respuesta.
        group_key: La clave que entra en la identidad de cada riesgo.
        group_hosts: Los hosts del análisis.

    Returns:
        dict: ``scope``, ``hostCount`` y ``risks``.
    """
    risks = assess_lateral_risk(group_key, group_hosts)
    return {"scope": scope, "hostCount": len(group_hosts),
            "risks": [_format_risk(risk) for risk in risks]}
