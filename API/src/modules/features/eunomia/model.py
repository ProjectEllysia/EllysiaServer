"""
Modelos del módulo Eunomia.

El catálogo de marcos no está aquí: son ficheros versionados (``catalog/``). Aquí vive lo
que **sí** es de un usuario: qué marcos ha adoptado y, en fases posteriores, lo que ha
evaluado y evidenciado. Las filas guardan ``(marco, versión, código de control)`` sin clave
ajena hacia el catálogo.
"""

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from sqlalchemy.orm import deferred

from src.modules.shared import Base, Document, EncryptedBinary, utcnow_naive

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


class EunomiaAssessmentEvent(Base):
    """Un cambio en la evaluación de un control. Solo se añade: nunca se edita.

    Dentro de una organización varias personas escriben en el espacio del dueño; cuando un
    control pasa de «implementado» a «pendiente» alguien preguntará quién y por qué. El
    historial es además una evidencia en sí mismo: demuestra que el cumplimiento se revisa.

    Attributes:
        id: Clave primaria.
        owner_user_id: Dueño efectivo de los datos.
        framework_key: Clave del marco.
        control_identifier: Identificador del control.
        actor_user_id: Quién lo cambió; ``None`` si esa cuenta se ha borrado.
        actor_name: Nombre visible de quien lo cambió, guardado al hacer el cambio para que
            sobreviva a la baja de la cuenta.
        occurred_at: Cuándo.
        changes: ``{campo: {"from": anterior, "to": nuevo}}`` de cada campo que cambió.
    """

    __tablename__ = "EunomiaAssessmentEvent"
    __table_args__ = (
        Index("ix_eunomia_event_owner_framework_control", "owner_user_id", "framework_key", "control_identifier"),
    )

    id                 = Column(Integer,     primary_key=True, autoincrement=True)
    owner_user_id      = Column(Integer,     ForeignKey("User.id"), nullable=False)
    framework_key      = Column(String(32),  nullable=False)
    control_identifier = Column(String(128), nullable=False)
    actor_user_id      = Column(Integer,     ForeignKey("User.id"), nullable=True)
    actor_name         = Column(String(255), nullable=False, default="")
    occurred_at        = Column(DateTime,    nullable=False, default=utcnow_naive)
    changes            = Column(JSON,        nullable=False)


class EunomiaEvidence(Base):
    """Un fichero que demuestra el cumplimiento de uno o varios controles.

    Existe por sí misma en el espacio del dueño efectivo y se enlaza con los controles que
    demuestra, de cualquier marco adoptado (``EunomiaEvidenceLink``): una política de control
    de acceso sirve a NIS2, al ENS y a ISO 27001 a la vez. El contenido va cifrado en reposo y
    en su propia tabla (``EunomiaEvidenceContent``), para poder purgarlo sin perder la ficha.

    Attributes:
        id: Clave primaria.
        owner_user_id: Dueño efectivo de los datos.
        title: Título que le pone quien la sube.
        description: Notas libres.
        filename: Nombre del fichero, saneado.
        content_type: Tipo detectado en el servidor, no el que declaró el navegador.
        size_bytes: Tamaño original del fichero (no el cifrado).
        sha256: Hash del contenido, para detectar si dos evidencias son el mismo fichero.
        valid_until: Hasta cuándo vale la evidencia, o ``None`` si no caduca.
        expiry_notified_for: El ``valid_until`` para el que ya se avisó de la caducidad, o
            ``None``: así el aviso se envía una vez por evidencia y fecha.
        uploaded_at: Cuándo se subió.
        uploaded_by_user_id: Quién la subió; ``None`` si esa cuenta se ha borrado.
    """

    __tablename__ = "EunomiaEvidence"

    id                  = Column(Integer,      primary_key=True, autoincrement=True)
    owner_user_id       = Column(Integer,      ForeignKey("User.id"), nullable=False, index=True)
    title               = Column(String(255),  nullable=False)
    description         = Column(Text,         nullable=True)
    filename            = Column(String(255),  nullable=False)
    content_type        = Column(String(128),  nullable=False)
    size_bytes          = Column(Integer,      nullable=False)
    sha256              = Column(String(64),   nullable=False)
    valid_until         = Column(Date,         nullable=True)
    expiry_notified_for = Column(Date,         nullable=True)
    uploaded_at         = Column(DateTime,     nullable=False, default=utcnow_naive)
    uploaded_by_user_id = Column(Integer,      ForeignKey("User.id"), nullable=True)


