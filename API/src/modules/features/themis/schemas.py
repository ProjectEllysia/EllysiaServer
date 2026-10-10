import re

from marshmallow import Schema, fields, validate, validates_schema, ValidationError

from src.modules.shared import UTCDateTime
from .model import OsintScanMode, ScanType
from .services.compliance_catalog import list_compliance_frameworks


class ScanIdQuerySchema(Schema):
    id = fields.Integer(required=True)


class LybraExportQuerySchema(Schema):
    format = fields.String(required=True, validate=validate.OneOf(["sarif", "stix", "ocsf"]))


class NmapScanRequestSchema(Schema):
    target = fields.String(required=True)
    ports = fields.String(required=True)
    timeout = fields.Integer(load_default=300, validate=validate.Range(min=1))


class NiktoScanRequestSchema(Schema):
    target = fields.String(required=True)
    timeout = fields.Integer(load_default=900, validate=validate.Range(min=1))


class NucleiScanRequestSchema(Schema):
    target = fields.String(required=True)
    # Perfil acotado por defecto: sin esto, Nuclei con el feed completo
    # contra un solo host son miles de peticiones. "info"
    # queda fuera del default a propósito — son miles de plantillas de
    # tech-detect y, al ser confirmed=True sin CVSS, el suelo de
    # score_finding las subiría todas a MEDIUM.
    severities = fields.List(
        fields.String(validate=validate.OneOf(["info", "low", "medium", "high", "critical"])),
        load_default=None,
    )
    tags = fields.List(fields.String(), load_default=None)
    rateLimit = fields.Integer(load_default=None, validate=validate.Range(min=1, max=1000))
    requestTimeout = fields.Integer(load_default=None, validate=validate.Range(min=1, max=120))
    timeout = fields.Integer(load_default=None, validate=validate.Range(min=1))


class LybraScanRequestSchema(Schema):
    # Un solo modo por HTTP: Lybra descubre los puertos del objetivo con su
    # propio transporte. El modo de payload externo existe en el
    # manager, pero no se expone aquí — llega en proceso desde Hygeia.
    target = fields.String(required=True)
    ports = fields.String()
    timeout = fields.Integer(load_default=120, validate=validate.Range(min=1))
    # La doble puerta del modo agresivo: esta petición explícita del
    # usuario es sólo la mitad. El manager sólo la honra cuando el objetivo
    # está además en el registro de autorización — un registro no autoriza
    # cualquier cosa contra el objetivo, sólo el escaneo pasivo.
    aggressive = fields.Boolean(load_default=False)
    # Perfil de escaneo: composición con nombre de los parámetros que arriba
    # se pueden pedir sueltos (puertos, modo). "standard" reproduce el
    # comportamiento de siempre; explícito y no None para que el informe
    # siempre pueda decir con qué perfil se generó.
    profile = fields.String(load_default="standard", validate=validate.OneOf(["fast", "standard", "thorough"]))
    # Enriquecimiento pasivo: preguntar a Shodan/Censys por el objetivo para
    # sugerir un CPE donde el fingerprint propio no llegó. Apagado por
    # defecto porque consultar a un tercero le revela que el objetivo nos
    # interesa; se pide escaneo a escaneo.
    osintEnrichment = fields.Boolean(load_default=False)


class OsintScanRequestSchema(Schema):
    """Cuerpo de ``POST /themis/osint``: el dominio y, opcionalmente, los selectores DKIM.

    Attributes:
        domain: El dominio que se consulta, de 1 a 253 caracteres.
        dkimSelectors: Selectores DKIM que comprobar. Por defecto ninguno.
    """

    # El dominio se valida y normaliza en ``OsintManager.create_passive_scan``;
    # aquí sólo se acota el tamaño.
    domain = fields.String(required=True, validate=validate.Length(min=1, max=253))
    # Los selectores DKIM que comprobar. Sin ellos DKIM no se comprueba:
    # adivinar selectores sería fuerza bruta contra el DNS del cliente.
    dkimSelectors = fields.List(fields.String(validate=validate.Length(min=1, max=63)),
                                load_default=list)


