"""
Marshmallow schemas for Iris REST API request/response validation.
Fields use camelCase for JSON keys as per the project convention.
"""

from __future__ import annotations

from marshmallow import Schema, ValidationError, fields, post_load, validate, validates_schema

import src.modules.system.config_reading as CR
from src.modules.shared import UTCDateTime

from .services.feedback_metrics import FEEDBACK_LABELS
from .model import SUBSCRIBABLE_WEBHOOK_EVENTS, CasePriority, CaseStatus, MailboxAction, TrustKind
from .services.quality import AnalysisMode
from .services.scoring import PROFILE_THRESHOLD_OFFSETS
from .services.trust import MAX_TRUST_EXPIRY_DAYS, MAX_TRUST_REASON_LENGTH


def _input_fields_in_use(data: dict) -> tuple[str, ...]:
    """Campos de entrada que va a analizar una petición de ``POST /iris/analyze``.

    Args:
        data: Cuerpo ya deserializado.

    Returns:
        tuple[str, ...]: ``("headers",)`` en modo cabeceras, ``("message",)`` en
            modo completo, o los dos si la petición no trae ``mode``.
    """
    mode = data.get("mode")
    if mode == AnalysisMode.HEADERS:
        return ("headers",)
    if mode == AnalysisMode.MESSAGE:
        return ("message",)
    return ("headers", "message")


class AnalyzeRequestSchema(Schema):
    """Cuerpo de ``POST /iris/analyze``.

    ``mode`` dice qué se analiza: ``headers`` (el bloque de cabeceras de
    ``headers``) o ``message`` (el ``.eml`` completo de ``message``). Con
    modo, solo se valida y se usa el campo de ese modo y el otro se descarta,
    así que elegir solo cabeceras nunca falla por el tamaño de un mensaje que
    no se va a analizar. Sin ``mode`` (clientes que no lo envían) basta con
    cualquiera de los dos y, si vienen ambos, ``message`` tiene prioridad por
    ser un superconjunto de las cabeceras.
    """
    title = fields.String(load_default=None, validate=validate.Length(max=120))
    mode = fields.String(load_default=None, validate=validate.OneOf([mode.value for mode in AnalysisMode]))
    headers = fields.String(load_default=None, validate=validate.Length(min=10))
    message = fields.String(load_default=None, validate=validate.Length(min=10))

    @validates_schema
    def validate_has_input(self, data, **kwargs):
        """Exige el campo que corresponde al modo, o al menos uno sin modo."""
        mode = data.get("mode")
        if mode == AnalysisMode.HEADERS and not data.get("headers"):
            raise ValidationError("El modo 'headers' necesita el campo 'headers'.", field_name="headers")
        if mode == AnalysisMode.MESSAGE and not data.get("message"):
            raise ValidationError(
                "El modo 'message' necesita el campo 'message' (el .eml completo).", field_name="message",
            )
        if not data.get("headers") and not data.get("message"):
            raise ValidationError(
                "Debe proporcionar 'headers' (cabeceras) o 'message' (mensaje completo .eml).",
                field_name="headers",
            )

    @validates_schema
    def validate_max_size(self, data, **kwargs):
        """Rechaza la entrada que se va a analizar si supera ``iris.maxMessageBytes``.

        Sin tope superior, un .eml de decenas de MB (adjuntos incluidos)
        entraría entero a una columna Text y se re-parsearía completo (incluida
        la decodificación base64) en cada lectura posterior. Solo se mira el
        campo que usa el modo (``_input_fields_in_use``). Leído con CR en cada
        validación, no horneado al importar el módulo, para que un cambio vía
        PUT /system surta efecto sin reiniciar la API (mismo patrón que
        ``hygeia/schemas.py::validate_array_limits``).
        """
        max_bytes = CR.iris_config().max_message_bytes
        for field_name in _input_fields_in_use(data):
            value = data.get(field_name)
            if value and len(value.encode("utf-8", errors="ignore")) > max_bytes:
                raise ValidationError(
                    f"'{field_name}' excede el tamaño máximo permitido ({max_bytes} bytes).",
                    field_name=field_name,
                )

    @post_load
    def drop_unused_input(self, data, **kwargs):
        """Descarta el campo de entrada que el modo elegido no usa.

        Así el endpoint y el manager siguen recibiendo ``headers`` y
        ``message`` como siempre, y con modo solo llega relleno el que toca.

        Returns:
            dict: Los datos con ``message`` a ``None`` en modo cabeceras, o
                ``headers`` a ``None`` en modo completo; sin modo, intactos.
        """
        in_use = _input_fields_in_use(data)
        for field_name in ("headers", "message"):
            if field_name not in in_use:
                data[field_name] = None
        return data


class IrisCapabilitiesResponseSchema(Schema):
    """Límites y modos que la interfaz necesita para decidir igual que el API.

    Existe para que el frontend no tenga que replicar constantes del backend:
    una copia en el navegador deriva en cuanto alguien cambia la config del
    servidor, y el usuario se lleva el rechazo después de haber cargado el
    fichero entero en memoria.

    ``headersOnlyUncoveredRules`` son las reglas que no tendrán nada que
    inspeccionar en modo cabeceras, y ``fullMessageNotice`` el aviso de que el
    modo completo puede incluir datos sensibles: la interfaz los enseña al
    elegir el modo, antes de enviar.

    ``verdictThresholds`` viaja ya en la respuesta del listado; se repite aquí
    para que una vista que aún no ha listado nada pueda pintar la escala de
    riesgo sin pedir primero una página de resultados.
    """
    maxMessageBytes = fields.Integer()
    minHeaders = fields.Integer()
    analysisModes = fields.List(fields.String())
    headersOnlyUncoveredRules = fields.List(fields.String())
    fullMessageNotice = fields.String()
    verdictThresholds = fields.Nested(lambda: VerdictThresholdsSchema())


class AnalysisIdQuerySchema(Schema):
    """Query parameter for ``GET /iris/status`` — supplied as ``?id=...``."""
    id = fields.Integer(required=True)


class IrisTriageFiltersSchema(Schema):
    """Filtros y orden del historial de análisis.

    Son los parámetros de ``GET /iris/results`` sin la paginación, y lo que
    guarda una vista guardada. Todos son opcionales y por defecto no filtran:

    - ``search``: subcadena del título.
    - ``verdict``, ``status``, ``source``: igualdad exacta.
    - ``tag``: etiqueta exacta del analista.
    - ``ioc``: un dominio, URL, IP, dirección o hash; se admite desactivado
      (``hxxp``, ``[.]``) y se busca en el índice de IOCs.
    - ``review``: ``pending`` (terminado y sin corregir) o ``reviewed``.
    - ``sort_by``/``sort_dir``: orden en servidor.
    """
    search = fields.String(load_default=None, validate=validate.Length(max=120))
    verdict = fields.String(load_default=None,
                             validate=validate.OneOf(["Legitimate", "Suspicious", "Phishing"]))
    status = fields.String(load_default=None,
                            validate=validate.OneOf(["pending", "running", "finished", "failed", "cancelled"]))
    source = fields.String(load_default=None, validate=validate.OneOf(["manual", "mailbox"]))
    sort_by = fields.String(load_default="date",
                             validate=validate.OneOf(["date", "score", "verdict", "title", "status"]))
    sort_dir = fields.String(load_default="desc", validate=validate.OneOf(["asc", "desc"]))
    tag = fields.String(load_default=None, validate=validate.Length(max=40))
    ioc = fields.String(load_default=None, validate=validate.Length(max=2048))
    review = fields.String(load_default=None, validate=validate.OneOf(["pending", "reviewed"]))


class ResultsQuerySchema(IrisTriageFiltersSchema):
    """Parámetros de ``GET /iris/results``: los filtros del historial más la página."""
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=10, validate=validate.Range(min=1, max=100))


class AnalyzeResponseSchema(Schema):
    """Response returned immediately after submitting headers."""
    message = fields.String()
    analysisId = fields.Integer()
    status = fields.String()


class AnalysisStatusResponseSchema(Schema):
    """Current lifecycle status and optional progress of an analysis.

    ``failureCode``/``failureReason`` solo viajan cuando ``status`` es
    ``failed``. Es aquí donde se consultan, y no en el informe completo,
    porque ``GET /iris/results/<id>`` exige un análisis ``finished``: un
    análisis que murió no tiene informe que devolver, solo un motivo.
    """
    analysisId = fields.Integer()
    status = fields.String()
    progress = fields.Integer(load_default=None)
    totalScore = fields.Float(load_default=None)
    verdict = fields.String(load_default=None)
    failureCode = fields.String(load_default=None, allow_none=True)
    failureReason = fields.String(load_default=None, allow_none=True)