class EunomiaEvidenceContent(Base):
    """El contenido de una evidencia, cifrado en reposo y en fila aparte (1:1).

    Separarlo permite purgar los bytes sin perder la ficha y que ninguna consulta de la ficha
    los cargue: la columna es ``deferred``.

    Attributes:
        id: Clave primaria.
        evidence_id: La evidencia a la que pertenece; única.
        content: Los bytes del fichero; se cifran al escribir y se descifran al leer.
    """

    __tablename__ = "EunomiaEvidenceContent"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    evidence_id = Column(Integer, ForeignKey("EunomiaEvidence.id", ondelete="CASCADE"),
                         nullable=False, unique=True)
    content     = deferred(Column(EncryptedBinary(purpose="eunomia_evidence"), nullable=False))


class EunomiaEvidenceLink(Base):
    """Enlace entre una evidencia y un control que demuestra. Muchos a muchos.

    Attributes:
        id: Clave primaria.
        evidence_id: La evidencia.
        framework_key: Clave del marco del control.
        control_identifier: Identificador del control en la versión adoptada.
        linked_at: Cuándo se enlazó.
        linked_by_user_id: Quién lo enlazó; ``None`` si esa cuenta se ha borrado.
    """

    __tablename__ = "EunomiaEvidenceLink"
    __table_args__ = (
        UniqueConstraint("evidence_id", "framework_key", "control_identifier",
                         name="uq_eunomia_evidence_link"),
        Index("ix_eunomia_evidence_link_control", "framework_key", "control_identifier"),
    )

    id                 = Column(Integer,     primary_key=True, autoincrement=True)
    evidence_id        = Column(Integer,     ForeignKey("EunomiaEvidence.id", ondelete="CASCADE"), nullable=False)
    framework_key      = Column(String(32),  nullable=False)
    control_identifier = Column(String(128), nullable=False)
    linked_at          = Column(DateTime,    nullable=False, default=utcnow_naive)
    linked_by_user_id  = Column(Integer,     ForeignKey("User.id"), nullable=True)


class EunomiaTemplateDraft(Base):
    """Los valores que el dueño efectivo tiene escritos para una plantilla de documento.

    Una fila por ``(dueño, plantilla)``: el dueño y los miembros de su organización rellenan el
    mismo borrador. Solo guarda lo que alguien escribió; lo que Ellysia ya sabe (el perfil de
    empresa, las evaluaciones) se precarga al leer, así que un cambio allí llega solo.

    Attributes:
        id: Clave primaria.
        owner_user_id: Dueño efectivo de los datos.
        template_key: Identificador de la plantilla (``"incident-procedure"``).
        template_version: Versión de la plantilla con la que se rellenó.
        values: ``{campo: texto}`` de lo escrito por el usuario.
        updated_at: Última escritura.
        updated_by_user_id: Quién escribió por última vez; ``None`` si esa cuenta se borró.
    """

    __tablename__ = "EunomiaTemplateDraft"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "template_key", name="uq_eunomia_template_draft_owner_template"),
    )

    id                 = Column(Integer,     primary_key=True, autoincrement=True)
    owner_user_id      = Column(Integer,     ForeignKey("User.id"), nullable=False, index=True)
    template_key       = Column(String(64),  nullable=False)
    template_version   = Column(String(16),  nullable=False)
    values             = Column(JSON,        nullable=False, default=dict)
    updated_at         = Column(DateTime,    nullable=False, default=utcnow_naive)
    updated_by_user_id = Column(Integer,     ForeignKey("User.id"), nullable=True)


