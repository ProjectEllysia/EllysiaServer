"""
Modelos del módulo Eunomia.

El catálogo de marcos no está aquí: son ficheros versionados (``catalog/``). Aquí vive lo
que **sí** es de un usuario: qué marcos ha adoptado y, en fases posteriores, lo que ha
evaluado y evidenciado. Las filas guardan ``(marco, versión, código de control)`` sin clave
ajena hacia el catálogo.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from src.modules.shared import Base, utcnow_naive

#: Estados de una adopción.
ADOPTION_ACTIVE = "active"
ADOPTION_ARCHIVED = "archived"


class EunomiaFrameworkAdoption(Base):
    """Un marco que el dueño efectivo de los datos ha adoptado, fijado a una versión.

    Adoptar es fijar **una versión concreta** del catálogo: las evaluaciones y evidencias
    cuelgan de ella, y si el catálogo publica otra el usuario sigue en la suya hasta que
    decide pasar. Quitar un marco lo **archiva**; solo se purga pasado el plazo.

    Attributes:
        id: Clave primaria.
        owner_user_id: Dueño efectivo de los datos (``resolve_data_owner``). Único por marco.
        framework_key: Clave del marco en el catálogo (``"nis2"``).
        catalog_version: Versión del catálogo a la que está fijada la adopción.
        status: ``"active"`` o ``"archived"``.
        adopted_at: Cuándo se adoptó.
        adopted_by_user_id: Quién lo adoptó (siempre el dueño: los miembros no adoptan).
        archived_at: Cuándo se archivó; ``None`` si está activa.
        archived_by_user_id: Quién lo archivó; ``None`` si está activa.
    """

    __tablename__ = "EunomiaFrameworkAdoption"
    __table_args__ = (UniqueConstraint("owner_user_id", "framework_key", name="uq_eunomia_adoption_owner_framework"),)

    id                  = Column(Integer,    primary_key=True, autoincrement=True)
    owner_user_id       = Column(Integer,    ForeignKey("User.id"), nullable=False, index=True)
    framework_key       = Column(String(32), nullable=False)
    catalog_version     = Column(String(64), nullable=False)
    status              = Column(String(16), nullable=False, default=ADOPTION_ACTIVE)
    adopted_at          = Column(DateTime,   nullable=False, default=utcnow_naive)
    adopted_by_user_id  = Column(Integer,    ForeignKey("User.id"), nullable=False)
    archived_at         = Column(DateTime,   nullable=True)
    archived_by_user_id = Column(Integer,    ForeignKey("User.id"), nullable=True)

    def __repr__(self) -> str:
        return f"<EunomiaFrameworkAdoption owner={self.owner_user_id} {self.framework_key}@{self.catalog_version} {self.status}>"