class EvidenceSchema(Schema):
    """Dónde está, dentro del mensaje, lo que una regla encontró.

    ``kind`` es ``header``, ``body``, ``mime_part``, ``attachment`` o ``url``;
    ``locator`` dice cómo encontrarlo (p. ej. ``{"header": "from",
    "occurrence": 0}`` o ``{"linkIndex": 2}``) y ``excerpt`` es el fragmento
    con URLs, dominios y direcciones ya desactivados (``hxxp``, ``[.]``,
    ``[@]``). Ver ``services/evidence.py``.
    """
    kind = fields.String()
    locator = fields.Dict()
    excerpt = fields.String()


class RuleResultSchema(Schema):
    """Outcome of a single rule within a finished analysis.

    Una regla que penaliza trae ``evidence`` o, si su hallazgo no se puede
    anclar a un fragmento del mensaje, ``evidenceUnavailableReason``.

    ``ruleId`` es el identificador estable del hallazgo (``ruleName`` es el
    nombre visible y puede cambiar); ``severity`` es su gravedad, separada del
    score, y ``mitreTechniques`` sus técnicas ATT&CK. Los tres valen ``null``
    (o lista vacía) en análisis anteriores a la taxonomía.
    """
    ruleId = fields.String(load_default=None, allow_none=True)
    ruleName = fields.String()
    severity = fields.String(load_default=None, allow_none=True)
    mitreTechniques = fields.List(fields.String(), load_default=list)
    category = fields.String(load_default=None)
    score = fields.Float()
    verdict = fields.String()
    details = fields.Dict(load_default=None)
    recommendation = fields.String(load_default=None)
    evidence = fields.List(fields.Nested(EvidenceSchema), load_default=None)
    evidenceUnavailableReason = fields.String(load_default=None, allow_none=True)


class TopSignalSchema(Schema):
    """One of the highest-penalty rules for a finished analysis."""
    ruleId = fields.String(load_default=None, allow_none=True)
    ruleName = fields.String()
    category = fields.String(load_default=None)
    score = fields.Float()
    index = fields.Integer()


class AiSummarySchema(Schema):
    """AI-generated executive narrative for a finished analysis (IA1)."""
    executive_summary = fields.String()
    attacker_intent = fields.String()
    recommendations = fields.List(fields.String())
    confidence = fields.String()


class FailedRuleSchema(Schema):
    """Regla que no se pudo **ejecutar** durante un análisis.

    No confundir con una regla que detectó algo: esas van en ``rules`` con su
    puntuación negativa. Estas son las que lanzaron una excepción, así que su
    parte del mensaje se quedó sin inspeccionar.
    """
    name = fields.String()
    ruleId = fields.String(load_default=None, allow_none=True)
    family = fields.String(load_default=None, allow_none=True)
    category = fields.String(load_default=None, allow_none=True)


class IrisFeedbackRequestSchema(Schema):
    """Corrección del analista sobre el veredicto de un análisis terminado.

    ``label`` es ``malicious``, ``legitimate`` o ``unknown`` (revisado, pero
    no se puede decidir). No modifica el veredicto: se guarda aparte y
    alimenta las métricas.
    """
    label = fields.String(required=True, validate=validate.OneOf(FEEDBACK_LABELS))
    note = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=2000))


class IrisFeedbackItemSchema(Schema):
    """Una corrección registrada: etiqueta, nota, autor y fecha."""
    feedbackId = fields.Integer()
    analysisId = fields.Integer()
    label = fields.String()
    note = fields.String(load_default=None, allow_none=True)
    author = fields.String()
    createdAt = fields.String()


class IrisFeedbackListResponseSchema(Schema):
    """Historial de correcciones de un análisis, de la más reciente a la más antigua."""
    analysisId = fields.Integer()
    feedback = fields.List(fields.Nested(IrisFeedbackItemSchema))


class IrisFeedbackOverallMetricsSchema(Schema):
    """Matriz de confusión y tasas globales del detector frente a las etiquetas.

    Un veredicto positivo es cualquiera que avisa (``Suspicious`` o
    ``Phishing``). Las tasas valen ``null`` cuando no hay datos.
    """
    truePositives = fields.Integer()
    falsePositives = fields.Integer()
    falseNegatives = fields.Integer()
    trueNegatives = fields.Integer()
    precision = fields.Float(allow_none=True)
    recall = fields.Float(allow_none=True)
    disagreementRate = fields.Float(allow_none=True)


class IrisFeedbackFamilyMetricsSchema(Schema):
    """Métricas de una familia de reglas: ¿disparar esta familia coincide con malicioso?"""
    family = fields.String()
    fired = fields.Integer()
    precision = fields.Float(allow_none=True)
    recall = fields.Float(allow_none=True)
    disagreementRate = fields.Float(allow_none=True)
    coverage = fields.Float(allow_none=True)


class IrisFeedbackMetricsResponseSchema(Schema):
    """Métricas del detector calculadas con las correcciones vigentes del usuario."""
    analysesTotal = fields.Integer()
    reviewed = fields.Integer()
    unknown = fields.Integer()
    feedbackCoverage = fields.Float(allow_none=True)
    overall = fields.Nested(IrisFeedbackOverallMetricsSchema)
    families = fields.List(fields.Nested(IrisFeedbackFamilyMetricsSchema))


class CoverageSchema(Schema):
    """Qué partes del mensaje se pudieron inspeccionar.

    ``mode`` es ``full_message`` (había cuerpo o adjuntos) o ``headers_only``;
    en este último, ``uncoveredRules`` lista las reglas de cuerpo, enlaces y
    adjuntos que no tuvieron nada que mirar.
    """
    mode = fields.String()
    uncoveredRules = fields.List(fields.String(), load_default=None)


class PreviewHeadersSchema(Schema):
    """Cabeceras de la vista previa del mensaje que produjo el veredicto.

    Salen del contexto ganador (ver ``winningContext``): en un reenvío cuyo
    envoltorio es más grave que el original, son las del envoltorio.
    """
    subject = fields.String(load_default=None, allow_none=True)
    from_ = fields.String(data_key="from", attribute="from", load_default=None, allow_none=True)
    to = fields.String(load_default=None, allow_none=True)
    replyTo = fields.String(load_default=None, allow_none=True)
    returnPath = fields.String(load_default=None, allow_none=True)
    date = fields.String(load_default=None, allow_none=True)


class SecondaryContextSchema(Schema):
    """El otro mensaje de un reenvío: el que **no** decidió el veredicto.

    Se conserva entero —veredicto, score y reglas— para que el analista pueda
    ver por qué perdió sin que se mezcle con la evidencia del ganador.
    """
    contextType = fields.String()
    verdict = fields.String(load_default=None, allow_none=True)
    totalScore = fields.Float(load_default=None, allow_none=True)
    analysisQuality = fields.String(load_default=None, allow_none=True)
    rules = fields.List(fields.Nested(RuleResultSchema), load_default=None)


class AnalysisDetailResponseSchema(Schema):
    """Full analysis report: headers, per-rule results, verdict.

    ``winningContext`` dice qué mensaje produjo el veredicto (``inner`` o
    ``wrapper``); ``rules``, ``topSignals``, ``previewHeaders`` y los IOCs
    describen siempre ese mensaje. ``secondaryContext`` trae el otro, solo
    en reenvíos.

    ``confidence`` es ordinal (``high``/``medium``/``low``), **no** una
    probabilidad; ``uncertaintyReasons`` explica por qué no es ``high`` y
    ``coverage`` dice si se inspeccionó el mensaje completo o solo cabeceras.
    """
    analysisId = fields.Integer()
    title = fields.String(load_default=None)
    status = fields.String()
    rawHeaders = fields.String()
    totalScore = fields.Float(load_default=None)
    verdict = fields.String(load_default=None)
    gateReasons = fields.List(fields.String(), load_default=None)
    analysisQuality = fields.String(load_default=None, allow_none=True)
    failedRules = fields.List(fields.Nested(FailedRuleSchema), load_default=None)
    detectorVersion = fields.String(load_default=None, allow_none=True)
    confidence = fields.String(load_default=None, allow_none=True)
    coverage = fields.Nested(CoverageSchema, load_default=None, allow_none=True)
    scoringVersion = fields.String(load_default=None, allow_none=True)
    scoringSnapshot = fields.Dict(load_default=None, allow_none=True)
    uncertaintyReasons = fields.List(fields.String(), load_default=None)
    topSignals = fields.List(fields.Nested(TopSignalSchema), load_default=None)
    aiSummary = fields.Nested(AiSummarySchema, load_default=None, allow_none=True)
    aiSummaryStatus = fields.String(load_default=None, allow_none=True)
    aiSummaryModel = fields.String(load_default=None, allow_none=True)
    aiSummaryPromptVersion = fields.String(load_default=None, allow_none=True)
    unwrappedFromForward = fields.Boolean(load_default=False)
    wrapperFrom = fields.String(load_default=None, allow_none=True)
    wrapperSubject = fields.String(load_default=None, allow_none=True)
    reportChannel = fields.String(load_default=None, allow_none=True)
    winningContext = fields.String(load_default=None, allow_none=True)
    winningReason = fields.String(load_default=None, allow_none=True)
    secondaryContext = fields.Nested(SecondaryContextSchema, load_default=None, allow_none=True)
    previewHeaders = fields.Nested(PreviewHeadersSchema, load_default=None, allow_none=True)
    startedAt = fields.String(load_default=None)
    finishedAt = fields.String(load_default=None)
    failureCode = fields.String(load_default=None, allow_none=True)
    failureReason = fields.String(load_default=None, allow_none=True)
    user = fields.String()
    rules = fields.List(fields.Nested(RuleResultSchema))
    recommendations = fields.List(fields.String())
    latestFeedback = fields.Nested(IrisFeedbackItemSchema, load_default=None, allow_none=True)
    trustApplied = fields.Dict(load_default=None, allow_none=True)
    tags = fields.List(fields.String(), load_default=list)
    campaign = fields.Nested("AnalysisCampaignSchema", load_default=None, allow_none=True)
    contactDeviation = fields.Nested("ContactDeviationSchema", load_default=None, allow_none=True)
    organizationSightings = fields.Nested("OrganizationSightingsSchema", load_default=None, allow_none=True)


