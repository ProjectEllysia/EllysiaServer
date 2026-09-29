# Lybra — Fases 8 y 9: ampliar lo que el motor encuentra

Registro de la sesión del 2026-09-28. Explica qué se decidió, qué está hecho, cómo debe quedar el
proyecto de GitHub y cómo seguir. Escrito para que lo entienda cualquiera, técnico o no; los
nombres de ficheros y otros detalles técnicos van al final.

---

## 1. En pocas palabras

Lybra es el motor de escaneo propio de Themis: revisa los equipos que el usuario tiene
autorizados y avisa de lo que está mal configurado o expuesto. Se le pidió a un «consejo» de
cuatro especialistas (Windows y Directorio Activo, web, criptografía y correo, y servicios de
datos y DevOps) que buscara **qué problemas no relacionados con vulnerabilidades catalogadas
(CVE) todavía no intenta encontrar**.

El consejo llegó a tres conclusiones:

1. **Tres comprobaciones que ya estaban publicadas fallaban.** Ya están corregidas (ver §3).
2. **Mucho de lo que falta ya se lee y se tira.** Las sondas del motor recogen datos (si una base
   de datos cifra la conexión, qué cifrado usa el escritorio remoto, cómo es el certificado…) que
   nunca se convierten en un aviso. Es lo más barato de añadir.
3. **El resto necesita piezas nuevas** en el lenguaje con el que se escriben las comprobaciones.

De ahí salen dos fases nuevas en el backlog de Lybra:

- **Fase 8 — Lo que ya se lee.** Casi todo realista a corto plazo: los tres fallos, los datos que
  se tiran y las comprobaciones que caben hoy en el motor.
- **Fase 9 — El catálogo nuevo.** La maquinaria que falta y las comprobaciones que dependen de ella.

Se añaden al proyecto que ya existe en lugar de abrir uno nuevo, porque el backlog de Lybra ya
tiene exactamente esta forma y un proyecto aparte lo partiría en dos.

---

## 2. Cómo debe quedar el proyecto de GitHub

Proyecto: **«Themis — Necesidades del motor Lybra»** (proyecto 4 de la organización
ProjectEllysia).

### 2.1 Estructura

```
[Fase 8] Lo que ya se lee            ← issue padre (una por fase)
 ├─ [L87] …                          ← sub-issues: una necesidad cada una
 ├─ [L88] …
 └─ …
[Fase 9] El catálogo nuevo
 ├─ [L101] …
 └─ …
```

- **Un issue padre por fase.** Título `[Fase N] Nombre`. Contiene la tabla de sus necesidades
  ordenada por prioridad, «Por qué esta fase existe», «Orden interno» y «Criterio de cierre de la
  fase». Mismo formato que [Fase 6] y [Fase 7].
- **Un sub-issue por necesidad.** Título `[LNN] Frase que explica el problema`, sin nombres de
  código. La numeración L es continua en todo el backlog: la última antes de esta sesión era
  L86, así que la Fase 8 va de L87 a L100 y la Fase 9 de L101 a L117.
- Cada sub-issue se **enlaza a su padre** como sub-issue de GitHub, de forma que el padre muestre
  la barra de progreso.

### 2.2 Campos del proyecto

| Campo | Qué se pone |
|---|---|
| Fase | «Fase 8 — Lo que ya se lee» o «Fase 9 — El catálogo nuevo» (opciones ya creadas) |
| Status | Todo al crearlo; Done al cerrarlo |
| Categoría | Bug, Mejora, Funcionalidad, Arquitectura… |
| Realismo | R1 (días, con piezas que ya existen) · R2 (realista) · R3 (estratégico, más caro) · R4 (experimental) |
| Impacto | 1 a 5: cuánto duele el problema |
| Facilidad | 1 a 5: cuánto cuesta arreglarlo (5 = muy fácil) |
| Prioridad | Impacto × Facilidad |
| Orden | Posición en la tabla maestra; sigue tras el 57. Fase 8 ocupa 58–71 y Fase 9 72–88 |

Los padres de fase solo llevan Fase y Status.

### 2.3 Etiquetas

Cada sub-issue lleva `lybra-roadmap`, `themis`, la de su fase y estas cuatro:

| Etiqueta | Regla |
|---|---|
| `cat:*` | La categoría (`cat:bug`, `cat:funcionalidad`, `cat:arquitectura`, `cat:mejora`) |
| `realismo:r1` … `r4` | El realismo |
| `fac:alta` / `media` / `baja` | Facilidad 4–5 / 3 / 1–2 |
| `prio:critica` / `alta` / `media` / `baja` | Prioridad ≥ 16 / 12–15 / 8–11 / ≤ 7 |

