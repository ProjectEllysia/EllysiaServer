/**
 * Tests de las herramientas gratuitas: el catálogo (`src/freeTools/catalog.js`),
 * lo que cuelga de él y la lógica del generador de contraseñas.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * Lo que se fija es que añadir una herramienta al catálogo es suficiente para
 * que aparezca en el hub de su módulo, y que un módulo sin herramientas no
 * enseña la sección. Y que no se puede añadir una entrada a medias: sin su
 * vista, sin sus textos en los dos idiomas o con una URL que el proxy mandaría
 * a la API, falla aquí y no en producción.
 */

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { generatePassword } from '@projectellysia/acheron-core-js'
import {
  FREE_TOOLS,
  FREE_TOOLS_PATH,
  FREE_TOOL_ACCESS,
  freeToolPath,
  freeToolSeoKey,
  freeToolViewFile,
  selectFreeTools,
} from '../src/freeTools/catalog.js'
import {
  CHARACTER_CLASSES,
  PASSWORD_LENGTH,
  characterKind,
  clampPasswordLength,
  isLastActiveClass,
  strengthLabelKey,
  toGeneratorOptions,
} from '../src/components/freeTools/passwordGenerator.js'
import {
  CVE_SEVERITIES,
  DISTRO_STATUSES,
  distroStatusLabelKey,
  epssPercent,
  hiddenCount,
  isCveId,
  normalizeCveId,
  severityLabelKey,
  severityLevel,
} from '../src/components/freeTools/cveLookup.js'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const read = (path) => readFileSync(appRoot + path, 'utf-8').replace(/\r\n/g, '\n')

let failures = 0
function test(name, fn) {
  try {
    fn()
    console.log(`  ✓ ${name}`)
  } catch (error) {
    failures += 1
    console.error(`  ✗ ${name}\n    ${error.message}`)
  }
}

const MODULES = ['themis', 'aegis', 'iris', 'acheron', 'hygeia', 'eunomia']
/** Prefijos que `web/Caddyfile` y el proxy de Vite mandan a Flask. */
const API_PREFIXES = ['themis', 'aegis', 'iris', 'acheron', 'hygeia', 'eunomia', 'oauth', 'users', 'plans', 'organizations', 'system']

const locales = {
  es: JSON.parse(read('src/i18n/locales/es.json')),
  en: JSON.parse(read('src/i18n/locales/en.json')),
}

console.log('catálogo')

test('hay al menos una herramienta y todas tienen la forma esperada', () => {
  assert.ok(FREE_TOOLS.length > 0)
  for (const tool of FREE_TOOLS) {
    assert.match(tool.id, /^[a-z][A-Za-z0-9]*$/, `id de ${tool.id}`)
    assert.ok(MODULES.includes(tool.module), `módulo desconocido en ${tool.id}: ${tool.module}`)
    assert.match(tool.slug, /^[a-z0-9]+(-[a-z0-9]+)*$/, `slug de ${tool.id}`)
    assert.ok(FREE_TOOL_ACCESS.includes(tool.access), `acceso de ${tool.id}: ${tool.access}`)
    if (tool.surface !== undefined) assert.equal(typeof tool.surface, 'string', `surface de ${tool.id}`)
  }
})

test('los id y las rutas no se repiten', () => {
  const ids = FREE_TOOLS.map((tool) => tool.id)
  const paths = FREE_TOOLS.map(freeToolPath)
  assert.equal(new Set(ids).size, ids.length)
  assert.equal(new Set(paths).size, paths.length)
})

test('las rutas cuelgan de /herramientas, que ninguna regla de la API captura', () => {
  assert.ok(!API_PREFIXES.includes(FREE_TOOLS_PATH.slice(1)))
  for (const tool of FREE_TOOLS) assert.ok(freeToolPath(tool).startsWith(`${FREE_TOOLS_PATH}/`), freeToolPath(tool))
})

test('cada herramienta tiene su vista', () => {
  for (const tool of FREE_TOOLS) {
    assert.ok(existsSync(`${appRoot}src/views/tools/${freeToolViewFile(tool)}.vue`), `falta la vista de ${tool.id}`)
  }
})

for (const [code, dictionary] of Object.entries(locales)) {
  test(`${code}: cada herramienta tiene sus textos (tarjeta, página y buscadores)`, () => {
    for (const tool of FREE_TOOLS) {
      const item = dictionary.freeTools.items[tool.id]
      for (const key of ['title', 'desc', 'subtitle']) assert.ok(item?.[key], `falta freeTools.items.${tool.id}.${key}`)
      const seo = dictionary.seo.pages[freeToolSeoKey(tool)]
      assert.ok(seo?.title && seo?.description, `falta seo.pages.${freeToolSeoKey(tool)}`)
    }
  })
}

test('cada herramienta está en el sitemap', () => {
  const sitemap = read('public/sitemap.xml')
  for (const tool of FREE_TOOLS) assert.ok(sitemap.includes(`<loc>https://www.ellysia.es${freeToolPath(tool)}</loc>`), `falta ${freeToolPath(tool)}`)
})