class AnalysisCampaignSchema(Schema):
    """La campaña de un análisis, tal como acompaña a su informe."""
    campaignId = fields.Integer()
    label = fields.String(allow_none=True)
    relatedCount = fields.Integer()


class OrganizationSightingIndicatorSchema(Schema):
    """Un indicador del análisis y cuántos miembros de la organización lo han visto."""
    kind = fields.String()
    value = fields.String()
    memberCount = fields.Integer()


class OrganizationSightingsSchema(Schema):
    """Indicadores del análisis que también han visto otros miembros de la organización."""
    minMembers = fields.Integer()
    indicators = fields.List(fields.Nested(OrganizationSightingIndicatorSchema))


class ContactDeviationSchema(Schema):
    """El remitente imita a un contacto habitual del usuario.

    ``kind`` es ``display_name_reuse`` (usa su nombre desde otra dirección) o
    ``address_domain_change`` (su misma dirección con otro dominio).
    """
    kind = fields.String()
    senderAddress = fields.String()
    displayName = fields.String(allow_none=True)
    habitualAddress = fields.String()
    habitualMessages = fields.Integer()


class AnalysisListItemSchema(Schema):
    """Summary of a single analysis shown in a paginated list."""
    analysisId = fields.Integer()
    title = fields.String(load_default=None)
    status = fields.String()
    failureCode = fields.String(load_default=None, allow_none=True)
    analysisQuality = fields.String(load_default=None, allow_none=True)
    confidence = fields.String(load_default=None, allow_none=True)
    totalScore = fields.Float(load_default=None)
    verdict = fields.String(load_default=None)
    startedAt = fields.String(load_default=None)
    finishedAt = fields.String(load_default=None)
    connectionId = fields.Integer(load_default=None)
    provider = fields.String(load_default=None)
    accountEmail = fields.String(load_default=None)
    tags = fields.List(fields.String(), load_default=list)
    reviewed = fields.Boolean(load_default=False)


class VerdictThresholdsSchema(Schema):
    """Score thresholds used to classify a verdict — sent alongside the list
    so the frontend can render them (e.g. a score rail) without hardcoding
    ``iris.legitimate_threshold``/``iris.suspicious_threshold``.
    """
    legitimate = fields.Float()
    suspicious = fields.Float()


class AnalysisListResponseSchema(Schema):
    """Paginated list of analyses for the current user."""
    analyses = fields.List(fields.Nested(AnalysisListItemSchema))
    total = fields.Integer()
    page = fields.Integer()
    perPage = fields.Integer()
    thresholds = fields.Nested(VerdictThresholdsSchema)


class AnalysisDeleteResponseSchema(Schema):
    """Confirmation after deleting an analysis."""
    message = fields.String()
    analysisId = fields.Integer()


class AnalysisCancelResponseSchema(Schema):
    """Confirmation after cancelling a running analysis."""
    message = fields.String()
    analysisId = fields.Integer()
    status = fields.String()


class ReceivedHopSchema(Schema):
    """Single hop inside a Received-chain path.

    Ordered oldest -> newest when returned by the API.
    """
    hop = fields.Integer()
    index = fields.Integer()
    fromAddress = fields.String(attribute="from", allow_none=True)
    fromIp = fields.String(allow_none=True)
    by = fields.String(allow_none=True)
    withProtocol = fields.String(attribute="with", allow_none=True)
    protocol = fields.String(allow_none=True)
    id = fields.String(allow_none=True)
    forAddress = fields.String(attribute="for", allow_none=True)
    tls = fields.Boolean()
    timestamp = fields.String(allow_none=True)
    flags = fields.List(fields.String())
    raw = fields.String()


class ReceivedTransitionSchema(Schema):
    """Edge between two consecutive hops (oldest -> newest direction)."""
    from_ = fields.Integer(attribute="from")
    to = fields.Integer()
    delayMs = fields.Integer(allow_none=True)
    suspicious = fields.Boolean()
    reasons = fields.List(fields.String())


class ReceivedPathResponseSchema(Schema):
    """Response for ``GET /iris/results/<id>/path``.

    ``hops`` and ``transitions`` are empty when no Received chain is
    available (e.g. headers-only submissions). ``contextType`` dice de qué
    mensaje del reenvío sale la cadena: el mismo que decidió el veredicto.
    """
    analysisId = fields.Integer()
    contextType = fields.String(load_default=None, allow_none=True)
    available = fields.Boolean()
    hopsCount = fields.Integer()
    hops = fields.List(fields.Nested(ReceivedHopSchema))
    transitions = fields.List(fields.Nested(ReceivedTransitionSchema))
    reason = fields.String(load_default=None)


class AnalysisIocsResponseSchema(Schema):
    """Response for ``GET /iris/results/<id>/iocs`` (O1).

    Each field is a sorted, deduplicated list of pivotable indicators
    derived from the analyzed message — empty lists (not null) when a
    category yields nothing (e.g. no body links in a headers-only
    submission). ``contextType`` dice de qué mensaje del reenvío salen: el
    mismo que decidió el veredicto.
    """
    analysisId = fields.Integer()
    contextType = fields.String(load_default=None, allow_none=True)
    domains = fields.List(fields.String())
    urls = fields.List(fields.String())
    ips = fields.List(fields.String())
    emails = fields.List(fields.String())
    hashes = fields.List(fields.String())


class GenerateDocumentResponseSchema(Schema):
    """Response returned immediately after queuing PDF generation."""
    message = fields.String()
    documentId = fields.Integer()
    analysisId = fields.Integer()
    status = fields.String()
    downloadUrl = fields.String(load_default=None)


class GenerateAiSummaryRequestSchema(Schema):
    """Parámetros de ``POST /iris/results/<id>/ai-summary``.

    ``regenerate`` distingue las dos intenciones que antes eran una sola
    petición indistinguible: repetirla porque el navegador reintentó o porque
    el usuario hizo doble clic (y entonces lo correcto es devolver el resumen
    que ya hay, sin cobrar), o pedir explícitamente otra redacción (y entonces
    sí se genera de nuevo, y se cobra).
    """
    regenerate = fields.Boolean(load_default=False)


class GenerateAiSummaryResponseSchema(Schema):
    """Response returned immediately after queuing AI summary generation (IA1).

    There is no separate status to poll: the caller re-fetches
    ``GET /iris/results/<id>`` (``aiSummary``) to see the result once the
    background task finishes.

    ``status`` dice qué pasó de verdad con esta llamada: ``running`` si encoló
    la generación (o si ya había una en curso) y ``done`` si el resumen ya
    existía y se devolvió sin trabajo ni cobro.
    """
    message = fields.String()
    analysisId = fields.Integer()
    status = fields.String()


class DocumentStatusQuerySchema(Schema):
    """Query parameters for ``GET /iris/document-status``.

    Accepts either ``documentId`` (specific document) or ``analysisId``
    (latest document for that analysis) — at least one is required.
    """
    documentId = fields.Integer(load_default=None)
    analysisId = fields.Integer(load_default=None)

    @validates_schema
    def validate_has_id(self, data, **kwargs):
        if not data.get("documentId") and not data.get("analysisId"):
            raise ValidationError(
                "Debe proporcionar 'documentId' o 'analysisId'.",
                field_name="documentId",
            )


