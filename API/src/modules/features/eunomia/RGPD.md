# RGPD — material de partida para Eunomia

Este documento es el equivalente de `NIS2.md` para el Reglamento General de Protección de Datos.
Recoge lo comprobado sobre el RGPD para su catálogo (EUN46), sus plantillas (EUN47) y sus
registros (Fase 8), para no tener que volver a buscar las fuentes. Igual que en NIS2, **esto no es
todavía el catálogo**: el formato lo fija EUN09.

| Fichero | Qué contiene |
|---|---|
| `catalog/rgpd/fuentes/reglamento-2016-679.es.txt` | Texto oficial en castellano del RGPD: la parte dispositiva completa, artículos 1 a 99. |

Se extrajo el **2026-10-10** de EUR-Lex (CELEX 32016R0679, DO L 119 de 4.5.2016). Es legislación
de la UE, así que se puede reutilizar citando la fuente (Decisión 2011/833/UE).

**El catálogo del RGPD ya está en `catalog/rgpd/2016-679.json`** (borrador): los capítulos II, III y IV, con el texto oficial, y sus correspondencias con NIS2 y el ENS en `catalog/crosswalks/`. **Todavía no se ha descargado la LOPDGDD** (Ley Orgánica 3/2018), que completa al RGPD en España.
Está en el BOE y también se puede reutilizar. **Tampoco se ha comprobado la licencia de las guías de
la AEPD** (EUN13).

## Por qué el RGPD entra en dos mitades

1. **Como marco del catálogo (EUN46).** El RGPD se basa en demostrar el cumplimiento
   (responsabilidad proactiva, arts. 5.2 y 24), que es justo lo que hace Eunomia: obligaciones,
   evaluación y evidencias.
2. **Como registros (Fase 8).** Lo que más pide una inspección no son controles sino registros de
   muchas fichas: el de actividades de tratamiento, el de violaciones de seguridad y el de
   solicitudes de derechos. Eso necesita el mecanismo de EUN48.

## Artículos que estructuran el catálogo

Títulos comprobados en el texto oficial:

| Artículo | Título | Uso en Eunomia |
|---|---|---|
| 5 | Principios relativos al tratamiento | Requisitos. El 5.2 (responsabilidad proactiva) es el fundamento del módulo. |
| 6 | Licitud del tratamiento | Requisito; la base jurídica se anota en cada ficha del registro de actividades. |
| 7 | Condiciones para el consentimiento | Requisito. |
| 9 | Tratamiento de categorías especiales de datos personales | Requisito; quita la exención del art. 30.5. |
| 12 | Transparencia de la información, comunicación y modalidades de ejercicio de los derechos del interesado | El 12.3 fija el plazo de respuesta (registro de solicitudes, EUN50). |
| 13 y 14 | Información que se facilita al interesado (datos obtenidos de él o de otra fuente) | Plantillas de cláusula informativa (EUN47). |
| 15–22 | Derechos del interesado (acceso, supresión, oposición…) | Requisitos; registro de solicitudes (EUN50). |
| 24 | Responsabilidad del responsable del tratamiento | Requisito. |
| 25 | Protección de datos desde el diseño y por defecto | Requisito. |
| 28 | Encargado del tratamiento | El 28.3 fija el contenido mínimo del contrato (plantilla de EUN47). |
| 30 | Registro de las actividades de tratamiento | Registro de EUN49. |
| 32 | Seguridad del tratamiento | Requisito; es el punto de más solapamiento con NIS2 21.2 y con el ENS (correspondencias de EUN30). |
| 33 | Notificación de una violación de la seguridad de los datos personales a la autoridad de control | Registro único de incidentes y brechas (EUN44). |
| 34 | Comunicación de una violación de la seguridad de los datos personales al interesado | Ídem. |
| 35 | Evaluación de impacto relativa a la protección de datos | EUN51 (largo plazo). |
| 37–39 | Delegado de protección de datos (designación, posición, funciones) | Requisitos. |

## Datos concretos comprobados

- **Art. 12.3.** Respuesta a una solicitud de derechos en el plazo de un mes desde la recepción,
  que «podrá prorrogarse otros dos meses en caso necesario, teniendo en cuenta la complejidad y el
  número de solicitudes».
- **Art. 30.5.** El registro de actividades no es obligatorio para quien emplee a menos de 250
  personas, salvo si el tratamiento puede entrañar un riesgo, no es ocasional o incluye categorías
  especiales (art. 9.1) o datos penales (art. 10). En la práctica casi ninguna empresa queda
  exenta: las nóminas no son un tratamiento ocasional.
- **Art. 33.1.** Notificación a la autoridad de control «a más tardar 72 horas después de que haya
  tenido constancia», salvo que sea improbable que la violación constituya un riesgo.
- **Art. 33.5.** El responsable documenta **cualquier** violación de seguridad, se notifique o no,
  con los hechos, sus efectos y las medidas correctivas.

## Coincidencia con NIS2

Un mismo incidente puede ser **significativo** según NIS2 (art. 23: alerta en 24 horas,
notificación en 72 horas, informe final al mes) y **violación de seguridad** según el RGPD
(art. 33: notificación en 72 horas; art. 34: comunicación a los afectados si el riesgo es alto).
Los plazos de los dos corren desde que se tiene constancia del incidente. Por eso Eunomia los lleva
en un único registro (EUN44), que calcula los plazos de cada marco al que afecte el incidente.
