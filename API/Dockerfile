# La imagen se construye en tres etapas para que la final lleve solo lo que se
# ejecuta: las herramientas de descarga (curl, unzip, git) y la caché de
# instalación de Python se quedan en las etapas intermedias y no ocupan sitio
# en la imagen que se despliega.
#
# La base es la variante `slim` de Debian y no Alpine: todas las dependencias
# de requirements.txt se instalan desde wheels manylinux (glibc), que en musl
# no sirven y obligarían a compilar opencv, cryptography o psycopg2.

# ---------------------------------------------------------------------------
# Etapa 1: escáneres externos (Nuclei, sus plantillas y Nikto)
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS tools

# Versión fijada (no "latest") para que la imagen sea reproducible — revisar
# periódicamente en https://github.com/projectdiscovery/nuclei/releases.
# Q_NUCLEI: verificar los flags de este Dockerfile contra `nuclei -h` de la
# versión fijada antes de asumir que siguen siendo correctos (roadmap Fase U1):
# `-update-templates` es el nombre largo de v3; una imagen que acabe en v2
# necesitaría ajustar solo este bloque.
ARG NUCLEI_VERSION=3.3.7

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    git \
    && git clone --depth 1 https://github.com/sullo/nikto.git /nikto \
    && rm -rf /nikto/.git \
    && chmod +x /nikto/program/nikto.pl \
    && ln -s /nikto/program /nikto/latest \
    && curl -sL "https://github.com/projectdiscovery/nuclei/releases/download/v${NUCLEI_VERSION}/nuclei_${NUCLEI_VERSION}_linux_amd64.zip" -o /tmp/nuclei.zip \
    && unzip -q /tmp/nuclei.zip -d /usr/local/bin nuclei \
    && chmod +x /usr/local/bin/nuclei

# Plantillas horneadas en build (roadmap Fase U1): sin sincronización en
# tiempo de ejecución — una llamada de red a mitad de un escaneo dentro de un
# worker sería latencia y un fallo posible nuevo, así que NucleiScanTask
# siempre pasa `-duc`. Consecuencia consciente: el feed envejece hasta el
# siguiente build de esta imagen; no hay cron de refresco todavía (deuda
# documentada en el roadmap — el patrón a seguir cuando se cierre es el mismo
# que `KbSyncManager` ya tiene para la KB de Lybra). La versión resultante se
# vuelca a un fichero que `config_reading.get_nuclei_templates_version()` lee
# como fallback, para no depender solo del valor estático de SecOpsConfig.json.
#
# La descarga va sin `-duc`: ese flag desactiva toda comprobación de
# actualizaciones, también la que pide `-update-templates`, y el paso
# terminaría sin bajar nada. La versión se toma de `-templates-version` (la
# del feed, con su `v` delante, igual que la captura del banner de
# NucleiScanTask) y no de `-version`, que da la del motor.
#
# Nuclei guarda las plantillas (`/root/nuclei-templates`) y su configuración
# bajo el HOME de root; ese directorio se copia entero a la imagen final, sin
# la caché de la descarga.
RUN nuclei -update-templates -silent \
    && test -d /root/nuclei-templates \
    && (nuclei -templates-version -duc 2>&1 | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | tail -1 > /nuclei_templates_version.txt || true) \
    && rm -rf /root/.cache

# ---------------------------------------------------------------------------
# Etapa 2: dependencias de Python en un entorno virtual
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS deps

# uv instala lo mismo que pip desde el mismo requirements.txt (es lo que usa
# la CI). Su caché vive en un montaje de BuildKit: acelera el siguiente build
# y no acaba en ninguna capa. Los .pyc se generan aquí para que el arranque
# del contenedor no tenga que compilarlos.
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python -r requirements.txt

# ---------------------------------------------------------------------------
# Etapa 3: imagen final
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm

WORKDIR /app

# Solo paquetes que se ejecutan: los escáneres (nmap, traceroute), Perl y los
# módulos que Nikto necesita, tesseract para el OCR de Iris y sudo, con el que
# se lanzan nmap y traceroute.
RUN apt-get update && apt-get install -y --no-install-recommends \
    sudo \
    nmap \
    traceroute \
    perl \
    libio-socket-ssl-perl \
    libjson-perl \
    libnet-ssleay-perl \
    libxml-writer-perl \
    tesseract-ocr \
    tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

COPY --from=tools /usr/local/bin/nuclei /usr/local/bin/nuclei
COPY --from=tools /nikto /nikto
COPY --from=tools /root/ /root/
RUN ln -s /nikto/program/nikto.pl /usr/local/bin/nikto

COPY --from=deps /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:/nikto/program:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY src/ ./src/
COPY run.py .
COPY SecOpsConfig.json .
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY resources/ ./resources/
COPY --from=tools /nuclei_templates_version.txt ./resources/nuclei_templates_version.txt

RUN mkdir -p /app/data/themis/output /app/data/themis/csv /app/data/aegis/output /app/data/aegis/stack /app/data/iris/output /app/temp /app/logs

EXPOSE 5000

# E5: sin USER no-root — el nmap de Debian (7.93, sin libcap-ng) exige UID 0
# real para escaneos SYN pase lo que pase con las capabilities del binario
# (verificado: setcap cap_net_raw+eip + usuario no-root → "requires root
# privileges" incluso con --cap-add=NET_RAW). Bajar privilegios aquí
# rompería el escaneo Nmap en silencio; requiere una imagen de nmap con
# soporte libcap-ng (no la de Debian) antes de poder hacerlo con seguridad.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/system/say-hello', timeout=3)" || exit 1

# ponytail: 1 worker process (gthread, 8 hilos) en vez de N workers gunicorn —
# el scheduler (APScheduler) y la reconciliación de huérfanos en create_app()
# son en memoria por proceso; con >1 worker se duplicarían. Escalar a más
# procesos exige antes un lock distribuido (Redis) para ambos.
# La fábrica se declara con la sintaxis de llamada `módulo:invocable()`, no con
# el flag --factory: requirements.txt pide `gunicorn>=21.2.0`, la 26 ya no
# tiene ese flag, y la sintaxis de llamada la entienden todas las versiones
# desde la 20.1. Es `create_api_app()`, la misma fábrica que `python run.py`,
# para que `CREATE_DATABASE` funcione también aquí.
CMD ["gunicorn", "run:create_api_app()", "--bind", "0.0.0.0:5000", \
     "--workers", "1", "--threads", "8", "--timeout", "60"]