class IrisDocumentStatusResponseSchema(Schema):
    """Current generation status of a single IrisDocument."""
    documentId = fields.Integer()
    analysisId = fields.Integer()
    status = fields.String()
    verdict = fields.String(allow_none=True)
    createdAt = UTCDateTime(allow_none=True)
    generatedAt = UTCDateTime(allow_none=True)
    downloadUrl = fields.String(allow_none=True)


class IrisDocumentItemSchema(Schema):
    """Summary of a single IrisDocument shown in a listing."""
    documentId = fields.Integer()
    analysisId = fields.Integer()
    status = fields.String()
    verdict = fields.String(allow_none=True)
    createdAt = UTCDateTime(allow_none=True)
    generatedAt = UTCDateTime(allow_none=True)
    downloadUrl = fields.String(allow_none=True)


class IrisDocumentsQuerySchema(Schema):
    """Query parameters for ``GET /iris/documents``: antes devolvía
    todos los documentos del usuario de golpe, sin límite -- misma
    convención página/tamaño que ``ResultsQuerySchema`` para el listado de
    análisis."""
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=10, validate=validate.Range(min=1, max=100))


class IrisDocumentListResponseSchema(Schema):
    """Página de los IrisDocument del usuario actual."""
    documents = fields.List(fields.Nested(IrisDocumentItemSchema))
    total = fields.Integer()
    page = fields.Integer()
    perPage = fields.Integer()


class AnalysisDocumentsResponseSchema(Schema):
    """All IrisDocuments generated for a specific analysis."""
    analysisId = fields.Integer()
    documents = fields.List(fields.Nested(IrisDocumentItemSchema))
    total = fields.Integer()


class IrisDocumentDeleteResponseSchema(Schema):
    """Confirmation after deleting an IrisDocument."""
    message = fields.String()
    documentId = fields.Integer()


# =============================================================================
# Mailbox connector — Gmail / Microsoft Graph
# =============================================================================

class IrisMailboxProvidersResponseSchema(Schema):
    """Providers configured/supported for the mailbox connector."""
    providers = fields.List(fields.String())


class IrisMailboxConnectRequestSchema(Schema):
    """Request body for ``POST /iris/mailbox/connect``."""
    provider = fields.String(required=True)
    fullMessageMode = fields.Boolean(load_default=False)
    # Pide al proveedor permiso de escritura, necesario para la cuarentena y
    # las demás acciones sobre el buzón. Por defecto, solo lectura.
    remediationEnabled = fields.Boolean(load_default=False)
    # La validación real (existe, pertenece a esta cuenta/proveedor) es
    # de red y solo se puede hacer con un access_token en la mano -- ver
    # IrisMailboxManager._validate_folder(), llamada desde handle_callback().
    # Aquí solo se descarta lo evidentemente inválido antes de firmar el
    # state y mandar al usuario al proveedor.
    folder = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))


class IrisMailboxConnectResponseSchema(Schema):
    """Authorization URL to redirect the user to."""
    authorizeUrl = fields.String()


class IrisMailboxConnectionItemSchema(Schema):
    """A connected mailbox — never includes tokens, encrypted or otherwise."""
    connectionId = fields.Integer()
    provider = fields.String()
    accountEmail = fields.String()
    folder = fields.String(allow_none=True)
    folderDisplayName = fields.String(allow_none=True)
    folderType = fields.String(allow_none=True)
    fullMessageMode = fields.Boolean()
    remediationEnabled = fields.Boolean()
    canAct = fields.Boolean()
    status = fields.String()
    lastSyncAt = UTCDateTime(allow_none=True)
    lastError = fields.String(allow_none=True)
    syncStartedAt = UTCDateTime(allow_none=True)
    createdAt = UTCDateTime(allow_none=True)
    authMode = fields.String()
    additionalFolders = fields.List(fields.Dict())


class IrisMailboxConnectionListResponseSchema(Schema):
    """All mailbox connections belonging to the current user."""
    connections = fields.List(fields.Nested(IrisMailboxConnectionItemSchema))
    total = fields.Integer()


class IrisMailboxUpdateConnectionRequestSchema(Schema):
    """Request body for ``PATCH /iris/mailbox/connections/<id>``."""
    folder = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    status = fields.String(load_default=None, allow_none=True,
                            validate=validate.OneOf(["active", "paused"]))


class IrisMailboxFolderSchema(Schema):
    """Una carpeta/etiqueta real de la cuenta conectada."""
    providerId = fields.String()
    displayName = fields.String()
    folderType = fields.String()


class IrisMailboxFoldersResponseSchema(Schema):
    """Carpetas que expone la cuenta de una conexión -- los únicos valores
    válidos para ``folder`` en ``PATCH /iris/mailbox/connections/<id>``."""
    folders = fields.List(fields.Nested(IrisMailboxFolderSchema))


class IrisMailboxHealthResponseSchema(Schema):
    """Estado observable de una conexión de buzón, sin tener que leer los
    logs del servidor."""
    status = fields.String()
    lastSyncAt = UTCDateTime(allow_none=True)
    lastSuccessAt = UTCDateTime(allow_none=True)
    lastError = fields.String(allow_none=True)
    syncStartedAt = UTCDateTime(allow_none=True)
    lastSyncDurationMs = fields.Integer(allow_none=True)
    cursorEstablished = fields.Boolean()
    ingestedToday = fields.Integer()
    maxIngestedPerDay = fields.Integer()
    messagesDiscoveredTotal = fields.Integer()
    messagesAcceptedTotal = fields.Integer()
    messagesPending = fields.Integer()
    messagesRetrying = fields.Integer()
    messagesDead = fields.Integer()
    oldestPendingMessageAgeSeconds = fields.Integer(allow_none=True)
    eventSubscription = fields.Dict(allow_none=True)


class IrisMailboxConnectionDeleteResponseSchema(Schema):
    """Confirmation after deleting a mailbox connection."""
    message = fields.String()
    connectionId = fields.Integer()


class IrisMailboxSyncResponseSchema(Schema):
    """Confirmation after queuing a manual sync."""
    message = fields.String()
    connectionId = fields.Integer()


class IrisMailboxCallbackQuerySchema(Schema):
    """Query params on the OAuth redirect back from Google/Microsoft.

    ``error`` is present instead of ``code`` when the user denies consent —
    both are optional here so the endpoint can distinguish and redirect
    accordingly rather than failing schema validation on a normal decline.
    """
    state = fields.String(required=True)
    code = fields.String(load_default=None)
    error = fields.String(load_default=None)


class IrisRetentionReportResponseSchema(Schema):
    """Política de retención vigente y estado real de los análisis del
    usuario frente a ella."""
    rawMessageRetentionDays = fields.Integer()
    analysisRetentionDays = fields.Integer(allow_none=True)
    totalAnalyses = fields.Integer()
    analysesWithRawRetained = fields.Integer()
    analysesWithRawPurged = fields.Integer()


class IrisNotificationPreferenceResponseSchema(Schema):
    """Preferencias de notificación del usuario actual."""
    digestEnabled = fields.Boolean()
    mutedUntil = UTCDateTime(allow_none=True)
    notifyReauthRequired = fields.Boolean()
    notifySyncStuck = fields.Boolean()
    digestLastSentAt = UTCDateTime(allow_none=True)


class IrisNotificationPreferenceUpdateRequestSchema(Schema):
    """Request body for ``PUT /iris/notification-preferences``.

    Los cuatro campos son opcionales e independientes -- omitir uno deja su
    valor actual intacto (actualización parcial, mismo patrón que
    ``IrisMailboxUpdateConnectionRequestSchema``); el endpoint distingue
    "no venía en el cuerpo" mirando si la clave está en los datos cargados.

    ``mutedForMinutes`` en vez de una fecha absoluta: el cliente sabe "cuánto
    tiempo" (silenciar 1 hora / 1 día / 1 semana), no una marca de tiempo en
    UTC, y resolverla en el servidor evita todo el terreno resbaladizo de
    aceptar una fecha con zona horaria ambigua desde fuera. ``0`` quita un
    silenciado activo (poner ``mutedUntil`` a ``None``); cualquier valor
    positivo lo fija a ``ahora + esos minutos``.
    """
    digestEnabled = fields.Boolean()
    mutedForMinutes = fields.Integer(validate=validate.Range(min=0))
    notifyReauthRequired = fields.Boolean()
    notifySyncStuck = fields.Boolean()