test('el router genera las rutas desde el catálogo y el hub pinta la sección sin que los hubs declaren nada', () => {
  assert.match(read('src/router/index.js'), /\.\.\.freeToolRoutes/)
  assert.match(read('src/components/shared/ModuleHub.vue'), /<FreeTools :module-id="moduleId" \/>/)
  for (const module of MODULES) {
    const hub = read(`src/views/${module}/${module.charAt(0).toUpperCase()}${module.slice(1)}HubView.vue`)
    assert.ok(!/free-?tools/i.test(hub), `el hub de ${module} no debe nombrar las herramientas: las trae el catálogo`)
  }
})

console.log('selección')

const catalog = [
  { id: 'alpha', module: 'themis', slug: 'alfa', access: 'public' },
  { id: 'beta', module: 'themis', slug: 'beta', access: 'account', surface: 'betaSurface' },
  { id: 'gamma', module: 'aegis', slug: 'gamma', access: 'public' },
]

test('un módulo solo recibe las suyas, con su ruta', () => {
  const tools = selectFreeTools({ tools: catalog, moduleId: 'aegis' })
  assert.deepEqual(tools.map((tool) => tool.id), ['gamma'])
  assert.equal(tools[0].path, '/herramientas/aegis/gamma')
})

test('un módulo sin herramientas recibe una lista vacía: el hub no enseña la sección', () => {
  assert.deepEqual(selectFreeTools({ tools: catalog, moduleId: 'hygeia' }), [])
})

test('sin módulo se devuelven todas las abiertas, en el orden del catálogo', () => {
  assert.deepEqual(selectFreeTools({ tools: catalog }).map((tool) => tool.id), ['alpha', 'gamma'])
})

test('una herramienta con superficie cerrada se esconde y con la superficie abierta se enseña', () => {
  assert.deepEqual(selectFreeTools({ tools: catalog, moduleId: 'themis' }).map((tool) => tool.id), ['alpha'])
  const open = selectFreeTools({ tools: catalog, moduleId: 'themis', isSurfaceEnabled: (surface) => surface === 'betaSurface' })
  assert.deepEqual(open.map((tool) => tool.id), ['alpha', 'beta'])
})

test('si el servidor cierra la única superficie de un módulo, su sección desaparece', () => {
  const onlyGated = [{ id: 'solo', module: 'iris', slug: 'solo', access: 'public', surface: 'x' }]
  assert.deepEqual(selectFreeTools({ tools: onlyGated, moduleId: 'iris' }), [])
})

test('seleccionar no modifica el catálogo', () => {
  selectFreeTools({ tools: catalog, moduleId: 'themis' })
  assert.equal(catalog[0].path, undefined)
})

console.log('generador de contraseñas')

test('la longitud se lleva al rango y lo que no es un número, al valor inicial', () => {
  assert.equal(clampPasswordLength(3), PASSWORD_LENGTH.min)
  assert.equal(clampPasswordLength(500), PASSWORD_LENGTH.max)
  assert.equal(clampPasswordLength('24'), 24)
  assert.equal(clampPasswordLength(17.6), 18)
  assert.equal(clampPasswordLength(''), PASSWORD_LENGTH.min)
  assert.equal(clampPasswordLength(undefined), PASSWORD_LENGTH.initial)
  assert.equal(clampPasswordLength('abc'), PASSWORD_LENGTH.initial)
})

test('la última casilla activa no se puede desmarcar, y solo ella', () => {
  const onlyDigits = { uppercase: false, lowercase: false, digits: true, symbols: false }
  assert.equal(isLastActiveClass(onlyDigits, 'digits'), true)
  assert.equal(isLastActiveClass(onlyDigits, 'symbols'), false)
  assert.equal(isLastActiveClass({ ...onlyDigits, symbols: true }, 'digits'), false)
})

test('sin ningún tipo activo se activan las minúsculas para que haya alfabeto', () => {
  const options = toGeneratorOptions({ length: 12, uppercase: false, lowercase: false, digits: false, symbols: false, excludeAmbiguous: true })
  assert.equal(options.lowercase, true)
  assert.equal(options.uppercase, false)
})

test('las opciones que se pasan al generador salen del estado y respetan la longitud', () => {
  const options = toGeneratorOptions({ length: '400', uppercase: true, lowercase: true, digits: false, symbols: false, excludeAmbiguous: false })
  assert.deepEqual(options, { length: PASSWORD_LENGTH.max, uppercase: true, lowercase: true, digits: false, symbols: false, excludeAmbiguous: false })
})

test('el generador devuelve la longitud pedida y solo los tipos marcados', () => {
  for (const characterClass of CHARACTER_CLASSES) {
    const state = { length: 30, uppercase: false, lowercase: false, digits: false, symbols: false, excludeAmbiguous: true, [characterClass]: true }
    const password = generatePassword(toGeneratorOptions(state))
    assert.equal(password.length, 30)
    const expected = { uppercase: /^[A-Z]+$/, lowercase: /^[a-z]+$/, digits: /^\d+$/, symbols: /^[^A-Za-z0-9]+$/ }[characterClass]
    assert.match(password, expected, characterClass)
  }
})

