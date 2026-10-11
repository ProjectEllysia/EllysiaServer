"""Qué checks de ``security_header`` debe disparar un servidor sin endurecer.

Los bancos necesitan saber qué es un acierto y qué es un falso positivo, y para
la familia de cabeceras esa lista estaba escrita a mano **dos veces**: una en
``test_lybra_precision_bench.py`` y otra en ``test_lybra_oracle_bench.py``, las
dos con los mismos tres identificadores. Cuando el feed creció de 28 a 55 checks
y aparecieron CSP, ``Referrer-Policy`` y ``Permissions-Policy``, ninguna
de las dos se enteró. Los tres checks nuevos son detecciones **correctas** —un
nginx recién sacado de la caja no manda ninguna de esas cabeceras— pero como el
catálogo no los listaba como esperados, se contaron como falsos positivos en los
diecisiete objetivos HTTP del banco y hundieron la precisión del banco a
0,557 frente a un umbral de 0,90. El banco nocturno llevaba tres noches en rojo
por eso.

La lección es la del repositorio de siempre: una lista que hay que acordarse de
actualizar a mano se desincroniza, y lo hace en silencio. Así que aquí no se
escribe la lista, **se deriva del feed** — la misma fuente de la que el motor
saca los checks que ejecuta, de modo que las dos no pueden divergir.

Lo único que se declara a mano es la excepción, y con su razón al lado: los
checks de la familia que **no** dispara todo servidor sin endurecer, porque
dependen de que la respuesta traiga algo que un ``return 200 "ok"`` no trae.

Not a test module itself (no ``test_`` prefix) — pytest does not collect it.
"""

from __future__ import annotations

from typing import Dict, Set

from src.modules.features.themis.lybra.checks import load_checks

HEADER_CATEGORY = "security_header"

# Los checks de la familia que dependen de algo que la respuesta puede traer o
# no, con el motivo por el que no valen como cabecera "que falta siempre".
#
# Clasificar mal uno de éstos falla en la dirección segura: pasaría a esperarse
# en todos los objetivos, no dispararía en ninguno, y saldría como falso
# negativo ruidoso en vez de inflar la precisión en silencio.
CONDITIONAL_HEADER_CHECKS: Dict[str, str] = {
    "lybra:session-cookie-without-secure@3":
        "necesita un Set-Cookie en la respuesta; los objetivos del catálogo "
        "sirven un 200 sin cookies, así que no hay cookie que juzgar",
    "lybra:session-cookie-without-httponly@2": "necesita un Set-Cookie en la respuesta",
    "lybra:session-cookie-without-samesite@2": "necesita un Set-Cookie en la respuesta",
    "lybra:http-no-https-redirect@1":
        "sólo en un puerto en claro que sirve la página sin redirigir a HTTPS",
    "lybra:hsts-weak-max-age@1": "necesita una HSTS presente y con max-age corto",
    "lybra:x-frame-options-deprecated@1": "necesita X-Frame-Options sin frame-ancestors",
    "lybra:http-version-disclosure@1": "necesita una cabecera con número de versión",
    "lybra:http-compression-breach@1": "necesita compresión y cookies sobre HTTPS",
    "lybra:cors-wildcard-origin-with-credentials@1":
        "necesita Access-Control-Allow-Origin: * y Access-Control-Allow-Credentials: "
        "true a la vez; un 200 sin CORS configurado no manda ninguna de las dos",
    "lybra:cors-reflects-any-origin-with-credentials@1":
        "necesita que la respuesta refleje el Origin de la sonda con credenciales; "
        "un 200 sin CORS configurado no manda ninguna cabecera de CORS",
    "lybra:session-response-cacheable@1":
        "necesita una cookie de sesión en la respuesta; un 200 sin cookies no tiene sesión que cachear",
    "lybra:session-cookie-without-prefix@1": "necesita una cookie de sesión en la respuesta",
    "lybra:cookie-prefix-requirements-unmet@1":
        "necesita una cookie con prefijo __Host- o __Secure- que incumpla sus requisitos",
    "lybra:login-form-served-over-http@1":
        "necesita que el rastreo haya descubierto un formulario de acceso; sin uno, "
        "sólo se prueba la ruta placeholder del feed, que ningún objetivo del catálogo sirve",
}


def _check_id(check) -> str:
    """El identificador con el que un hallazgo nombra a su check."""
    return f"{check.namespace}:{check.id}@{check.version}"


def header_family_from_feed() -> Set[str]:
    """Todos los checks de ``security_header`` que declara el feed."""
    return {
        _check_id(check)
        for check in load_checks()
        if check.category == HEADER_CATEGORY
    }


def always_missing_header_checks() -> Set[str]:
    """Los que debe disparar cualquier servidor que no mande ninguna cabecera.

    Es la familia entera menos las excepciones declaradas arriba. Se deriva en
    cada llamada en vez de congelarse en una constante de módulo para que un
    test que parchee el feed vea lo que ha parcheado.
    """
    return header_family_from_feed() - set(CONDITIONAL_HEADER_CHECKS)


# Lo que un nginx o un Apache **de serie** dispara además de la cabecera que
# falta, y lo que cambia según hablen HTTP en claro o TLS. Estaban entre las
# excepciones de arriba —«no lo dispara todo servidor sin endurecer»—, y es
# verdad, pero todos los objetivos del catálogo son precisamente eso: un servidor
# de serie respondiendo 200 en la raíz. Sin declararlo aparte, cada uno de esos
# hallazgos ciertos contaba como falso positivo en todos los objetivos HTTP y
# hundía la precisión del banco a 0,748.
HTTPS_ONLY_HEADER_CHECKS: Dict[str, str] = {
    "lybra:missing-hsts-header@2":
        "HSTS sólo tiene efecto recibida por HTTPS (RFC 6797 §8.1): en un puerto "
        "en claro no se exige, y no es un falso negativo que no salga",
}

STOCK_SERVER_HEADER_CHECKS: Dict[str, str] = {
    "lybra:http-version-disclosure@1":
        "nginx y Apache de serie mandan «Server: nginx/1.x.y» o «Apache/2.4.x», "
        "con o sin TLS; hace falta ``server_tokens off`` o equivalente para callarlo",
}

CLEAR_PORT_HEADER_CHECKS: Dict[str, str] = {
    "lybra:http-no-https-redirect@1":
        "un puerto en claro que sirve la raíz con un 200 en vez de redirigir a "
        "HTTPS; es lo que hacen todos los objetivos HTTP del catálogo",
}


def stock_server_header_findings(over_tls: bool) -> Set[str]:
    """Los hallazgos de ``security_header`` de un servidor de serie que sirve un 200.

    Es :func:`always_missing_header_checks` ajustada al esquema y con lo que un
    nginx o un Apache sin tocar manda además: la versión en ``Server`` y, en
    claro, que no redirige a HTTPS. No vale para un servidor endurecido, que es
    justo el que no debe disparar nada de esto.

    Args:
        over_tls: ``True`` si el objetivo habla TLS; ``False`` si habla HTTP en claro.

    Returns:
        Set[str]: Los ``check_id`` esperados. Por TLS entra HSTS y no el aviso de
            falta de redirección; en claro, al revés.
    """
    found = always_missing_header_checks() | set(STOCK_SERVER_HEADER_CHECKS)
    if over_tls:
        return found
    return (found - set(HTTPS_ONLY_HEADER_CHECKS)) | set(CLEAR_PORT_HEADER_CHECKS)