class IrisReplayPolicySpecSchema(Schema):
    """Descripción de una política de puntuación para el simulador de reglas.

    Vacía, es la vigente. Con ``snapshot`` se reconstruye una política
    guardada (el ``scoringSnapshot`` de un análisis). Si no, se parte de la
    vigente y se cambian el perfil, los umbrales efectivos y los pesos
    indicados; ``weightOverrides`` se **suma** a los pesos vigentes.
    """
    snapshot = fields.Dict(load_default=None, allow_none=True)
    profile = fields.String(load_default=None, allow_none=True,
                            validate=validate.OneOf(sorted(PROFILE_THRESHOLD_OFFSETS)))
    legitimateThreshold = fields.Float(load_default=None, allow_none=True,
                                       validate=validate.Range(min=0, max=100))
    suspiciousThreshold = fields.Float(load_default=None, allow_none=True,
                                       validate=validate.Range(min=0, max=100))
    weightOverrides = fields.Dict(keys=fields.String(), values=fields.Float(),
                                  load_default=None, allow_none=True)


class IrisReplayMessageSchema(Schema):
    """Un mensaje suelto para el simulador: se compara, pero no se guarda."""
    raw = fields.String(required=True, validate=validate.Length(min=1))
    label = fields.String(load_default=None, allow_none=True, validate=validate.OneOf(FEEDBACK_LABELS))


class IrisReplayRequestSchema(Schema):
    """Cuerpo de ``POST /iris/admin/replay``.

    ``candidate`` es la política a probar; ``baseline``, la referencia (por
    defecto la vigente). Se evalúa el corpus versionado si ``includeCorpus``
    (por defecto sí) y, además, hasta 20 mensajes sueltos.
    """
    candidate = fields.Nested(IrisReplayPolicySpecSchema, required=True)
    baseline = fields.Nested(IrisReplayPolicySpecSchema, load_default=None, allow_none=True)
    messages = fields.List(fields.Nested(IrisReplayMessageSchema), load_default=list,
                           validate=validate.Length(max=20))
    includeCorpus = fields.Boolean(load_default=True)


class IrisReplayResponseSchema(Schema):
    """Informe del simulador de reglas.

    ``policies`` trae, para ``baseline`` y ``candidate``, su
    ``scoringVersion``, su ``snapshot``, sus ``metrics`` frente a las
    etiquetas y los ids de sus falsos positivos y negativos conocidos.
    ``samples`` trae, por muestra, el resultado de cada política, si cambió
    el veredicto y qué gates añade o quita la candidata.
    """
    baseline = fields.String()
    corpusVersion = fields.String(allow_none=True)
    detectorVersion = fields.String()
    policies = fields.Dict()
    samples = fields.List(fields.Dict())
    changedCount = fields.Integer()


class IrisTrustedSenderRequestSchema(Schema):
    """Cuerpo de ``POST /iris/trusted-senders``.

    ``kind`` es ``sender`` (una dirección exacta) o ``domain`` (el dominio del
    ``From`` y sus subdominios). ``reason`` es obligatorio: queda en la
    auditoría. ``expiresInDays`` va de 1 a 365; por defecto, 90.
    """
    kind = fields.String(required=True, validate=validate.OneOf([kind.value for kind in TrustKind]))
    value = fields.String(required=True, validate=validate.Length(min=3, max=320))
    reason = fields.String(required=True, validate=validate.Length(min=1, max=MAX_TRUST_REASON_LENGTH))
    expiresInDays = fields.Integer(load_default=None, allow_none=True,
                                   validate=validate.Range(min=1, max=MAX_TRUST_EXPIRY_DAYS))


class IrisTrustedSendersQuerySchema(Schema):
    """Parámetros de ``GET /iris/trusted-senders``.

    Con ``includeInactive`` se listan también las caducadas y las revocadas
    (vista de auditoría); por defecto solo las activas.
    """
    includeInactive = fields.Boolean(load_default=False)


class IrisTrustedSenderItemSchema(Schema):
    """Una excepción de confianza: qué cubre, por qué, y si sigue en vigor.

    ``status`` es ``active``, ``expired`` o ``revoked``.
    """
    trustedSenderId = fields.Integer()
    kind = fields.String()
    value = fields.String()
    reason = fields.String()
    status = fields.String()
    createdAt = fields.String()
    expiresAt = fields.String()
    revokedAt = fields.String(allow_none=True)


class IrisTrustedSenderListResponseSchema(Schema):
    """Excepciones de confianza del usuario, de la más reciente a la más antigua."""
    trustedSenders = fields.List(fields.Nested(IrisTrustedSenderItemSchema))
    total = fields.Integer()


class IrisSavedViewRequestSchema(Schema):
    """Cuerpo de ``POST /iris/triage/views``: nombre y filtros a guardar."""
    name = fields.String(required=True, validate=validate.Length(min=1, max=60))
    filters = fields.Nested(IrisTriageFiltersSchema, load_default=dict)


class IrisSavedViewItemSchema(Schema):
    """Una vista guardada: ``filters`` usa las claves de ``GET /iris/results``."""
    viewId = fields.Integer()
    name = fields.String()
    filters = fields.Dict()
    createdAt = fields.String()


class IrisSavedViewListResponseSchema(Schema):
    """Vistas guardadas del usuario, por nombre."""
    views = fields.List(fields.Nested(IrisSavedViewItemSchema))


class IrisSavedViewDeleteResponseSchema(Schema):
    """Confirmación tras borrar una vista guardada."""
    message = fields.String()
    viewId = fields.Integer()


class IrisAnalysisTagsRequestSchema(Schema):
    """Cuerpo de ``PUT /iris/results/<id>/tags``: el conjunto completo de etiquetas.

    El tope de la lista es solo contra abusos; el límite real por análisis lo
    aplica el manager tras normalizar (quitar vacías y duplicadas).
    """
    tags = fields.List(fields.String(validate=validate.Length(max=200)), required=True,
                       validate=validate.Length(max=50))


class IrisAnalysisTagsResponseSchema(Schema):
    """Etiquetas que quedan en un análisis, ya normalizadas."""
    analysisId = fields.Integer()
    tags = fields.List(fields.String())


class IrisTagCountSchema(Schema):
    """Una etiqueta del usuario y en cuántos análisis aparece."""
    name = fields.String()
    count = fields.Integer()


class IrisTagListResponseSchema(Schema):
    """Etiquetas del usuario, de la más usada a la menos."""
    tags = fields.List(fields.Nested(IrisTagCountSchema))


_CASE_STATUSES = [status.value for status in CaseStatus]
_CASE_PRIORITIES = [priority.value for priority in CasePriority]


class IrisCaseCreateRequestSchema(Schema):
    """Cuerpo de ``POST /iris/cases``: título, prioridad, análisis y etiquetas iniciales."""
    title = fields.String(required=True, validate=validate.Length(min=1, max=200))
    priority = fields.String(load_default=CasePriority.MEDIUM.value, validate=validate.OneOf(_CASE_PRIORITIES))
    analysisIds = fields.List(fields.Integer(), load_default=list, validate=validate.Length(max=50))
    tags = fields.List(fields.String(validate=validate.Length(max=200)), load_default=list,
                       validate=validate.Length(max=50))


class IrisCaseUpdateRequestSchema(Schema):
    """Cuerpo de ``PATCH /iris/cases/<id>``: solo cambia lo que viene.

    ``assigneeId`` a ``null`` quita la asignación; solo puede ser el dueño del caso.
    """
    title = fields.String(validate=validate.Length(min=1, max=200))
    priority = fields.String(validate=validate.OneOf(_CASE_PRIORITIES))
    tags = fields.List(fields.String(validate=validate.Length(max=200)), validate=validate.Length(max=50))
    assigneeId = fields.Integer(allow_none=True)


class IrisCaseStatusRequestSchema(Schema):
    """Cuerpo de ``POST /iris/cases/<id>/status``; ``reason`` es obligatoria al cerrar."""
    status = fields.String(required=True, validate=validate.OneOf(_CASE_STATUSES))
    reason = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=4000))


class IrisCaseNoteRequestSchema(Schema):
    """Cuerpo de ``POST /iris/cases/<id>/notes``."""
    note = fields.String(required=True, validate=validate.Length(min=1, max=4000))


class IrisCaseLinkRequestSchema(Schema):
    """Cuerpo de ``POST /iris/cases/<id>/analyses``."""
    analysisId = fields.Integer(required=True)


class IrisCasesQuerySchema(Schema):
    """Filtros de ``GET /iris/cases``; ninguno filtra por defecto."""
    status = fields.String(load_default=None, validate=validate.OneOf(_CASE_STATUSES))
    priority = fields.String(load_default=None, validate=validate.OneOf(_CASE_PRIORITIES))
    assignedToMe = fields.Boolean(load_default=False)


class IrisCaseAnalysisItemSchema(Schema):
    """Un análisis de un caso, tal como es: el caso no lo modifica."""
    analysisId = fields.Integer()
    title = fields.String(allow_none=True)
    status = fields.String()
    verdict = fields.String(allow_none=True)
    totalScore = fields.Float(allow_none=True)
    confidence = fields.String(allow_none=True)
    addedAt = fields.String()


