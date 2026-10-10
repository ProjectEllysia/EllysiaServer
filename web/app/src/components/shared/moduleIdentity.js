/**
 * Lo que identifica a cada módulo de Ellysia y no cambia con el idioma: su orden, su
 * nombre, su lema latino y las capacidades que presenta su hub. Es JavaScript puro
 * (sin imágenes ni Vue) para poder probarlo con `node`; las imágenes están en
 * `moduleIcons.js`.
 *
 * Lo comparten el hub (`ModuleHub`) y las páginas de herramientas gratuitas
 * (`ToolShell`), para que ambos presenten al módulo igual.
 */

/** Módulos, en el orden del panteón. */
export const MODULE_IDS = Object.freeze(['themis', 'aegis', 'iris', 'acheron', 'hygeia', 'eunomia'])

/**
 * Identidad de cada módulo.
 *
 * - `numeral` — número romano del panteón.
 * - `name` — nombre del módulo.
 * - `epigraph` — lema latino que rotula su hub.
 * - `route` — ruta de su hub.
 */
export const MODULE_IDENTITY = Object.freeze({
  themis: Object.freeze({ numeral: 'I', name: 'Themis', epigraph: 'Iudicium', route: '/themis' }),
  aegis: Object.freeze({ numeral: 'II', name: 'Aegis', epigraph: 'Praesidio', route: '/aegis' }),
  iris: Object.freeze({ numeral: 'III', name: 'Iris', epigraph: 'Veritas', route: '/iris' }),
  acheron: Object.freeze({ numeral: 'IV', name: 'Acheron', epigraph: 'Custodia', route: '/acheron' }),
  hygeia: Object.freeze({ numeral: 'V', name: 'Hygeia', epigraph: 'Salus', route: '/hygeia' }),
  eunomia: Object.freeze({ numeral: 'VI', name: 'Eunomia', epigraph: 'Ordo', route: '/eunomia' }),
})

/**
 * Claves del diccionario con los textos de presentación de cada módulo: `tagline`
 * (bajada de las capacidades), `myth` (frase mítica de la cabecera) y `claim` (el
 * lema, que es el titular). Las usa el hub y las páginas de herramientas gratuitas.
 */
export const HUB_COPY_KEYS = Object.freeze({
  themis: Object.freeze({ tagline: 'themisHub.tagline', myth: 'landing.tools.themis.myth', claim: 'landing.tools.themis.title' }),
  aegis: Object.freeze({ tagline: 'aegisHub.tagline', myth: 'landing.tools.aegis.myth', claim: 'landing.tools.aegis.title' }),
  iris: Object.freeze({ tagline: 'irisHub.tagline', myth: 'landing.tools.iris.myth', claim: 'landing.tools.iris.title' }),
  acheron: Object.freeze({ tagline: 'acheronHub.tagline', myth: 'acheronHub.myth', claim: 'acheronHub.claim' }),
  hygeia: Object.freeze({ tagline: 'hygeiaHub.tagline', myth: 'hygeiaHub.myth', claim: 'landing.tools.hygeia.title' }),
  eunomia: Object.freeze({ tagline: 'eunomiaHub.tagline', myth: 'eunomiaHub.myth', claim: 'landing.tools.eunomia.title' }),
})

/**
 * Capacidades que presenta el hub de cada módulo, en orden. Sus textos están en
 * `<módulo>Hub.features.<id>` (`kicker`, `title`, `desc`) del diccionario, y los usan
 * tanto el hub como el pie de las herramientas gratuitas.
 */
export const HUB_FEATURE_IDS = Object.freeze({
  themis: Object.freeze(['engine', 'classics', 'reports', 'schedule']),
  aegis: Object.freeze(['pills', 'quiz', 'campaigns', 'evidence']),
  iris: Object.freeze(['rules', 'quishing', 'iocs', 'verdict']),
  acheron: Object.freeze(['local', 'types', 'generator', 'lybra']),
  hygeia: Object.freeze(['push', 'alerts', 'down', 'email']),
  eunomia: Object.freeze(['frameworks', 'evidence', 'documents', 'registers']),
})
