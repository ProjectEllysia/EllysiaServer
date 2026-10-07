"""AuthorizedTargetManager — el registro de objetivos autorizados.

Extraído de ``lybra/engine.py``: no comparte modelo, repositorio ni lógica con
``LybraEngineManager`` — es un gate legal transversal, consultado también por
``format_scan`` y por cualquier operación que toque la red del objetivo (los
escaneos activos y, ahora, las sondas de exposición en la nube). Vivía junto al
motor solo porque Lybra fue su primer consumidor.

El registro guarda tres formas de objetivo, que se distinguen por la propia
cadena canónica sin columna aparte: una **IP o CIDR**, un **dominio** (que se
autoriza a sí mismo y a sus subdominios) y un **recurso cloud**
``proveedor:identificador``. Cada forma tiene su propia comprobación de
pertenencia, porque autorizan cosas distintas: una IP autoriza los paquetes que
se le mandan, un dominio autoriza sus subdominios (para el takeover) y un
recurso cloud se autoriza a sí mismo, exactamente.
"""

from __future__ import annotations

import ipaddress
import logging
import socket

from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository
from ..repositories import AuthorizedTargetRepository
from ..model import AuthorizedTarget
from ..lybra import normalize_domain, parse_cloud_resource
from ..services.parsing import is_hostname
from ..exceptions import (
    AuthorizationDeclarationOutdatedError,
    AuthorizationDeclarationRequiredError,
    AuthorizedTargetNotFoundError,
    DuplicateAuthorizedTargetError,
    InvalidAuthorizedTargetError,
    IPValidationError,
    TargetNotAuthorizedError,
)

logger = logging.getLogger(__name__)

#: Versión vigente del texto de la declaración que se enseña al autorizar un
#: objetivo («declaro que soy titular de este sistema o que tengo autorización
#: escrita de su titular para analizarlo»). Tiene que coincidir con la que
#: declara ``authorizationDeclaration.js`` y cambia a la vez que la política de uso
#: aceptable; ``test_authorization_declaration_version_matches_the_spa`` lo comprueba.
AUTHORIZATION_DECLARATION_VERSION = "2026-10-07"


def _network_of(target: str):
    """La red que representa un objetivo, o ``None`` si no es una IP ni un CIDR.

    Args:
        target: La cadena de una entrada del registro.

    Returns:
        ipaddress._BaseNetwork | None: La red canónica, o ``None`` si la cadena
            no es una dirección ni un rango (un dominio o un recurso cloud lo
            son, y se ignoran para la autorización por red).
    """
    try:
        return ipaddress.ip_network(target.strip(), strict=False)
    except ValueError:
        return None


def _domain_of(target: str):
    """El dominio que representa una entrada del registro, o ``None``.

    Un recurso cloud lleva ``:`` y nunca es un dominio; una IP o un CIDR
    tampoco. Todo lo demás se intenta normalizar como dominio.

    Args:
        target: La cadena de una entrada del registro.

    Returns:
        Optional[str]: El dominio normalizado, o ``None`` si la entrada no es un
            dominio.
    """
    if ":" in target or _network_of(target) is not None:
        return None
    return normalize_domain(target)


def _canonical_target(target: str) -> str:
    """Valida un objetivo de cualquiera de las tres formas y lo canoniza.

    Prueba, en orden, IP/CIDR, recurso cloud y dominio. El orden importa: una
    IP nunca parece un dominio, y un recurso cloud lleva ``:``, así que no hay
    ambigüedad.

    Args:
        target: El texto tal como lo declaró el usuario.

    Returns:
        str: La cadena canónica que se guarda: la red (``"10.0.0.0/24"``), el
            recurso cloud (``"s3:mi-bucket"``) o el dominio (``"example.com"``).

    Raises:
        InvalidAuthorizedTargetError: Si ``target`` no es ninguna de las tres formas.
    """
    network = _network_of(target)
    if network is not None:
        return str(network)
    resource = parse_cloud_resource(target)
    if resource is not None:
        return resource.canonical
    domain = normalize_domain(target)
    if domain is not None:
        return domain
    raise InvalidAuthorizedTargetError(target)


