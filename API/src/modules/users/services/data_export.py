"""
Exportación de todos los datos de un usuario a un archivo ZIP.

**Para qué existe.** El RGPD da a cada persona derecho a una copia de sus datos
(artículo 15) y a llevárselos en un formato estructurado a otro servicio
(artículo 20). Este fichero escribe esa copia: un ZIP con un JSON por módulo
(``profile.json``, ``themis.json``…) y un ``manifest.json`` que dice qué hay
dentro y qué se ha dejado fuera a propósito.

**Quién decide qué entra.** Cada módulo declara sus tablas junto a sus modelos
(``features/<módulo>/data_export.py``, ``EXPORT_TABLES``), incluidas las
columnas que no deben salir. Aquí solo se recogen esas declaraciones y se
escriben, así que añadir una tabla a la exportación no obliga a tocar este
fichero. Un test recorre las claves ajenas hacia ``User`` para que ninguna
tabla se quede sin decidir.

**Cómo se escribe.** Las filas se leen por tandas y se escriben al ZIP según
llegan: un usuario con cien mil hallazgos no tiene que caber en memoria. El
fichero se escribe en uno temporal y se renombra al terminar, así que nadie
descarga un ZIP a medias.
"""

from __future__ import annotations

import base64
import enum
import json
import logging
import os
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from src.modules.shared import ExportTable, isoformat_utc, owned_by
from src.modules.users.model import MFATotpCredential, User, UserAttribute
from src.modules.users.services.user_data import UserDataRegistry

logger = logging.getLogger(__name__)

#: Versión del formato del archivo. Se sube si cambia la forma de los JSON, para
#: que quien lo lea desde otro servicio sepa a qué atenerse.
EXPORT_FORMAT_VERSION = 1

#: Filas que se leen de la base de datos de una vez al recorrer una tabla.
_BATCH_SIZE = 500


def _profile_tables() -> tuple[ExportTable, ...]:
    """Las tablas del propio módulo de usuarios: perfil, permisos y segundo factor.

    Returns:
        tuple[ExportTable, ...]: Sin los hashes de contraseña y de enlaces ni el
            secreto del segundo factor, que no se entregan a nadie, ni a su dueño.
    """
    return (
        ExportTable(
            "user", User, owned_by(User.id),
            frozenset({
                "password_hash", "password_salt",
                "email_verification_hash", "password_reset_hash",
            }),
        ),
        ExportTable("attributes", UserAttribute, owned_by(UserAttribute.user_id)),
        ExportTable("two_factor", MFATotpCredential, owned_by(MFATotpCredential.user_id), frozenset({"totp_secret"})),
    )


def export_modules() -> dict[str, tuple[ExportTable, ...]]:
    """Las tablas que entran en la exportación, agrupadas por módulo y en orden.

    Las de los módulos registrados en ``UserDataRegistry`` (``accounts``) las
    aportan ellos. Las de las features siguen importadas aquí, con los imports
    diferidos: apuntan «hacia abajo» (users → features) y al nivel de módulo
    cerrarían un ciclo.

    Returns:
        dict[str, tuple[ExportTable, ...]]: Nombre del módulo (el del fichero
            JSON que se escribe) → sus tablas. Primero ``profile``, luego los
            módulos registrados por prioridad y después las features.
    """
    from src.modules.features.acheron.data_export import EXPORT_TABLES as acheron_tables
    from src.modules.features.aegis.data_export import EXPORT_TABLES as aegis_tables
    from src.modules.features.hygeia.data_export import EXPORT_TABLES as hygeia_tables
    from src.modules.features.iris.data_export import EXPORT_TABLES as iris_tables
    from src.modules.features.themis.data_export import EXPORT_TABLES as themis_tables

    registered = {
        item.name: item.export_tables
        for item in UserDataRegistry.contributions()
        if item.export_tables
    }
    return {
        "profile": _profile_tables(),
        **registered,
        "themis": themis_tables,
        "aegis": aegis_tables,
        "iris": iris_tables,
        "hygeia": hygeia_tables,
        "acheron": acheron_tables,
    }


#: Tablas con clave ajena hacia ``User`` que **no** se exportan, con el motivo. El
#: test del grafo de claves ajenas exige que toda tabla esté exportada o aquí:
#: así nadie añade una y se olvida de decidir si es parte de la copia.
NOT_EXPORTED_TABLES: dict[str, str] = {
    "AccessToken": "sesión: credencial de acceso, no un dato del usuario",
    "RefreshToken": "sesión: credencial de acceso, no un dato del usuario",
    "MFAChallenge": "desafío de segundo factor a medias: credencial temporal",
    "MFARecoveryCode": "códigos de recuperación: solo se guarda su hash y no se entrega a nadie",
    "OrganizationInvitation": "invitaciones: contienen correos de terceros que no son el usuario",
    "IrisTenantProfile": "perfil de la organización, no del usuario que lo modificó por última vez",
    "DataExport": "la propia exportación: es el registro de este archivo, no un dato suyo",
}


