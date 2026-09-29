/**
 * Las tres formas que admite el registro de objetivos autorizados, reconocidas
 * en el navegador para poder explicarlas mientras se escribe.
 *
 * El servidor es quien decide de verdad (`AuthorizedTargetManager` canoniza y
 * rechaza); esto solo sirve para que el formulario diga qué va a registrar
 * —«una red», «un dominio y sus subdominios», «un bucket»— antes de enviarlo,
 * y para no dejar enviar algo que seguro que no es ninguna de las tres. Las
 * reglas de los recursos cloud copian las de `lybra/cloud.py`: un nombre que
 * el proveedor no aceptaría tampoco se deja registrar.
 *
 * Sin Vue ni textos: devuelve claves, y quien pinta elige la frase
 * (CONVENCIONES.md §12.5).
 */

/** Forma de cada objetivo: la clave con la que el diccionario lo rotula. */
export const TARGET_SHAPES = Object.freeze(['network', 'domain', 'cloud'])

const IPV4_RE = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/
// IPv6 sin validar cada grupo: basta con distinguirla de un dominio y de un
// recurso cloud, que es lo único que aquí se decide.
const IPV6_RE = /^[0-9a-f:]+$/i

const CLOUD_RULES = {
  s3: /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/,
  gcs: /^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$/,
  firebase: /^[a-z0-9][a-z0-9-]{4,28}[a-z0-9]$/,
}
const AZURE_ACCOUNT_RE = /^[a-z0-9]{3,24}$/
const AZURE_CONTAINER_RE = /^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$/

// Etiquetas separadas por puntos, al menos dos, y una última que no sea un
// número (así «10.0.0» no pasa por dominio). Admite letras no ASCII: el
// servidor las convierte a su forma ASCII al guardarlas.
const DOMAIN_LABEL_RE = /^[\p{L}\p{N}](?:[\p{L}\p{N}-]{0,61}[\p{L}\p{N}])?$/u
const MAX_DOMAIN_LENGTH = 253

/**
 * Si un texto es una dirección IP o un rango CIDR.
 *
 * @param {string} text - El texto ya recortado.
 * @returns {boolean} `true` para `203.0.113.10`, `203.0.113.0/24` o una IPv6
 *          con o sin prefijo.
 */
function isNetwork(text) {
  const [address, prefix, extra] = text.split('/')
  if (extra !== undefined) return false
  if (IPV4_RE.test(address)) return prefix === undefined || (/^\d{1,2}$/.test(prefix) && Number(prefix) <= 32)
  if (address.includes(':') && IPV6_RE.test(address)) return prefix === undefined || (/^\d{1,3}$/.test(prefix) && Number(prefix) <= 128)
  return false
}

/**
 * Si un texto es un recurso cloud `proveedor:identificador` que el proveedor
 * aceptaría.
 *
 * @param {string} text - El texto ya recortado y en minúsculas.
 * @returns {boolean} `true` para `s3:nombre`, `gcs:nombre`,
 *          `azure:cuenta/contenedor` o `firebase:proyecto` bien formados.
 */
function isCloudResource(text) {
  const separator = text.indexOf(':')
  if (separator <= 0) return false
  const provider = text.slice(0, separator)
  const identifier = text.slice(separator + 1)
  if (provider === 'azure') {
    const [account, container, extra] = identifier.split('/')
    return extra === undefined && AZURE_ACCOUNT_RE.test(account || '') && AZURE_CONTAINER_RE.test(container || '')
  }
  return !!CLOUD_RULES[provider]?.test(identifier)
}

/**
 * Si un texto es un nombre de dominio con al menos dos etiquetas.
 *
 * @param {string} text - El texto ya recortado y en minúsculas.
 * @returns {boolean} `true` para `example.com` o `dev.example.com`; `false`
 *          para una sola palabra o para algo que acaba en número.
 */
function isDomain(text) {
  const domain = text.endsWith('.') ? text.slice(0, -1) : text
  if (!domain || domain.length > MAX_DOMAIN_LENGTH) return false
  const labels = domain.split('.')
  if (labels.length < 2 || !labels.every(label => DOMAIN_LABEL_RE.test(label))) return false
  return !/^\d+$/.test(labels[labels.length - 1])
}

/**
 * Qué forma tiene lo que el usuario quiere registrar.
 *
 * El orden es el del servidor: red, recurso cloud y dominio. Una IPv6 lleva
 * `:` como un recurso cloud, pero ningún proveedor se escribe con dígitos
 * hexadecimales solos, así que no hay ambigüedad.
 *
 * @param {string} raw - El texto tal como está en el campo.
 * @returns {'network'|'domain'|'cloud'|null} La forma reconocida, o `null` si
 *          el texto está vacío o no es ninguna de las tres.
 */
export function classifyTarget(raw) {
  const text = (raw || '').trim()
  if (!text) return null
  if (isNetwork(text)) return 'network'
  const lowered = text.toLowerCase()
  if (isCloudResource(lowered)) return 'cloud'
  if (isDomain(lowered)) return 'domain'
  return null
}
