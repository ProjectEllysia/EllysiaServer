"""
Modelos del módulo Eunomia.

El catálogo de marcos no está aquí: son ficheros versionados (``catalog/``). Aquí vive lo
que **sí** es de un usuario: qué marcos ha adoptado y, en fases posteriores, lo que ha
evaluado y evidenciado. Las filas guardan ``(marco, versión, código de control)`` sin clave
ajena hacia el catálogo.
"""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from src.modules.shared import Base, utcnow_naive

#: Estados de una adopción.
ADOPTION_ACTIVE = "active"
ADOPTION_ARCHIVED = "archived"

#: Estados de la evaluación de un control. Sin fila, un control está «pendiente».
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_IMPLEMENTED = "implemented"
STATUS_NOT_APPLICABLE = "not_applicable"
ASSESSMENT_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_IMPLEMENTED, STATUS_NOT_APPLICABLE)


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


class EunomiaControlAssessment(Base):
    """Cómo de cumplido está un control, para el dueño efectivo de los datos.

    Una fila por ``(dueño, marco, control)``; el dueño y los miembros de su organización
    escriben sobre las mismas filas. No hay clave ajena hacia el catálogo: el control se
    identifica por ``(framework_key, catalog_version, control_identifier)`` y la versión es la
    de la adopción. Sin fila, el control está «pendiente».

    Attributes:
        id: Clave primaria.
        owner_user_id: Dueño efectivo de los datos.
        framework_key: Clave del marco.
        catalog_version: Versión del catálogo contra la que se evaluó (la de la adopción).
        control_identifier: Identificador del control dentro de esa versión (``"21.2.e"``).
        status: Uno de ``ASSESSMENT_STATUSES``.
        justification: Por qué «no aplica»; obligatoria en ese estado.
        notes: Notas libres de quien evalúa.
        responsible_user_id: El dueño o un miembro de su organización; ``None`` si nadie.
        due_date: Fecha límite, o ``None``.
        updated_at: Última escritura; es también el testigo de la concurrencia optimista.
        updated_by_user_id: Quién escribió por última vez; ``None`` si esa cuenta se borró.
    """

    __tablename__ = "EunomiaControlAssessment"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "framework_key", "control_identifier",
                         name="uq_eunomia_assessment_owner_framework_control"),
    )

    id                  = Column(Integer,     primary_key=True, autoincrement=True)
    owner_user_id       = Column(Integer,     ForeignKey("User.id"), nullable=False, index=True)
    framework_key       = Column(String(32),  nullable=False)
    catalog_version     = Column(String(64),  nullable=False)
    control_identifier  = Column(String(128), nullable=False)
    status              = Column(String(16),  nullable=False, default=STATUS_PENDING)
    justification       = Column(Text,        nullable=True)
    notes               = Column(Text,        nullable=True)
    responsible_user_id = Column(Integer,     ForeignKey("User.id"), nullable=True)
    due_date            = Column(Date,        nullable=True)
    updated_at          = Column(DateTime,    nullable=False, default=utcnow_naive)
    updated_by_user_id  = Column(Integer,     ForeignKey("User.id"), nullable=True)
