"""La evidencia cruda de un hallazgo — capturada, redactada y con hash.

Este módulo vive en la capa pura ``lybra/``: **no toca el ORM**. El motor
recoge la evidencia en una lista en memoria a través de un *recorder*
inyectable —igual que ``cve_lookup``—, y es el manager quien la vuelca a la
base de datos en la fase de persistencia. Aquí sólo están las dos operaciones
que no dependen de nada externo: **redactar** y **hashear**.

**Por qué la redacción es requisito y no mejora.** Una respuesta cruda puede
traer cookies de sesión, cabeceras ``Authorization``, tokens en el cuerpo o
datos personales del objetivo. Guardar evidencia sin redactar convertiría la
base de datos de Ellysia en un depósito de secretos ajenos. Filtrar las
cabeceras sensibles y truncar el cuerpo es la línea que separa «guardo lo que
vi» de «me quedo con las llaves de casa del cliente».
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# Cabeceras que nunca se persisten: llevan credenciales o material de sesión.
# Se comparan en minúsculas, así que la lista va en minúsculas.
_SENSITIVE_HEADERS = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "www-authenticate",
    "proxy-authenticate",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
    "x-xsrf-token",
    "api-key",
    "authentication-info",
})

# Lo que se pone en lugar de una cabecera redactada, para que la evidencia diga
# «aquí había algo y lo quitamos» en vez de esconder que existía.
_REDACTED = "[redacted]"

# Una asignación cuyo nombre delata un secreto, en las formas que sirven los
# ficheros que los checks buscan: PHP (``public $password = 'x';``,
# ``define('DB_PASSWORD', 'x')``), JSON (``"password":"x"``) y ``.env``
# (``SECRET_KEY=x``). El grupo 1 es todo lo anterior al valor.
#
# El coste tiene que ser lineal en la longitud del cuerpo, y el cuerpo lo
# decide el servidor analizado. Un ``[\w-]*`` libre a cada lado de la palabra
# clave haría que cada posición de una palabra larga la recorriera entera, un
# coste cuadrático: 20 000 letras seguidas se van a decenas de segundos. La búsqueda
# sólo arranca al principio de una palabra (``(?<![\w-])``) y los trozos del
# nombre alrededor de la palabra clave están acotados a
# :data:`_SECRET_NAME_AFFIX_MAX` caracteres, holgados para nombres reales como
# ``WORDPRESS_DB_PASSWORD``.
_SECRET_NAME_AFFIX_MAX = 64
_SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?i)((?<![\w-])[\w-]{0,%d}(?:pass(?:word|wd)?|secret|api[_-]?key|token|private[_-]?key)"""
    r"""[\w-]{0,%d}['"]?\s*(?:=>|[=:,])\s*['"]?)([^'"\s;,)]+)"""
    % (_SECRET_NAME_AFFIX_MAX, _SECRET_NAME_AFFIX_MAX))
# Un bloque de clave privada se tacha hasta su línea ``END`` o, si el cuerpo se
# ha recortado antes de llegar a ella, hasta el final: medio bloque sigue
# siendo media clave.
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL)

# Las clases de evidencia que el modelo reconoce. Una entrada con otro
# ``kind`` no se descarta, pero conviene que la lista viva en un sitio.
EVIDENCE_KINDS = ("http_response", "ssh_banner", "tls_cert", "probe_output", "osint_record")


@dataclass
class EvidenceRecord:
    """Una evidencia recogida por el motor, aún sin persistir.

    El ``dedup_key`` es lo que ata la evidencia a su hallazgo cuando el manager
    la vuelca: el hallazgo se identifica por esa clave, no por la identidad de
    un objeto Python que ``merge_findings`` podría haber recreado.

    Attributes:
        dedup_key: La clave del hallazgo que esta evidencia respalda.
        kind: La clase de evidencia (:data:`EVIDENCE_KINDS`).
        payload: El contenido observado, **sin** redactar todavía.
    """
    dedup_key: str
    kind: str
    payload: Dict[str, Any]


