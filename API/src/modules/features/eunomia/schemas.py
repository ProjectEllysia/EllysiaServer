"""Schemas Marshmallow del módulo Eunomia. Claves JSON en camelCase."""

from marshmallow import Schema, fields


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