class IrisCaseEventSchema(Schema):
    """Una entrada de la timeline: un cambio (``detail``) o una nota (``note``)."""
    eventId = fields.Integer()
    kind = fields.String()
    detail = fields.Dict(allow_none=True)
    note = fields.String(allow_none=True)
    actor = fields.String(allow_none=True)
    createdAt = fields.String()


class IrisCaseSummarySchema(Schema):
    """Lo que enseña el listado de casos."""
    caseId = fields.Integer()
    title = fields.String()
    status = fields.String()
    priority = fields.String()
    assignee = fields.String(allow_none=True)
    tags = fields.List(fields.String())
    analysisCount = fields.Integer()
    createdAt = fields.String()
    updatedAt = fields.String()
    closedAt = fields.String(allow_none=True)


class IrisCaseDetailSchema(IrisCaseSummarySchema):
    """Un caso entero: resumen, razón de cierre, análisis y timeline.

    ``ownerId`` es el dueño, el único al que se puede asignar el caso.
    """
    ownerId = fields.Integer()
    assigneeId = fields.Integer(allow_none=True)
    resolutionReason = fields.String(allow_none=True)
    analyses = fields.List(fields.Nested(IrisCaseAnalysisItemSchema))
    timeline = fields.List(fields.Nested(IrisCaseEventSchema))


class IrisCaseListResponseSchema(Schema):
    """Casos del usuario y cuántos tiene en cada estado (sin aplicar los filtros)."""
    cases = fields.List(fields.Nested(IrisCaseSummarySchema))
    total = fields.Integer()
    countsByStatus = fields.Dict(keys=fields.String(), values=fields.Integer())


class IrisBatchItemSchema(Schema):
    """Un mensaje del lote: qué pasó con él y, si tiene análisis, cómo va."""
    position = fields.Integer()
    filename = fields.String()
    status = fields.String()
    analysisId = fields.Integer(allow_none=True)
    error = fields.String(allow_none=True)
    analysisStatus = fields.String(allow_none=True)
    verdict = fields.String(allow_none=True)
    totalScore = fields.Float(allow_none=True)


class IrisBatchCountsSchema(Schema):
    """Cuántos mensajes del lote hay en cada estado."""
    created = fields.Integer()
    duplicate = fields.Integer()
    rejected = fields.Integer()
    failed = fields.Integer()


class IrisBatchResponseSchema(Schema):
    """Un lote: resumen por estado y un elemento por mensaje."""
    batchId = fields.Integer()
    createdAt = fields.String()
    total = fields.Integer()
    counts = fields.Nested(IrisBatchCountsSchema)
    items = fields.List(fields.Nested(IrisBatchItemSchema))


class IrisBatchSummarySchema(Schema):
    """Un lote en el listado: sin los elementos."""
    batchId = fields.Integer()
    createdAt = fields.String()
    total = fields.Integer()
    counts = fields.Nested(IrisBatchCountsSchema)


class IrisBatchListResponseSchema(Schema):
    """Lotes recientes del usuario, del más nuevo al más antiguo."""
    batches = fields.List(fields.Nested(IrisBatchSummarySchema))


class IrisCampaignsQuerySchema(Schema):
    """Paginación de ``GET /iris/campaigns``."""
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))


class IrisCampaignSummarySchema(Schema):
    """Una campaña en el listado.

    ``analysisCount`` cuenta análisis y ``messageCount`` correos distintos: un
    mismo correo analizado otra vez suma un análisis pero no un mensaje.
    ``verdicts`` es ``{veredicto: análisis}``.
    """
    campaignId = fields.Integer()
    label = fields.String(allow_none=True)
    analysisCount = fields.Integer()
    messageCount = fields.Integer()
    firstSeenAt = fields.String(allow_none=True)
    lastSeenAt = fields.String(allow_none=True)
    verdicts = fields.Dict(keys=fields.String(), values=fields.Integer())


class IrisCampaignListResponseSchema(Schema):
    """Campañas del usuario, de la de actividad más reciente a la que menos."""
    campaigns = fields.List(fields.Nested(IrisCampaignSummarySchema))
    total = fields.Integer()
    page = fields.Integer()
    perPage = fields.Integer()


class IrisCampaignAnalysisSchema(Schema):
    """Un mensaje de la campaña y por qué entró en ella."""
    analysisId = fields.Integer()
    title = fields.String(allow_none=True)
    verdict = fields.String(allow_none=True)
    totalScore = fields.Float(allow_none=True)
    receivedAt = fields.String(allow_none=True)
    similarity = fields.Float()
    matchedSignals = fields.List(fields.String())


class IrisCampaignIndicatorSchema(Schema):
    """Un indicador que comparten varios mensajes de la campaña."""
    kind = fields.String()
    value = fields.String()
    analysisCount = fields.Integer()


class IrisCampaignDetailSchema(IrisCampaignSummarySchema):
    """Una campaña con sus mensajes, los indicadores comunes y las marcas suplantadas."""
    analyses = fields.List(fields.Nested(IrisCampaignAnalysisSchema))
    sharedIndicators = fields.List(fields.Nested(IrisCampaignIndicatorSchema))
    brands = fields.List(fields.String())


class IrisGraphQuerySchema(Schema):
    """Filtros de ``GET /iris/graph``."""
    address = fields.String(load_default=None, validate=validate.Length(max=320))
    limit = fields.Integer(load_default=200, validate=validate.Range(min=1, max=500))


class IrisGraphSenderSchema(Schema):
    """Un remitente del grafo con sus recuentos."""
    address = fields.String()
    displayName = fields.String(allow_none=True)
    messageCount = fields.Integer()
    legitimateCount = fields.Integer()
    isHabitual = fields.Boolean()
    firstSeenAt = fields.String(allow_none=True)
    lastSeenAt = fields.String(allow_none=True)


class IrisGraphEdgeSchema(Schema):
    """Una arista: el remitente escribió a (o pidió respuesta en) otra dirección."""
    sender = fields.String()
    recipient = fields.String()
    kind = fields.String()
    messageCount = fields.Integer()
    legitimateCount = fields.Integer()
    firstSeenAt = fields.String(allow_none=True)
    lastSeenAt = fields.String(allow_none=True)


class IrisGraphResponseSchema(Schema):
    """El grafo de comunicación del usuario y cómo se interpreta."""
    senders = fields.List(fields.Nested(IrisGraphSenderSchema))
    edges = fields.List(fields.Nested(IrisGraphEdgeSchema))
    habitualMinMessages = fields.Integer()
    retentionDays = fields.Integer()
    enabled = fields.Boolean()


class IrisGraphDeleteResponseSchema(Schema):
    """Cuántas aristas se olvidaron."""
    deletedEdges = fields.Integer()


class IntelExportQuerySchema(Schema):
    """Opciones de ``GET /iris/results/<id>/export/intel`` (JSON versionado)."""
    defang = fields.Boolean(load_default=True)


class IntelExportRequestSchema(Schema):
    """Petición explícita de exportación de indicadores.

    ``format`` es ``json`` (el esquema versionado de Iris), ``stix`` (STIX 2.1)
    o ``misp`` (evento MISP). ``defang`` solo cuenta en ``json``: STIX y MISP
    llevan siempre los valores reales, porque un patrón desactivado no casa
    con nada.
    """
    format = fields.String(required=True, validate=validate.OneOf(["json", "stix", "misp"]))
    defang = fields.Boolean(load_default=True)


class IrisDomainContextSchema(Schema):
    """Contexto de infraestructura de un dominio (RDAP).

    ``status`` es ``ok``, ``unavailable`` (el registro no respondió: modo
    neutro), ``rate_limited`` o ``disabled``. La edad es contexto: ninguna
    decisión de Iris depende solo de ella.
    """
    domain = fields.String()
    registrableDomain = fields.String()
    status = fields.String()
    cached = fields.Boolean()
    registeredAt = fields.String(allow_none=True)
    ageDays = fields.Integer(allow_none=True)
    isRecentlyRegistered = fields.Boolean()
    registryExpiresAt = fields.String(allow_none=True)
    registrar = fields.String(allow_none=True)
    registryStatus = fields.List(fields.String())
    nameservers = fields.List(fields.String())
    address = fields.String(allow_none=True)
    networkName = fields.String(allow_none=True)
    country = fields.String(allow_none=True)
    asn = fields.String(allow_none=True)
    error = fields.String(allow_none=True)
    fetchedAt = fields.String(allow_none=True)


class UrlExpansionRequestSchema(Schema):
    """URL de un análisis que se quiere seguir hasta su destino."""
    url = fields.String(required=True, validate=validate.Length(min=1, max=4096))


