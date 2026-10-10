"""
Tipos de registro: listas de fichas del mismo tipo que crecen con el tiempo.

Un marco es un árbol fijo con una evaluación por control; un *registro* es otra cosa: una ficha por
tratamiento de datos, por incidente, por solicitud de derechos, cada una con sus campos y, a veces,
con plazos que corren desde una fecha de la propia ficha. Igual que el catálogo y las plantillas,
la estructura de cada tipo es un **dato** (``registers/<tipo>@<versión>.json``) y el código es uno
solo.

Los plazos se **calculan al leer** y nunca se guardan, para que cambiar la definición no deje
fechas viejas en las fichas.

Puro: no toca base de datos ni red.
"""

import calendar
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional

from .catalog import CATALOG_ROOT, CatalogFormatError, load_version

#: Carpeta con las definiciones de registro.
REGISTERS_ROOT = Path(__file__).resolve().parents[1] / "registers"

FIELD_TEXT = "text"
FIELD_LONG_TEXT = "longtext"
FIELD_DATE = "date"
FIELD_DATETIME = "datetime"
FIELD_LIST = "list"
FIELD_PERSON = "person"
FIELD_SELECT = "select"
FIELD_TYPES = (FIELD_TEXT, FIELD_LONG_TEXT, FIELD_DATE, FIELD_DATETIME, FIELD_LIST, FIELD_PERSON, FIELD_SELECT)

#: Longitud máxima del valor de un campo.
MAX_VALUE_LENGTH = 20_000

DEADLINE_PENDING_INPUT = "pending_input"
DEADLINE_UPCOMING = "upcoming"
DEADLINE_OVERDUE = "overdue"
DEADLINE_DONE = "done"

_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_FILE = re.compile(r"^([a-z0-9-]+)@(\d+)\.json$")
_UNITS = ("hours", "days", "months")


@dataclass(frozen=True)
class RegisterField:
    """Un campo de la ficha.

    Attributes:
        key: Nombre del campo; único en el tipo.
        label: Texto que ve el usuario.
        type: Uno de ``FIELD_TYPES``.
        is_required: Si hay que rellenarlo para guardar la ficha.
        options: ``((valor, etiqueta), …)`` de un ``select``; vacío en los demás tipos.
        help: Ayuda breve; ``""`` si no tiene.
    """

    key: str
    label: str
    type: str
    is_required: bool
    options: tuple[tuple[str, str], ...]
    help: str


@dataclass(frozen=True)
class RegisterDeadline:
    """Un plazo que corre desde una fecha de la ficha.

    Attributes:
        key: Identificador del plazo; único en el tipo.
        label: Qué hay que hacer («Alerta temprana a la autoridad»).
        from_field: Campo ``date``/``datetime`` desde el que corre.
        amount: Cantidad de ``unit``.
        unit: ``hours``, ``days`` o ``months``.
        done_field: Campo que, relleno, da el plazo por cumplido; ``None`` si no hay.
        when_field: Campo que condiciona que el plazo aplique; ``None`` si aplica siempre.
        when_equals: Valores que ``when_field`` puede tener para que aplique (uno o varios).
        framework: Marco al que pertenece el plazo, para agrupar en pantalla; ``""`` si ninguno.
    """

    key: str
    label: str
    from_field: str
    amount: int
    unit: str
    done_field: Optional[str]
    when_field: Optional[str]
    when_equals: tuple[str, ...]
    framework: str


@dataclass(frozen=True)
class RegisterType:
    """Una definición de registro validada.

    Attributes:
        key: Identificador (``"rgpd-actividades-tratamiento"``).
        version: Versión de la definición.
        title: Nombre del registro.
        summary: Para qué sirve, en una frase.
        title_field: Campo cuyo valor titula cada ficha.
        controls: ``{marco: identificadores}`` de los requisitos que el registro demuestra.
        fields: Campos, en el orden del formulario.
        deadlines: Plazos calculados; puede estar vacío.
        examples: Fichas de ejemplo que se ofrecen al empezar.
        advice: Avisos que dependen del perfil de empresa: ``{"companyField", "lessThan",
            "message"}``; el aviso sale si ese campo numérico del perfil es menor que el umbral.
    """

    key: str
    version: str
    title: str
    summary: str
    title_field: str
    controls: Mapping[str, tuple[str, ...]]
    fields: tuple[RegisterField, ...]
    deadlines: tuple[RegisterDeadline, ...]
    examples: tuple[Mapping[str, str], ...]
    advice: tuple[Mapping[str, object], ...] = ()

    def field(self, key: str) -> Optional[RegisterField]:
        """El campo con esa clave, o ``None``."""
        return next((item for item in self.fields if item.key == key), None)


