/**
 * Tests de `findingsArrangement` — orden y filtros de los hallazgos de Lybra.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`.
 *
 * Lo que se fija aquí es lo que el usuario ve al abrir el capítulo de
 * hallazgos: que lo más grave salga arriba sin tocar nada, que cada filtro
 * esconda lo que dice y nada más, y que los recuentos cuadren con la lista.
 */

import assert from 'node:assert/strict'

const { arrangeGroups, defaultCriteria, isFiltering, isResolved, normalizeText } =
  await import('../src/components/themis/lybra/findingsArrangement.js')

let failures = 0
function test(name, fn) {
  try { fn(); console.log(`  ok   ${name}`) }
  catch (err) { failures++; console.error(`  FAIL ${name}\n       ${err.message}`) }
}

/** Criterios por defecto con lo que cambie cada test encima. */
function criteria(overrides = {}) {
  return { ...defaultCriteria(), ...overrides }
}

let nextId = 1
function finding(fields) {
  return { id: nextId++, priority: 'LOW', title: 'Hallazgo', state: 'open', confirmed: false, cveIds: [], ...fields }
}

/** Un escaneo pequeño con las dos secciones y de todo un poco. */
function sampleGroups() {
  return [
    {
      label: 'OpenSSH 8.2', isProduct: true, port: 22, service: 'ssh', priority: 'CRITICAL',
      findings: [
        finding({ title: 'Zeta baja', priority: 'LOW', cvssScore: 3.1 }),
        finding({ title: 'Alfa crítica', priority: 'CRITICAL', cvssScore: 9.8, cveIds: ['CVE-2024-6387'], confirmed: true }),
        finding({ title: 'Media resuelta', priority: 'MEDIUM', cvssScore: 5.0, state: 'fixed' }),
      ],
    },
    {
      label: 'Apache httpd 2.4', isProduct: true, port: 80, service: 'http', priority: 'HIGH',
      findings: [
        finding({ title: 'Beta alta', priority: 'HIGH', cvssScore: 7.5, epssScore: 0.9 }),
        finding({ title: 'Info aceptada', priority: 'INFO', state: 'accepted' }),
      ],
    },
    {
      label: 'Falta la cabecera HSTS', isProduct: false, port: 443, service: 'https', priority: 'MEDIUM',
      findings: [
        finding({ title: 'Cabecera de configuración', priority: 'MEDIUM', confirmed: true, epssScore: 0.1 }),
      ],
    },
  ]
}

function titles(group) { return group.findings.map(f => f.title) }
function labels(section) { return section.groups.map(g => g.label) }

console.log('findingsArrangement')

test('sin tocar nada, lo más grave va arriba dentro de cada grupo', () => {
  const { sections } = arrangeGroups(sampleGroups(), defaultCriteria())
  assert.deepEqual(titles(sections[0].groups[0]), ['Alfa crítica', 'Media resuelta', 'Zeta baja'])
  assert.deepEqual(labels(sections[0]), ['OpenSSH 8.2', 'Apache httpd 2.4'])
})

test('siempre hay dos secciones, productos y configuración, en ese orden', () => {
  const { sections } = arrangeGroups(sampleGroups(), criteria({ sortKey: 'product' }))
  assert.deepEqual(sections.map(s => s.key), ['prod', 'conf'])
  assert.deepEqual(labels(sections[1]), ['Falta la cabecera HSTS'])
})

test('invertir la gravedad pone lo más leve arriba', () => {
  const { sections } = arrangeGroups(sampleGroups(), criteria({ reversed: true }))
  const openssh = sections[0].groups.find(g => g.label === 'OpenSSH 8.2')
  assert.deepEqual(titles(openssh), ['Zeta baja', 'Media resuelta', 'Alfa crítica'])
  assert.deepEqual(labels(sections[0]), ['Apache httpd 2.4', 'OpenSSH 8.2'])
})