def _domain_covers(authorized_domain: str, candidate: str) -> bool:
    """Si un dominio autorizado cubre a otro: él mismo o un subdominio suyo.

    Autorizar ``example.com`` cubre ``example.com`` y ``dev.example.com``, pero
    no un hermano (``otro.com``) ni un sufijo engañoso (``evil-example.com``,
    que no termina en ``.example.com``).

    Args:
        authorized_domain: El dominio que el usuario autorizó, normalizado.
        candidate: El dominio que se comprueba, normalizado.

    Returns:
        bool: ``True`` si ``candidate`` es ``authorized_domain`` o termina en
            ``.authorized_domain``.
    """
    return candidate == authorized_domain or candidate.endswith("." + authorized_domain)


class AuthorizedTargetManager:
    """CRUD y comprobación de pertenencia para el registro de objetivos autorizados.

    Registro de objetivos autorizados. Antes de que Lybra ejecute cualquier
    operación que toque la red del objetivo (autodescubrimiento propio,
    fingerprinting propio, comprobaciones activas del runtime, sondas de
    exposición en la nube), el objetivo debe estar en este registro por usuario.
    Es un gate legal, no de red o de privilegios: complementa, no sustituye, el
    rechazo de IPs privadas que ya hace ``ScanManager.validate_ip``.
    """

    @staticmethod
    def _normalize(target: str) -> str:
        """Valida ``target`` como IP o CIDR y devuelve su forma canónica.

        Args:
            target: El texto a validar.

        Returns:
            str: La red en su forma canónica (``"10.0.0.0/24"``).

        Raises:
            IPValidationError: Si ``target`` no es una IP ni un CIDR.
        """
        network = _network_of(target)
        if network is None:
            raise IPValidationError(
                message=f"'{target}' no es una IP ni un CIDR válido",
                ip_spec=target,
            )
        return str(network)

    def assert_declaration(self, accepted: bool, version: str) -> None:
        """Exige que el usuario haya aceptado la versión vigente de la declaración.

        Args:
            accepted: Si el usuario marcó la aceptación.
            version: La versión del texto que se le enseñó.

        Raises:
            AuthorizationDeclarationRequiredError: Si no la aceptó.
            AuthorizationDeclarationOutdatedError: Si aceptó una versión que
                ya no es la vigente.
        """
        if not accepted:
            raise AuthorizationDeclarationRequiredError()
        if version != AUTHORIZATION_DECLARATION_VERSION:
            raise AuthorizationDeclarationOutdatedError(version, AUTHORIZATION_DECLARATION_VERSION)

    def add(
        self,
        user_id: int,
        target: str,
        label: str | None = None,
        declaration_version: str | None = None,
        declaration_ip: str | None = None,
    ) -> AuthorizedTarget:
        """Añade un objetivo al registro del usuario. Rechaza duplicados.

        Args:
            user_id: Dueño de la entrada.
            target: El objetivo, en cualquiera de las tres formas admitidas
                (IP/CIDR, dominio o recurso cloud).
            label: Nota libre opcional. Por defecto ``None``.
            declaration_version: Versión de la declaración que el usuario
                aceptó (``AUTHORIZATION_DECLARATION_VERSION``). La valida el
                endpoint con ``assert_declaration``; aquí solo se guarda. Por
                defecto ``None``: una entrada creada sin declaración.
            declaration_ip: IP desde la que la aceptó. Por defecto ``None``.

        Returns:
            AuthorizedTarget: La entrada ya guardada.

        Raises:
            InvalidAuthorizedTargetError: Si ``target`` no es una forma válida.
            DuplicateAuthorizedTargetError: Si ya existe esa entrada canónica.
        """
        normalized = _canonical_target(target)
        with UnitOfWork() as uow:
            repo = AuthorizedTargetRepository(uow)
            if repo.get_by_target_and_user(normalized, user_id):
                raise DuplicateAuthorizedTargetError(normalized)
            entry = AuthorizedTarget(
                user_id=user_id, target=normalized, label=label or None,
                declaration_version=declaration_version, declaration_ip=declaration_ip,
            )
            repo.save(entry)
        logger.info(f"Objetivo autorizado '{normalized}' añadido por usuario {user_id}")
        return entry

    def list(self, user_id: int) -> list[AuthorizedTarget]:
        """Lista el registro completo del usuario."""
        return build_repository(AuthorizedTargetRepository).get_by_user(user_id)

    def remove(self, target_id: int, user_id: int) -> str:
        """Elimina una entrada del registro, verificando propiedad.

        Returns:
            El target canónico de la entrada eliminada.
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

        Sólo mira las entradas de IP/CIDR: los dominios y los recursos cloud del
        registro autorizan otras cosas (subdominios y buckets), no direcciones.
        Una IP está autorizada si cae en alguna entrada de red. Un **nombre** se
        resuelve y está autorizado sólo si **todas** sus direcciones lo están:
        autorizar un servidor no autoriza cualquier otro al que el nombre
        también apunte.

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
        networks = [network for network in (_network_of(entry.target) for entry in entries)
                    if network is not None]
        return bool(addresses) and all(
            any(address in network for network in networks) for address in addresses)

    def assert_authorized(self, user_id: int, target: str) -> None:
        """Exige que ``target`` esté en el registro de objetivos autorizados del usuario.

        Es el cerrojo que comparten los cuatro escáneres: Nmap, Nikto, Nuclei y
        el autodescubrimiento de Lybra. Se llama desde el ``run_scan`` de cada
        uno, por donde entran tanto el endpoint HTTP como los escaneos
        programados, así que un escaneo programado no esquiva la declaración del
        usuario.

        Args:
            user_id: El usuario que lanza el escaneo.
            target: Una IP o un nombre de host, ya resuelto si venía como URL.

        Raises:
            TargetNotAuthorizedError: Si no está autorizado (ver ``is_authorized``).
        """
        if not self.is_authorized(user_id, target):
            raise TargetNotAuthorizedError(target)

    @staticmethod
    def is_domain_authorized(user_id: int, domain: str) -> bool:
        """Si un dominio (o subdominio suyo) está cubierto por el registro del usuario.

        La comprobación que necesita el takeover de subdominios: los subdominios
        candidatos salen de un escaneo pasivo del dominio, y autorizar el
        dominio padre autoriza tocarlos. Un dominio hermano o un sufijo engañoso
        (``evil-example.com`` frente a ``example.com``) **no** quedan cubiertos.

        Args:
            user_id: El usuario.
            domain: El dominio o subdominio que se comprueba.

        Returns:
            bool: ``True`` si alguna entrada de dominio del registro lo cubre;
                ``False`` si no, o si ``domain`` no es un nombre de dominio
                válido.
        """
        normalized = normalize_domain(domain)
        if normalized is None:
            return False
        entries = build_repository(AuthorizedTargetRepository).get_by_user(user_id)
        authorized_domains = [authorized for authorized in
                              (_domain_of(entry.target) for entry in entries)
                              if authorized is not None]
        return any(_domain_covers(authorized, normalized) for authorized in authorized_domains)

    @staticmethod
    def is_cloud_resource_authorized(user_id: int, resource: str) -> bool:
        """Si un recurso cloud está declarado, exactamente, en el registro del usuario.

        Un bucket o una base no tienen red que acotar: se autorizan a sí mismos
        y sólo a sí mismos, por su forma canónica. Un recurso inválido nunca
        está autorizado.

        Args:
            user_id: El usuario.
            resource: El recurso, en forma ``proveedor:identificador``.

        Returns:
            bool: ``True`` si su forma canónica coincide con una entrada del
                registro; ``False`` si no, o si ``resource`` no es un recurso
                cloud válido.
        """
        parsed = parse_cloud_resource(resource)
        if parsed is None:
            return False
        entry = build_repository(AuthorizedTargetRepository).get_by_target_and_user(
            parsed.canonical, user_id)
        return entry is not None