Los padres solo llevan `lybra-roadmap`, `themis` y la de su fase.

### 2.4 Plantilla de cada sub-issue

1. Cabecera: «Necesidad **LNN** del backlog del motor **Lybra** · propuesta del consejo de
   especialistas del 2026-09-28 sobre la rama `v0.5`».
2. Tabla: Categoría, Fase, Impacto, Facilidad, Prioridad, Realismo, Orden.
3. Secciones, en este orden: **En pocas palabras**, **Qué ocurre hoy**, **Por qué importa**,
   **Qué hay que hacer**, **Cómo sabremos que está hecho**, **Dependencias y orden** y, al final,
   **Detalle técnico** (ficheros, piezas del motor, tests y señuelo del banco, con cada término
   explicado).
4. El pie `<sub>…</sub>` estándar del backlog de Lybra (el de #1034).

Regla de oro heredada del backlog: **cada comprobación nueva entra con su señuelo**, es decir, un
equipo de pruebas que *no* debe hacerla saltar, además del que sí. Es lo que mantiene la
precisión del motor.

---

## 3. Estado a 2026-09-28

**Hecho:**

- Opciones «Fase 8 — Lo que ya se lee» y «Fase 9 — El catálogo nuevo» añadidas al campo Fase.
  Antes se guardó una copia de la fase de los 99 elementos y, al comparar después, no había
  cambiado ninguno.
- Etiqueta `lybra:fase-8` creada.
- Los tres fallos corregidos, mergeados en `v0.5` y con sus issues cerrados:

| Necesidad | Issue | PR | Qué pasaba |
|---|---|---|---|
| L87 | #1034 | #1039 | Si una respuesta web traía varias cookies, el motor solo veía la primera, así que los avisos sobre cookies de sesión inseguras no la veían. |
| L88 | #1036 | #1042 | El aviso de «acceso anónimo a LDAP» saltaba en todos los controladores de dominio, porque el protocolo obliga a aceptar esa conexión para servir su ficha pública. Ahora solo salta si el directorio entrega entradas sin credenciales. |
| L89 | #1035 | #1040 | El motor no podía detectar TLS antiguo ni cifrados débiles, porque la librería de Python ya no los ofrece. Ahora pregunta expresamente por TLS 1.0 y 1.1, y dice «no se sabe» cuando la máquina no puede comprobarlo. |

**Pendiente:**

- Etiqueta `lybra:fase-9`.
- Los dos issues padre.
- Los sub-issues L90–L100 (Fase 8) y L101–L117 (Fase 9).
- Un comentario en #316 (inteligencia pasiva) proponiendo que la higiene del dominio de correo
  (SPF, DMARC, DKIM, MTA-STS, CAA, DNSSEC) viva allí. Son consultas a DNS público y no tienen
  puerto que escanear, así que no encajan en un motor que analiza equipos.

---

## 4. Las necesidades

### Fase 8 — Lo que ya se lee (14 necesidades · prioridad acumulada 230)

| Id | Necesidad | Categoría | I | F | I×F | R | Orden | Estado |
|---|---|---|---|---|---|---|---|---|
| L95 | etcd, Consul y Kibana se reconocen, pero no se comprueba si están abiertos sin credenciales | Funcionalidad | 5 | 5 | 25 | R1 | 58 | Pendiente |
| L91 | Escritorio remoto con el cifrado antiguo en vez de TLS | Funcionalidad | 4 | 5 | 20 | R1 | 59 | Pendiente |
| L94 | Correo, directorio y PostgreSQL aceptan contraseñas sin cifrar | Funcionalidad | 4 | 5 | 20 | R1 | 60 | Pendiente |
| L97 | Paneles de administración y páginas de estado de terceros en su dirección habitual | Funcionalidad | 4 | 5 | 20 | R1 | 61 | Pendiente |
| L99 | El certificado del correo y de otros servicios que cifran a mitad de conexión no se revisa | Funcionalidad | 5 | 4 | 20 | R1 | 62 | Pendiente |
| L87 | Las cabeceras repetidas se pierden | Bug | 4 | 4 | 16 | R1 | 63 | **Hecho** |
| L88 | Falso positivo del acceso anónimo a LDAP | Bug | 4 | 4 | 16 | R1 | 64 | **Hecho** |
| L96 | La administración remota de Windows acepta contraseñas en claro | Funcionalidad | 4 | 4 | 16 | R1 | 65 | Pendiente |
| L89 | TLS antiguo y cifrados débiles indetectables | Bug | 5 | 3 | 15 | R1 | 66 | **Hecho** |
| L90 | SQL Server sin cifrado de conexión | Funcionalidad | 3 | 5 | 15 | R1 | 67 | Pendiente |
| L93 | Propiedades del certificado: clave corta, firma antigua, caducidad próxima… | Funcionalidad | 3 | 5 | 15 | R1 | 68 | Pendiente |
| L100 | Dominio de Windows en un nivel de compatibilidad antiguo, o directorio sin vía cifrada | Funcionalidad | 3 | 4 | 12 | R2 | 69 | Pendiente |
| L92 | Lo que el equipo cuenta de sí mismo sin credenciales: nombre, dominio, instancias… (avisos informativos) | Mejora | 2 | 5 | 10 | R1 | 70 | Pendiente |
| L98 | Páginas de error por defecto y trazas internas visibles | Funcionalidad | 2 | 5 | 10 | R1 | 71 | Pendiente |

### Fase 9 — El catálogo nuevo (17 necesidades · prioridad acumulada 195)

| Id | Necesidad | Categoría | I | F | I×F | R | Orden | Depende de |
|---|---|---|---|---|---|---|---|---|
| L106 | Web que deja a cualquier otra web leer sus respuestas con la sesión del usuario | Funcionalidad | 4 | 5 | 20 | R2 | 72 | L87, L103 |
| L112 | Servicios de monitorización y DevOps abiertos sin credenciales | Funcionalidad | 4 | 4 | 16 | R2 | 73 | — |
| L104 | Lector del saludo TLS en crudo | Arquitectura | 5 | 3 | 15 | R2 | 74 | — |
| L109 | Versiones TLS aceptadas, cadena de certificados incompleta, intercambio de claves débil | Funcionalidad | 5 | 3 | 15 | R2 | 75 | L104 |
| L101 | El rastreador de la web no alimenta a las comprobaciones | Arquitectura | 4 | 3 | 12 | R2 | 76 | — |
| L107 | Mapas de código fuente publicados | Funcionalidad | 3 | 4 | 12 | R2 | 77 | L103 |
| L108 | Aprovechar lo que descubre el rastreador: copias olvidadas, carpetas listables, login sin HTTPS | Funcionalidad | 4 | 3 | 12 | R2 | 78 | L101, L102 |
| L113 | Servicios de datos con protocolo propio abiertos sin credenciales | Funcionalidad | 4 | 3 | 12 | R2 | 79 | — |
| L114 | Software fuera de soporte del fabricante | Mejora | 4 | 3 | 12 | R2 | 80 | — |
| L105 | Cliente mínimo de las llamadas remotas de Windows | Arquitectura | 5 | 2 | 10 | R3 | 81 | — |
| L110 | Carpetas compartidas visibles sin usuario | Funcionalidad | 5 | 2 | 10 | R3 | 82 | L105 |
| L102 | Respuesta de referencia para reconocer webs que contestan «200» a todo | Arquitectura | 3 | 3 | 9 | R2 | 83 | — |
| L103 | Piezas que le faltan al lenguaje de comprobaciones | Arquitectura | 3 | 3 | 9 | R2 | 84 | — |
| L115 | SSH: comprobaciones que no se leen en el primer mensaje | Funcionalidad | 3 | 3 | 9 | R2 | 85 | — |
| L111 | Servicios de impresión y de llamadas remotas expuestos en un controlador de dominio | Funcionalidad | 4 | 2 | 8 | R3 | 86 | L105 |
| L117 | Comprobaciones que solo corren en modo agresivo y con autorización expresa | Funcionalidad | 4 | 2 | 8 | R3 | 87 | — |
| L116 | Higiene web de menor peso | Mejora | 2 | 3 | 6 | R2 | 88 | — |

Orden interno recomendado: en la Fase 8, lo pendiente por prioridad. En la Fase 9, primero la
maquinaria (L101–L105), porque desbloquea a las demás.

---

## 5. Cómo seguir

### 5.1 Cómo se trabaja cada necesidad

- Una rama por issue, sacada de `v0.5`, con el nombre `<tipo>/themis/<descripción>`
  (p. ej. `fix/themis/lybra-repeated-headers`), cada una en su propio working tree.
- PR hacia `v0.5`. Se mergea si no hay conflictos, sin esperar a la CI.
- Como `v0.5` no es la rama por defecto, GitHub no cierra los issues al mergear: se cierran a
  mano, con un comentario que cite el PR.
- El trabajo se delega en subagentes, según `API/CLAUDE.md`: Haiku para tareas muy cortas,
  Sonnet para las medianas y Opus para las largas o delicadas.

### 5.2 El filtro de seguridad, y cómo no tropezar con él

Durante la sesión, el filtro de contenido del servicio cortó varias respuestas. Revisa lo que se
genera, lo escriba el asistente principal o un subagente. No es una configuración del usuario,
ni de la red, ni de la visibilidad del repositorio, y no se puede desactivar.

| Qué se estaba generando | Resultado |
|---|---|
| Leer el feed con las peticiones exactas de los confirmadores | Cortado |
| Lanzar a los especialistas con la lista de debilidades a buscar | Cortado, aunque los agentes llegaron a arrancar |
| Informes individuales de cada especialista | Pasaron |
| Redactar de golpe los 31 issues a partir de esos informes | Cortado; no se creó nada |
| Issues y código de las correcciones de comprobaciones existentes | Pasaron |

Cuando corta, indica que no se vuelva a producir ese contenido, ni reformulado, así que no se
reintenta lo mismo con otras palabras. Pero el corte no es un veto general: las correcciones y los
informes individuales pasaron. Plan para crear lo pendiente:

1. **De uno en uno**, nunca en bloque.
2. **Empezar por lo de menor riesgo:** primero la maquinaria (L101–L105), después los datos que
   ya se leen (L90–L100) y por último las comprobaciones nuevas.
3. **Describir cada detección por la condición que se observa** («el servidor no anuncia
   cifrado»), nunca con peticiones, cadenas de protocolo ni rutas concretas.
4. **Si el filtro corta un issue, se para ahí** y no se reintenta. Ese texto lo redacta el
   usuario, y un agente se ocupa solo de lo mecánico: etiquetas, enlace al padre y campos.

---

## 6. Detalle técnico

**Identificadores del proyecto** (para `gh project item-edit`):

- Proyecto: `PVT_kwDOEb4C_M4Bh5QX`
- Campo Fase: `PVTSSF_lADOEb4C_M4Bh5QXzhgzQU4`. Opciones: Fase 8 = `caa06d46`, Fase 9 = `7d6ae68e`.
- Status: Todo = `f75ad846`
- Categoría: Bug `f273b4fb` · Mejora `74bbee48` · Funcionalidad `6683c00b` · Arquitectura `5c97a9c9`
- Realismo: R1 `5ccc9abf` · R2 `f0692012` · R3 `0c2e4240`
- Numéricos: Impacto `PVTF_lADOEb4C_M4Bh5QXzhgzQW0` · Facilidad `PVTF_lADOEb4C_M4Bh5QXzhgzQW4` ·
  Prioridad `PVTF_lADOEb4C_M4Bh5QXzhgzQXQ` · Orden `PVTF_lADOEb4C_M4Bh5QXzhgzQXU`

**Añadir opciones al campo Fase sin perder datos.** La mutación GraphQL `updateProjectV2Field`
sustituye la lista entera de opciones. Hay que reenviar cada opción existente **con su `id`**; si
no, se recrean y todos los elementos pierden su fase. Antes, conviene guardar la fase de cada
elemento y comparar después.

**Enlazar un sub-issue:**
`gh api -X POST repos/ProjectEllysia/EllysiaServer/issues/<padre>/sub_issues -F sub_issue_id=<id>`.
El valor es el `id` numérico interno de la issue hija, no su número.

**Dónde vive el motor:** `API/src/modules/features/themis/lybra/`. En `checks.py` están el
motor de comprobaciones y su validación; en `script_checks.py`, las comprobaciones escritas en
Python; en `feeds/checks_feed.yaml`, el catálogo declarativo; en `fingerprinting/`, las sondas que
identifican cada servicio (donde están los datos que hoy se tiran); y en `crawler.py`, el
rastreador web. Arreglar una comprobación existente sube su propio `version`; añadir una familia
nueva sube `CHECKS_FEED_VERSION` (ver el comentario junto a esa constante).

**Informes del consejo:** se guardaron en la carpeta temporal de la sesión, que no persiste.
Este documento recoge lo que se decidió a partir de ellos.