test('por nombre ordena los hallazgos por título sin mover los grupos', () => {
  const { sections } = arrangeGroups(sampleGroups(), criteria({ sortKey: 'title' }))
  assert.deepEqual(titles(sections[0].groups[0]), ['Alfa crítica', 'Media resuelta', 'Zeta baja'])
  assert.deepEqual(labels(sections[0]), ['OpenSSH 8.2', 'Apache httpd 2.4'])
  const reversed = arrangeGroups(sampleGroups(), criteria({ sortKey: 'title', reversed: true }))
  assert.deepEqual(titles(reversed.sections[0].groups[0]), ['Zeta baja', 'Media resuelta', 'Alfa crítica'])
})

test('por producto ordena los grupos alfabéticamente y deja los hallazgos por gravedad', () => {
  const { sections } = arrangeGroups(sampleGroups(), criteria({ sortKey: 'product' }))
  assert.deepEqual(labels(sections[0]), ['Apache httpd 2.4', 'OpenSSH 8.2'])
  const reversed = arrangeGroups(sampleGroups(), criteria({ sortKey: 'product', reversed: true }))
  assert.deepEqual(labels(reversed.sections[0]), ['OpenSSH 8.2', 'Apache httpd 2.4'])
  assert.deepEqual(titles(reversed.sections[0].groups[0]), ['Alfa crítica', 'Media resuelta', 'Zeta baja'])
})

test('por CVSS va de mayor a menor y lo que no tiene nota va al final en los dos sentidos', () => {
  const groups = [{ label: 'X', isProduct: true, findings: [
    finding({ title: 'sin nota', priority: 'CRITICAL' }),
    finding({ title: 'cinco', cvssScore: 5 }),
    finding({ title: 'nueve', cvssScore: 9 }),
  ] }]
  assert.deepEqual(titles(arrangeGroups(groups, criteria({ sortKey: 'cvss' })).sections[0].groups[0]), ['nueve', 'cinco', 'sin nota'])
  assert.deepEqual(titles(arrangeGroups(groups, criteria({ sortKey: 'cvss', reversed: true })).sections[0].groups[0]), ['cinco', 'nueve', 'sin nota'])
})

test('por EPSS los grupos se ordenan por el EPSS más alto de lo que muestran', () => {
  const { sections } = arrangeGroups(sampleGroups(), criteria({ sortKey: 'epss' }))
  assert.deepEqual(labels(sections[0]), ['Apache httpd 2.4', 'OpenSSH 8.2'])
})

test('a igual gravedad, un hallazgo en KEV va antes', () => {
  const groups = [{ label: 'X', isProduct: true, findings: [
    finding({ title: 'normal', priority: 'HIGH', cvssScore: 9 }),
    finding({ title: 'explotada', priority: 'HIGH', cvssScore: 7, inKev: true }),
  ] }]
  assert.deepEqual(titles(arrangeGroups(groups, defaultCriteria()).sections[0].groups[0]), ['explotada', 'normal'])
})

test('el orden es estable: los empates totales conservan el orden de llegada', () => {
  const twins = Array.from({ length: 50 }, (_, index) => finding({ title: 'igual', priority: 'LOW', marker: index }))
  const { sections } = arrangeGroups([{ label: 'X', isProduct: true, findings: twins }], defaultCriteria())
  assert.deepEqual(sections[0].groups[0].findings.map(f => f.marker), twins.map(f => f.marker))
})

test('los números dentro del título se ordenan como números', () => {
  const groups = [{ label: 'X', isProduct: true, findings: [
    finding({ title: 'CVE-2021-1000' }), finding({ title: 'CVE-2021-999' }),
  ] }]
  assert.deepEqual(titles(arrangeGroups(groups, criteria({ sortKey: 'title' })).sections[0].groups[0]), ['CVE-2021-999', 'CVE-2021-1000'])
})

test('pendientes esconde lo corregido, aceptado y desmentido; resueltos, lo contrario', () => {
  const pending = arrangeGroups(sampleGroups(), criteria({ state: 'pending' }))
  assert.equal(pending.visibleTotal, 4)
  assert.ok(pending.sections.every(s => s.groups.every(g => g.findings.every(f => !isResolved(f)))))
  const resolved = arrangeGroups(sampleGroups(), criteria({ state: 'resolved' }))
  assert.deepEqual(resolved.sections[0].groups.flatMap(titles), ['Media resuelta', 'Info aceptada'])
})

test('un hallazgo regresado cuenta como pendiente', () => {
  assert.equal(isResolved({ state: 'regressed' }), false)
  assert.equal(isResolved({ state: 'false_positive' }), true)
  assert.equal(isResolved({}), false)
})