def _json_default(value: Any) -> Any:
    """Convierte a algo que JSON entienda los tipos que las columnas devuelven.

    Args:
        value: Un valor que ``json`` no sabe serializar.

    Returns:
        Any: Fechas en ISO 8601 (las de fecha y hora, en UTC con ``Z``), los
            decimales y los UUID como texto, los bytes en base64, los enums por
            su valor y los conjuntos como lista ordenada. Cualquier otra cosa,
            como texto.
    """
    if isinstance(value, datetime):
        return isoformat_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    return str(value)


def serialize_row(instance: Any, exclude: frozenset[str]) -> dict[str, Any]:
    """Una fila como diccionario, con las columnas que no deben salir ya quitadas.

    Se usa el mapper de la propia instancia, no el del modelo declarado: si es
    la base de una herencia (un escaneo), salen también las columnas de su
    subclase. Una columna excluida ni siquiera se lee: así un secreto cifrado
    nunca se descifra para el archivo.

    Args:
        instance: La fila cargada.
        exclude: Atributos que no salen.

    Returns:
        dict[str, Any]: Atributo → valor, tal cual lo devuelve el modelo.
    """
    mapper = sa_inspect(instance).mapper
    return {
        attribute.key: getattr(instance, attribute.key)
        for attribute in mapper.column_attrs
        if attribute.key not in exclude
    }


def iter_table_rows(session: Session, table: ExportTable, user_id: int) -> Iterator[dict[str, Any]]:
    """Recorre las filas de un usuario en una tabla, por tandas y por clave primaria.

    No se cargan las relaciones (``enable_eagerloads(False)``): la exportación
    quiere las columnas de cada tabla, y cada tabla tiene su propia entrada. Sin
    esto, una relación con carga ansiosa impediría leer por tandas.

    Args:
        session: Sesión abierta.
        table: La tabla y su alcance.
        user_id: El usuario.

    Yields:
        dict[str, Any]: Cada fila, ya sin las columnas excluidas.
    """
    primary_key = sa_inspect(table.model).primary_key
    query = (
        session.query(table.model)
        .enable_eagerloads(False)
        .filter(table.scope(user_id))
        .order_by(*primary_key)
        .yield_per(_BATCH_SIZE)
    )
    for instance in query:
        yield serialize_row(instance, table.exclude)


def _write_module(
    archive: zipfile.ZipFile, session: Session, module_name: str,
    tables: tuple[ExportTable, ...], user_id: int,
) -> dict[str, int]:
    """Escribe el JSON de un módulo, tabla a tabla, sin tenerlo entero en memoria.

    Args:
        archive: El ZIP abierto para escribir.
        session: Sesión abierta.
        module_name: Nombre del módulo; da nombre al fichero (``themis.json``).
        tables: Sus tablas.
        user_id: El usuario.

    Returns:
        dict[str, int]: Filas escritas por tabla.
    """
    counts: dict[str, int] = {}
    with archive.open(f"{module_name}.json", "w", force_zip64=True) as handle:
        handle.write(b"{")
        for table_position, table in enumerate(tables):
            handle.write((",\n" if table_position else "\n").encode("utf-8"))
            handle.write(f'  {json.dumps(table.name)}: ['.encode("utf-8"))
            written = 0
            for row in iter_table_rows(session, table, user_id):
                handle.write((",\n    " if written else "\n    ").encode("utf-8"))
                handle.write(json.dumps(row, ensure_ascii=False, default=_json_default).encode("utf-8"))
                written += 1
            handle.write(b"\n  ]" if written else b"]")
            counts[table.name] = written
        handle.write(b"\n}\n")
    return counts


def write_export_archive(
    session: Session, user_id: int, destination: Path, generated_at: datetime,
) -> dict[str, dict[str, int]]:
    """Escribe el ZIP con todos los datos de un usuario.

    Se escribe en un fichero temporal junto al destino y se renombra al
    terminar: una exportación interrumpida no deja un ZIP truncado que alguien
    pudiera descargar.

    Args:
        session: Sesión abierta con la que leer.
        user_id: El usuario del que se exportan los datos.
        destination: Ruta final del ZIP. Su carpeta debe existir.
        generated_at: Cuándo se generó, UTC sin zona; va en el manifiesto.

    Returns:
        dict[str, dict[str, int]]: Módulo → tabla → filas escritas.
    """
    temporary = destination.with_name(destination.name + ".partial")
    counts: dict[str, dict[str, int]] = {}
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for module_name, tables in export_modules().items():
                counts[module_name] = _write_module(archive, session, module_name, tables, user_id)
            archive.writestr("manifest.json", json.dumps({
                "formatVersion": EXPORT_FORMAT_VERSION,
                "generatedAt": isoformat_utc(generated_at),
                "userId": user_id,
                "modules": counts,
                "notIncluded": NOT_EXPORTED_TABLES,
                "notes": [
                    "Los secretos y las credenciales no se incluyen: contraseñas, tokens de sesión, "
                    "tokens de proveedores de correo y claves de agentes.",
                    "La bóveda de Acheron va tal cual está guardada, cifrada: solo se abre con tu "
                    "contraseña maestra.",
                    "El contenido completo de los correos analizados por Iris no se incluye: es una "
                    "copia temporal del buzón que se borra sola. Sí se incluye el resultado de cada análisis.",
                    "Los informes en PDF no se incluyen; sí sus metadatos.",
                ],
            }, ensure_ascii=False, indent=2))
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return counts