class CloudScanRequestSchema(Schema):
    """Cuerpo de ``POST /themis/cloud``: el dominio y qué comprobar de él.

    Attributes:
        domain: El dominio al que pertenece lo que se comprueba, de 1 a 253
            caracteres. Debe estar en el registro de objetivos autorizados si
            se piden los subdominios.
        cloudResources: Recursos cloud a comprobar, en forma
            ``proveedor:identificador`` (``s3:nombre``, ``gcs:nombre``,
            ``azure:cuenta/contenedor``, ``firebase:proyecto``). Cada uno debe
            estar en el registro de objetivos autorizados. Por defecto ninguno.
        checkSubdomains: Si se comprueba el takeover del dominio y de los
            subdominios que un escaneo pasivo previo encontró. Por defecto sí.
    """

    # El dominio y los recursos se validan y autorizan en
    # ``CloudScanManager.create_cloud_scan``; aquí sólo se acota el tamaño.
    domain = fields.String(required=True, validate=validate.Length(min=1, max=253))
    cloudResources = fields.List(fields.String(validate=validate.Length(min=1, max=300)),
                                 load_default=list, validate=validate.Length(max=25))
    checkSubdomains = fields.Boolean(load_default=True)


class AssetGroupRequestSchema(Schema):
    """Cuerpo de ``POST /themis/asset-groups``: el nombre y el rango de la red.

    Attributes:
        name: Nombre legible del grupo, de 1 a 100 caracteres, único por usuario.
        cidr: El rango que define la red (``10.0.0.0/24``). Se valida en
            ``NetworkRiskManager.create_group``.
    """

    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    cidr = fields.String(required=True, validate=validate.Length(min=1, max=43))


class NetworkRiskQuerySchema(Schema):
    """Consulta de ``GET /themis/network-risk``: qué red se analiza.

    Hay que dar **exactamente uno** de los dos; se comprueba en el endpoint.

    Attributes:
        groupId: Un grupo de activos: sus hosts son los escaneados dentro de su rango.
        scanId: Un escaneo de red: sus hosts son los hijos del escaneo.
    """

    groupId = fields.Integer(load_default=None, validate=validate.Range(min=1))
    scanId = fields.Integer(load_default=None, validate=validate.Range(min=1))


class OsintScanListQuerySchema(Schema):
    """Consulta de ``GET /themis/osint``.

    Attributes:
        limit: Cuántos escaneos devolver, de 1 a 200. Por defecto 50.
        mode: Solo los de este modo (``passive`` o ``cloud``). Por defecto
            ninguno: todos.
    """

    limit = fields.Integer(load_default=50, validate=validate.Range(min=1, max=200))
    mode = fields.String(load_default=None, allow_none=True,
                         validate=validate.OneOf([mode.value for mode in OsintScanMode]))


class OsintScanStartResponseSchema(Schema):
    """Respuesta de ``POST /themis/osint``: el escaneo pasivo recién encolado."""

    message = fields.String()
    osintScanId = fields.Integer()
    domain = fields.String()
    mode = fields.String()
    status = fields.String()
    user = fields.String()


class OsintScanDetailResponseSchema(Schema):
    """Respuesta de ``GET /themis/osint/<id>``: el escaneo pasivo con todo su detalle.

    Cada hallazgo de ``findings`` tiene la forma común de un hallazgo de Lybra
    más ``provenance`` (fuente, fecha de observación, fecha de descarga y
    antigüedad en días).
    """

    osintScanId = fields.Integer()
    domain = fields.String()
    mode = fields.String()
    status = fields.String()
    startedAt = fields.String(allow_none=True)
    finishedAt = fields.String(allow_none=True)
    failureReason = fields.String(allow_none=True)
    subdomainCount = fields.Integer()
    findingCount = fields.Integer()
    dkimSelectors = fields.List(fields.String())
    cloudResources = fields.List(fields.String())
    checkSubdomains = fields.Boolean()
    sources = fields.List(fields.Dict())
    dnsChecks = fields.List(fields.Dict())
    subdomains = fields.List(fields.Dict())
    findings = fields.List(fields.Dict())


class OsintScanListResponseSchema(Schema):
    """Respuesta de ``GET /themis/osint``: los escaneos pasivos recientes, sin detalle."""

    message = fields.String()
    count = fields.Integer()
    results = fields.List(fields.Dict())
    user = fields.String()


class UnresolvedProductsQuerySchema(Schema):
    limit = fields.Integer(load_default=50, validate=validate.Range(min=1, max=500))
    # El origen separa dos frentes de trabajo distintos: los banners de red
    # aportan muestras desde el primer escaneo, mientras que el inventario
    # necesita agentes desplegados.
    origin = fields.String(load_default=None, allow_none=True,
                           validate=validate.OneOf(["network", "inventory"]))


