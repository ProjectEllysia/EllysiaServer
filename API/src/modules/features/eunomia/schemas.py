"""Schemas Marshmallow del módulo Eunomia. Claves JSON en camelCase."""

from marshmallow import Schema, fields, validate


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

class AdoptionSchema(Schema):
    """Un marco adoptado por el dueño efectivo, con su versión fijada."""

    frameworkKey = fields.String()
    name = fields.String()
    shortName = fields.String()
    catalogVersion = fields.String()
    currentVersion = fields.String()
    hasNewerVersion = fields.Boolean()
    status = fields.String()
    adoptedAt = fields.DateTime()
    adoptedByUserId = fields.Integer()
    archivedAt = fields.DateTime(allow_none=True)
    purgeAt = fields.DateTime(allow_none=True)


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


class AdoptionCreateSchema(Schema):
    """Cuerpo de ``POST /eunomia/adoptions``."""

    frameworkKey = fields.String(required=True, validate=validate.Length(min=1, max=32))
