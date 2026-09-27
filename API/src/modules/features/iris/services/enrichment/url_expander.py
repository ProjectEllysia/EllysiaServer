"""
Seguir una URL de un correo hasta la página a la que lleva de verdad.

Iris analiza la URL escrita en el mensaje; aquí se ve el resto del camino: los
acortadores, las redirecciones encadenadas, el *cloaking* (una URL inocente que
redirige a otra según quién la pide) y el dominio final. Cada salto pasa por
``egress.fetch_following``, así que ninguno alcanza la red interna, y queda
registrado con su código, su IP y su certificado.

No se renderiza la página ni se ejecuta nada de ella: solo se lee el principio
del HTML para sacar su ``<title>``, que ya dice mucho («Iniciar sesión en tu
cuenta de Microsoft» en un dominio que no es de Microsoft).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from ..text import registrable_domain
from .egress import RedirectChain, fetch_following

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

#: Longitud máxima del título que se guarda.
_MAX_TITLE_LENGTH = 300


@dataclass(frozen=True)
class UrlExpansionResult:
    """A dónde llevó una URL.

    Attributes:
        hops: Cada salto, serializado (``url``, ``status``, ``peerAddress``,
            ``certificate``, ``error``).
        final_url: Última URL que respondió, o ``None`` si ninguna.
        final_domain: Su nombre de host, o ``None``.
        final_status: Su código HTTP, o ``None``.
        page_title: Título de la página final, o ``None``.
        content_type: Tipo de contenido de la página final, o ``None``.
        is_domain_changed: Si el dominio registrable final no es el de partida;
            ``None`` si no hubo página final.
    """

    hops: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    final_url: Optional[str] = None
    final_domain: Optional[str] = None
    final_status: Optional[int] = None
    page_title: Optional[str] = None
    content_type: Optional[str] = None
    is_domain_changed: Optional[bool] = None


def expand_url(url: str, *, max_redirects: int, timeout_seconds: float, max_bytes: int) -> UrlExpansionResult:
    """Sigue una URL y resume a dónde llegó.

    Nunca lanza por la red: un salto que falla queda con su ``error``.

    Args:
        url: URL de partida.
        max_redirects: Redirects que se siguen como mucho.
        timeout_seconds: Tiempo máximo de cada operación de red.
        max_bytes: Bytes que se leen de cada salto.

    Returns:
        UrlExpansionResult: Los saltos y el destino final.
    """
    chain = fetch_following(url, max_redirects=max_redirects, timeout_seconds=timeout_seconds,
                            max_bytes=max_bytes, accept="text/html,*/*;q=0.5")
    return summarize_chain(url, chain)


def summarize_chain(url: str, chain: RedirectChain) -> UrlExpansionResult:
    """Resume una cadena de redirects ya recorrida.

    Args:
        url: URL de partida.
        chain: La cadena.

    Returns:
        UrlExpansionResult: Los saltos serializados y el destino final.
    """
    hops = tuple(
        {"url": hop.url, "status": hop.status, "peerAddress": hop.peer_address,
         "certificate": hop.certificate, "error": hop.error}
        for hop in chain.hops
    )
    final = chain.final
    if final is None:
        return UrlExpansionResult(hops=hops)
    final_domain = (urlsplit(final.url).hostname or "").lower() or None
    content_type = (final.headers.get("content-type") or "").split(";")[0].strip().lower() or None
    return UrlExpansionResult(
        hops=hops,
        final_url=final.url,
        final_domain=final_domain,
        final_status=final.status,
        page_title=_page_title(final.body) if content_type in (None, "text/html", "application/xhtml+xml") else None,
        content_type=content_type,
        is_domain_changed=_registrable(final_domain) != _registrable(urlsplit(url).hostname),
    )


def _registrable(host: Optional[str]) -> Optional[str]:
    """Dominio registrable de un host, o el host si no se puede calcular.

    Args:
        host: Nombre de host, o ``None``.

    Returns:
        Optional[str]: El dominio registrable en minúsculas.
    """
    if not host:
        return None
    return registrable_domain(host.lower()) or host.lower()


def _page_title(body: bytes) -> Optional[str]:
    """``<title>`` de un HTML, sin entidades ni espacios de más.

    Args:
        body: Principio del HTML.

    Returns:
        Optional[str]: El título, o ``None`` si no hay.
    """
    match = _TITLE_RE.search(body.decode("utf-8", errors="replace"))
    if not match:
        return None
    title = " ".join(html.unescape(match.group(1)).split())
    return title[:_MAX_TITLE_LENGTH] or None
