/**
 * Lógica sin Vue del comprobador de SPF, DKIM y DMARC gratuito
 * (`views/tools/iris/MailAuthCheckerView.vue`), para poder probarla con `node` a
 * secas.
 *
 * Las consultas de DNS las hace el navegador del usuario a un servicio público de
 * DNS sobre HTTPS (Cloudflare, y Google si el primero falla): nada pasa por el
 * servidor de Ellysia ni sale desde su dirección.
 *
 * Los registros se leen de forma estática. Por ejemplo, el límite de diez
 * consultas de SPF se cuenta sobre los mecanismos del propio registro, sin
 * seguir los `include`.
 */

/** Gravedades de un hallazgo, de la menor a la mayor. */
export const FINDING_LEVELS = Object.freeze(['ok', 'info', 'warn', 'bad'])

/** Hallazgos posibles, con su texto en `freeTools.items.mailAuthChecker.findings`. */
export const FINDING_CODES = Object.freeze([
  'domainNotFound',
  'spfMissing', 'spfMultiple', 'spfStrict', 'spfSoftfail', 'spfNeutral', 'spfOpen', 'spfNoAll', 'spfRedirect', 'spfPtr', 'spfTooManyLookups',
  'dmarcMissing', 'dmarcInherited', 'dmarcMultiple', 'dmarcInvalid', 'dmarcReject', 'dmarcQuarantine', 'dmarcNone', 'dmarcSubdomainWeaker', 'dmarcPartial', 'dmarcNoReports',
  'dkimMissing', 'dkimRevoked', 'dkimInvalid', 'dkimOk', 'dkimShortKey', 'dkimTestMode',
])

/** Servicios de DNS sobre HTTPS, por orden de preferencia. */
const RESOLVERS = Object.freeze([
  (name) => `https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(name)}&type=TXT`,
  (name) => `https://dns.google/resolve?name=${encodeURIComponent(name)}&type=TXT`,
])

/** Mecanismos de SPF que cuestan una consulta de DNS. */
const LOOKUP_TERM = /^[+\-~?]?(include|a|mx|ptr|exists)([:/]|$)|^redirect=/i

/** Cuántas consultas de DNS permite el estándar de SPF. */
export const SPF_LOOKUP_LIMIT = 10

/**
 * Deja un dominio como se consulta en DNS.
 *
 * Acepta lo que la gente pega: un dominio, una dirección de correo, una URL con
 * ruta o con puerto, con mayúsculas o con punto final.
 *
 * @param {unknown} text - Lo escrito por el usuario.
 * @returns {string|null} El dominio en minúsculas y en forma ASCII (los nombres con
 *   acentos pasan a su forma `xn--`), o `null` si no es un nombre de dominio válido.
 */
