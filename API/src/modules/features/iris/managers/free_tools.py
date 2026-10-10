"""
Las herramientas gratuitas de Iris: trozos de un análisis que se pueden usar
sin cuenta (el detector de dominios engañosos y el analizador de cabeceras).

Cada herramienta pasa lo que escribe el visitante por las mismas reglas que
usa un análisis de Iris, en memoria: no se guarda nada (ni lo que se envía ni
el resultado) y no se encola ningún trabajo. Lo que se devuelve son códigos y
datos, no las frases de ``RuleResult.recommendation``: la interfaz los traduce
al idioma de quien la usa.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..exceptions import IrisInvalidInputError
from ..services.idn import assess_domain
from ..services.parsers import (
    build_path, decode_mime_words, parse_raw_message, validate_headers_parsed, validate_headers_pre,
)
from ..services.rules.auth_rules import check_dkim, check_dmarc, check_domain_alignment, check_spf
from ..services.rules.sender_identity_rules import check_lookalike_domain, check_subdomain_impersonation
from ..services.text import registrable_domain, registrable_label, url_host
from ..services.wordlists import canonical_brands

#: Una etiqueta de un nombre de dominio ya en ASCII: letras, cifras y guiones.
_DOMAIN_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

#: Longitud máxima de un nombre de dominio completo (RFC 1035).
_MAX_DOMAIN_LENGTH = 253


class IrisFreeToolsManager:
    """Las herramientas gratuitas de Iris, sin estado y sin base de datos."""

    def inspect_domain(self, text: str) -> Dict:
        """
        Dice si un dominio imita a una marca conocida, con las reglas de Iris.

        Pasa el dominio por las dos reglas que lo juzgan en un análisis: la de
        dominio parecido (homógrafos IDN, mezcla de alfabetos, erratas, primos y
        homóglifos) y la de suplantación por subdominio (la marca a la izquierda
        de un dominio que no es suyo, o combinada con palabras de acción).

        Args:
            text: Lo que escribió el visitante: un dominio (también en Unicode),
                una dirección de correo o una URL.

        Returns:
            Dict: ``domain`` (en ASCII, como viaja), ``unicodeDomain`` (como se
                lee), ``registrableDomain`` (el que de verdad se compra),
                ``ownBrand`` (la marca si el dominio registrable es el suyo;
                ``None`` si no), ``isSuspicious`` y ``findings``: una lista de
                ``{type, brand, label, scripts, action}`` donde ``type`` es
                ``idn_homograph``, ``idn_mixed_script``, ``cousin``,
                ``homoglyph``, ``typo``, ``brand_in_subdomain`` o
                ``brand_action_combo``. Vacía si no imita nada.

        Raises:
            IrisInvalidInputError: Si el texto no contiene un nombre de dominio
                válido (una IP tampoco lo es).
        """
        domain = _domain_from(text)
        headers = {"from": f"visitante@{domain}"}
        findings = _merge_findings(
            check_lookalike_domain(headers).details,
            check_subdomain_impersonation(headers).details,
        )
        own_label = registrable_label(domain)
        return {
            "domain": domain,
            "unicodeDomain": assess_domain(domain, canonical_brands()).unicode_domain,
            "registrableDomain": registrable_domain(domain),
            "ownBrand": own_label if own_label in canonical_brands() else None,
            "isSuspicious": bool(findings),
            "findings": findings,
        }

    def inspect_headers(self, raw: str) -> Dict:
        """
        Lee las cabeceras de un correo como lo hace un análisis de Iris, sin
        veredicto: la ruta que siguió y lo que dicen SPF, DKIM y DMARC.

        Es la parte del análisis que solo mira las cabeceras de autenticación y
        la cadena ``Received``. No corre el resto de reglas, no mira el cuerpo
        ni los adjuntos y no puntúa.

        Args:
            raw: El bloque de cabeceras pegado por el visitante (o el mensaje
                entero: del cuerpo no se usa nada).

        Returns:
            Dict: ``sender`` (la cabecera ``From``) y ``subject`` decodificados; ``fromDomain``, el
                dominio registrable del remitente o ``None``; ``auth``, una
                lista de ``{check, verdict, domains}`` para ``spf``, ``dkim``,
                ``dmarc`` y ``alignment``, donde ``verdict`` es el de la regla
                (``pass``, ``fail``, ``softfail``, ``neutral``, ``none``,
                ``bestguess``, ``policy``, ``error`` o ``missing``) y
                ``domains`` los dominios autenticados cuando la alineación los
                compara; y ``path``, la ruta salto a salto de ``build_path``.

        Raises:
            IrisInvalidInputError: Si el texto no tiene cabeceras suficientes
                para leer nada (el mínimo de ``features.iris.minHeaders``).
        """
        validate_headers_pre(raw)
        context = parse_raw_message(raw)
        validate_headers_parsed(context.headers)
        headers = context.headers

        alignment = check_domain_alignment(headers)
        compared = alignment.details.get("aligned") or alignment.details.get("authenticated_domains") or {}
        return {
            "sender": decode_mime_words(headers.get("from", "")),
            "subject": decode_mime_words(headers.get("subject", "")),
            "fromDomain": alignment.details.get("from_domain"),
            "auth": [
                {"check": "spf", "verdict": check_spf(headers).verdict, "domains": []},
                {"check": "dkim", "verdict": check_dkim(headers).verdict, "domains": []},
                {"check": "dmarc", "verdict": check_dmarc(headers).verdict, "domains": []},
                {"check": "alignment", "verdict": alignment.verdict, "domains": sorted(set(compared.values()))},
            ],
            "path": build_path(context.received_headers),
        }


def _domain_from(text: str) -> str:
    """
    Saca el nombre de dominio de lo que haya escrito el visitante.

    Args:
        text: Un dominio, una dirección de correo o una URL, con o sin esquema,
            puerto o ruta.

    Returns:
        str: El dominio en minúsculas, sin punto final y en ASCII (las etiquetas
            con acentos o de otros alfabetos pasan a punycode).

    Raises:
        IrisInvalidInputError: Si no queda un nombre de dominio de al menos dos
            etiquetas válidas.
    """
    candidate = (text or "").strip()
    # Sin esquema, se le pone uno para que la URL se lea igual que una con él;
    # una dirección de correo queda como «credenciales@host» y url_host las quita.
    host = url_host(candidate if "://" in candidate else f"http://{candidate}") or ""
    host = host.strip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise IrisInvalidInputError("No es un nombre de dominio válido.") from error
    labels = host.split(".")
    if len(labels) < 2 or len(host) > _MAX_DOMAIN_LENGTH or not all(_DOMAIN_LABEL.match(label) for label in labels):
        raise IrisInvalidInputError("No es un nombre de dominio válido.")
    if labels[-1].isdigit():
        raise IrisInvalidInputError("Una dirección IP no es un nombre de dominio.")
    return host


def _merge_findings(lookalike: Dict, subdomain: Dict) -> List[Dict]:
    """
    Junta lo que encontraron las dos reglas en una sola lista, sin repetir.

    La regla de subdominio también avisa de un homógrafo IDN
    (``punycode_in_subdomain``), pero es el mismo hallazgo que ya da la de
    dominio parecido, con menos detalle: se omite.

    Args:
        lookalike: ``details`` de ``check_lookalike_domain``.
        subdomain: ``details`` de ``check_subdomain_impersonation``.

    Returns:
        List[Dict]: Hallazgos ``{type, brand, label, scripts, action}``, en el
            orden en que los dieron las reglas.
    """
    raw: List[Dict] = []
    if lookalike.get("type") in ("idn_homograph", "idn_mixed_script"):
        raw.append({"type": lookalike["type"], "brand": lookalike.get("brand"),
                    "label": lookalike.get("label"), "scripts": lookalike.get("scripts") or []})
    for finding in lookalike.get("findings") or []:
        raw.append({"type": finding["type"], "brand": finding.get("brand"), "label": finding.get("token")})
    for finding in subdomain.get("findings") or []:
        raw.append({"type": finding["type"], "brand": finding.get("brand") or finding.get("token"),
                    "label": finding.get("subdomain_label") or finding.get("label"),
                    "action": finding.get("action")})

    merged: List[Dict] = []
    seen: set[tuple[str, Optional[str], Optional[str]]] = set()
    for finding in raw:
        key = (finding["type"], finding.get("brand"), finding.get("label"))
        if key in seen:
            continue
        seen.add(key)
        merged.append({"scripts": [], "action": None, **finding})
    return merged
