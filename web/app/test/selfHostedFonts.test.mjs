/**
 * La SPA no carga tipografías desde Google Fonts.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * Cargar una tipografía de fonts.googleapis.com o fonts.gstatic.com hace que
 * el navegador de cada visitante envíe su dirección IP a Google sin necesidad.
 * Las tipografías viven en `src/assets/fonts/`; esta prueba falla si algún
 * fichero de `src/` o el `index.html` vuelve a apuntar a Google, y si falta
 * algún fichero que `fonts.css` declara.
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const appRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const GOOGLE_FONT_HOSTS = /fonts\.(googleapis|gstatic)\.com/

/** Todos los ficheros de texto de un directorio, recursivamente. */
function listTextFiles(directory) {
  const found = []
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry)
    if (statSync(path).isDirectory()) found.push(...listTextFiles(path))
    else if (/\.(vue|js|css|html|mjs)$/.test(entry)) found.push(path)
  }
  return found
}

const offenders = [...listTextFiles(join(appRoot, 'src')), join(appRoot, 'index.html')]
  .filter((path) => GOOGLE_FONT_HOSTS.test(readFileSync(path, 'utf8')))
assert.deepEqual(offenders, [], `Referencias a Google Fonts en: ${offenders.join(', ')}`)

const fontsDir = join(appRoot, 'src', 'assets', 'fonts')
const declared = [...readFileSync(join(fontsDir, 'fonts.css'), 'utf8').matchAll(/url\('\.\/([^']+)'\)/g)].map((m) => m[1])
assert.ok(declared.length > 0, 'fonts.css no declara ninguna tipografía')
const missing = declared.filter((relative) => !existsSync(join(fontsDir, relative)))
assert.deepEqual(missing, [], `Tipografías declaradas que no existen: ${missing.join(', ')}`)

console.log(`selfHostedFonts: sin Google Fonts; ${declared.length} ficheros de tipografía presentes`)
