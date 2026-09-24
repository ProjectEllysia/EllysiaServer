"""CheckPlanner — qué servicios de un re-escaneo no hace falta volver a sondear.

Cada escaneo Lybra repetía el trabajo entero: mismos puertos, mismo
fingerprint, mismos checks, aunque el objetivo no hubiera cambiado nada desde
la vez anterior. El motor ya tenía la información para evitarlo — el
*surface tracking* de ``HostService`` guarda producto, versión y CPE de cada
servicio visto en el escaneo anterior —, pero no se usaba para planificar
nada, sólo para el diff informativo de ``_detect_surface_changes``.

Este módulo cubre la regla más barata y menos arriesgada de las tres que
describe el roadmap: si el escaneo anterior ya identificó producto y versión
de un servicio en este mismo puerto/protocolo, no hace falta volver a
sondearlo por red para confirmarlo otra vez — se reutiliza esa identificación
y se deja que la detección por versión (que sí es barata, en memoria) vuelva
a consultar la base de conocimiento con ella. Las otras dos reglas del
roadmap (checks confirmados a ritmo reducido, ``aggressive`` sólo si la
superficie cambió) quedan fuera de este módulo: necesitan un presupuesto por
check que no existe todavía, y se dejan para una iteración posterior.

La identificación guardada **caduca**. Sólo se reutiliza si la sacó la
revisión actual del identificador (:data:`IDENTIFICATION_REVISION`) y hace
menos de ``maxAgeDays`` que se sondeó por red. Sin plazo, una versión leída
una vez se arrastraría para siempre: un servidor actualizado seguiría
cargando las vulnerabilidades de su versión vieja, y una mejora del
identificador —leer la revisión de distribución de un banner, por ejemplo—
no llegaría nunca a los equipos ya escaneados.

Deliberadamente conservador: **nunca** decide qué hallazgos mostrar, sólo qué
servicios no necesitan una sonda de red antes de la detección por versión.
La detección en sí (``LybraEngine.analyze``) se ejecuta siempre sobre todos
los servicios, sondeados o reutilizados — así que ningún hallazgo puede
cerrarse por "no se comprobó": el único ahorro es la sonda de red, nunca la
detección. Es lo que le permite a este módulo quedarse libre de ORM y de red,
como el resto de ``lybra/`` — no toma ninguna decisión que necesite lo uno ni
lo otro.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from src.modules.shared import utcnow_naive

from .engine import Service

#: La revisión de cómo identifica el motor producto y versión. Se guarda con
#: cada identificación (``HostService.identified_by``), y una identificación
#: de otra revisión no se reutiliza. **Se sube cada vez que cambie lo que el
#: fingerprinting extrae de un servicio**, para que los equipos ya escaneados
#: se vuelvan a sondear con el identificador nuevo. La revisión ``"2"`` es la
#: que conserva la revisión de distribución del banner de SSH.
IDENTIFICATION_REVISION = "2"


@dataclass(frozen=True)
class KnownService:
    """Lo que el surface tracking recuerda de un servicio del escaneo anterior.

    Sólo lleva los campos que ``CheckPlanner`` necesita — no es
    ``HostService`` en sí, para que este módulo no dependa de su ORM (la
    invariante que protege ``test_lybra_package_invariants.py``). El llamante
    (``managers/lybra/engine.py``, que sí puede tocar el ORM) construye una
    instancia por fila.

    Attributes:
        product: El producto identificado la última vez, o cadena vacía si
            nunca se resolvió.
        version: La versión identificada la última vez, o cadena vacía.
        cpe: El CPE resuelto la última vez, o ``None``.
        identified_at: Cuándo se sondeó por red para sacar esa identidad, o
            ``None`` si no consta. Por defecto ``None``.
        identified_by: La revisión del identificador que la sacó
            (:data:`IDENTIFICATION_REVISION` de entonces), o ``None`` si no
            consta. Por defecto ``None``.
    """
    product: str
    version: str
    cpe: Optional[str]
    identified_at: Optional[datetime] = None
    identified_by: Optional[str] = None


def _prior_for(
    previous_surface: Dict[Tuple[int, str], KnownService], service: Service,
) -> Optional[KnownService]:
    """Lo que el surface tracking recordaba de ``service``, o ``None``.

    Función de módulo, no método: no necesita más estado que lo que recibe
    por parámetro, así que no hay razón para que viva colgada de ``self``.
    """
    if service.port is None:
        return None
    return previous_surface.get((service.port, service.protocol or "tcp"))


class CheckPlanner:
    """Decide qué servicios de un re-escaneo pueden saltarse el fingerprint de red.

    Args:
        previous_surface: Mapa ``(port, protocol) -> KnownService`` con lo que
            el surface tracking sabía de cada servicio antes de este escaneo.
            La misma clave que usa ``LybraEngineManager._surface_key`` para un
            servicio con puerto — los servicios de inventario (sin puerto)
            nunca se pueden reutilizar por la misma razón que nunca se prueban
            por red: no hay nada que sondear.
        max_age_days: Cuántos días vale una identificación antes de volver a
            sondear el servicio. Viene de
            ``features.themis.scanners.lybra.planner.maxAgeDays``.
        now: El instante con el que se mide la antigüedad. Por defecto
            ``None``, que significa «ahora» (UTC sin zona, como el resto de
            fechas de la base de datos).
    """

    def __init__(
        self,
        previous_surface: Dict[Tuple[int, str], KnownService],
        max_age_days: int,
        now: Optional[datetime] = None,
    ) -> None:
        self._previous_surface = previous_surface
        self._max_age = timedelta(days=max_age_days)
        self._now = now or utcnow_naive()

    def needs_fingerprint(self, service: Service) -> bool:
        """Si ``service`` debe sondearse por red antes de analizarlo.

        Sólo se salta la sonda cuando el escaneo anterior dejó en este mismo
        puerto y protocolo una identificación **completa, vigente y de la
        revisión actual**: producto y versión, sondeados por red hace menos de
        ``max_age_days`` y con :data:`IDENTIFICATION_REVISION`.

        Args:
            service: El servicio del escaneo en curso.

        Returns:
            bool: ``False`` si se puede reutilizar lo que se sabía; ``True``
                en cualquier otro caso: un servicio nuevo, uno cuyo puerto
                cambió de protocolo, uno que nunca se llegó a identificar, uno
                identificado por otra revisión del motor o uno cuya
                identificación caducó (o no tiene fecha).
        """
        prior = _prior_for(self._previous_surface, service)
        if not (prior and prior.product and prior.version):
            return True
        if prior.identified_by != IDENTIFICATION_REVISION or prior.identified_at is None:
            return True
        return self._now - prior.identified_at > self._max_age

    def apply_cached_identity(self, service: Service) -> Service:
        """Aplica a ``service`` el producto/versión/CPE que ya se conocían.

        Sólo tiene sentido llamarlo cuando :meth:`needs_fingerprint` devolvió
        ``False`` para el mismo servicio; con un servicio nuevo no hay nada
        que reutilizar y el resultado sería idéntico a la entrada.
        """
        prior = _prior_for(self._previous_surface, service)
        if prior is None:
            return service
        return replace(
            service, product=prior.product, version=prior.version,
            cpe=prior.cpe or service.cpe,
        )

    def partition(self, services: list) -> Tuple[list, list]:
        """Separa ``services`` en los que hay que sondear y los que no.

        Returns:
            tuple: ``(to_probe, to_reuse)``, cada uno en el mismo orden
                relativo en que aparecían en ``services``. El llamante decide
                cómo recombinarlos manteniendo el orden original — este
                método no lo hace por sí mismo porque no sabe qué se hará con
                ``to_probe`` (una sonda de red que ``planner.py`` no puede
                ejecutar).
        """
        to_probe = [service for service in services if self.needs_fingerprint(service)]
        to_reuse = [service for service in services if not self.needs_fingerprint(service)]
        return to_probe, to_reuse