class UrlExpansionHopSchema(Schema):
    """Un salto de la cadena de redirects.

    ``error`` dice por qué se cortó ahí: ``private_address`` (apuntaba a la
    red interna), ``scheme``, ``port``, ``unresolvable``, ``timeout``,
    ``tls``, ``connection``, ``protocol`` o ``too_many_redirects``.
    """
    url = fields.String()
    status = fields.Integer(allow_none=True)
    peerAddress = fields.String(allow_none=True)
    certificate = fields.Dict(allow_none=True)
    error = fields.String(allow_none=True)


class UrlExpansionSchema(Schema):
    """Expansión de una URL.

    ``status`` es ``not_requested``, ``pending``, ``running``, ``done``,
    ``unavailable``, ``rate_limited`` o ``disabled``.
    """
    url = fields.String()
    status = fields.String()
    hops = fields.List(fields.Nested(UrlExpansionHopSchema))
    finalUrl = fields.String(allow_none=True)
    finalDomain = fields.String(allow_none=True)
    finalStatus = fields.Integer(allow_none=True)
    pageTitle = fields.String(allow_none=True)
    contentType = fields.String(allow_none=True)
    isDomainChanged = fields.Boolean(allow_none=True)
    requestedAt = fields.String(allow_none=True)
    fetchedAt = fields.String(allow_none=True)


class UrlExpansionListSchema(Schema):
    """Las URLs de un análisis con su expansión."""
    analysisId = fields.Integer()
    expansions = fields.List(fields.Nested(UrlExpansionSchema))


class ReputationRequestSchema(Schema):
    """Indicador por el que se pregunta la reputación."""
    kind = fields.String(required=True, validate=validate.OneOf(["domain", "url", "ip", "hash"]))
    value = fields.String(required=True, validate=validate.Length(min=1, max=4096))


class ReputationProviderSchema(Schema):
    """Lo que dijo un proveedor.

    ``verdict`` es ``known_malicious``, ``suspicious``, ``unknown``,
    ``unavailable`` o ``rate_limited`` (no se preguntó por falta de cupo).
    """
    provider = fields.String()
    verdict = fields.String()
    detail = fields.Dict()
    error = fields.String(allow_none=True)
    checkedAt = fields.String(allow_none=True)
    cached = fields.Boolean()


class ReputationResponseSchema(Schema):
    """Reputación de un indicador en los proveedores configurados.

    ``status`` es ``ok``, ``disabled`` (consultas externas apagadas) o
    ``not_configured`` (ningún proveedor con clave). ``verdict`` es el más
    grave de los proveedores que respondieron.
    """
    kind = fields.String()
    value = fields.String()
    status = fields.String()
    verdict = fields.String()
    providers = fields.List(fields.Nested(ReputationProviderSchema))


class TenantSharedIndicatorSchema(Schema):
    """Un indicador que han visto varios miembros en correos sospechosos o de phishing.

    ``imitatesProtected`` es el dominio protegido de la organización que imita,
    o ``null``.
    """
    kind = fields.String()
    value = fields.String()
    memberCount = fields.Integer()
    analysisCount = fields.Integer()
    firstSeenAt = fields.String(allow_none=True)
    lastSeenAt = fields.String(allow_none=True)
    imitatesProtected = fields.String(allow_none=True)


class TenantFrequentDomainSchema(Schema):
    """Un dominio del que varios miembros reciben correo legítimo."""
    domain = fields.String()
    memberCount = fields.Integer()
    legitimateMessages = fields.Integer()


class TenantOrganizationSchema(Schema):
    """La organización del usuario."""
    id = fields.Integer()
    name = fields.String()


class TenantIntelResponseSchema(Schema):
    """Inteligencia compartida de la organización del usuario.

    Las listas van vacías si la organización no comparte o el usuario no ha
    dado su consentimiento.
    """
    organization = fields.Nested(TenantOrganizationSchema)
    isOwner = fields.Boolean()
    hasConsented = fields.Boolean()
    contributingMembers = fields.Integer()
    minMembers = fields.Integer()
    windowDays = fields.Integer()
    sharingEnabled = fields.Boolean()
    protectedDomains = fields.List(fields.String())
    protectedBrands = fields.List(fields.String())
    updatedAt = fields.String(allow_none=True)
    sharedIndicators = fields.List(fields.Nested(TenantSharedIndicatorSchema))
    frequentDomains = fields.List(fields.Nested(TenantFrequentDomainSchema))


class TenantPolicyRequestSchema(Schema):
    """Política de inteligencia que fija el dueño de la organización."""
    sharingEnabled = fields.Boolean(required=True)
    protectedDomains = fields.List(fields.String(validate=validate.Length(max=253)), load_default=list,
                                   validate=validate.Length(max=100))
    protectedBrands = fields.List(fields.String(validate=validate.Length(max=200)), load_default=list,
                                  validate=validate.Length(max=100))


class TenantConsentRequestSchema(Schema):
    """Consentimiento de un miembro para aportar a lo compartido."""
    consent = fields.Boolean(required=True)


class IrisWebhookCreateRequestSchema(Schema):
    """Cuerpo de ``POST /iris/webhooks``: nombre, destino ``https`` y eventos."""
    name = fields.String(required=True, validate=validate.Length(min=1, max=80))
    url = fields.String(required=True, validate=validate.Length(min=1, max=2048))
    eventTypes = fields.List(fields.String(validate=validate.OneOf(SUBSCRIBABLE_WEBHOOK_EVENTS)),
                             required=True, validate=validate.Length(min=1))


class IrisWebhookUpdateRequestSchema(Schema):
    """Cuerpo de ``PATCH /iris/webhooks/<id>``: solo cambia lo que viene."""
    name = fields.String(validate=validate.Length(min=1, max=80))
    url = fields.String(validate=validate.Length(min=1, max=2048))
    eventTypes = fields.List(fields.String(validate=validate.OneOf(SUBSCRIBABLE_WEBHOOK_EVENTS)),
                             validate=validate.Length(min=1))
    isActive = fields.Boolean()


class IrisWebhookSubscriptionSchema(Schema):
    """Un webhook. ``secret`` solo aparece al crearlo o al rotar el secreto."""
    subscriptionId = fields.Integer()
    name = fields.String()
    url = fields.String()
    eventTypes = fields.List(fields.String())
    isActive = fields.Boolean()
    disabledReason = fields.String(allow_none=True)
    disabledAt = fields.String(allow_none=True)
    consecutiveFailures = fields.Integer()
    lastSuccessAt = fields.String(allow_none=True)
    lastFailureAt = fields.String(allow_none=True)
    lastError = fields.String(allow_none=True)
    createdAt = fields.String()
    updatedAt = fields.String()
    secret = fields.String()


class IrisWebhookListResponseSchema(Schema):
    """Webhooks del usuario y eventos a los que se puede suscribir."""
    subscriptions = fields.List(fields.Nested(IrisWebhookSubscriptionSchema))
    availableEventTypes = fields.List(fields.String())


class IrisWebhookDeleteResponseSchema(Schema):
    """Confirmación tras borrar un webhook."""
    message = fields.String()
    subscriptionId = fields.Integer()


class IrisWebhookDeliveriesQuerySchema(Schema):
    """Paginación de ``GET /iris/webhooks/<id>/deliveries``."""
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    perPage = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))


class IrisWebhookDeliverySchema(Schema):
    """Una entrega de un evento: estado, intentos y lo que se envía."""
    deliveryId = fields.Integer()
    eventId = fields.String()
    eventType = fields.String()
    status = fields.String()
    attempts = fields.Integer()
    nextAttemptAt = fields.String(allow_none=True)
    lastStatusCode = fields.Integer(allow_none=True)
    lastError = fields.String(allow_none=True)
    lastResponseExcerpt = fields.String(allow_none=True)
    createdAt = fields.String()
    deliveredAt = fields.String(allow_none=True)
    payload = fields.Dict()


class IrisIntegrationTokenCreateRequestSchema(Schema):
    """Cuerpo de ``POST /iris/integration-tokens``; ``lifetimeDays`` por defecto lo fija la config."""
    name = fields.String(required=True, validate=validate.Length(min=1, max=80))
    lifetimeDays = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=1))


class IrisIntegrationTokenSchema(Schema):
    """Un token de integración. ``token`` (completo, en claro) solo aparece al crearlo."""
    tokenId = fields.Integer()
    name = fields.String()
    keyId = fields.String()
    status = fields.String()
    createdAt = fields.String()
    expiresAt = fields.String(allow_none=True)
    lastUsedAt = fields.String(allow_none=True)
    revokedAt = fields.String(allow_none=True)
    token = fields.String()


class IrisIntegrationTokenListResponseSchema(Schema):
    """Tokens de integración del usuario, del más nuevo al más antiguo."""
    tokens = fields.List(fields.Nested(IrisIntegrationTokenSchema))


