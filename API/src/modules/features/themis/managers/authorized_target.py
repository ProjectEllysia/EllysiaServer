"""AuthorizedTargetManager — el registro de objetivos autorizados.

Extraído de ``lybra/engine.py``: no comparte modelo, repositorio ni lógica con
``LybraEngineManager`` — es un gate legal transversal, consultado también por
``format_scan`` y, en el futuro, por cualquier operación que toque la red del
objetivo. Vivía junto al motor solo porque Lybra fue su primer consumidor.
"""

from __future__ import annotations

import ipaddress
import logging
import socket

from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from ..repositories import AuthorizedTargetRepository
from ..model import AuthorizedTarget
from ..services.parsing import is_hostname
from ..exceptions import (
    AuthorizedTargetNotFoundError,
    DuplicateAuthorizedTargetError,
    IPValidationError,
)

logger = logging.getLogger(__name__)


class AuthorizedTargetManager:
    """CRUD y comprobación de pertenencia para el registro de objetivos autorizados.

    Registro de objetivos autorizados. Antes de que Lybra ejecute
    cualquier operación que toque la red del objetivo (autodescubrimiento propio,
    fingerprinting propio, comprobaciones activas del runtime), el objetivo debe
    estar en este registro por usuario. Es un gate legal, no de red o de
    privilegios: complementa, no sustituye, el rechazo de IPs privadas que ya
    hace ``ScanManager.validate_ip``.
    """

    @staticmethod
    def _normalize(target: str) -> str:
        """Valida ``target`` como IP o CIDR y devuelve su forma canónica."""
        try:
            return str(ipaddress.ip_network(target.strip(), strict=False))
        except ValueError as exc:
            raise IPValidationError(
                message=f"'{target}' no es una IP ni un CIDR válido",
                ip_spec=target,
            ) from exc

    def add(self, user_id: int, target: str, label: str | None = None) -> AuthorizedTarget:
        """Añade un objetivo al registro del usuario. Rechaza duplicados."""
        normalized = self._normalize(target)
        with UnitOfWork() as uow:
            repo = AuthorizedTargetRepository(uow)
            if repo.get_by_target_and_user(normalized, user_id):
                raise DuplicateAuthorizedTargetError(normalized)
            entry = AuthorizedTarget(user_id=user_id, target=normalized, label=label or None)
            repo.save(entry)
        logger.info(f"Objetivo autorizado '{normalized}' añadido por usuario {user_id}")
        return entry

    def list(self, user_id: int) -> list[AuthorizedTarget]:
        """Lista el registro completo del usuario."""
        return build_repository(AuthorizedTargetRepository).get_by_user(user_id)

    def remove(self, target_id: int, user_id: int) -> str:
        """Elimina una entrada del registro, verificando propiedad.

        Returns:
            El target (IP/CIDR) de la entrada eliminada.
        """
        with UnitOfWork() as uow:
            repo = AuthorizedTargetRepository(uow)
            entry = repo.get_by_id_and_user(target_id, user_id)
            if entry is None:
                raise AuthorizedTargetNotFoundError(target_id)
            target = entry.target
            repo.delete(entry)
        logger.info(f"Objetivo autorizado {target_id} eliminado por usuario {user_id}")
        return target

    @staticmethod
    def is_authorized(user_id: int, target: str) -> bool:
        """Si ``target`` está dentro del registro de objetivos autorizados del usuario.

        El registro guarda IPs y rangos. Una IP está autorizada si cae en alguna
        entrada. Un **nombre** se resuelve y está autorizado sólo si **todas**
        sus direcciones lo están: autorizar un servidor no autoriza cualquier
        otro al que el nombre también apunte.

        Args:
            user_id: El usuario.
            target: Una IP o un nombre de host.

        Returns:
            bool: ``True`` si está autorizado; ``False`` si no, si el nombre
                no resuelve o si no es ni IP ni nombre.
        """
        try:
            addresses = [ipaddress.ip_address(target.strip())]
        except ValueError:
            if not is_hostname(target):
                return False
            try:
                addresses = [ipaddress.ip_address(info[4][0])
                             for info in socket.getaddrinfo(target.strip(), None)]
            except OSError:
                return False
        entries = build_repository(AuthorizedTargetRepository).get_by_user(user_id)
        networks = [ipaddress.ip_network(entry.target, strict=False) for entry in entries]
        return bool(addresses) and all(
            any(address in network for network in networks) for address in addresses)
