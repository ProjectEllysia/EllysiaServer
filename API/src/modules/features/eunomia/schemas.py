"""Schemas Marshmallow del módulo Eunomia. Claves JSON en camelCase."""

from marshmallow import Schema, fields, validate

from src.modules.shared.schemas import UTCDateTime


class CatalogVersionSummarySchema(Schema):
    """Una versión publicada o en borrador de un marco."""

    version = fields.String()
    status = fields.String()


class CatalogFrameworkSchema(Schema):
    """Un marco del catálogo, con sus versiones y la vigente."""

    key = fields.String()
    name = fields.String()
    shortName = fields.String()
    current = fields.String()
    versions = fields.List(fields.Nested(CatalogVersionSummarySchema))


class CatalogFrameworkListSchema(Schema):
    """Respuesta de ``GET /eunomia/frameworks``."""

    frameworks = fields.List(fields.Nested(CatalogFrameworkSchema))


class CatalogSourceSchema(Schema):
    """De dónde sale una versión del catálogo."""

    name = fields.String()
    url = fields.String()
    license = fields.String()
    consultedAt = fields.String()


class CatalogNodeSchema(Schema):
    """Un nodo del árbol, con sus hijos anidados."""

    code = fields.String()
    identifier = fields.String()
    kind = fields.String()
    isAssessable = fields.Boolean()
    title = fields.String()
    officialText = fields.String()
    description = fields.String()
    actions = fields.List(fields.String())
    evidence = fields.List(fields.String())
    source = fields.String()
    register = fields.String(allow_none=True)
    metadata = fields.Dict()
    children = fields.List(fields.Nested(lambda: CatalogNodeSchema()))


class CatalogVersionSchema(Schema):
    """Respuesta de ``GET /eunomia/frameworks/<marco>/<versión>``."""

    key = fields.String()
    version = fields.String()
    status = fields.String()
    name = fields.String()
    shortName = fields.String()
    publishedAt = fields.String()
    licenseMode = fields.String()
    notes = fields.String()
    sources = fields.List(fields.Nested(CatalogSourceSchema))
    tree = fields.List(fields.Nested(CatalogNodeSchema))


# ── Adopción de marcos ────────────────────────────────────────────────────

class ProgressSchema(Schema):
    """Cuánto está cumplido un conjunto de controles."""

    counts = fields.Dict(keys=fields.String(), values=fields.Integer())
    total = fields.Integer()
    countable = fields.Integer()
    percent = fields.Float()


class AdoptionSchema(Schema):
    """Un marco adoptado por el dueño efectivo, con su versión fijada."""

    frameworkKey = fields.String()
    name = fields.String()
    shortName = fields.String()
    catalogVersion = fields.String()
    currentVersion = fields.String()
    hasNewerVersion = fields.Boolean()
    status = fields.String()
    adoptedAt = UTCDateTime()
    adoptedByUserId = fields.Integer()
    archivedAt = UTCDateTime(allow_none=True)
    purgeAt = UTCDateTime(allow_none=True)
    progress = fields.Nested(ProgressSchema, allow_none=True)


class OwnershipSchema(Schema):
    """De quién son los datos que se están viendo."""

    ownerUserId = fields.Integer()
    isOwnData = fields.Boolean()
    organizationName = fields.String(allow_none=True)
    ownerDisplayName = fields.String(allow_none=True)


class AdoptionListSchema(Schema):
    """Respuesta de ``GET /eunomia/adoptions``."""

    adoptions = fields.List(fields.Nested(AdoptionSchema))
    ownership = fields.Nested(OwnershipSchema)


class RemovalPreviewSchema(Schema):
    """Lo que se perdería al quitar un marco, antes de quitarlo."""

    assessments = fields.Integer()
    evidenceDeleted = fields.Integer()
    evidenceKept = fields.Integer()
    retentionDays = fields.Integer()
    purgeAt = UTCDateTime()


class AdoptionCreateSchema(Schema):
    """Cuerpo de ``POST /eunomia/adoptions``."""

    frameworkKey = fields.String(required=True, validate=validate.Length(min=1, max=32))


# ── Evaluación de controles ───────────────────────────────────────────────

class AssessmentSchema(Schema):
    """La evaluación de un control; ``updatedAt`` es el testigo de la concurrencia."""

    code = fields.String()
    controlIdentifier = fields.String()
    status = fields.String()
    justification = fields.String()
    notes = fields.String()
    responsibleUserId = fields.Integer(allow_none=True)
    responsibleName = fields.String(allow_none=True)
    dueDate = fields.Date(allow_none=True)
    updatedAt = UTCDateTime(allow_none=True)
    updatedByUserId = fields.Integer(allow_none=True)
    updatedByName = fields.String(allow_none=True)