@dataclass
class EvidenceRecorder:
    """Un recorder inyectable que acumula evidencia en memoria.

    El motor recibe uno de éstos y llama :meth:`record` cuando un hallazgo trae
    la respuesta que lo provocó. No sabe nada de la base de datos; el manager
    lee :attr:`records` al final y los persiste.
    """
    records: List[EvidenceRecord] = field(default_factory=list)

    def record(self, dedup_key: str, kind: str, payload: Dict[str, Any]) -> None:
        """Apunta una evidencia para un hallazgo.

        Args:
            dedup_key: La clave del hallazgo que respalda.
            kind: La clase de evidencia.
            payload: El contenido observado, sin redactar.
        """
        self.records.append(EvidenceRecord(dedup_key=dedup_key, kind=kind, payload=payload))


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Sustituye el valor de las cabeceras sensibles por un marcador.

    Se conserva el **nombre** de la cabecera —que dice que estaba— y se borra
    sólo el valor. Un informe que dice «había un ``Set-Cookie`` y lo redactamos»
    es más honesto que uno que finge que no existía.

    Args:
        headers: Las cabeceras de la respuesta.

    Returns:
        Una copia con los valores sensibles redactados.
    """
    return {
        name: (_REDACTED if name.lower() in _SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


def redact_secrets(text: str) -> str:
    """Quita de un cuerpo los valores de secretos que un hallazgo ha dejado a la vista.

    Los checks que más importan son justo los que encuentran secretos: un
    ``wp-config.php``, una copia de ``configuration.php`` o un ``.env``
    servidos como texto. Su evidencia es la respuesta, y guardarla tal cual
    copiaría las credenciales del objetivo a la base de datos de Ellysia.
    Se conserva el nombre de cada clave (lo que prueba el hallazgo) y se
    sustituye su valor, igual que con las cabeceras sensibles.

    Args:
        text: El cuerpo de la respuesta.

    Returns:
        str: El cuerpo con los valores de contraseñas, claves y tokens
            sustituidos por :data:`_REDACTED`, y los bloques de clave privada
            enteros.
    """
    text = _PRIVATE_KEY_RE.sub(_REDACTED, text)
    return _SECRET_ASSIGNMENT_RE.sub(lambda match: match.group(1) + _REDACTED, text)


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    """Recorta un texto para que su codificación UTF-8 no pase de un tope.

    Args:
        text: El texto a recortar.
        max_bytes: El tope, en bytes de UTF-8.

    Returns:
        str: El texto entero si cabe; si no, su prefijo más largo que cabe,
            sin partir ningún carácter multibyte.
    """
    return text.encode("utf-8", "ignore")[:max_bytes].decode("utf-8", "ignore")


def redact_evidence(payload: Dict[str, Any], max_body_bytes: int = 8192) -> Dict[str, Any]:
    """Redacta y trunca una evidencia antes de persistirla.

    El cuerpo se recorta **antes** de tacharle los secretos: sólo se guarda lo
    que cabe en el tope, así que no hay motivo para procesar el resto, y el
    tamaño del cuerpo lo decide el servidor analizado. Tras tachar se recorta
    otra vez, porque el marcador puede ocupar más que el valor que sustituye y
    el tope es una garantía, no una aproximación.

    Args:
        payload: El contenido observado. Puede traer ``headers`` (un dict) y
            ``body`` (texto); cualquier otra clave se conserva tal cual.
        max_body_bytes: El tope del cuerpo, en bytes de su codificación UTF-8.
            Por defecto ``8192``.

    Returns:
        Dict[str, Any]: Una copia redactada: cabeceras sensibles sin valor y
            cuerpo con los secretos tachados, de como mucho ``max_body_bytes``
            bytes. Si el cuerpo observado no cabía, ``body_truncated_bytes``
            dice cuántos bytes suyos se quedaron fuera; si cabía, esa clave no
            aparece.
    """
    redacted = dict(payload)
    if isinstance(redacted.get("headers"), dict):
        redacted["headers"] = redact_headers(redacted["headers"])
    body = redacted.get("body")
    if isinstance(body, str):
        observed_bytes = len(body.encode("utf-8", "ignore"))
        # PostgreSQL no admite el carácter NUL en texto ni en JSONB, y un
        # cuerpo comprimido —el check BREACH pide gzip— llega aquí como binario
        # decodificado con reemplazo, lleno de NUL. Sin quitarlos, el INSERT de
        # la evidencia revienta y se lleva por delante el escaneo entero. Se
        # sustituyen por el carácter de reemplazo, que sí es texto válido, para
        # no descuadrar las posiciones dentro del cuerpo.
        body = redact_secrets(_truncate_to_bytes(body, max_body_bytes)).replace("\x00", "�")
        redacted["body"] = _truncate_to_bytes(body, max_body_bytes)
        if observed_bytes > max_body_bytes:
            redacted["body_truncated_bytes"] = observed_bytes - max_body_bytes
    return redacted


def evidence_hash(payload: Dict[str, Any]) -> str:
    """Calcula el SHA-256 de una evidencia redactada, de forma estable.

    Se serializa con las claves ordenadas para que el mismo contenido produzca
    siempre el mismo hash, que es lo que permite afirmar después que la
    evidencia no se ha tocado.

    Args:
        payload: La evidencia ya redactada.

    Returns:
        El digest hexadecimal.
    """
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def prepare_evidence(
    payload: Dict[str, Any],
    max_body_bytes: int = 8192,
) -> Dict[str, Any]:
    """Redacta, trunca y hashea una evidencia en un solo paso.

    Args:
        payload: El contenido observado, sin redactar.
        max_body_bytes: El tope del cuerpo.

    Returns:
        Un dict ``{"payload": <redactado>, "content_hash": <sha256>}`` listo
        para el modelo.
    """
    redacted = redact_evidence(payload, max_body_bytes)
    return {"payload": redacted, "content_hash": evidence_hash(redacted)}


def build_recorder(enabled: bool) -> Optional[EvidenceRecorder]:
    """Devuelve un recorder si la captura está activada, o ``None``.

    Un ``None`` es la señal de «no captures nada», que el motor propaga sin
    ramas especiales: donde llamaría a ``recorder.record`` simplemente no hay
    recorder.

    Args:
        enabled: Si la captura de evidencia está activada.

    Returns:
        Un :class:`EvidenceRecorder` nuevo, o ``None``.
    """
    return EvidenceRecorder() if enabled else None


# Tipo del recorder que el motor recibe: una función que apunta una evidencia,
# o ``None``. Se declara para que las firmas lo nombren sin importar la clase.
RecorderFn = Optional[Callable[[str, str, Dict[str, Any]], None]]
