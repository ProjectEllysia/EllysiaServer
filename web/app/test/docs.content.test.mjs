/**
 * Tests de la documentación técnica: el formato en línea y los ficheros de
 * contenido de `src/content/documentation/`.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * Lo que se fija:
 *   - que los dos idiomas digan lo mismo con la misma forma: mismas secciones
 *     en el mismo orden, mismos tipos de bloque, mismo número de elementos y
 *     las mismas figuras. Una página que diverge entre idiomas es una página
 *     a medio traducir que nadie ve hasta que alguien cambia de idioma;
 *   - que cada bloque tenga los campos que la vista pinta, y ninguna marca de
 *     formato a medio cerrar;
 *   - que toda figura apunte a una imagen que existe, con texto alternativo;
 *   - que cada página tenga su ruta, y cada ruta su página.
 */

import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parseInlineText } from '../src/content/documentation/inline.js'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const contentRoot = `${appRoot}src/content/documentation/`
const figureRoot = `${appRoot}src/assets/images/documentation/`

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

const LOCALES = ['es', 'en']
const BLOCK_TYPES = new Set(['p', 'list', 'steps', 'terms', 'callout'])

/**
 * Los textos de un bloque, en orden, para revisarlos todos igual.
 *
 * @param {object} block - Un bloque de una sección.
 * @returns {string[]} Cada texto que la vista pinta.
 */
function blockTexts(block) {
  switch (block.type) {
    case 'p':
    case 'callout':
      return [block.text]
    case 'list':
      return block.items
    case 'steps':
      return block.items.flatMap((step) => [step.title, step.text])
    case 'terms':
      return block.items.flatMap((entry) => [entry.term, entry.text])
    default:
      return []
  }
}

/**
 * La forma de una página sin sus textos: lo que tiene que coincidir entre
 * idiomas.
 *
 * @param {object} page - Una página de documentación.
 * @returns {object[]} Por sección: su `id`, los tipos y tamaños de sus bloques
 *   y las imágenes de sus figuras.
 */
function pageShape(page) {
  return page.sections.map((section) => ({
    id: section.id,
    blocks: section.blocks.map((block) => `${block.type}:${block.items?.length ?? 1}`),
    figures: (section.figures ?? []).map((figure) => figure.image),
  }))
}

const pages = Object.fromEntries(LOCALES.map((locale) => [
  locale,
  Object.fromEntries(readdirSync(`${contentRoot}${locale}`)
    .filter((name) => name.endsWith('.json'))
    .map((name) => [name.replace('.json', ''), JSON.parse(readFileSync(`${contentRoot}${locale}/${name}`, 'utf-8'))])),
]))

console.log('docs.content')

test('parseInlineText separa negrita, código y texto', () => {
  assert.deepEqual(parseInlineText('Un **término** y `código`.'), [
    { kind: 'text', value: 'Un ' },
    { kind: 'strong', value: 'término' },
    { kind: 'text', value: ' y ' },
    { kind: 'code', value: 'código' },
    { kind: 'text', value: '.' },
  ])
})

test('parseInlineText deja como texto una marca sin cerrar', () => {
  assert.deepEqual(parseInlineText('3 ** 2 y un ` suelto'), [{ kind: 'text', value: '3 ** 2 y un ` suelto' }])
})

test('los dos idiomas documentan las mismas herramientas', () => {
  assert.deepEqual(Object.keys(pages.en).sort(), Object.keys(pages.es).sort())
})

for (const [tool, page] of Object.entries(pages.es)) {
  test(`${tool}: el inglés tiene la misma forma que el castellano`, () => {
    assert.deepEqual(pageShape(pages.en[tool]), pageShape(page))
  })

  for (const locale of LOCALES) {
    const localized = pages[locale][tool]

    test(`${tool} (${locale}): título, entradilla y secciones con id únicos`, () => {
      assert.ok(localized.title && localized.lede, 'falta title o lede')
      const ids = localized.sections.map((section) => section.id)
      assert.deepEqual(ids, [...new Set(ids)], 'hay ids de sección repetidos')
      for (const id of ids) assert.match(id, /^[a-z0-9]+(-[a-z0-9]+)*$/, `id no válido para un ancla: ${id}`)
    })

    test(`${tool} (${locale}): cada bloque es de un tipo conocido y tiene sus textos`, () => {
      for (const section of localized.sections) {
        assert.ok(section.heading, `la sección ${section.id} no tiene título`)
        for (const block of section.blocks) {
          assert.ok(BLOCK_TYPES.has(block.type), `tipo de bloque desconocido en ${section.id}: ${block.type}`)
          for (const text of blockTexts(block)) {
            assert.equal(typeof text, 'string', `texto ausente en ${section.id}`)
            assert.ok(text.trim(), `texto vacío en ${section.id}`)
            const unmatched = (text.match(/\*\*/g)?.length ?? 0) % 2 || (text.match(/`/g)?.length ?? 0) % 2
            assert.ok(!unmatched, `marca de formato sin cerrar en ${section.id}: ${text}`)
          }
        }
      }
    })

    test(`${tool} (${locale}): cada figura tiene imagen existente y texto alternativo`, () => {
      for (const section of localized.sections) {
        for (const figure of section.figures ?? []) {
          assert.ok(existsSync(figureRoot + figure.image), `no existe src/assets/images/documentation/${figure.image}`)
          assert.ok(figure.alt?.trim(), `la figura ${figure.image} no tiene alt`)
        }
      }
    })
  }
}

test('cada página tiene su ruta y cada ruta de herramienta su página', () => {
  const router = readFileSync(`${appRoot}src/router/index.js`, 'utf-8')
  const routed = [...router.matchAll(/path: '\/docs\/tecnica\/([a-z]+)'[\s\S]*?docTool: '([a-z]+)'/g)]
  for (const [, pathTool, metaTool] of routed) assert.equal(pathTool, metaTool, `la ruta /docs/tecnica/${pathTool} declara docTool '${metaTool}'`)
  assert.deepEqual(routed.map(([, tool]) => tool).sort(), Object.keys(pages.es).sort())
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
