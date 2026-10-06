from .base import (
    ActionResult, MailboxAuthenticationError, MailboxConnector, MailboxFolder, MessageRef, ServiceToken,
    SubscriptionInfo, TokenSet,
)
from .registry import MAILBOX_CONNECTORS, get_connector

# Importados por su efecto secundario: cada uno se da de alta en
# MAILBOX_CONNECTORS vía @register_connector al importarse. El
# paquete es el único punto que debe dispararlo — ver el docstring de
# registry.py sobre por qué éste no los importa directamente.
from . import gmail as _gmail  # noqa: F401
from . import microsoft as _microsoft  # noqa: F401
from . import imap as _imap  # noqa: F401
from .imap import ImapCredentials

__all__ = [
    "ActionResult", "ImapCredentials", "MailboxAuthenticationError", "MailboxConnector", "MailboxFolder",
    "MessageRef", "ServiceToken", "SubscriptionInfo", "TokenSet",
    "MAILBOX_CONNECTORS", "get_connector",
]
