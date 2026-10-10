"""
Proveedores de evidencia automática: lo que otros módulos ya saben y un auditor pide.

Themis sabe cuándo se escaneó por última vez, Aegis cómo responde la plantilla a la formación,
Hygeia qué equipos hay. Eunomia no puede importarlos —Themis ya importa Eunomia para el catálogo y
se formaría un ciclo, y Eunomia quedaría atada a cada módulo que aporte algo—, así que la
dependencia se invierte: cada módulo se da de alta aquí desde su propio ``__init__.py``, como en
``QueueRegistry``, y Eunomia recorre el registro sin conocer a nadie.

Una evidencia automática **no es un fichero ni se guarda**: se calcula al consultar el control.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping, Optional

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_MISSING = "missing"
#: Lo que se enseña cuando el proveedor falla; no lo devuelve ningún proveedor.
STATUS_UNAVAILABLE = "unavailable"
STATUSES = (STATUS_OK, STATUS_WARNING, STATUS_MISSING)


@dataclass(frozen=True)
class AutomaticEvidence:
    """Un dato que un módulo aporta a un control.

    Attributes:
        title: Qué es, en una línea (``"Último escaneo"``).
        summary: La cifra o la frase que lo resume, ya legible.
        data_date: Fecha a la que corresponden los datos, o ``None`` si no aplica.
        link: Ruta de la pantalla de origen en la SPA (``"/themis/escaneos"``), o ``""``.
        status: ``ok``, ``warning`` (hay algo que mirar) o ``missing`` (no hay datos).
    """

    title: str
    summary: str
    data_date: Optional[date] = None
    link: str = ""
    status: str = STATUS_OK


CollectHook = Callable[[int, str, str], list[AutomaticEvidence]]


@dataclass(frozen=True)
class EvidenceProvider:
    """Un módulo que aporta evidencias automáticas.

    Attributes:
        key: Identificador (``"themis.vulnerability_management"``), único en el registro.
        name: Nombre visible (``"Gestión de vulnerabilidades"``).
        controls: ``{marco: identificadores}`` de los controles a los que aporta. Los
            identificadores son los de la versión que el usuario tiene adoptada; un
            identificador que esa versión no tiene simplemente no se consulta.
        collect: ``(dueño efectivo, marco, identificador) -> evidencias``. Solo lee.
    """

    key: str
    name: str
    controls: Mapping[str, tuple[str, ...]]
    collect: CollectHook


class EvidenceProviderRegistry:
    """Registro de proveedores de evidencia automática."""

    _providers: dict[str, EvidenceProvider] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, key: str, *, name: str, controls: Mapping[str, tuple[str, ...]],
                 collect: CollectHook) -> None:
        """Da de alta un proveedor. Idempotente: registrar la misma ``key`` deja la última.

        Args:
            key: Identificador único del proveedor.
            name: Nombre visible.
            controls: ``{marco: identificadores}`` a los que aporta.
            collect: Función que calcula las evidencias de un control.
        """
        with cls._lock:
            cls._providers[key] = EvidenceProvider(key=key, name=name, controls=dict(controls), collect=collect)

    @classmethod
    def providers_for(cls, framework_key: str, identifier: str) -> list[EvidenceProvider]:
        """Los proveedores que aportan a un control, en orden de clave.

        Args:
            framework_key: Clave del marco.
            identifier: Identificador del control.
        """
        with cls._lock:
            found = [item for item in cls._providers.values() if identifier in item.controls.get(framework_key, ())]
        return sorted(found, key=lambda item: item.key)

    @classmethod
    def collect(cls, owner_user_id: int, framework_key: str, identifier: str) -> list[dict]:
        """Calcula las evidencias automáticas de un control.

        Un proveedor que falla no rompe la vista: se registra y sale como «no disponible».

        Args:
            owner_user_id: Dueño efectivo de los datos.
            framework_key: Clave del marco.
            identifier: Identificador del control.

        Returns:
            list[dict]: Un elemento por evidencia: ``providerKey``, ``providerName``, ``title``,
                ``summary``, ``dataDate``, ``link`` y ``status``. Un proveedor sin datos que
                devuelve una lista vacía no aparece.
        """
        results: list[dict] = []
        for provider in cls.providers_for(framework_key, identifier):
            try:
                items = provider.collect(owner_user_id, framework_key, identifier)
            except Exception:  # noqa: BLE001 — un proveedor ajeno no debe romper el detalle del control
                logger.exception("Proveedor de evidencia %s falló para %s:%s", provider.key, framework_key, identifier)
                results.append({"providerKey": provider.key, "providerName": provider.name,
                                "title": provider.name, "summary": "", "dataDate": None, "link": "",
                                "status": STATUS_UNAVAILABLE})
                continue
            for item in items:
                results.append({"providerKey": provider.key, "providerName": provider.name, "title": item.title,
                                "summary": item.summary, "dataDate": item.data_date, "link": item.link,
                                "status": item.status})
        return results
