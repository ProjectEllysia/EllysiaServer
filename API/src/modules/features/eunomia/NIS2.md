# NIS2 — material de partida para el catálogo de Eunomia

Este documento reúne lo que se sabe de NIS2 para construir su catálogo en Eunomia, para no tener
que volver a buscar las fuentes. Recoge qué dice la norma, de dónde sale cada dato, qué se puede
reproducir y qué falta por hacer.

**Esto todavía no es el catálogo.** El formato definitivo de un marco (un fichero inmutable por
versión, con descripción, actuaciones y evidencias por requisito) es el que fije EUN09. Lo que hay
aquí es la materia prima con la que se construye. Por eso este directorio todavía no es un paquete
Python: no tiene `__init__.py`, ningún import lo encuentra y no lo comprueba ningún test. El paquete
`eunomia` lo crea EUN01.

| Fichero | Qué contiene |
|---|---|
| `catalog/nis2/fuentes/directiva-2022-2555.es.txt` | Texto oficial en castellano de la Directiva: artículos 1 a 3, 20 a 23 y anexos I y II. |
| `catalog/nis2/fuentes/reglamento-ejecucion-2024-2690.es.txt` | Texto oficial en castellano del Reglamento de Ejecución: artículos 1 a 16 y anexo completo. |
| `catalog/nis2/borrador/nis2-estructura.json` | Lo mismo, estructurado. Recoge los artículos 3, 20, 21 y 23 (con los plazos de notificación), los sectores de los anexos I y II, y el anexo del Reglamento en 13 secciones, 47 subsecciones y 159 puntos con su texto literal y la letra del art. 21.2 a la que sirve cada sección. |

Todo se extrajo el **2026-10-10** del HTML de EUR-Lex en castellano.

---

## Fuentes y qué se puede reproducir

