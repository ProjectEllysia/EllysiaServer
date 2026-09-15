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
from typing import Dict, Optional, Tuple

from .engine import Service


@dataclass(frozen=True)
class KnownService:
    """Lo que el surface tracking recuerda de un servicio del escaneo anterior.

    Sólo lleva los tres campos que ``CheckPlanner`` necesita — no es
    ``HostService`` en sí, para que este módulo no dependa de su ORM (la
    invariante que protege ``test_lybra_package_invariants.py``). El llamante
    (``managers/lybra/engine.py``, que sí puede tocar el ORM) construye una
    instancia por fila.

    Attributes:
        product: El producto identificado la última vez, o cadena vacía si
            nunca se resolvió.
        version: La versión identificada la última vez, o cadena vacía.
        cpe: El CPE resuelto la última vez, o ``None``.
    """
    product: str
    version: str
    cpe: Optional[str]


class CheckPlanner:
    """Decide qué servicios de un re-escaneo pueden saltarse el fingerprint de red.

    Args:
        previous_surface: Mapa ``(port, protocol) -> KnownService`` con lo que
            el surface tracking sabía de cada servicio antes de este escaneo.
            La misma clave que usa ``LybraEngineManager._surface_key`` para un
            servicio con puerto — los servicios de inventario (sin puerto)
            nunca se pueden reutilizar por la misma razón que nunca se prueban
            por red: no hay nada que sondear.
    """

    def __init__(self, previous_surface: Dict[Tuple[int, str], KnownService]) -> None:
        self._previous_surface = previous_surface

    def _prior_for(self, service: Service) -> Optional[KnownService]:
        if service.port is None:
            return None
        return self._previous_surface.get((service.port, service.protocol or "tcp"))

    def needs_fingerprint(self, service: Service) -> bool:
        """True si ``service`` debe sondearse por red antes de analizarlo.

        Falso únicamente cuando el escaneo anterior identificó ya producto
        **y** versión en este mismo puerto/protocolo — un servicio nuevo, uno
        cuyo puerto cambió de protocolo, o uno que nunca se llegó a
        identificar la vez anterior, siempre se sondea.
        """
        prior = self._prior_for(service)
        return not (prior and prior.product and prior.version)

    def apply_cached_identity(self, service: Service) -> Service:
        """Aplica a ``service`` el producto/versión/CPE que ya se conocían.

        Sólo tiene sentido llamarlo cuando :meth:`needs_fingerprint` devolvió
        ``False`` para el mismo servicio; con un servicio nuevo no hay nada
        que reutilizar y el resultado sería idéntico a la entrada.
        """
        prior = self._prior_for(service)
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
