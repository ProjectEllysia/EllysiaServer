"""
Validación de identificadores fiscales españoles (DNI, NIE y CIF).

Solo comprueba la forma y el dígito o letra de control; no consulta ningún
registro, así que un identificador bien formado puede no existir.
"""

import re

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}
_CIF_PATTERN = re.compile(r"^([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])$")
_CIF_CONTROL_LETTERS = "JABCDEFGHI"
# Sociedades cuyo control es siempre una letra, y las que lo llevan siempre en número.
_CIF_LETTER_CONTROL = frozenset("PQRSNW")
_CIF_DIGIT_CONTROL = frozenset("ABEH")


def normalize_tax_id(value: str) -> str:
    """Pasa un identificador a mayúsculas y le quita espacios y guiones.

    Args:
        value: Identificador tal como lo escribió la persona (``"b-12345674"``).

    Returns:
        str: El identificador en mayúsculas, sin separadores.
    """
    return re.sub(r"[\s\-.]", "", value or "").upper()


def is_valid_spanish_tax_id(value: str) -> bool:
    """Indica si un identificador es un DNI, NIE o CIF español bien formado.

    shortcut: los NIF especiales que empiezan por K, L o M (menores y
    residentes sin NIE) no se aceptan; se añaden si un cliente los necesita.

    Args:
        value: Identificador a comprobar; se normaliza antes (``normalize_tax_id``).

    Returns:
        bool: ``True`` si la forma y el carácter de control son correctos;
            ``False`` en cualquier otro caso, incluida una cadena vacía.
    """
    tax_id = normalize_tax_id(value)

    if re.fullmatch(r"\d{8}[A-Z]", tax_id):
        return _DNI_LETTERS[int(tax_id[:8]) % 23] == tax_id[8]

    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", tax_id):
        number = _NIE_PREFIX[tax_id[0]] + tax_id[1:8]
        return _DNI_LETTERS[int(number) % 23] == tax_id[8]

    match = _CIF_PATTERN.match(tax_id)
    if match is None:
        return False
    organization_type, digits, control = match.groups()
    # Posiciones impares (1.ª, 3.ª…) se duplican y se suman sus cifras; las pares se suman tal cual.
    total = 0
    for index, character in enumerate(digits):
        digit = int(character)
        if index % 2 == 0:
            digit *= 2
            digit = digit // 10 + digit % 10
        total += digit
    control_digit = (10 - total % 10) % 10
    if organization_type in _CIF_LETTER_CONTROL:
        return control == _CIF_CONTROL_LETTERS[control_digit]
    if organization_type in _CIF_DIGIT_CONTROL:
        return control == str(control_digit)
    return control in (str(control_digit), _CIF_CONTROL_LETTERS[control_digit])