| Fuente | Identificador | ¿Se puede reproducir el texto? |
|---|---|---|
| Directiva (UE) 2022/2555 (NIS2), DO L 333 de 27.12.2022 | CELEX 32022L2555 | Sí. Es legislación de la UE: su reutilización está permitida citando la fuente (Decisión 2011/833/UE). |
| Reglamento de Ejecución (UE) 2024/2690 de la Comisión, de 17.10.2024 | CELEX 32024R2690 | Sí, en las mismas condiciones. |
| ENISA, *NIS2 Technical Implementation Guidance*, 26 de junio de 2025 | [Página de ENISA](https://www.enisa.europa.eu/publications/NIS2-technical-implementation-guidance) | **Sin licencia concreta (comprobado el 2026-10-10).** El aviso legal de ENISA autoriza reproducir «siempre que se cite la fuente, salvo que se indique otra cosa» y no nombra ninguna licencia abierta; cada publicación puede traer restricciones propias. Se usa como referencia y se escribe con redacción propia (`licenseMode: own_wording`). |

Sobre la guía de ENISA:

- Acompaña cada requisito del Reglamento 2024/2690 con **ejemplos de evidencias**. Es la fuente
  natural para el campo `evidence` de cada requisito (EUN11).
- Como material adicional publica una **tabla de correspondencias** (versión 1.2 según la página de
  ENISA). La versión en borrador relacionaba cada requisito con ISO/IEC 27001:2022, ISO/IEC
  27002:2022, NIST CSF 2.0, ETSI EN 319 401, CEN/TS 18026 y varios marcos nacionales. No se ha
  comprobado si la versión final mantiene esa lista. Es la base de las correspondencias entre
  marcos de EUN30.
- **No es vinculante.** Va dirigida sobre todo a las autoridades nacionales.
- **Todavía no se ha descargado ni procesado.** Es el siguiente paso para EUN11.

---

## Qué es cada texto

**La Directiva** dice *qué* tiene que hacer una entidad, de forma general:

- el **art. 20** trata la gobernanza;
- el **art. 21** fija las medidas de gestión de riesgos, en diez letras;
- el **art. 23** regula la notificación de incidentes.

La Directiva obliga a los Estados, no a las empresas: cada Estado la transpone con una ley propia
(ver más abajo el estado en España).

**El Reglamento de Ejecución 2024/2690** dice *cómo* hacerlo, con requisitos concretos para el
art. 21.2. Obliga directamente a los proveedores de DNS, los registros de dominios de primer nivel,
la nube, los centros de datos, las CDN, los servicios gestionados y de seguridad gestionada, los
mercados en línea, los motores de búsqueda, las redes sociales y los prestadores de servicios de
confianza (art. 1). Para cualquier otra entidad no es obligatorio, pero es la referencia más
detallada que existe, y por eso el catálogo de Eunomia desarrolla el art. 21.2 con él.

---

## Estructura

### Artículo 20 — Gobernanza

- Los órganos de dirección **aprueban** las medidas del art. 21, **supervisan** su aplicación y
  **responden** de su incumplimiento.
- Los miembros de los órganos de dirección **deben recibir formación**, y se anima a ofrecer
  formación similar a los empleados con regularidad.

### Artículo 21.2 — Medidas mínimas, y su desarrollo en el Reglamento 2024/2690

| Letra | Medida (texto de la Directiva, abreviado) | Secciones del anexo del Reglamento |
|---|---|---|
| a) | Políticas de seguridad de los sistemas de información y análisis de riesgos | 1. Política de seguridad de los sistemas de redes y de información (1.1, 1.2) · 2. Política de gestión de riesgos (2.1–2.3) |
| b) | Gestión de incidentes | 3. Gestión de incidentes (3.1–3.6) |
| c) | Continuidad de las actividades (copias de seguridad, recuperación en caso de catástrofe) y gestión de crisis | 4. Continuidad de las actividades y gestión de crisis (4.1–4.3) · también 13 |
| d) | Seguridad de la cadena de suministro | 5. Seguridad de las cadenas de suministro (5.1, 5.2) |
| e) | Seguridad en la adquisición, el desarrollo y el mantenimiento, incluida la gestión y divulgación de vulnerabilidades | 6. Adquisición, desarrollo y mantenimiento (6.1–6.10) · también 13 |
| f) | Políticas y procedimientos para evaluar la eficacia de las medidas | 7. Evaluación de la eficacia (puntos 7.1–7.3, sin subsecciones) |
| g) | Prácticas básicas de ciberhigiene y formación en ciberseguridad | 8. Formación y ciberhigiene (8.1, 8.2) |
| h) | Criptografía y, en su caso, cifrado | 9. Criptografía (puntos 9.1–9.3, sin subsecciones) |
| i) | Seguridad de los recursos humanos, control de acceso y gestión de activos | 10. Recursos humanos (10.1–10.4) · 11. Control de accesos (11.1–11.6) · 12. Gestión de activos (12.1–12.5) · también 13 |
| j) | Autenticación multifactor o continua, comunicaciones seguras y de emergencia | 11. Control de accesos, sobre todo 11.7 (autenticación de múltiples factores) |

Tres secciones del anexo sirven a más de una letra:

- la **11** sirve a i) y j);
- la **13** (seguridad medioambiental y física: 13.1 servicios públicos, 13.2 amenazas físicas y
  medioambientales, 13.3 control de acceso perimetral y físico) sirve a c), e) e i).

En el catálogo, cada una cuelga de su letra principal y se relaciona con las demás mediante
correspondencias (EUN10, EUN30). El campo `directiveLetters` del borrador recoge, para cada
sección, las letras que cita el propio Reglamento.

**Una cláusula que afecta a la evaluación** (Reglamento, art. 2.2): cuando el anexo dice «según
proceda», «cuando proceda» o «en la medida de lo posible» y la entidad considera que no procede,
tiene que **documentar el motivo**. Es exactamente el estado «no aplica con justificación
obligatoria» de EUN19.

### Artículo 23 — Notificación de incidentes significativos

Un incidente es **significativo** (art. 23.3) si ha causado o puede causar graves perturbaciones
operativas o pérdidas económicas a la entidad, o perjuicios considerables a terceros. Para las
entidades del Reglamento, sus artículos 3 a 14 concretan umbrales. El general (art. 3) es el
siguiente: pérdidas de más de 500 000 € o del 5 % de la facturación anual (lo que sea menor),
exfiltración de secretos comerciales, muerte o daño considerable a la salud de una persona, o
acceso malicioso efectivo capaz de causar perturbaciones graves.