export function normalizeDomain(text) {
  if (typeof text !== 'string') return null
  let candidate = text.trim().toLowerCase()
  if (candidate.includes('@')) candidate = candidate.slice(candidate.lastIndexOf('@') + 1)
  candidate = candidate.replace(/^[a-z][a-z0-9+.-]*:\/\//, '').split(/[/?#]/)[0].replace(/:\d+$/, '').replace(/\.$/, '')
  if (!candidate) return null
  let ascii
  try {
    ascii = new URL(`http://${candidate}`).hostname
  } catch {
    return null
  }
  const labels = ascii.split('.')
  const isValid = ascii.length <= 253
    && labels.length >= 2
    && labels.every((label) => /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/.test(label))
    && /^([a-z]{2,}|xn--[a-z0-9-]+)$/.test(labels[labels.length - 1])
  return isValid ? ascii : null
}

/**
 * Valida el nombre de un selector DKIM.
 *
 * @param {unknown} text - Lo escrito por el usuario.
 * @returns {string|null} El selector en minúsculas, o `null` si no es un nombre de
 *   etiqueta DNS razonable (letras, cifras, puntos, guiones y guiones bajos).
 */
export function normalizeSelector(text) {
  if (typeof text !== 'string') return null
  const selector = text.trim().toLowerCase()
  return /^[a-z0-9]([a-z0-9._-]{0,62})$/.test(selector) ? selector : null
}

/**
 * Une los trozos de un registro TXT.
 *
 * Un TXT largo llega partido en cadenas entre comillas de 255 caracteres como
 * máximo (`"v=DKIM1; p=MIIB" "IjAN..."`), y el significado es su unión.
 *
 * @param {string} data - El campo `data` de una respuesta de DNS.
 * @returns {string} El texto del registro, sin comillas.
 */
export function joinTxtData(data) {
  const chunks = [...data.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((match) => match[1].replace(/\\(.)/g, '$1'))
  return chunks.length ? chunks.join('') : data
}

/**
 * Lee la respuesta JSON de un servicio de DNS sobre HTTPS.
 *
 * @param {object} json - Cuerpo de la respuesta (`Status`, `Answer`).
 * @returns {{status: 'ok'|'nxdomain'|'error', records: string[]}} `nxdomain` si el
 *   nombre no existe; `error` ante cualquier otro código de fallo; `ok` con los
 *   registros TXT (vacío si el nombre existe pero no tiene ninguno).
 */
export function parseDnsAnswer(json) {
  if (!json || typeof json !== 'object') return { status: 'error', records: [] }
  if (json.Status === 3) return { status: 'nxdomain', records: [] }
  if (json.Status !== 0) return { status: 'error', records: [] }
  const records = (json.Answer ?? []).filter((answer) => answer.type === 16 && typeof answer.data === 'string').map((answer) => joinTxtData(answer.data))
  return { status: 'ok', records }
}

/**
 * Pide los registros TXT de un nombre.
 *
 * @param {string} name - Nombre completo (`_dmarc.ejemplo.com`).
 * @param {typeof fetch} [fetchImplementation] - `fetch`; se inyecta en los tests.
 * @returns {Promise<{status: 'ok'|'nxdomain', records: string[]}>} Lo que dice el primer
 *   servicio que responde sin error; «el nombre no existe» cuenta como respuesta.
 * @throws {Error} Si ningún servicio responde.
 */
export async function lookupTxt(name, fetchImplementation = fetch) {
  for (const buildUrl of RESOLVERS) {
    try {
      const response = await fetchImplementation(buildUrl(name), { headers: { accept: 'application/dns-json' } })
      if (!response.ok) continue
      const answer = parseDnsAnswer(await response.json())
      if (answer.status !== 'error') return answer
    } catch {
      // Se prueba con el siguiente servicio.
    }
  }
  throw new Error(`DNS: sin respuesta para ${name}`)
}

/**
 * Lee las etiquetas `clave=valor;` de un registro DMARC o DKIM.
 *
 * @param {string} record - El registro.
 * @returns {Record<string, string>} Las etiquetas, con la clave en minúsculas y los
 *   espacios recortados. Si una clave se repite, vale la primera.
 */
export function parseTags(record) {
  const tags = {}
  for (const part of record.split(';')) {
    const separator = part.indexOf('=')
    if (separator === -1) continue
    const key = part.slice(0, separator).trim().toLowerCase()
    if (key && !(key in tags)) tags[key] = part.slice(separator + 1).trim()
  }
  return tags
}

/**
 * Analiza los registros TXT del dominio buscando el de SPF.
 *
 * @param {string[]} records - Todos los TXT del dominio.
 * @returns {{record: string|null, findings: Array<{code: string, level: string, params?: object}>}}
 *   El registro SPF (el primero si hay varios) y lo que se ha encontrado en él.
 */
export function analyseSpf(records) {
  const spfRecords = records.filter((record) => /^v=spf1(\s|$)/i.test(record.trim()))
  if (!spfRecords.length) return { record: null, findings: [{ code: 'spfMissing', level: 'bad' }] }

  const record = spfRecords[0].trim()
  const findings = []
  if (spfRecords.length > 1) findings.push({ code: 'spfMultiple', level: 'bad' })

  const terms = record.split(/\s+/).slice(1)
  const allTerm = terms.find((term) => /^[+\-~?]?all$/i.test(term))
  if (allTerm) {
    const qualifier = allTerm.startsWith('-') ? 'Strict' : allTerm.startsWith('~') ? 'Softfail' : allTerm.startsWith('?') ? 'Neutral' : 'Open'
    const level = { Strict: 'ok', Softfail: 'info', Neutral: 'warn', Open: 'bad' }[qualifier]
    findings.push({ code: `spf${qualifier}`, level })
  } else if (terms.some((term) => /^redirect=/i.test(term))) {
    findings.push({ code: 'spfRedirect', level: 'info' })
  } else {
    findings.push({ code: 'spfNoAll', level: 'warn' })
  }
  if (terms.some((term) => /^[+\-~?]?ptr([:/]|$)/i.test(term))) findings.push({ code: 'spfPtr', level: 'warn' })
  const lookups = terms.filter((term) => LOOKUP_TERM.test(term)).length
  if (lookups > SPF_LOOKUP_LIMIT) findings.push({ code: 'spfTooManyLookups', level: 'bad', params: { count: lookups } })
  return { record, findings }
}

/** Orden de las políticas de DMARC, de la más laxa a la más estricta. */
const POLICY_RANK = Object.freeze({ none: 0, quarantine: 1, reject: 2 })

/**
 * Analiza los registros TXT de `_dmarc.<dominio>`.
 *
 * @param {string[]} records - Todos los TXT de ese nombre.
 * @returns {{record: string|null, tags: Record<string, string>, findings: Array<{code: string, level: string, params?: object}>}}
 *   El registro DMARC (el primero si hay varios), sus etiquetas y lo encontrado.
 */
export function analyseDmarc(records) {
  const dmarcRecords = records.filter((record) => /^v=DMARC1\s*(;|$)/i.test(record.trim()))
  if (!dmarcRecords.length) return { record: null, tags: {}, findings: [{ code: 'dmarcMissing', level: 'bad' }] }

  const record = dmarcRecords[0].trim()
  const tags = parseTags(record)
  const findings = []
  if (dmarcRecords.length > 1) findings.push({ code: 'dmarcMultiple', level: 'bad' })

  const policy = (tags.p ?? '').toLowerCase()
  if (!(policy in POLICY_RANK)) {
    findings.push({ code: 'dmarcInvalid', level: 'bad' })
  } else {
    findings.push({ code: { reject: 'dmarcReject', quarantine: 'dmarcQuarantine', none: 'dmarcNone' }[policy], level: policy === 'none' ? 'warn' : 'ok' })
    const subdomainPolicy = (tags.sp ?? '').toLowerCase()
    if (subdomainPolicy in POLICY_RANK && POLICY_RANK[subdomainPolicy] < POLICY_RANK[policy]) {
      findings.push({ code: 'dmarcSubdomainWeaker', level: 'warn', params: { policy: subdomainPolicy } })
    }
    const percentage = tags.pct === undefined ? 100 : Number.parseInt(tags.pct, 10)
    if (policy !== 'none' && Number.isFinite(percentage) && percentage < 100) findings.push({ code: 'dmarcPartial', level: 'warn', params: { percentage } })
  }
  if (!tags.rua) findings.push({ code: 'dmarcNoReports', level: 'info' })
  return { record, tags, findings }
}

/**
 * Estima los bits de una clave RSA a partir de la parte pública de un registro DKIM.
 *
 * @param {string} base64 - Valor de la etiqueta `p=` (clave pública en base64, DER).
 * @returns {number|null} El tamaño más cercano entre 512, 1024, 2048, 3072 y 4096, o
 *   `null` si no es base64 válido. Es una estimación por la longitud de la clave.
 */
export function estimateRsaBits(base64) {
  let bytes
  try {
    bytes = atob(base64.replace(/\s+/g, '')).length
  } catch {
    return null
  }
  const rawBits = (bytes - 38) * 8
  return [512, 1024, 2048, 3072, 4096].reduce((best, size) => (Math.abs(size - rawBits) < Math.abs(best - rawBits) ? size : best))
}

/**
 * Analiza los registros TXT de `<selector>._domainkey.<dominio>`.
 *
 * @param {string[]} records - Todos los TXT de ese nombre.
 * @returns {{record: string|null, findings: Array<{code: string, level: string, params?: object}>}}
 *   El registro (el primero que declara una clave) y lo encontrado.
 */
export function analyseDkim(records) {
  const record = records.map((candidate) => candidate.trim()).find((candidate) => /(^|;)\s*p\s*=/i.test(candidate)) ?? null
  if (!record) return { record: null, findings: [{ code: 'dkimMissing', level: 'bad' }] }

  const tags = parseTags(record)
  const findings = []
  const key = (tags.p ?? '').replace(/\s+/g, '')
  if (!key) return { record, findings: [{ code: 'dkimRevoked', level: 'warn' }] }

  const keyType = (tags.k ?? 'rsa').toLowerCase()
  if (keyType === 'ed25519') {
    findings.push({ code: 'dkimOk', level: 'ok', params: { bits: 256 } })
  } else {
    const bits = estimateRsaBits(key)
    if (bits === null) findings.push({ code: 'dkimInvalid', level: 'bad' })
    else findings.push(bits < 2048 ? { code: 'dkimShortKey', level: 'warn', params: { bits } } : { code: 'dkimOk', level: 'ok', params: { bits } })
  }
  if ((tags.t ?? '').split(':').map((flag) => flag.trim().toLowerCase()).includes('y')) findings.push({ code: 'dkimTestMode', level: 'warn' })
  return { record, findings }
}

/**
 * Gravedad más alta de una lista de hallazgos.
 *
 * @param {Array<{level: string}>} findings - Hallazgos.
 * @returns {string} Uno de `FINDING_LEVELS`; `ok` si la lista está vacía.
 */
export function worstLevel(findings) {
  return findings.reduce((worst, finding) => (FINDING_LEVELS.indexOf(finding.level) > FINDING_LEVELS.indexOf(worst) ? finding.level : worst), 'ok')
}

/**
 * Dominios padre de uno, del más cercano al más general, sin llegar al sufijo solo.
 *
 * @param {string} domain - Dominio en minúsculas (`mail.ejemplo.com`).
 * @returns {string[]} `['ejemplo.com']` para el ejemplo; vacío si el dominio ya tiene
 *   dos etiquetas. No conoce la lista de sufijos públicos, así que `a.ejemplo.co.uk`
 *   también devuelve `co.uk`; consultarlo es inofensivo y no tiene registros.
 */
export function parentDomains(domain) {
  const labels = domain.split('.')
  return labels.slice(1, -1).map((_, index) => labels.slice(index + 1).join('.'))
}

/**
 * Busca la política DMARC de un dominio, subiendo a sus padres si él no tiene.
 *
 * DMARC se hereda: un subdominio sin registro propio queda cubierto por el del
 * dominio de la organización. Un fallo de DNS al mirar un padre se salta, porque
 * lo que se pregunta es solo si hay herencia.
 *
 * @param {string} domain - Dominio en minúsculas.
 * @param {{status: string, records: string[]}} ownLookup - Respuesta de `_dmarc.<domain>`.
 * @param {typeof fetch} fetchImplementation - `fetch`.
 * @returns {Promise<object>} El resultado de `analyseDmarc`; si lo hereda, con un
 *   hallazgo `dmarcInherited` (nivel `info`) delante.
 */
async function resolveDmarc(domain, ownLookup, fetchImplementation) {
  const own = analyseDmarc(ownLookup.records)
  if (own.record) return own
  for (const parent of parentDomains(domain)) {
    try {
      const inherited = analyseDmarc((await lookupTxt(`_dmarc.${parent}`, fetchImplementation)).records)
      if (inherited.record) return { ...inherited, findings: [{ code: 'dmarcInherited', level: 'info', params: { domain: parent } }, ...inherited.findings] }
    } catch {
      // Sin respuesta de DNS para este padre: se sigue con el siguiente.
    }
  }
  return own
}

/**
 * Comprueba la autenticación de correo de un dominio.
 *
 * @param {object} options - Opciones.
 * @param {string} options.domain - Dominio ya normalizado (`normalizeDomain`).
 * @param {string|null} [options.selector] - Selector DKIM ya normalizado; `null` no comprueba DKIM.
 * @param {typeof fetch} [options.fetchImplementation] - `fetch`; se inyecta en los tests.
 * @returns {Promise<{domain: string, exists: boolean, spf: object|null, dmarc: object|null, dkim: object|null}>}
 *   Si el dominio no existe (`exists: false`) no hay más resultados. `dkim` es `null`
 *   cuando no se pidió un selector.
 * @throws {Error} Si ningún servicio de DNS responde.
 */
export async function checkMailAuthentication({ domain, selector = null, fetchImplementation = fetch }) {
  const [root, dmarcRecords, dkimRecords] = await Promise.all([
    lookupTxt(domain, fetchImplementation),
    lookupTxt(`_dmarc.${domain}`, fetchImplementation),
    selector ? lookupTxt(`${selector}._domainkey.${domain}`, fetchImplementation) : Promise.resolve(null),
  ])
  if (root.status === 'nxdomain') return { domain, exists: false, spf: null, dmarc: null, dkim: null }
  return {
    domain,
    exists: true,
    spf: analyseSpf(root.records),
    dmarc: await resolveDmarc(domain, dmarcRecords, fetchImplementation),
    dkim: dkimRecords ? analyseDkim(dkimRecords.records) : null,
  }
}
