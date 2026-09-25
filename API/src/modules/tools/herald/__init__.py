"""
src.modules.tools.herald — Envío de correo transversal.

Módulo compartido, hermano de ``scribe``: cualquier módulo (Aegis, ...)
construye un ``EmailMessage`` y se lo pasa a un ``Mailer``, que delega en una
estrategia de envío inyectada (SMTP hoy; APIs de proveedores transaccionales
más adelante). La estrategia se decide por módulo desde ``SecOpsConfig.json``
mediante ``build_mailer``. Aegis depende de herald; herald no conoce a Aegis.

El asunto y el cuerpo se componen con ``render_email``, que renderiza las
plantillas Jinja de ``templates/<idioma>/`` sobre una envoltura de marca
común — ningún módulo vuelve a concatenar HTML a mano ni escribe el asunto en
el código.

Uso típico:
    >>> from src.modules.tools.herald import build_mailer, render_email, EmailMessage
    >>> rendered = render_email("campaign", language="es", pill_title="…", link="…")
    >>> mailer = build_mailer("aegis")
    >>> result = mailer.send(EmailMessage(
    ...     to="user@example.com", subject=rendered.subject,
    ...     html_body=rendered.html, text_body=rendered.text,
    ... ))
"""

from .inputs import EmailMessage, InlineImage, SendResult
from .strategies import EmailStrategy, SmtpStrategy
from .mailer import Mailer
from .factory import build_mailer
from .rendering import RenderedEmail, render_email
from .branding import LOGO_CONTENT_ID, apply_white_label, default_brand
from .exceptions import (
    EmailConnectionError,
    EmailSendError,
    EmailConfigurationError,
)

__all__ = [
    "EmailMessage",
    "InlineImage",
    "SendResult",
    "EmailStrategy",
    "SmtpStrategy",
    "Mailer",
    "build_mailer",
    "render_email",
    "RenderedEmail",
    "apply_white_label",
    "default_brand",
    "LOGO_CONTENT_ID",
    "EmailConnectionError",
    "EmailSendError",
    "EmailConfigurationError",
]
