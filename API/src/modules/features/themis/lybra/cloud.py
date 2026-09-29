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

Como el resto de ``lybra/``, aquí no hay ORM ni efectos de red propios: lo que
toca la red llega por callables inyectados (ver :class:`CloudProbe`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

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