class AssessmentWriteSchema(Schema):
    """Cuerpo de ``PUT /eunomia/adoptions/<marco>/controls/<identificador>``."""

    status = fields.String(required=True, validate=validate.OneOf(
        ["pending", "in_progress", "implemented", "not_applicable"]))
    justification = fields.String(load_default="", validate=validate.Length(max=4000))
    notes = fields.String(load_default="", validate=validate.Length(max=8000))
    responsibleUserId = fields.Integer(load_default=None, allow_none=True)
    dueDate = fields.Date(load_default=None, allow_none=True)
    # El ``updatedAt`` que vio el cliente (o ``null`` si el control no tenía fila): obligatorio
    # para que dos personas no se pisen sin saberlo.
    updatedAt = fields.DateTime(required=True, allow_none=True)


class AdoptedNodeSchema(Schema):
    """Un nodo del árbol personal: catálogo más la evaluación del dueño efectivo."""

    code = fields.String()
    identifier = fields.String()
    kind = fields.String()
    isAssessable = fields.Boolean()
    title = fields.String()
    officialText = fields.String()
    description = fields.String()
    actions = fields.List(fields.String())
    evidence = fields.List(fields.String())
    source = fields.String()
    metadata = fields.Dict()
    suggestions = fields.List(fields.Dict())
    linkedEvidence = fields.List(fields.Dict())
    evidenceState = fields.String()
    assessment = fields.Nested(AssessmentSchema, allow_none=True)
    progress = fields.Nested(ProgressSchema)
    children = fields.List(fields.Nested(lambda: AdoptedNodeSchema()))


class PersonSchema(Schema):
    """Una persona a la que se puede asignar un control."""

    userId = fields.Integer()
    name = fields.String()


class AdoptedTreeSchema(Schema):
    """Respuesta de ``GET /eunomia/adoptions/<marco>/tree``."""

    people = fields.List(fields.Nested(PersonSchema))
    key = fields.String()
    version = fields.String()
    status = fields.String()
    name = fields.String()
    shortName = fields.String()
    notes = fields.String()
    sources = fields.List(fields.Nested(CatalogSourceSchema))
    tree = fields.List(fields.Nested(AdoptedNodeSchema))


class AssessmentEventSchema(Schema):
    """Un cambio en la evaluación de un control."""

    actorUserId = fields.Integer(allow_none=True)
    actorName = fields.String()
    occurredAt = UTCDateTime()
    changes = fields.Dict()


class AssessmentHistorySchema(Schema):
    """Respuesta de ``GET /eunomia/adoptions/<marco>/controls/<identificador>/history``."""

    events = fields.List(fields.Nested(AssessmentEventSchema))


class SummaryBranchSchema(ProgressSchema):
    """El progreso de una rama de primer nivel."""

    code = fields.String()
    identifier = fields.String()
    title = fields.String()


class SummaryControlSchema(Schema):
    """Un control que pide atención: vence pronto o no tiene responsable."""

    code = fields.String()
    identifier = fields.String()
    title = fields.String()
    status = fields.String()
    dueDate = fields.Date(allow_none=True)
    isOverdue = fields.Boolean(load_default=False)
    responsibleUserId = fields.Integer(allow_none=True)
    responsibleName = fields.String(allow_none=True)


class SummarySchema(Schema):
    """Respuesta de ``GET /eunomia/adoptions/<marco>/summary``."""

    # ``global`` es palabra reservada de Python: el campo se declara con ``data_key``.
    overall = fields.Nested(ProgressSchema, data_key="global")
    branches = fields.List(fields.Nested(SummaryBranchSchema))
    upcoming = fields.List(fields.Nested(SummaryControlSchema))
    unassigned = fields.List(fields.Nested(SummaryControlSchema))
    unassignedCount = fields.Integer()
    suggestedCoverage = fields.Integer()


# ── Evidencias ────────────────────────────────────────────────────────────

class EvidenceLinkSchema(Schema):
    """Un control al que está enlazada una evidencia."""

    frameworkKey = fields.String(required=True)
    controlIdentifier = fields.String(required=True)


class EvidenceSchema(Schema):
    """La ficha de una evidencia, sin su contenido."""

    id = fields.Integer()
    title = fields.String()
    description = fields.String()
    filename = fields.String()
    contentType = fields.String()
    sizeBytes = fields.Integer()
    sha256 = fields.String()
    validUntil = fields.Date(allow_none=True)
    uploadedAt = UTCDateTime()
    uploadedByName = fields.String(allow_none=True)
    links = fields.List(fields.Nested(EvidenceLinkSchema))


class EvidenceUsageSchema(Schema):
    """Cuánto almacenamiento de evidencias lleva gastado el dueño efectivo."""

    usedBytes = fields.Integer()
    limitBytes = fields.Integer(allow_none=True)
    remainingBytes = fields.Integer(allow_none=True)


class EvidenceListSchema(Schema):
    """Respuesta de ``GET /eunomia/evidence``."""

    evidence = fields.List(fields.Nested(EvidenceSchema))
    usage = fields.Nested(EvidenceUsageSchema)


class EvidenceUpdateSchema(Schema):
    """Cuerpo de ``PATCH /eunomia/evidence/<id>``: todos los campos son opcionales."""

    title = fields.String(validate=validate.Length(min=1, max=255))
    description = fields.String(validate=validate.Length(max=8000))
    validUntil = fields.Date(allow_none=True)
