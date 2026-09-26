/**
 * Guardas del mecanismo de idiomas sobre el código del SPA.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`. Lee los
 * ficheros de `src/` como texto; no los ejecuta.
 *
 * Dos reglas de `CONVENCIONES.md` § 12.5 que, sin nada que las compruebe, se
 * degradan en cuanto alguien copia un trozo de código viejo:
 *   - fechas, números y orden alfabético no llevan el idioma escrito a mano
 *     ni usan el del navegador: pasan por `src/i18n/format.js`;
 *   - un componente no tiene texto escrito en su plantilla, salvo los que
 *     aún esperan su migración en `PENDING_FILES`.
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

/**
 * Ficheros que todavía llevan texto escrito en su plantilla. Todo `.vue` que
 * no esté aquí tiene que sacar sus textos del diccionario; al migrar uno, se
 * quita de la lista. Un componente nuevo nace vigilado.
 */
const PENDING_FILES = [
  'components/acheron/ChangePasswordModal.vue',
  'components/acheron/StorableFormModal.vue',
  'components/aegis/CampaignModal.vue',
  'components/aegis/DistributionListsModal.vue',
  'components/aegis/DocumentEditor.vue',
  'components/aegis/DocumentViewer.vue',
  'components/aegis/HistoryPanel.vue',
  'components/aegis/OrgProfilePanel.vue',
  'components/aegis/TopicGrid.vue',
  'components/aegis/TrackedProductsModal.vue',
  'components/aegis/TweaksForm.vue',
  'components/config/ModelPicker.vue',
  'components/config/ScannerCard.vue',
  'components/hygeia/AgentKeyModal.vue',
  'components/hygeia/AssetDetail.vue',
  'components/hygeia/AssetList.vue',
  'components/hygeia/AssetPicker.vue',
  'components/hygeia/AssetTabs.vue',
  'components/hygeia/AssetTagsModal.vue',
  'components/hygeia/CreateAssetModal.vue',
  'components/hygeia/InventoryAnalysisModal.vue',
  'components/hygeia/InventoryReportModal.vue',
  'components/hygeia/MetricNav.vue',
  'components/hygeia/MetricsChart.vue',
  'components/iris/IrisAddToCase.vue',
  'components/iris/IrisArchiveModal.vue',
  'components/iris/IrisBatchPanel.vue',
  'components/iris/IrisCompareModal.vue',
  'components/iris/IrisDocumentsModal.vue',
  'components/iris/IrisEmailPath.vue',
  'components/iris/IrisForm.vue',
  'components/iris/IrisHistoryStrip.vue',
  'components/iris/IrisIocsPanel.vue',
  'components/iris/IrisReportViewer.vue',
  'components/iris/IrisRuleCard.vue',
  'components/iris/IrisTrustForm.vue',
  'components/iris/IrisVerdictHero.vue',
  'components/iris/MailboxConnectionList.vue',
  'views/acheron/AcheronHubView.vue',
  'views/acheron/AcheronView.vue',
  'views/aegis/AegisCampaignsView.vue',
  'views/aegis/AegisHubView.vue',
  'views/aegis/AegisView.vue',
  'views/aegis/QuizView.vue',
  'views/hygeia/HygeiaDocumentsView.vue',
  'views/hygeia/HygeiaHubView.vue',
  'views/hygeia/HygeiaStatsView.vue',
  'views/hygeia/HygeiaTagsView.vue',
  'views/hygeia/HygeiaView.vue',
  'views/iris/IrisCasesView.vue',
  'views/iris/IrisConnectionsView.vue',
  'views/iris/IrisHubView.vue',
  'views/iris/IrisReplayView.vue',
  'views/iris/IrisTrustView.vue',
  'views/iris/IrisView.vue',
  'views/system/ConfigView.vue',
  'views/system/LogsView.vue',
  'views/system/QueueView.vue',
]

/**
 * Palabras que se escriben igual en todos los idiomas y pueden quedar en una
 * plantilla migrada: nombres propios del producto y su dominio. Las siglas
 * tampoco cuentan (ver `findHandwrittenText`).
 */
const LANGUAGE_NEUTRAL_WORDS = new Set(['Ellysia', 'Themis', 'Aegis', 'Iris', 'Acheron', 'Hygeia', 'Lybra', 'GitHub', 'ProjectEllysia', 'Nmap', 'Nikto', 'Nuclei', 'Cron', 'ellysia', 'es', 'v', 'ms'])