class KbSearchQuerySchema(Schema):
    # Un identificador de CVE o un trozo de nombre de producto; ver
    # ``KbQueryManager.search``.
    query = fields.String(required=True, validate=validate.Length(min=2, max=128))
    limit = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))


class KbCveLookupQuerySchema(Schema):
    # Consulta pública: solo un identificador de CVE completo, nunca un texto
    # libre ni un producto. Así el coste de cada petición es el de una lectura
    # por clave, y no una búsqueda por prefijo que cualquiera pueda encadenar.
    id = fields.String(
        required=True,
        validate=validate.Regexp(r"^CVE-\d{4}-\d{4,7}\Z", flags=re.IGNORECASE,
                                 error="Not a valid CVE identifier."),
    )


class KbVersionCheckQuerySchema(Schema):
    # Consulta pública: un nombre de producto y una versión, nunca un prefijo.
    # El nombre se resuelve por coincidencia exacta tras normalizarlo (como un
    # servicio de un escaneo), así que no sirve para recorrer el índice.
    product = fields.String(required=True, validate=validate.Length(min=1, max=80))
    version = fields.String(
        required=True,
        validate=validate.Regexp(r"^[0-9A-Za-z][0-9A-Za-z.+~_:-]{0,39}\Z", error="Not a valid version."),
    )


class KbSyncRequestSchema(Schema):
    # Nunca el histórico completo de NVD: el botón lanza el mismo delta que el
    # job nocturno. Ver ``KbSyncTaskManager.request_sync``.
    source = fields.String(required=True, validate=validate.OneOf(
        ["all", "nvd", "kev", "epss", "oval"]))


class FindingStateRequestSchema(Schema):
    # ``accepted`` y ``false_positive`` dicen cosas opuestas y por eso son
    # estados distintos en vez de compartir casilla: aceptar un riesgo es
    # "esto es real, lo asumo"; desmentirlo es "esto no es real, el motor se
    # equivocó". Un informe que
    # cuenta los segundos como riesgos aceptados miente sobre la postura de
    # seguridad. ``fixed`` y ``regressed`` no están porque los pone el ciclo de
    # vida al comparar escaneos: dejarlos escribir aquí permitiría falsear el
    # historial.
    state = fields.String(
        required=True,
        validate=validate.OneOf(["accepted", "false_positive", "open"]),
    )
    reason = fields.String(load_default=None, allow_none=True,
                           validate=validate.Length(max=500))


class FindingStateResponseSchema(Schema):
    message = fields.String()
    findingId = fields.Integer()
    state = fields.String()
    user = fields.String()


class AddAuthorizedTargetSchema(Schema):
    """Cuerpo de ``POST /themis/authorized-targets``: lo que se autoriza y una nota.

    Attributes:
        target: El objetivo, de 1 a 255 caracteres, en cualquiera de las tres
            formas del registro: una IP o un rango CIDR (``203.0.113.0/24``), un
            dominio (``example.com``, que cubre también sus subdominios) o un
            recurso cloud ``proveedor:identificador`` (``s3:mi-bucket``). El
            tope es el de la columna: un dominio puede tener hasta 253
            caracteres. La forma se valida en ``AuthorizedTargetManager.add``.
        label: Nota libre opcional, hasta 255 caracteres. Por defecto ``None``.
        declarationAccepted: ``true`` si el usuario ha aceptado la declaración de
            que el sistema es suyo o de que su titular le ha autorizado a
            analizarlo. Sin ella el objetivo no se añade.
        declarationVersion: Versión del texto de la declaración que se le
            enseñó; tiene que ser la vigente (``AUTHORIZATION_DECLARATION_VERSION``).
    """

    target = fields.String(required=True, validate=validate.Length(min=1, max=255))
    label = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    declarationAccepted = fields.Boolean(required=True)
    declarationVersion = fields.String(required=True, validate=validate.Length(min=1, max=32))


class AuthorizedTargetSchema(Schema):
    id = fields.Integer()
    target = fields.String()
    label = fields.String(allow_none=True)
    createdAt = UTCDateTime()
    declarationVersion = fields.String(allow_none=True)


class AuthorizedTargetListResponseSchema(Schema):
    message = fields.String()
    targets = fields.List(fields.Nested(AuthorizedTargetSchema))
    user = fields.String()


class AuthorizedTargetActionResponseSchema(Schema):
    message = fields.String()
    targetId = fields.Integer()
    target = fields.String()
    user = fields.String()


class ComplianceFrameworkSchema(Schema):
    key = fields.String()
    name = fields.String()
    shortName = fields.String()