def parse_register(document: dict, root: Path = CATALOG_ROOT) -> RegisterType:
    """Valida una definición de registro.

    Args:
        document: El JSON ya cargado.
        root: Carpeta del catálogo, contra la que se comprueban los requisitos que declara.

    Returns:
        RegisterType: La definición validada.

    Raises:
        CatalogFormatError: Si falta algo, un plazo apunta a un campo que no es fecha, un
            requisito no existe en la versión vigente del marco, o un ejemplo no cumple la
            definición.
    """
    where = document.get("key", "?")
    for required in ("key", "version", "title", "summary", "titleField", "fields"):
        if required not in document:
            raise CatalogFormatError(f"{where}: falta «{required}»")

    fields: list[RegisterField] = []
    for raw in document["fields"]:
        key = raw.get("key", "")
        if not _KEY.match(key):
            raise CatalogFormatError(f"{where}: la clave de campo «{key}» no es válida")
        if any(item.key == key for item in fields):
            raise CatalogFormatError(f"{where}: el campo «{key}» está repetido")
        if raw.get("type") not in FIELD_TYPES:
            raise CatalogFormatError(f"{where}: el campo «{key}» tiene un tipo desconocido")
        options = tuple((option["value"], option["label"]) for option in raw.get("options", []))
        if (raw["type"] == FIELD_SELECT) != bool(options):
            raise CatalogFormatError(f"{where}: el campo «{key}» necesita opciones si y solo si es un select")
        fields.append(RegisterField(key, raw.get("label", key), raw["type"], bool(raw.get("required", False)),
                                    options, raw.get("help", "")))
    by_key = {item.key: item for item in fields}
    if document["titleField"] not in by_key:
        raise CatalogFormatError(f"{where}: «titleField» no es un campo")

    deadlines: list[RegisterDeadline] = []
    for raw in document.get("deadlines", []):
        unit = next((candidate for candidate in _UNITS if candidate in raw), None)
        source = by_key.get(raw.get("from", ""))
        if unit is None or source is None or source.type not in (FIELD_DATE, FIELD_DATETIME):
            raise CatalogFormatError(f"{where}: el plazo «{raw.get('key')}» necesita un campo fecha en «from» y una cantidad")
        for reference in ("doneField", "whenField"):
            if reference in raw and raw[reference] not in by_key:
                raise CatalogFormatError(f"{where}: el plazo «{raw.get('key')}» usa un campo que no existe: {raw[reference]}")
        deadlines.append(RegisterDeadline(raw["key"], raw["label"], raw["from"], int(raw[unit]), unit,
                                          raw.get("doneField"), raw.get("whenField"),
                                          _as_tuple(raw.get("whenEquals")), raw.get("framework", "")))

    controls = {framework: tuple(identifiers) for framework, identifiers in document.get("controls", {}).items()}
    for framework, identifiers in controls.items():
        index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        entry = next((item for item in index["frameworks"] if item["key"] == framework), None)
        version = load_version(framework, entry["current"], root) if entry else None
        for identifier in identifiers:
            node = version.node(f"{framework}:{identifier}") if version else None
            if node is None or not node.is_assessable:
                raise CatalogFormatError(f"{where}: el requisito «{framework}:{identifier}» no existe o no es evaluable")

    register = RegisterType(
        key=document["key"], version=str(document["version"]), title=document["title"], summary=document["summary"],
        title_field=document["titleField"], controls=controls, fields=tuple(fields), deadlines=tuple(deadlines),
        examples=tuple(document.get("examples", [])), advice=tuple(document.get("advice", [])),
    )
    for position, example in enumerate(register.examples):
        problems = validate_values(register, example)
        if problems:
            raise CatalogFormatError(f"{where}: el ejemplo {position} no cumple la definición: {problems[0]}")
    return register


def _as_tuple(value) -> tuple[str, ...]:
    """Un valor o una lista de valores de la definición, siempre como tupla."""
    if value is None:
        return ()
    return (value,) if isinstance(value, str) else tuple(value)