test('con «evitar caracteres confusos» nunca salen 0, O, 1, l ni I', () => {
  const state = { length: 64, uppercase: true, lowercase: true, digits: true, symbols: false, excludeAmbiguous: true }
  for (let attempt = 0; attempt < 40; attempt += 1) assert.doesNotMatch(generatePassword(toGeneratorOptions(state)), /[0O1lI]/)
})

test('cada carácter se clasifica como letra, cifra o símbolo', () => {
  assert.deepEqual([...'aZ7!_'].map(characterKind), ['letter', 'letter', 'digit', 'symbol', 'symbol'])
})

test('la puntuación de solidez se lleva a una clave del diccionario existente', () => {
  for (const [code, dictionary] of Object.entries(locales)) {
    for (const score of [0, 1, 2, 3, 4]) {
      const key = strengthLabelKey(score).replace('freeTools.items.passwordGenerator.strength.', '')
      assert.ok(dictionary.freeTools.items.passwordGenerator.strength[key], `${code}: nivel ${score}`)
    }
  }
  assert.equal(strengthLabelKey(-3), 'freeTools.items.passwordGenerator.strength.0')
  assert.equal(strengthLabelKey(9), 'freeTools.items.passwordGenerator.strength.4')
  assert.equal(strengthLabelKey(undefined), 'freeTools.items.passwordGenerator.strength.0')
})

console.log('consulta de CVE')

test('el identificador se normaliza: sin espacios y en mayúsculas', () => {
  assert.equal(normalizeCveId('  cve-2024-6387 '), 'CVE-2024-6387')
  assert.equal(normalizeCveId('cve - 2024 - 6387'), 'CVE-2024-6387')
  assert.equal(normalizeCveId(undefined), '')
  assert.equal(normalizeCveId(42), '')
})

test('solo un identificador completo es válido, con el mismo formato que el servidor', () => {
  for (const valid of ['CVE-2024-6387', 'cve-2023-4863', 'CVE-2022-12345', 'CVE-2021-1234567']) assert.equal(isCveId(valid), true, valid)
  for (const invalid of ['', 'openssh', 'CVE-24-1', 'CVE-2024-123', 'CVE-2024-12345678', 'CVE-2024-6387 OR 1=1', 'CVE-2024-']) {
    assert.equal(isCveId(invalid), false, invalid)
  }
})

test('cada gravedad conocida tiene rótulo en los dos idiomas, y una desconocida cae en «sin puntuar»', () => {
  for (const [code, dictionary] of Object.entries(locales)) {
    const labels = dictionary.freeTools.items.cveLookup.severity
    for (const severity of [...CVE_SEVERITIES, 'unrated']) assert.ok(labels[severity], `${code}: ${severity}`)
  }
  assert.equal(severityLabelKey('CRITICAL'), 'freeTools.items.cveLookup.severity.critical')
  assert.equal(severityLabelKey('catastrophic'), 'freeTools.items.cveLookup.severity.unrated')
  assert.equal(severityLabelKey(null), 'freeTools.items.cveLookup.severity.unrated')
  assert.equal(severityLevel('High'), 'high')
  assert.equal(severityLevel(undefined), 'unrated')
})

test('cada estado de distribución tiene rótulo en los dos idiomas, y uno desconocido cae en «sin dato»', () => {
  for (const [code, dictionary] of Object.entries(locales)) {
    for (const status of DISTRO_STATUSES) assert.ok(dictionary.freeTools.items.cveLookup.distroStatus[status], `${code}: ${status}`)
  }
  assert.equal(distroStatusLabelKey('fixed'), 'freeTools.items.cveLookup.distroStatus.fixed')
  assert.equal(distroStatusLabelKey('wontfix'), 'freeTools.items.cveLookup.distroStatus.unknown')
})

test('EPSS pasa de probabilidad a porcentaje con un decimal, y sin dato no inventa nada', () => {
  assert.equal(epssPercent(0.12345), 12.3)
  assert.equal(epssPercent(1), 100)
  assert.equal(epssPercent(0), 0)
  assert.equal(epssPercent(7), 100)
  assert.equal(epssPercent(null), null)
  assert.equal(epssPercent(undefined), null)
  assert.equal(epssPercent(Number.NaN), null)
})

test('se cuenta lo que el servidor recortó y nunca sale negativo', () => {
  assert.equal(hiddenCount(new Array(50), 75), 25)
  assert.equal(hiddenCount(new Array(3), 3), 0)
  assert.equal(hiddenCount(new Array(5), 2), 0)
  assert.equal(hiddenCount(undefined, 10), 0)
  assert.equal(hiddenCount([1], undefined), 0)
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