| Paso | Plazo |
|---|---|
| a) Alerta temprana | 24 horas desde que se tiene constancia |
| b) Notificación del incidente, con evaluación inicial, gravedad, impacto e indicadores de compromiso | 72 horas desde que se tiene constancia (24 horas para los prestadores de servicios de confianza) |
| c) Informe intermedio | Cuando lo pida el CSIRT o la autoridad competente |
| d) Informe final: descripción, causa, medidas aplicadas y repercusión transfronteriza | Un mes después de la notificación b) |
| e) Si el incidente sigue en curso al llegar d) | Informe de situación en ese momento, e informe final un mes después de gestionarlo |

Estos plazos son el contenido del procedimiento de notificación (plantilla de EUN32) y del
registro de incidentes (EUN44).

### Artículo 3 y anexos I y II — A quién se aplica

- **Entidades esenciales** (art. 3.1): sobre todo las de los sectores del **anexo I** que superan
  el tamaño de mediana empresa de la Recomendación 2003/361/CE. Algunos tipos lo son sea cual sea
  su tamaño: prestadores cualificados de servicios de confianza, registros de dominios de primer
  nivel y proveedores de DNS.
- **Entidades importantes** (art. 3.2): el resto de entidades de los anexos I o II incluidas en el
  ámbito de aplicación.
- **Anexo I** («sectores de alta criticidad»): 11 sectores, entre ellos energía, transporte,
  banca, infraestructuras de los mercados financieros, sanidad, agua potable, aguas residuales,
  infraestructura digital, gestión de servicios TIC (entre empresas), Administración pública y
  espacio.
- **Anexo II** («otros sectores críticos»): 7 sectores. Son servicios postales y de mensajería,
  gestión de residuos, sustancias y mezclas químicas, alimentos, fabricación, proveedores de
  servicios digitales e investigación.
- El borrador JSON recoge cada sector con sus subsectores y tipos de entidad, literales. Es la
  materia prima de la herramienta «¿Me aplica NIS2?» (EUN41).

---

## Transposición en España

Lo siguiente sale de fuentes **no oficiales** consultadas el 2026-10-10. Hay que verificarlo en el
BOE antes de abordar EUN42.

- La Ley de Coordinación y Gobernanza de la Ciberseguridad (la transposición) se aprobó como
  anteproyecto en el Consejo de Ministros el 14 de enero de 2025. Según esas fuentes, **no se ha
  publicado en el BOE**.
- España no cumplió el plazo de transposición (17 de octubre de 2024), y la Comisión Europea la
  llevó ante el Tribunal de Justicia de la UE en julio de 2026.
- Mientras tanto sigue vigente el régimen de NIS1: el Real Decreto-ley 12/2018 y el Real Decreto
  43/2021.

---

## Relación con lo que ya existe

`themis/lybra/feeds/compliance_mappings.json` tiene hoy seis entradas de NIS2 que usan los mapeos
de hallazgos de Lybra: `21.2`, `21.2.c`, `21.2.e`, `21.2.h`, `21.2.i` y `21.2.j`. El catálogo
publicado debe **conservar esos identificadores** (EUN10, EUN12). El borrador los recoge en
`lybraIdentifiers`.

## Qué hay hecho y qué falta

**Hecho.** El catálogo vive en `catalog/nis2/2022-2555.json` (versión `draft`): los artículos 20,
21 y 23 y los 13 apartados del anexo, con el texto oficial (`officialText`), el artículo o punto
de origen de cada nodo y, para cada requisito evaluable, descripción llana, actuaciones y
evidencias con redacción propia. El anexo cuelga de la letra del art. 21.2 que desarrolla; el
apartado 11.7 (autenticación multifactor) cuelga de la letra j) y el resto del 11 de la i). Las
secciones 7 y 9 no tienen subapartados y son requisito por sí mismas. La licencia de la guía de
ENISA está comprobada: ver la tabla de fuentes.

**Falta.**

1. **Revisión por auditoría.** La versión se publicó (`published`, con su línea en
   `catalog/LOCK.json`) sin la revisión de alguien con experiencia en auditoría. Una versión
   publicada no se modifica: cualquier corrección de las descripciones, actuaciones o evidencias
   sale como una versión nueva con su correspondencia con esta.
2. **Correspondencias** del anexo con ISO 27001, el ENS y NIST CSF (la guía de ENISA trae una
   tabla; hay que leer su aviso antes de copiarla).
3. **Aplicabilidad.** Convertir los anexos I y II y el art. 3 en reglas (qué entidades están
   dentro y cuáles de ellas, en el ámbito obligatorio del reglamento de ejecución).
