"""
Registro proveedor -> conector para el mailbox connector de Iris.

A diferencia de ``tools/herald``/``tools/scribe`` (una estrategia por
*módulo*, elegida en ``SecOpsConfig.json``), aquí la selección es por dato:
cada ``IrisMailboxConnection`` lleva su propio ``provider``, así que un
diccionario simple basta -- ver ``base.py`` para la justificación completa.

El alta es declarativa (B4/B5, ``@register_connector``) junto a cada clase
de conector, no una lista aparte en este fichero. Este módulo no importa
``.gmail``/``.microsoft`` directamente — harían falta de vuelta a
``register_connector`` de aquí, un ciclo real (confirmado con el import
directo que ya hace ``tests/unit/test_iris_mailbox_connectors.py``). Quien
dispara el registro es ``mailbox/__init__.py``, que Python siempre ejecuta
antes que cualquier submódulo del paquete.
"""

from __future__ import annotations

from typing import Optional

from .base import MailboxConnector

MAILBOX_CONNECTORS: dict[str, type[MailboxConnector]] = {}


def register_connector(name: str):
    """Decorador: da de alta la clase decorada como conector de ``name``."""
    def decorator(cls: type[MailboxConnector]) -> type[MailboxConnector]:
        MAILBOX_CONNECTORS[name] = cls
        return cls
    return decorator


def get_connector(provider: str, redirect_uri: str, folder: Optional[str] = None, **options) -> MailboxConnector:
    """Instancia el conector del ``provider`` dado.

    Args:
        provider: ``gmail``, ``microsoft`` o ``imap``.
        redirect_uri: URL de vuelta del flujo OAuth.
        folder: Carpeta que vigila; ``None`` para la bandeja de entrada.
        **options: Lo que ese conector necesita además: ``mailbox_address``
            (buzón que se lee con una cuenta de servicio) o ``credentials``
            (``ImapCredentials``).

    Returns:
        MailboxConnector: El conector.

    Raises:
        ValueError: Si ``provider`` no es uno de los soportados.
    """
    connector_cls = MAILBOX_CONNECTORS.get(provider)
    if connector_cls is None:
        raise ValueError(
            f"Proveedor de buzón desconocido: '{provider}'. "
            f"Soportados: {', '.join(sorted(MAILBOX_CONNECTORS))}."
        )
    return connector_cls(redirect_uri, folder=folder, **options)
