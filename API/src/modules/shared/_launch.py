"""
Cierre de las superficies que la instalación no tiene abiertas al público.

La decisión la toma ``LaunchConfig`` (``general.launch``); aquí solo está la
comprobación que la convierte en un error. Se llama dentro de la lógica que
realmente ejecuta cada función —el ``run_scan`` de un escáner, el lanzamiento
de una campaña—, no solo en el endpoint, para que los flujos programados y los
trabajos en segundo plano queden igual de cerrados.

Saber si un usuario concreto está exento (el administrador principal) exige
conocer su rol, que es cosa del módulo ``users``: por eso la exención llega
aquí como un booleano ya resuelto.
"""
from ._exceptions import SurfaceDisabledError


def assert_surface_enabled(surface: str, *, is_exempt: bool = False) -> None:
    """Lanza ``SurfaceDisabledError`` si la superficie está cerrada al público.

    Args:
        surface: La superficie que se va a usar, como miembro de
            ``LaunchSurface`` o como su valor (``"registration"``…).
        is_exempt: Si quien la usa está exento del cierre. Por defecto
            ``False``. Solo lo pone a ``True`` quien ya ha comprobado el rol
            (``UserManager.assert_launch_surface_enabled``).

    Raises:
        SurfaceDisabledError: Si la superficie está cerrada y no hay exención.
        ValueError: Si ``surface`` no es una superficie conocida.
    """
    # Import diferido: config_reading carga system/__init__.py, que carga la
    # TaskQueue, que importa shared. Al cargar shared cerraría el ciclo.
    import src.modules.system.config_reading as CR

    surface_key = CR.LaunchSurface(surface)
    if is_exempt or CR.launch_config().is_surface_enabled(surface_key):
        return
    raise SurfaceDisabledError(surface_key.value)