/** Una etiqueta HTML entera, aunque sus atributos lleven `>` entre comillas. */
const TAG_RE = /<(?:[^>"']|"[^"]*"|'[^']*')*>/g

/**
 * Llamadas que formatean con un idioma fijo o con el del navegador.
 *
 * - `toLocaleDateString('es-ES')`, `Intl.Collator('es')`,
 *   `localeCompare(x, 'es')`: idioma escrito a mano.
 * - `toLocaleString()` sin argumentos: idioma del navegador, que no tiene por
 *   qué ser el de la interfaz.
 */
const HARDCODED_LOCALE_PATTERNS = [
  /\.toLocale(?:Date|Time)?String\(\s*['"`]/,
  /\.toLocale(?:Date|Time)?String\(\s*\)/,
  /new\s+Intl\.\w+\(\s*['"`]/,
  /\.localeCompare\([^)]*,\s*['"`][a-z]{2}/,
]

/**
 * Recorre `src/` y devuelve las rutas de los ficheros `.js` y `.vue`.
 *
 * @param {string} directory - Directorio desde el que empezar.
 * @returns {string[]} Rutas absolutas.
 */
function listSourceFiles(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name)
    if (statSync(path).isDirectory()) return listSourceFiles(path)
    return /\.(js|vue)$/.test(name) ? [path] : []
  })
}

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('i18n/guard')

test('ningún formato de fecha, número u orden lleva el idioma fijo', () => {
  const offenders = []
  for (const path of listSourceFiles(sourceRoot)) {
    const relativePath = relative(sourceRoot, path).replaceAll('\\', '/')
    if (relativePath.startsWith('i18n/')) continue
    readFileSync(path, 'utf-8').split('\n').forEach((line, index) => {
      if (HARDCODED_LOCALE_PATTERNS.some((pattern) => pattern.test(line))) {
        offenders.push(`${relativePath}:${index + 1}: ${line.trim()}`)
      }
    })
  }
  assert.deepEqual(offenders, [], 'usa formatDate/formatDateTime/formatNumber/getCollator de src/i18n/format.js')
})

/**
 * Devuelve las palabras escritas a mano que quedan en la plantilla de un `.vue`.
 *
 * Quita comentarios, interpolaciones `{{ }}`, iconos SVG, etiquetas y entidades
 * HTML; lo que queda con letras es texto que el usuario lee y que no sale del
 * diccionario. Los nombres propios de `LANGUAGE_NEUTRAL_WORDS` no cuentan.
 *
 * @param {string} source - Contenido completo del fichero `.vue`.
 * @returns {string[]} Palabras sin repetir, más los atributos de texto
 *   (`title`, `aria-label`, `placeholder`, `alt`) escritos con un literal.
 */
function findHandwrittenText(source) {
  const template = source.match(/<template>([\s\S]*)<\/template>/)?.[1] ?? ''
  const withoutMarkup = template
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/\{\{[\s\S]*?\}\}/g, ' ')
    .replace(/<svg[\s\S]*?<\/svg>/g, ' ')
    .replace(TAG_RE, ' ')
    .replace(/&\w+;/g, ' ')
  // Las siglas (NVD, MFA, PDF) se escriben igual en todos los idiomas.
  const words = (withoutMarkup.match(/\p{L}[\p{L}'’-]*/gu) ?? [])
    .filter((word) => !LANGUAGE_NEUTRAL_WORDS.has(word) && word !== word.toUpperCase())
  const literalAttributes = [...template.matchAll(/\s(title|aria-label|placeholder|alt)="([^"]*\p{L}[^"]*)"/gu)]
    .map((match) => `${match[1]}="${match[2]}"`)
  return [...new Set(words), ...literalAttributes]
}

const componentFiles = listSourceFiles(sourceRoot)
  .filter((path) => path.endsWith('.vue'))
  .map((path) => relative(sourceRoot, path).replaceAll('\\', '/'))

test('ningún componente fuera de PENDING_FILES tiene texto escrito en su plantilla', () => {
  const offenders = componentFiles
    .filter((relativePath) => !PENDING_FILES.includes(relativePath))
    .map((relativePath) => [relativePath, findHandwrittenText(readFileSync(join(sourceRoot, relativePath), 'utf-8'))])
    .filter(([, handwritten]) => handwritten.length)
    .map(([relativePath, handwritten]) => `${relativePath}: ${handwritten.join(', ')}`)
  assert.deepEqual(offenders, [], 'los textos de un componente van en locales/es.json y se piden con t()')
})

test('PENDING_FILES solo lista componentes que existen y aún tienen texto escrito', () => {
  // Un fichero ya migrado que sigue en la lista dejaría de estar vigilado.
  const stale = PENDING_FILES.filter((relativePath) => !componentFiles.includes(relativePath)
    || findHandwrittenText(readFileSync(join(sourceRoot, relativePath), 'utf-8')).length === 0)
  assert.deepEqual(stale, [], 'quita de PENDING_FILES los ficheros ya migrados o borrados')
})

test('la guarda de texto detecta una plantilla sin migrar', () => {
  // Protege a la propia guarda: una plantilla con texto tiene que dar positivo,
  // y una que lo pide todo al diccionario, negativo.
  const handwritten = '<template><p title="Ayuda">Hola, {{ name }}</p></template>'
  const translated = `<template><p :title="t('help')">{{ t('greeting', { name }) }}</p></template>`
  assert.deepEqual(findHandwrittenText(handwritten), ['Hola', 'title="Ayuda"'])
  assert.deepEqual(findHandwrittenText(translated), [])
})

test('la guarda de formato detecta un idioma escrito a mano', () => {
  const samples = ["d.toLocaleDateString('es-ES')", 'n.toLocaleString()', "new Intl.Collator('es')", "a.localeCompare(b, 'es')"]
  const undetected = samples.filter((line) => !HARDCODED_LOCALE_PATTERNS.some((pattern) => pattern.test(line)))
  assert.deepEqual(undetected, [])
})

if (failures) { console.error(`\n${failures} test(s) fallaron`); process.exit(1) }