class EunomiaDocument(Document):
    """Un documento de cumplimiento generado en segundo plano, en PDF o en Word.

    Hereda de ``Document`` (herencia *joined-table*, como los de Hygeia, Iris y Themis): la tabla
    común guarda el dueño, el formato, el estado (``pending``/``running``/``done``/``error``),
    las fechas y la ruta del fichero. ``Document.user_id`` es el **dueño efectivo** de los datos,
    no quien lo pidió, de modo que los miembros de la organización ven y descargan los mismos
    documentos que el dueño.

    Attributes:
        id: Clave primaria; clave ajena a ``Document.id``.
        template_key: Identificador de la plantilla (``"incident-procedure"``).
        template_version: Versión de la plantilla con la que se generó.
        title: Título del documento en el momento de pedirlo.
        values: ``{campo: texto}`` ya resueltos (guardados y precargados) en el momento de pedirlo:
            el documento se genera con lo que el usuario vio, aunque el borrador cambie después.
        requested_by_name: Nombre de quien lo pidió, tal como se leía entonces.
        download_name: Nombre con el que se descarga; ``None`` mientras no está listo.
    """

    __tablename__ = "EunomiaDocument"

    id                = Column(Integer, ForeignKey("Document.id"), primary_key=True)
    template_key      = Column(String(64),  nullable=False)
    template_version  = Column(String(16),  nullable=False)
    title             = Column(String(255), nullable=False)
    values            = Column(JSON,        nullable=False, default=dict)
    requested_by_name = Column(String(255), nullable=False, default="")
    download_name     = Column(String(200), nullable=True)

    __mapper_args__ = {"polymorphic_identity": "eunomia"}

    def to_dict(self) -> dict:
        """El documento para la API, sin la ruta en disco ni los valores.

        Returns:
            dict: ``id``, ``templateKey``, ``templateVersion``, ``title``, ``format``, ``status``,
                ``requestedByName``, ``downloadName``, ``createdAt`` y ``generatedAt``.
        """
        return {
            "id": self.id, "templateKey": self.template_key, "templateVersion": self.template_version,
            "title": self.title, "format": self.format, "status": self.status,
            "requestedByName": self.requested_by_name, "downloadName": self.download_name,
            "createdAt": self.created_at, "generatedAt": self.generated_at,
        }


class EunomiaRecord(Base):
    """Una ficha de un registro (un tratamiento de datos, un incidente, una solicitud…).

    Una fila por ficha, en el espacio del dueño efectivo: el dueño y los miembros de su
    organización crean y editan las mismas fichas. La definición del tipo (``registers/``) dice
    qué campos tiene; aquí solo viven los valores. Archivar una ficha no la borra: deja de
    salir en el registro pero conserva su historial.

    Attributes:
        id: Clave primaria.
        owner_user_id: Dueño efectivo de los datos.
        register_key: Tipo de registro (``"rgpd-actividades-tratamiento"``).
        register_version: Versión de la definición con la que se escribió.
        values: ``{campo: texto}`` validado contra la definición.
        is_archived: Si la ficha está archivada.
        created_at: Alta.
        created_by_user_id: Quién la creó; ``None`` si esa cuenta se borró.
        updated_at: Última escritura; es también el testigo de la concurrencia optimista.
        updated_by_user_id: Quién escribió por última vez; ``None`` si esa cuenta se borró.
        notified_deadlines: Claves de los plazos de los que ya se avisó por correo, para no
            repetir el aviso.
    """

    __tablename__ = "EunomiaRecord"
    __table_args__ = (
        Index("ix_eunomia_record_owner_register", "owner_user_id", "register_key"),
    )

    id                 = Column(Integer,     primary_key=True, autoincrement=True)
    owner_user_id      = Column(Integer,     ForeignKey("User.id"), nullable=False)
    register_key       = Column(String(64),  nullable=False)
    register_version   = Column(String(16),  nullable=False)
    values             = Column(JSON,        nullable=False, default=dict)
    is_archived        = Column(Boolean,     nullable=False, default=False)
    created_at         = Column(DateTime,    nullable=False, default=utcnow_naive)
    created_by_user_id = Column(Integer,     ForeignKey("User.id"), nullable=True)
    updated_at         = Column(DateTime,    nullable=False, default=utcnow_naive)
    updated_by_user_id = Column(Integer,     ForeignKey("User.id"), nullable=True)
    notified_deadlines = Column(JSON,        nullable=False, default=list)


class EunomiaRecordEvent(Base):
    """Un cambio en una ficha. Solo se añade: nunca se edita.

    Attributes:
        id: Clave primaria.
        record_id: La ficha.
        owner_user_id: Dueño efectivo de los datos.
        actor_user_id: Quién lo cambió; ``None`` si esa cuenta se borró.
        actor_name: Nombre visible de quien lo cambió, guardado al hacer el cambio.
        occurred_at: Cuándo.
        changes: ``{campo: {"from": anterior, "to": nuevo}}``; ``isArchived`` entra como un campo más.
    """

    __tablename__ = "EunomiaRecordEvent"

    id            = Column(Integer,     primary_key=True, autoincrement=True)
    record_id     = Column(Integer,     ForeignKey("EunomiaRecord.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_user_id = Column(Integer,     ForeignKey("User.id"), nullable=False)
    actor_user_id = Column(Integer,     ForeignKey("User.id"), nullable=True)
    actor_name    = Column(String(255), nullable=False, default="")
    occurred_at   = Column(DateTime,    nullable=False, default=utcnow_naive)
    changes       = Column(JSON,        nullable=False)
