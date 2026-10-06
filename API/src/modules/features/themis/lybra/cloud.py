"""Detección de exposición en la nube y SaaS: recursos, firmas y sonda.

Un bucket S3 público, un contenedor Blob de Azure abierto, una base de Firebase
sin reglas o un subdominio secuestrable son hallazgos graves que **no tienen
puerto que escanear**: el modelo del motor —descubrir puertos, identificar
servicios, comprobar— no los alcanza. Este módulo los cubre con dos piezas:

- La **gramática de un recurso cloud** (:class:`CloudResource`,
  :func:`parse_cloud_resource`): la forma canónica ``proveedor:identificador``
  con la que el usuario declara un bucket o una base, y con la que el registro
  de objetivos autorizados decide si puede tocarse. La comparten la
  autorización (``AuthorizedTargetManager``) y la sonda, por eso vive en la capa
  pura y no en el manager.

- La **sonda** (:class:`CloudProbe`): para cada recurso declarado, una petición
  anónima que dice si el almacenamiento lista su contenido a cualquiera, y para
  cada subdominio, una resolución de CNAME más una comparación con el catálogo
  de firmas de takeover (``feeds/takeover_signatures.json``).

Nunca se **enumeran** nombres: los recursos se declaran o llegan de un escaneo
pasivo del dominio. Adivinar nombres de bucket genera tráfico masivo contra
terceros y no es lo que este módulo hace.

Como el resto de ``lybra/``, aquí no hay ORM ni efectos de red propios: lo que
toca la red llega por callables inyectados (ver :class:`CloudProbe`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .checks import CHECKS_FEED_VERSION, Response

# Los cuatro proveedores que se saben detectar sin credenciales ni SDK. El
# prefijo de un recurso declarado es uno de éstos.
CLOUD_PROVIDERS: Tuple[str, ...] = ("s3", "gcs", "azure", "firebase")

# Forma de cada identificador, con las reglas de nombres reales de cada
# proveedor para que un recurso inválido se rechace al declararlo y no al
# fallar la petición:
#: Nombre de bucket S3: 3-63 caracteres, minúsculas, dígitos, punto y guion,
#: empezando y terminando en carácter alfanumérico.
_S3_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
#: Nombre de bucket GCS: hasta 222 caracteres; admite además el guion bajo.
_GCS_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
#: Cuenta de almacenamiento de Azure: 3-24 caracteres, sólo minúsculas y dígitos.
_AZURE_ACCOUNT_RE = re.compile(r"^[a-z0-9]{3,24}$")
#: Contenedor Blob de Azure: 3-63 caracteres, minúsculas, dígitos y guion.
_AZURE_CONTAINER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
#: Identificador de proyecto de Firebase: 6-30 caracteres, minúsculas, dígitos
#: y guion, sin empezar ni terminar en guion.
_FIREBASE_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{4,28}[a-z0-9]$")


@dataclass(frozen=True)
class CloudResource:
    """Un recurso de almacenamiento en la nube declarado por el usuario.

    Es lo que el registro de objetivos autorizados guarda y compara, y lo que
    la sonda usa para construir la petición: la forma canónica
    ``proveedor:identificador`` en minúsculas.

    Attributes:
        provider: El proveedor, uno de :data:`CLOUD_PROVIDERS` (``"s3"``,
            ``"gcs"``, ``"azure"`` o ``"firebase"``).
        identifier: El identificador ya canónico dentro del proveedor: el
            nombre del bucket para ``s3``/``gcs``, ``cuenta/contenedor`` para
            ``azure`` y el id de proyecto para ``firebase``.
    """
    provider: str
    identifier: str

    @property
    def canonical(self) -> str:
        """La forma canónica ``proveedor:identificador``, en minúsculas.

        Returns:
            str: La cadena con la que el recurso se guarda y se compara.
        """
        return f"{self.provider}:{self.identifier}"


def parse_cloud_resource(raw: str) -> Optional[CloudResource]:
    """Parsea y valida un recurso cloud declarado, o devuelve ``None``.

    Acepta las cuatro formas ``proveedor:identificador``: ``s3:nombre``,
    ``gcs:nombre``, ``azure:cuenta/contenedor`` y ``firebase:proyecto``. La
    validación es estricta: cada identificador tiene que cumplir las reglas de
    nombres reales del proveedor, para que un recurso mal escrito se rechace al
    declararlo y no al fallar la petición.

    Args:
        raw: El texto tal como lo escribió el usuario. Se le quitan los espacios
            de los bordes y se pasa a minúsculas antes de validar.

    Returns:
        Optional[CloudResource]: El recurso en forma canónica, o ``None`` si el
            texto no lleva un prefijo de proveedor conocido, si le falta el
            identificador o si el identificador no respeta la forma del
            proveedor.
    """
    candidate = (raw or "").strip().lower()
    if ":" not in candidate:
        return None
    provider, _, identifier = candidate.partition(":")
    if provider not in CLOUD_PROVIDERS or not identifier:
        return None
    if provider in ("s3", "gcs"):
        pattern = _S3_BUCKET_RE if provider == "s3" else _GCS_BUCKET_RE
        return CloudResource(provider, identifier) if pattern.match(identifier) else None
    if provider == "firebase":
        return CloudResource(provider, identifier) if _FIREBASE_PROJECT_RE.match(identifier) else None
    account, separator, container = identifier.partition("/")
    if not separator or not _AZURE_ACCOUNT_RE.match(account) or not _AZURE_CONTAINER_RE.match(container):
        return None
    return CloudResource(provider, f"{account}/{container}")


# =========================================================================
# TAKEOVER DE SUBDOMINIO: el catálogo de firmas
# =========================================================================

_BUNDLED_TAKEOVER_SIGNATURES = Path(__file__).parent / "feeds" / "takeover_signatures.json"


@dataclass(frozen=True)
class TakeoverSignature:
    """Cómo se reconoce un subdominio secuestrable de un proveedor.

    Attributes:
        service: Identificador corto del servicio (``"github-pages"``).
        provider: Nombre legible del proveedor, para el título del hallazgo.
        cnames: Fragmentos del destino del CNAME que identifican al servicio
            (``"github.io"``). Basta con que el destino contenga uno.
        fingerprints: Textos que el servicio devuelve cuando el recurso ya no
            existe. Basta con que la respuesta contenga uno. Son específicos del
            servicio a propósito: un ``404`` genérico daría falsos positivos.
    """
    service: str
    provider: str
    cnames: Tuple[str, ...]
    fingerprints: Tuple[str, ...]


def _read_takeover_document(path: Optional[str]) -> dict:
    """Lee el catálogo de firmas de takeover.

    Args:
        path: Ruta de un catálogo JSON, o ``None`` para el que viaja con el
            módulo.

    Returns:
        dict: El documento parseado.
    """
    return json.loads(Path(path or _BUNDLED_TAKEOVER_SIGNATURES).read_text(encoding="utf-8"))


def load_takeover_signatures(path: Optional[str] = None) -> List[TakeoverSignature]:
    """Carga el catálogo de firmas de takeover.

    Args:
        path: Ruta de un catálogo JSON. Por defecto, el que viaja con el módulo.

    Returns:
        List[TakeoverSignature]: Las firmas, en el orden del catálogo.
    """
    return [
        TakeoverSignature(
            service=entry["service"], provider=entry["provider"],
            cnames=tuple(entry["cnames"]), fingerprints=tuple(entry["fingerprints"]))
        for entry in _read_takeover_document(path).get("signatures", [])
    ]


def takeover_signatures_version(path: Optional[str] = None) -> str:
    """La versión del catálogo de firmas, para el ``feed_version`` de los hallazgos.

    Args:
        path: Ruta de un catálogo JSON. Por defecto, el que viaja con el módulo.

    Returns:
        str: El campo ``version`` del catálogo, o ``"lybra-takeover-0"`` si
            no lo declara.
    """
    return str(_read_takeover_document(path).get("version") or "lybra-takeover-0")


# =========================================================================
# LA SONDA
# =========================================================================

# Los puertos con los que la sonda pide: los servicios de almacenamiento se
# hablan siempre por HTTPS; un subdominio, en claro, porque un servicio
# abandonado a menudo ni tiene certificado para el nombre.
_HTTPS_PORT = 443
_HTTP_PORT = 80

# Lo que el listado de un almacenamiento abierto trae en el cuerpo. Un bucket
# privado contesta con un error (AccessDenied) que nombra otras cosas.
_S3_LISTING_MARKER = "<ListBucketResult"
_AZURE_LISTING_MARKER = "<EnumerationResults"

# Lo que Firebase contesta cuando las reglas cierran la base: no hay datos
# expuestos que reportar.
_FIREBASE_DENIED_MARKER = "Permission denied"


class CloudProbe:
    """Comprueba recursos cloud declarados y subdominios, sin credenciales.

    Todo lo que toca la red llega inyectado, así que la clase es pura y se
    prueba con respuestas fabricadas.

    Args:
        fetch: ``(host, puerto, ruta) -> Response | None``: un ``GET`` a
            ``https://host/ruta`` (puerto 443) o ``http://host/ruta``
            (puerto 80). ``None`` es una petición que no obtuvo respuesta, y
            cuenta como «no hay nada que reportar», nunca como hallazgo.
        resolve_cname: ``nombre -> destino del CNAME | None``: el destino al que
            apunta el nombre, o ``None`` si no es un CNAME o no resuelve.
        signatures: El catálogo de takeover. Por defecto, el que viaja con el
            módulo.
    """

    def __init__(self, fetch: Callable[[str, int, str], Optional[Response]],
                 resolve_cname: Callable[[str], Optional[str]],
                 signatures: Optional[List[TakeoverSignature]] = None) -> None:
        self._fetch = fetch
        self._resolve_cname = resolve_cname
        self._signatures = signatures if signatures is not None else load_takeover_signatures()
        self._takeover_version = takeover_signatures_version()

    def probe_resource(self, resource: CloudResource) -> Optional[dict]:
        """Pregunta, de forma anónima, si un recurso declarado expone su contenido.

        Args:
            resource: El recurso, ya validado por :func:`parse_cloud_resource`.

        Returns:
            Optional[dict]: Un hallazgo (con la forma que produce el motor) si
                cualquiera puede listar el bucket o leer la base; ``None`` si
                el recurso es privado, no existe o no contestó.
        """
        name = resource.identifier
        if resource.provider == "s3":
            is_open = _lists(self._fetch(f"{name}.s3.amazonaws.com", _HTTPS_PORT, "/"),
                                  _S3_LISTING_MARKER)
            title = f"Bucket S3 público: cualquiera puede listar su contenido ({name})"
            check, severity = "cloud-s3-public-bucket", "HIGH"
        elif resource.provider == "gcs":
            is_open = _lists(self._fetch("storage.googleapis.com", _HTTPS_PORT, f"/{name}/"),
                                  _S3_LISTING_MARKER)
            title = f"Bucket de Google Cloud Storage público: cualquiera puede listar su contenido ({name})"
            check, severity = "cloud-gcs-public-bucket", "HIGH"
        elif resource.provider == "azure":
            account, _, container = name.partition("/")
            is_open = _lists(
                self._fetch(f"{account}.blob.core.windows.net", _HTTPS_PORT,
                            f"/{container}?restype=container&comp=list"),
                _AZURE_LISTING_MARKER)
            title = f"Contenedor Blob de Azure público: cualquiera puede listar su contenido ({name})"
            check, severity = "cloud-azure-public-container", "HIGH"
        else:
            is_open = _has_firebase_data(self._fetch(f"{name}.firebaseio.com", _HTTPS_PORT, "/.json"))
            title = f"Base de Firebase sin reglas: cualquiera puede leer sus datos ({name})"
            check, severity = "cloud-firebase-open-database", "CRITICAL"
        if not is_open:
            return None
        return _cloud_finding(title, severity, check, resource.canonical, CHECKS_FEED_VERSION)

    def probe_subdomain(self, name: str) -> Optional[dict]:
        """Comprueba si un subdominio apunta a un servicio que ya no aloja su recurso.

        Resuelve el CNAME, busca una firma cuyo destino case y, sólo entonces,
        pide la página del nombre: el hallazgo exige las dos cosas —el CNAME
        colgando **y** la huella del proveedor en la respuesta—, porque un CNAME
        a un servicio de terceros es normal y sólo es un problema cuando el
        recurso ya no existe.

        Args:
            name: El subdominio, normalizado y ya autorizado por quien llama.

        Returns:
            Optional[dict]: Un hallazgo si el subdominio es reclamable;
                ``None`` si no es un CNAME, no apunta a un servicio conocido, el
                recurso sigue existiendo o la petición no contestó.
        """
        target = self._resolve_cname(name)
        if not target:
            return None
        target = target.rstrip(".").lower()
        for signature in self._signatures:
            if not any(fragment in target for fragment in signature.cnames):
                continue
            response = self._fetch(name, _HTTP_PORT, "/")
            if response is None:
                continue
            body = (response.body or "").lower()
            if any(fingerprint.lower() in body for fingerprint in signature.fingerprints):
                return _cloud_finding(
                    f"Subdominio susceptible de takeover: {name} apunta a {signature.provider} "
                    f"({target}), que ya no aloja el recurso",
                    "HIGH", f"cloud-takeover-{signature.service}", name, self._takeover_version)
        return None


def _lists(response: Optional[Response], marker: str) -> bool:
    """Si una respuesta es el listado de un almacenamiento abierto.

    Args:
        response: La respuesta, o ``None`` si no hubo.
        marker: El texto que abre el listado en ese proveedor.

    Returns:
        bool: ``True`` sólo con un ``200`` cuyo cuerpo trae el marcador.
    """
    return response is not None and response.status == 200 and marker in (response.body or "")

@staticmethod
def _has_firebase_data(response: Optional[Response]) -> bool:
    """Si una respuesta de Firebase entrega datos reales.

    Args:
        response: La respuesta a ``GET /.json``, o ``None`` si no hubo.

    Returns:
        bool: ``True`` con un ``200`` cuyo cuerpo es JSON con contenido. Una
            base con reglas responde ``401`` con «Permission denied», y una
            base vacía responde ``null``: ninguna expone datos.
    """
    if response is None or response.status != 200:
        return False
    body = (response.body or "").strip()
    if not body or _FIREBASE_DENIED_MARKER in body:
        return False
    try:
        return bool(json.loads(body))
    except ValueError:
        return False


def _cloud_finding(title: str, severity: str, check: str, subject: str, feed_version: str) -> dict:
    """Construye el hallazgo de una exposición cloud.

    El hallazgo no tiene puerto, así que la clave de deduplicación se distingue
    por ``service``: por eso el sujeto (el recurso o el subdominio) viaja ahí, y
    dos recursos distintos con el mismo check no se funden.

    Args:
        title: El título legible.
        severity: ``"CRITICAL"``, ``"HIGH"``…
        check: El identificador del check, sin espacio de nombres ni versión.
        subject: El recurso (``"s3:bucket"``) o el subdominio afectado.
        feed_version: La versión de la fuente de datos usada.

    Returns:
        dict: Con la forma que el resto del motor entiende.
    """
    return {
        "title": title, "category": "cloud_exposure", "severity": severity,
        "port": None, "service": subject, "protocol": "tcp", "source": "lybra",
        "check_id": f"lybra:{check}@1", "feed_version": feed_version,
        "qod": 99, "confirmed": True, "state": "open",
    }