def validate_values(register: RegisterType, values: Mapping[str, str]) -> list[str]:
    """Comprueba los valores de una ficha contra su definición.

    Args:
        register: La definición.
        values: ``{campo: texto}`` de la ficha.

    Returns:
        list[str]: Claves de los campos con problema; vacía si la ficha es válida. Un campo
            desconocido, un valor que no es texto o demasiado largo, una fecha mal formada, una
            opción que no existe o un obligatorio vacío cuentan como problema.
    """
    problems: list[str] = []
    for key, value in values.items():
        field = register.field(key)
        if field is None or not isinstance(value, str) or len(value) > MAX_VALUE_LENGTH:
            problems.append(key)
            continue
        if not value.strip():
            continue
        if field.type == FIELD_DATE and not _is_iso(value, date.fromisoformat):
            problems.append(key)
        elif field.type == FIELD_DATETIME and not _is_iso(value, datetime.fromisoformat):
            problems.append(key)
        elif field.type == FIELD_SELECT and value not in {option for option, _ in field.options}:
            problems.append(key)
    for field in register.fields:
        if field.is_required and not str(values.get(field.key, "")).strip() and field.key not in problems:
            problems.append(field.key)
    return problems


def _is_iso(value: str, parser) -> bool:
    """Si ``parser`` (``fromisoformat``) acepta el texto."""
    try:
        parser(value)
    except ValueError:
        return False
    return True


def _add_months(moment: datetime, months: int) -> datetime:
    """Suma meses de calendario, ajustando el día al último del mes si hace falta."""
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    return moment.replace(year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1]))


def compute_deadlines(register: RegisterType, values: Mapping[str, str], now: datetime) -> list[dict]:
    """Calcula los plazos de una ficha. Nunca se guardan.

    Args:
        register: La definición.
        values: Valores de la ficha.
        now: Instante de referencia (naive UTC) para decidir si un plazo venció.

    Returns:
        list[dict]: Un elemento por plazo que aplica, con ``key``, ``label``, ``framework``,
            ``dueAt`` (``None`` si falta la fecha de origen), ``fromField`` y ``status``:
            ``pending_input`` (falta la fecha de origen), ``upcoming``, ``overdue`` o ``done``.
    """
    results = []
    for deadline in register.deadlines:
        if deadline.when_field is not None and values.get(deadline.when_field, "") not in deadline.when_equals:
            continue
        origin = values.get(deadline.from_field, "").strip()
        due: Optional[datetime] = None
        if origin:
            moment = datetime.fromisoformat(origin) if "T" in origin or " " in origin else datetime.combine(
                date.fromisoformat(origin), datetime.min.time())
            moment = moment.replace(tzinfo=None)
            if deadline.unit == "hours":
                due = moment + timedelta(hours=deadline.amount)
            elif deadline.unit == "days":
                due = moment + timedelta(days=deadline.amount)
            else:
                due = _add_months(moment, deadline.amount)
        if deadline.done_field and values.get(deadline.done_field, "").strip():
            status = DEADLINE_DONE
        elif due is None:
            status = DEADLINE_PENDING_INPUT
        else:
            status = DEADLINE_OVERDUE if due < now else DEADLINE_UPCOMING
        results.append({"key": deadline.key, "label": deadline.label, "framework": deadline.framework,
                        "dueAt": due, "fromField": deadline.from_field, "status": status})
    return results


@lru_cache(maxsize=None)
def _load_all(registers_root: str, catalog_root: str) -> tuple[RegisterType, ...]:
    found: list[RegisterType] = []
    for path in sorted(Path(registers_root).glob("*.json")):
        match = _FILE.match(path.name)
        if match is None:
            raise CatalogFormatError(f"{path.name}: el nombre debe ser <tipo>@<versión>.json")
        register = parse_register(json.loads(path.read_text(encoding="utf-8")), Path(catalog_root))
        if (register.key, register.version) != match.groups():
            raise CatalogFormatError(f"{path.name}: la clave o la versión no coinciden con el nombre del fichero")
        found.append(register)
    return tuple(found)


def load_registers(registers_root: Path = REGISTERS_ROOT, catalog_root: Path = CATALOG_ROOT) -> tuple[RegisterType, ...]:
    """Carga y valida todas las definiciones de registro.

    Args:
        registers_root: Carpeta de definiciones.
        catalog_root: Carpeta del catálogo contra la que se validan los requisitos.

    Returns:
        tuple[RegisterType, ...]: Todas las versiones, por nombre de fichero.
    """
    return _load_all(str(registers_root), str(catalog_root))


def get_register(key: str, **roots) -> Optional[RegisterType]:
    """La última versión de un tipo de registro, o ``None``.

    Args:
        key: Identificador del tipo.
        **roots: ``registers_root`` y ``catalog_root``, para pruebas.
    """
    matches = [item for item in load_registers(**roots) if item.key == key]
    return max(matches, key=lambda item: int(item.version), default=None)