class ComplianceFrameworksRequestSchema(Schema):
    """Marcos de cumplimiento elegidos; ``null`` deja de elegir."""

    frameworks = fields.List(
        fields.String(validate=validate.OneOf([framework.key for framework in list_compliance_frameworks()])),
        required=True, allow_none=True,
    )


class CompliancePreferencesResponseSchema(Schema):
    """Preferencias de marcos: el catálogo, las elecciones y la que se aplica."""

    frameworks = fields.List(fields.Nested(ComplianceFrameworkSchema))
    mine = fields.List(fields.String(), allow_none=True)
    organization = fields.List(fields.String(), allow_none=True)
    effective = fields.List(fields.String())
    isLockedByOrganization = fields.Boolean()
    canManageOrganization = fields.Boolean()


class ResultsQuerySchema(Schema):
    type = fields.String(load_default="all", validate=validate.OneOf([scan_type.value for scan_type in ScanType] + ["all"]))
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=10, validate=validate.Range(min=1, max=100))
    # Solo con type=lybra: acota la lista a los escaneos originados por
    # el inventario de un activo de Hygeia. Omitirlo devuelve los escaneos
    # lanzados desde el panel de Themis (los de agente se ven por agente, no
    # mezclados en la feed general).
    assetId = fields.Integer(load_default=None, allow_none=True)


class GeneratePdfRequestSchema(Schema):
    id = fields.Integer(required=True)
    aiReport = fields.Boolean(load_default=False)


class DocumentStatusQuerySchema(Schema):
    document_id = fields.Integer()
    scan_id = fields.Integer()

    @validates_schema
    def validate_at_least_one(self, data, **kwargs):
        if not data.get("document_id") and not data.get("scan_id"):
            raise ValidationError("Indica el documento o el escaneo.")


class DocumentsQuerySchema(Schema):
    # Derived from ScanType and OsintScanMode, not hand-listed: a new scan
    # type or domain-scan mode is filterable here automatically.
    scan_type = fields.String(load_default="all", validate=validate.OneOf(
        [scan_type.value for scan_type in ScanType] + [mode.value for mode in OsintScanMode] + ["all"]))


class ScheduledScanRequestSchema(Schema):
    scan_type = fields.String(required=True)
    arguments = fields.Dict(required=True)
    schedule_type = fields.String(required=True)
    schedule_config = fields.Dict(required=True)


class ScanResponseSchema(Schema):
    message = fields.String()
    scanId = fields.Integer()
    scanType = fields.String()
    user = fields.String()


class NmapScanResponseSchema(Schema):
    message = fields.String()
    scanIds = fields.List(fields.Integer())
    target = fields.Dict()
    totalScans = fields.Integer()
    user = fields.String()


class ScanStatusResponseSchema(Schema):
    message = fields.String()
    scanId = fields.Integer()
    status = fields.String()
    scanType = fields.String()
    progress = fields.Float(required=False)
    scan = fields.Dict(required=False)


class IsFinishedResponseSchema(Schema):
    message = fields.String()
    scanId = fields.Integer()
    isFinished = fields.Boolean()
    scanType = fields.String()


class ResultsResponseSchema(Schema):
    message = fields.String()
    filter = fields.String()
    count = fields.Integer()
    results = fields.List(fields.Dict())
    page = fields.Integer(required=False)
    perPage = fields.Integer(required=False)
    totalCount = fields.Integer(required=False)
    totalPages = fields.Integer(required=False)
    user = fields.String()


class ScanDetailResponseSchema(Schema):
    message = fields.String()
    result = fields.Dict()
    user = fields.String()


class DocumentStatusResponseSchema(Schema):
    documentId = fields.Integer()
    scanId = fields.Integer(allow_none=True)
    osintScanId = fields.Integer(allow_none=True)
    status = fields.String()
    aiReport = fields.Boolean()
    createdAt = UTCDateTime(allow_none=True)
    generatedAt = UTCDateTime(allow_none=True)
    downloadUrl = fields.String(allow_none=True)


class DocumentListResponseSchema(Schema):
    documents = fields.List(fields.Dict())
    total = fields.Integer()
    filter = fields.String(required=False)


class ScanDocumentsResponseSchema(Schema):
    scanId = fields.Integer()
    documents = fields.List(fields.Dict())
    total = fields.Integer()


class DocumentDeleteResponseSchema(Schema):
    message = fields.String()
    documentId = fields.Integer()


