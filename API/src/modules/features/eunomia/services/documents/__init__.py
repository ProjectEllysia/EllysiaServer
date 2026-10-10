"""Documentos de cumplimiento: del modelo de una plantilla y sus valores a PDF y a Word."""

from .render import Block, RenderedDocument, RenderedSection, missing_required, render_document

__all__ = ["Block", "RenderedDocument", "RenderedSection", "missing_required", "render_document"]
