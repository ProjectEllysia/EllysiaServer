/**
 * Tests de `scanWindow` —la ventana de escaneos que se le pide al backend— y
 * de `pageAfterRemoval`, la página a la que vuelve una lista tras un borrado.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * La ventana protege de un refresco que devuelva menos (o distintos) escaneos
 * de los que había en pantalla; la página tras un borrado, de una última
 * página vacía con el paginador diciendo que hay más.
 */

import assert from 'node:assert/strict'

const { scanWindow, pageAfterRemoval, MAX_PER_PAGE } =
  await import('../src/stores/scanWindow.js')

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

console.log('scanWindow')

test('sin revelar nada, la petición es la de siempre', () => {
  assert.deepEqual(
    scanWindow({ page: 1, perPage: 10, loadedPages: 1 }),
    { page: 1, perPage: 10 },
  )
})

test('la paginación clásica no cambia de comportamiento', () => {
  // nmap/nikto/nuclei van por goToPage y nunca revelan páginas: tienen que
  // seguir pidiendo exactamente la página que se les pide.
  assert.deepEqual(
    scanWindow({ page: 4, perPage: 10, loadedPages: 1 }),
    { page: 4, perPage: 10 },
  )
})

test('revelar páginas agranda la ventana, no avanza la página', () => {
  // Justo el fallo: tras dos "ver más" hay que pedir los 30 desde el
  // principio, no la página 3.
  assert.deepEqual(
    scanWindow({ page: 1, perPage: 10, loadedPages: 3 }),
    { page: 1, perPage: 30 },
  )
})

test('la ventana no rebasa el tope de per_page del backend', () => {
  // `ResultsQuerySchema` valida per_page con Range(min=1, max=100): pedir más
  // no sería una ventana mayor sino un 422.
  assert.equal(scanWindow({ page: 1, perPage: 10, loadedPages: 40 }).perPage, MAX_PER_PAGE)
})

test('un estado incompleto no produce una petición inválida', () => {
  assert.deepEqual(scanWindow({}), { page: 1, perPage: 10 })
  assert.deepEqual(scanWindow(undefined), { page: 1, perPage: 10 })
  assert.deepEqual(scanWindow({ page: 0, perPage: 0, loadedPages: 0 }), { page: 1, perPage: 10 })
})

console.log('pageAfterRemoval')

test('borrar sin vaciar la página se queda en ella', () => {
  assert.equal(pageAfterRemoval({ page: 3, perPage: 10, totalCount: 23 }, 2), 3)
})

test('vaciar la última página retrocede a la anterior', () => {
  // 23 escaneos: la página 3 tiene 3. Borrarlos deja 20, que caben en dos.
  assert.equal(pageAfterRemoval({ page: 3, perPage: 10, totalCount: 23 }, 3), 2)
})

test('un borrado que se lleva varias páginas cae en la última que queda', () => {
  assert.equal(pageAfterRemoval({ page: 5, perPage: 10, totalCount: 50 }, 35), 2)
})

test('sin escaneos restantes se vuelve a la primera', () => {
  assert.equal(pageAfterRemoval({ page: 2, perPage: 10, totalCount: 11 }, 11), 1)
  assert.equal(pageAfterRemoval({}, 0), 1)
})

if (failures) {
  console.error(`\n${failures} test(s) fallaron`)
  process.exit(1)
}
console.log('\ntodo en verde')