class IrisReportResponseSchema(Schema):
    """Resultado de reportar un correo: el análisis creado, o el que ya existía."""
    analysisId = fields.Integer()
    status = fields.String()
    isDuplicate = fields.Boolean()
    reportChannel = fields.String(allow_none=True)


class IrisReportStatusSchema(Schema):
    """Cómo va el análisis de un correo reportado (para un aviso breve en el cliente)."""
    analysisId = fields.Integer()
    status = fields.String()
    verdict = fields.String(allow_none=True)
    totalScore = fields.Float(allow_none=True)
    finishedAt = fields.String(allow_none=True)


class IrisWebhookDeliveryListResponseSchema(Schema):
    """Historial de entregas de un webhook, de la más nueva a la más antigua."""
    deliveries = fields.List(fields.Nested(IrisWebhookDeliverySchema))
    total = fields.Integer()
    page = fields.Integer()
    perPage = fields.Integer()


class IrisMailboxActionRequestSchema(Schema):
    """Cuerpo de ``POST /iris/mailbox/messages/<id>/actions``.

    ``confirm`` es obligatorio (``true``) en las acciones que sacan el correo de
    la bandeja; ``idempotencyKey`` hace que repetir la petición no la repita.
    """
    action = fields.String(required=True, validate=validate.OneOf([action.value for action in MailboxAction]))
    reason = fields.String(required=True, validate=validate.Length(min=1, max=1000))
    confirm = fields.Boolean(load_default=False)
    idempotencyKey = fields.String(load_default=None, allow_none=True, validate=validate.Length(min=8, max=80))


class IrisMailboxRollbackRequestSchema(Schema):
    """Cuerpo de ``POST /iris/mailbox/actions/<id>/rollback``."""
    reason = fields.String(required=True, validate=validate.Length(min=1, max=1000))


class IrisMailboxActionSchema(Schema):
    """Una acción sobre el buzón tal como queda en la auditoría."""
    actionId = fields.Integer()
    analysisId = fields.Integer(allow_none=True)
    connectionId = fields.Integer(allow_none=True)
    provider = fields.String()
    action = fields.String()
    status = fields.String()
    isDestructive = fields.Boolean()
    isRollback = fields.Boolean()
    rollbackOfId = fields.Integer(allow_none=True)
    reason = fields.String()
    actor = fields.String()
    permission = fields.String()
    wasRecommended = fields.Boolean()
    error = fields.String(allow_none=True)
    createdAt = fields.String()
    startedAt = fields.String(allow_none=True)
    completedAt = fields.String(allow_none=True)
    isRepeat = fields.Boolean()


class IrisMailboxActionOptionSchema(Schema):
    """Una acción posible y si exige confirmación."""
    action = fields.String()
    isDestructive = fields.Boolean()


class IrisMailboxMessageActionsSchema(Schema):
    """Recomendación, acciones posibles e historial de un correo de un buzón conectado."""
    analysisId = fields.Integer()
    verdict = fields.String(allow_none=True)
    recommendedAction = fields.String(allow_none=True)
    canAct = fields.Boolean()
    unavailableReason = fields.String(allow_none=True)
    actions = fields.List(fields.Nested(IrisMailboxActionOptionSchema))
    history = fields.List(fields.Nested(IrisMailboxActionSchema))


class IrisMailboxActionsQuerySchema(Schema):
    """Paginación de ``GET /iris/mailbox/actions``."""
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    perPage = fields.Integer(load_default=50, validate=validate.Range(min=1, max=200))


class IrisMailboxActionListSchema(Schema):
    """Registro de acciones sobre buzones del usuario, de la más reciente a la más antigua."""
    actions = fields.List(fields.Nested(IrisMailboxActionSchema))
    total = fields.Integer()
    page = fields.Integer()
    perPage = fields.Integer()


class IrisImapCredentialsSchema(Schema):
    """Servidor y credenciales de un buzón IMAP (solo TLS directo)."""
    host = fields.String(required=True, validate=validate.Length(min=3, max=255))
    port = fields.Integer(load_default=993, validate=validate.Range(min=1, max=65535))
    username = fields.String(required=True, validate=validate.Length(min=1, max=320))
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=1, max=512))


class IrisImapConnectRequestSchema(IrisImapCredentialsSchema):
    """Cuerpo de ``POST /iris/mailbox/imap``: conectar un buzón personal por IMAP."""
    folder = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    fullMessageMode = fields.Boolean(load_default=False)


class IrisMailboxCredentialsRequestSchema(Schema):
    """Cuerpo de ``PUT /iris/mailbox/connections/<id>/credentials``: contraseña IMAP nueva."""
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=1, max=512))


class IrisMailboxFoldersRequestSchema(Schema):
    """Cuerpo de ``PUT /iris/mailbox/connections/<id>/folders``: carpetas que se vigilan además de la principal."""
    folders = fields.List(fields.String(validate=validate.Length(min=1, max=255)), required=True,
                          validate=validate.Length(max=20))


class IrisSharedMailboxCreateRequestSchema(Schema):
    """Cuerpo de ``POST /iris/mailbox/shared``: conectar un buzón compartido de la organización.

    Con ``gmail`` o ``microsoft`` se usa la cuenta de servicio de la
    instalación y ``address`` es obligatoria; con ``imap``, las credenciales.
    """
    provider = fields.String(required=True, validate=validate.OneOf(["gmail", "microsoft", "imap"]))
    address = fields.Email(load_default=None, allow_none=True)
    folder = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    fullMessageMode = fields.Boolean(load_default=False)
    imap = fields.Nested(IrisImapCredentialsSchema, load_default=None, allow_none=True)

    @validates_schema
    def validate_access(self, data, **kwargs):
        """Exige la dirección con cuenta de servicio y las credenciales con IMAP."""
        if data["provider"] == "imap" and not data.get("imap"):
            raise ValidationError("Un buzón IMAP necesita servidor y credenciales.", field_name="imap")
        if data["provider"] != "imap" and not data.get("address"):
            raise ValidationError("Falta la dirección del buzón.", field_name="address")


class IrisSharedMailboxItemSchema(Schema):
    """Un buzón compartido, visto por una persona con acceso. Nunca credenciales."""
    id = fields.Integer()
    provider = fields.String()
    accountEmail = fields.String()
    authMode = fields.String()
    status = fields.String()
    folder = fields.String(allow_none=True)
    folderDisplayName = fields.String(allow_none=True)
    additionalFolders = fields.List(fields.Dict())
    fullMessageMode = fields.Boolean()
    lastSyncAt = fields.String(allow_none=True)
    lastError = fields.String(allow_none=True)
    createdAt = fields.String(allow_none=True)
    myAccess = fields.String()


class IrisSharedMailboxListResponseSchema(Schema):
    """Buzones compartidos a los que tiene acceso la persona."""
    mailboxes = fields.List(fields.Nested(IrisSharedMailboxItemSchema))


class IrisSharedMailboxMemberRequestSchema(Schema):
    """Cuerpo de ``PUT /iris/mailbox/shared/<id>/members/<userId>``."""
    access = fields.String(required=True, validate=validate.OneOf(["viewer", "manager"]))


class IrisSharedMailboxMemberSchema(Schema):
    """Una persona con acceso a un buzón compartido."""
    userId = fields.Integer()
    username = fields.String(allow_none=True)
    access = fields.String()
    grantedAt = fields.String(allow_none=True)


class IrisSharedMailboxMemberListResponseSchema(Schema):
    """Personas con acceso a un buzón compartido."""
    members = fields.List(fields.Nested(IrisSharedMailboxMemberSchema))


class IrisSharedMailboxAnalysesQuerySchema(Schema):
    """Paginación de ``GET /iris/mailbox/shared/<id>/analyses``."""
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    perPage = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))


class IrisSharedMailboxAnalysisItemSchema(Schema):
    """Resumen de un análisis de un buzón compartido."""
    analysisId = fields.Integer()
    title = fields.String(allow_none=True)
    status = fields.String()
    verdict = fields.String(allow_none=True)
    totalScore = fields.Float(allow_none=True)
    startedAt = fields.String(allow_none=True)
    finishedAt = fields.String(allow_none=True)


class IrisSharedMailboxAnalysesResponseSchema(Schema):
    """Página de análisis de un buzón compartido."""
    analyses = fields.List(fields.Nested(IrisSharedMailboxAnalysisItemSchema))
    total = fields.Integer()
    page = fields.Integer()
    perPage = fields.Integer()


class IrisFreeDomainQuerySchema(Schema):
    """Consulta de la herramienta gratuita de dominios engañosos, sin sesión.

    Un dominio, una dirección de correo o una URL. El tope de longitud acota el
    coste de cada petición; lo que no sea un nombre de dominio lo rechaza el
    manager con un 400.
    """
    domain = fields.String(required=True, validate=validate.Length(min=1, max=300))
