# CLAUDE.md — API

Backend REST Flask. **Es el área principal de trabajo.**

Todo (comandos, arquitectura, TaskQueue, configuración, convenciones y "cosas que muerden") está
en la guía maestra del repositorio: [`../CLAUDE.md`](../CLAUDE.md). No se duplica aquí a
propósito — dos copias de lo mismo derivan, y la que se queda atrás es la que alguien acaba
leyendo.

Docstrings y comentarios en **castellano**; sigue el idioma del fichero que tocas.

Nunca hagas una tarea por tu cuenta. Siempre delégalo a un subagent (o varios, si la carga de trabajo lo permite), adecuando el modelo de IA que usa para la carga de la tarea:

    1: Para tareas espontáneas y muy cortas: Haiku.
    2: Para tareas de carga de trabajo media: Sonnet.
    3: Para tareas largas y de pensamiento: Opus.
