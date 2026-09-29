"""El presupuesto de tiempo por test: cuándo un test lento pasa a ser un fallo.

La suite no espera tiempo real: la red y Redis están sellados y las pausas del
motor de escaneo no se duermen (``tests/conftest.py``). Un test que tarda
mucho casi siempre está esperando algo que no llega —una pausa, un reintento,
un plazo—, y esas esperas no hacen fallar nada: sólo hacen crecer la suite,
en silencio, hasta que un día tarda media hora. Este módulo decide cuándo esa
lentitud merece señalarse con nombre y apellidos: el ``conftest`` hace fallar
el test en la CI y lo anota en el resumen final en local.

Vive aparte del ``conftest`` para poder probarlo sin arrancar la suite: el
``conftest`` lo carga por ruta (hay más de un ``conftest`` en el árbol y el
nombre sería ambiguo) y ``tests/unit/test_time_budget.py`` hace lo mismo.
"""

from __future__ import annotations

from typing import Mapping, Optional

#: El presupuesto por defecto, en segundos, de la ejecución de un test. Casi
#: todos tardan milésimas; los más lentos legítimos rondan los 12 s en Windows
#: con ocho procesos a la vez (el análisis de ``src/`` entero de
#: ``test_code_conventions``, el recorrido de todas las excepciones de
#: ``test_shared_error_messages``). Veinte deja margen a esos sin dejar pasar
#: ninguna espera de verdad: las que se encontraron iban de 29 a 220 s.
DEFAULT_BUDGET_SECONDS = 20.0


def build_budget_failure(
    test_id: str,
    duration_seconds: float,
    budget_seconds: float,
    known_slow_tests: Mapping[str, str],
) -> Optional[str]:
    """Decide si un test que ha pasado debe fallar por su duración.

    Args:
        test_id: El identificador de pytest del test
            (``tests/…/test_x.py::test_y``, con sus parámetros si los tiene).
        duration_seconds: Lo que ha tardado su ejecución, sin la preparación.
        budget_seconds: El presupuesto. ``0`` o un valor negativo lo desactivan.
        known_slow_tests: Los tests a los que se les permite pasar del
            presupuesto, cada uno con el motivo.

    Returns:
        Optional[str]: ``None`` si el test puede pasar. Si no, el mensaje del
            fallo: o bien ha pasado del presupuesto sin estar en
            ``known_slow_tests`` (hay que abaratarlo o justificarlo), o bien
            está en la lista pero ha terminado en menos de la mitad del
            presupuesto (ya no es lento y hay que quitarlo, para que la lista
            sólo encoja).
    """
    if budget_seconds <= 0:
        return None
    is_known_slow = test_id in known_slow_tests
    if not is_known_slow and duration_seconds > budget_seconds:
        return (
            f"{test_id} ha tardado {duration_seconds:.1f} s, más que el presupuesto de "
            f"{budget_seconds:.0f} s por test. Casi siempre es una espera real (una pausa, "
            f"un reintento, un plazo de red) que el test no necesita: abarátala. Si la "
            f"lentitud es inevitable, añade el test a KNOWN_SLOW_TESTS en tests/conftest.py "
            f"con el motivo."
        )
    if is_known_slow and duration_seconds < budget_seconds / 2:
        return (
            f"{test_id} está en KNOWN_SLOW_TESTS pero ha tardado sólo "
            f"{duration_seconds:.1f} s: ya no es lento. Quítalo de la lista."
        )
    return None