class PdfGenerateResponseSchema(Schema):
    message = fields.String()
    documentId = fields.Integer()
    scanId = fields.Integer()
    status = fields.String()
    aiReport = fields.Boolean()
    downloadUrl = fields.String()


class ScheduledScanResponseSchema(Schema):
    message = fields.String()
    programedScanId = fields.Integer()
    scanType = fields.String()
    scheduleType = fields.String()
    scheduleConfig = fields.Dict()
    nextRunAt = UTCDateTime(allow_none=True)
    user = fields.String()


class ScheduledScanListItemSchema(Schema):
    id = fields.Integer()
    scanType = fields.String()
    arguments = fields.Dict()
    scheduleType = fields.String()
    scheduleConfig = fields.Dict()
    isActive = fields.Boolean()
    lastRunAt = UTCDateTime(allow_none=True)
    nextRunAt = UTCDateTime(allow_none=True)
    createdAt = UTCDateTime(allow_none=True)


class ScheduledScanListResponseSchema(Schema):
    message = fields.String()
    count = fields.Integer()
    scheduledScans = fields.List(fields.Dict())
    user = fields.String()


class ScheduledScanActionResponseSchema(Schema):
    message = fields.String()
    programedScanId = fields.Integer()
    scanType = fields.String()
    user = fields.String()


# =========================================================================
# FOLDER SCHEMAS
# =========================================================================

class CreateFolderSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=255))


class RenameFolderSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=255))


class MoveScanToFolderSchema(Schema):
    scanId = fields.Integer(required=True)


class AddScansToFolderSchema(Schema):
    scanIds = fields.List(fields.Integer(), required=True, validate=validate.Length(min=1))


class FolderSchema(Schema):
    id = fields.Integer(allow_none=True)
    name = fields.String()
    createdAt = UTCDateTime(allow_none=True)
    updatedAt = UTCDateTime(allow_none=True)
    scanCount = fields.Integer()
    scans = fields.List(fields.Dict())


class FolderListResponseSchema(Schema):
    message = fields.String()
    folders = fields.List(fields.Nested(FolderSchema))
    unfoldered = fields.Nested(FolderSchema)
    user = fields.String()


class FolderActionResponseSchema(Schema):
    message = fields.String()
    folderId = fields.Integer()
    name = fields.String()
    user = fields.String()


class ScanFolderActionResponseSchema(Schema):
    message = fields.String()
    scanId = fields.Integer(allow_none=True)
    folderId = fields.Integer(allow_none=True)
    user = fields.String()


class BulkDeleteScansSchema(Schema):
    scanIds = fields.List(fields.Integer(), required=True, validate=validate.Length(min=1, max=100))


class BulkDeleteResultSchema(Schema):
    scanId = fields.Integer()
    status = fields.String()
    error = fields.String(allow_none=True)


class BulkDeleteScansResponseSchema(Schema):
    message = fields.String()
    deletedCount = fields.Integer()
    failedCount = fields.Integer()
    results = fields.List(fields.Nested(BulkDeleteResultSchema))
    user = fields.String()


# =========================================================================
# HISTORY / STATISTICS SCHEMAS
# =========================================================================

class HistoryHostItemSchema(Schema):
    target = fields.String()
    scanType = fields.String()
    scanCount = fields.Integer()
    lastScannedAt = UTCDateTime(allow_none=True)


class HistoryHostsResponseSchema(Schema):
    message = fields.String()
    hosts = fields.List(fields.Nested(HistoryHostItemSchema))
    user = fields.String()


class HistoryStatsQuerySchema(Schema):
    target = fields.String(required=True)
    type = fields.String(required=True, validate=validate.OneOf([scan_type.value for scan_type in ScanType]))


class HistoryStatsResponseSchema(Schema):
    message = fields.String()
    scanType = fields.String()
    target = fields.String()
    metricLabel = fields.String()
    axes = fields.Dict()
    series = fields.List(fields.Dict())
    diff = fields.Dict()
    legend = fields.List(fields.Dict())
    scanCount = fields.Integer()
    user = fields.String()


# =========================================================================
# TRACEROUTE SCHEMAS
# =========================================================================

class TracerouteResponseSchema(Schema):
    message = fields.String()
    target = fields.String()
    hops = fields.List(fields.Dict())
    hopCount = fields.Integer()
    computedAt = fields.String(allow_none=True)
    cached = fields.Boolean()
    status = fields.String()  # "pending" | "done" | "failed"
    user = fields.String()
