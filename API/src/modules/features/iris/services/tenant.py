"""
Inteligencia de Iris compartida dentro de una organización.

Toda la inteligencia de Iris es por usuario salvo esto, que es la única forma
en que algo de un miembro llega a otro. Por eso lo compartido son solo
**agregados anonimizados**:

- indicadores (dominios, URLs, hashes) que aparecieron en correos sospechosos
  o de phishing de **varios** miembros: cuántos miembros y cuántos análisis,
  nunca quiénes ni cuáles;
- dominios de los que **varios** miembros reciben correo legítimo (los
  «dominios frecuentes» de la organización);
- y la política que fija el dueño: sus dominios y marcas protegidos.

Un agregado solo sale si lo han visto al menos ``minMembers`` miembros
distintos (k-anonimato): con menos, «esto solo lo recibió una persona» señala
a esa persona. Nunca cruza un correo, un análisis, una dirección de correo ni
un id de miembro. Solo cuentan los miembros que han dado su consentimiento.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from .text import is_free_provider, levenshtein, normalize_homoglyphs, registrable_label, url_host

#: Máximo de dominios o marcas protegidos por organización.
MAX_PROTECTED_ENTRIES = 50

#: Longitud máxima de una marca protegida.
_MAX_BRAND_LENGTH = 64

_DOMAIN_RE = re.compile(r"^(?=.{3,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

#: Una etiqueta más corta no se compara por parecido: «ab» se parece a todo.
_MIN_LOOKALIKE_LABEL = 4


def normalize_protected_domains(domains: Iterable[str]) -> List[str]:
    """Limpia la lista de dominios protegidos de una organización.

    Args:
        domains: Dominios tal como los escribió el dueño.

    Returns:
        List[str]: En minúsculas, sin ``www.`` ni punto final, sin duplicados
            y ordenados.

    Raises:
        ValueError: Si alguno no es un dominio o son más de
            ``MAX_PROTECTED_ENTRIES``; el mensaje es el texto para el usuario.
    """
    cleaned = set()
    for domain in domains:
        value = (domain or "").strip().lower().rstrip(".")
        value = value[4:] if value.startswith("www.") else value
        if not value:
            continue
        if not _DOMAIN_RE.match(value):
            raise ValueError(f"«{value}» no es un dominio válido.")
        cleaned.add(value)
    if len(cleaned) > MAX_PROTECTED_ENTRIES:
        raise ValueError(f"Puedes proteger como mucho {MAX_PROTECTED_ENTRIES} dominios.")
    return sorted(cleaned)


def normalize_protected_brands(brands: Iterable[str]) -> List[str]:
    """Limpia la lista de marcas protegidas de una organización.

    Args:
        brands: Marcas tal como las escribió el dueño.

    Returns:
        List[str]: En minúsculas, sin espacios sobrantes, sin duplicados y
            ordenadas.

    Raises:
        ValueError: Si alguna es demasiado larga o son más de
            ``MAX_PROTECTED_ENTRIES``; el mensaje es el texto para el usuario.
    """
    cleaned = set()
    for brand in brands:
        value = " ".join((brand or "").split()).lower()
        if not value:
            continue
        if len(value) > _MAX_BRAND_LENGTH:
            raise ValueError(f"Una marca no puede pasar de {_MAX_BRAND_LENGTH} caracteres.")
        cleaned.add(value)
    if len(cleaned) > MAX_PROTECTED_ENTRIES:
        raise ValueError(f"Puedes proteger como mucho {MAX_PROTECTED_ENTRIES} marcas.")
    return sorted(cleaned)


def find_imitated_protected(kind: str, value: str, protected_domains: List[str]) -> Optional[str]:
    """Si un indicador imita uno de los dominios protegidos de la organización.

    Imitar es parecerse sin serlo: la misma etiqueta con otro TLD o dentro de
    otra palabra (``acme-soporte.com`` frente a ``acme.com``), un carácter de
    diferencia o letras de otro alfabeto que se ven igual.

    Args:
        kind: ``domain`` o ``url``; otro tipo nunca imita nada.
        value: El indicador.
        protected_domains: Dominios protegidos.

    Returns:
        Optional[str]: El dominio protegido imitado, o ``None``.
    """
    host = value if kind == "domain" else (url_host(value) if kind == "url" else None)
    if not host:
        return None
    label = registrable_label(host)
    if not label:
        return None
    for protected in protected_domains:
        protected_label = registrable_label(protected)
        if not protected_label or host == protected or host.endswith("." + protected):
            continue
        if label == protected_label or normalize_homoglyphs(label) == protected_label:
            return protected
        if len(protected_label) >= _MIN_LOOKALIKE_LABEL and (
                protected_label in label or levenshtein(label, protected_label) == 1):
            return protected
    return None


def is_shareable_sender_domain(domain: str) -> bool:
    """Si un dominio remitente puede aparecer entre los frecuentes de la organización.

    Los de correo gratuito no: que varios miembros reciban de ``gmail.com``
    no dice nada, y detrás hay personas concretas.

    Args:
        domain: Dominio remitente.

    Returns:
        bool: ``True`` si no es de correo gratuito.
    """
    return not is_free_provider(domain)