test('el filtro de gravedad deja solo los niveles elegidos y oculta los grupos vacíos', () => {
  const { sections, visibleTotal } = arrangeGroups(sampleGroups(), criteria({ priorities: ['CRITICAL', 'HIGH'] }))
  assert.equal(visibleTotal, 2)
  assert.deepEqual(labels(sections[0]), ['OpenSSH 8.2', 'Apache httpd 2.4'])
  assert.equal(sections[1].groups.length, 0)
})

test('el filtro de certeza separa comprobados de potenciales', () => {
  assert.equal(arrangeGroups(sampleGroups(), criteria({ certainty: 'confirmed' })).visibleTotal, 2)
  assert.equal(arrangeGroups(sampleGroups(), criteria({ certainty: 'potential' })).visibleTotal, 4)
})

test('la búsqueda encuentra por título, por CVE y por producto, sin tildes ni mayúsculas', () => {
  assert.equal(arrangeGroups(sampleGroups(), criteria({ text: 'CONFIGURACION' })).visibleTotal, 1)
  assert.equal(arrangeGroups(sampleGroups(), criteria({ text: 'cve-2024-6387' })).visibleTotal, 1)
  assert.equal(arrangeGroups(sampleGroups(), criteria({ text: 'apache' })).visibleTotal, 2)
  assert.equal(arrangeGroups(sampleGroups(), criteria({ text: 'no existe' })).visibleTotal, 0)
})

test('un grupo filtrado dice cuánto muestra, cuánto tiene y su gravedad visible', () => {
  const { sections } = arrangeGroups(sampleGroups(), criteria({ priorities: ['LOW'] }))
  const group = sections[0].groups[0]
  assert.equal(group.totalFindings, 1)
  assert.equal(group.allFindings, 3)
  assert.equal(group.priority, 'LOW')
})

test('la balanza de cada sección pesa solo lo visible', () => {
  const { sections } = arrangeGroups(sampleGroups(), criteria({ state: 'pending' }))
  assert.deepEqual(sections[0].balance, [
    { level: 'CRITICAL', count: 1 }, { level: 'HIGH', count: 1 }, { level: 'LOW', count: 1 },
  ])
  assert.equal(sections[0].total, 3)
})

test('el recuento de cada gravedad ignora su propio filtro pero respeta los demás', () => {
  const { priorityCounts } = arrangeGroups(sampleGroups(), criteria({ state: 'pending', priorities: ['CRITICAL'] }))
  assert.deepEqual(priorityCounts, { CRITICAL: 1, HIGH: 1, MEDIUM: 1, LOW: 1, INFO: 0 })
})

test('el recuento de estados ignora el filtro de estado pero respeta los demás', () => {
  const { stateCounts } = arrangeGroups(sampleGroups(), criteria({ state: 'resolved', priorities: ['MEDIUM'] }))
  assert.deepEqual(stateCounts, { pending: 1, resolved: 1 })
})

test('no modifica los grupos ni los hallazgos recibidos', () => {
  const groups = sampleGroups()
  const snapshot = JSON.stringify(groups)
  arrangeGroups(groups, criteria({ sortKey: 'title', reversed: true, state: 'pending' }))
  assert.equal(JSON.stringify(groups), snapshot)
})

test('sin grupos devuelve las dos secciones vacías', () => {
  const result = arrangeGroups([], defaultCriteria())
  assert.deepEqual(result.sections.map(s => s.groups.length), [0, 0])
  assert.equal(result.total, 0)
})

test('ordenar no cuenta como filtrar; cualquier filtro sí', () => {
  assert.equal(isFiltering(criteria({ sortKey: 'cvss', reversed: true })), false)
  assert.equal(isFiltering(criteria({ text: '   ' })), false)
  assert.equal(isFiltering(criteria({ state: 'pending' })), true)
  assert.equal(isFiltering(criteria({ priorities: ['LOW'] })), true)
})

test('normalizar quita tildes y pasa a minúsculas', () => {
  assert.equal(normalizeText('Configuración ÉXITO'), 'configuracion exito')
  assert.equal(normalizeText(null), '')
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
