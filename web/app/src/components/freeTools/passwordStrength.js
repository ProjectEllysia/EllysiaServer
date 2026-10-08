/**
 * Lógica sin Vue del medidor de contraseñas gratuito
 * (`views/tools/acheron/PasswordStrengthView.vue`), para poder probarla con
 * `node` a secas. Todo ocurre en el navegador: la contraseña no sale de aquí,
 * salvo los cinco primeros caracteres de su hash si el usuario pide mirar las
 * filtraciones (`pwnedRangeRequest`).
 *
 * Es una ESTIMACIÓN. Parte de que cada carácter sale al azar de su alfabeto, y
 * rebaja el coste de lo que un atacante probaría primero: palabras corrientes,
 * secuencias, repeticiones, filas del teclado y años. No conoce un diccionario
 * completo, así que una frase hecha de palabras normales aguanta menos de lo que
 * aquí se calcula.
 */

/** Intentos por segundo que se supone a un atacante con la contraseña ya robada
 *  (hash rápido y varias tarjetas gráficas). Es la hipótesis que la pantalla dice. */
export const GUESSES_PER_SECOND = 1e10

/** Niveles de solidez, del peor al mejor, con los bits de entropía desde los que se alcanzan. */
export const STRENGTH_LEVELS = Object.freeze([
  { level: 0, minBits: 0 },
  { level: 1, minBits: 28 },
  { level: 2, minBits: 40 },
  { level: 3, minBits: 60 },
  { level: 4, minBits: 80 },
])

/** Hallazgos que explican por qué una contraseña puntúa menos de lo que parece. */
export const WEAKNESS_CODES = Object.freeze(['short', 'commonWord', 'sequence', 'repeat', 'keyboard', 'year', 'oneKind'])

/** Palabras que un atacante prueba antes que nada, de la más a la menos frecuente. */
const COMMON_WORDS = [
  'password', 'contrasena', 'qwerty', 'admin', 'letmein', 'welcome', 'login', 'iloveyou', 'tequiero', 'hola',
  'monkey', 'dragon', 'master', 'sunshine', 'princess', 'football', 'futbol', 'baseball', 'shadow', 'superman',
  'michael', 'jordan', 'ashley', 'bailey', 'trustno', 'abc', 'amor', 'secret', 'secreto', 'cliente', 'usuario',
  'user', 'root', 'test', 'prueba', 'guest', 'invitado', 'default', 'changeme', 'cambiame', 'access', 'acceso',
  'summer', 'verano', 'winter', 'invierno', 'spring', 'primavera', 'autumn', 'otono', 'enero', 'febrero', 'marzo',
  'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre', 'january',
  'february', 'march', 'april', 'june', 'july', 'august', 'september', 'october', 'november', 'december',
  'madrid', 'barcelona', 'sevilla', 'valencia', 'real', 'barca', 'betis', 'messi', 'ronaldo', 'carlos', 'juan',
  'jose', 'maria', 'antonio', 'manuel', 'david', 'daniel', 'javier', 'miguel', 'laura', 'carmen', 'ana', 'lucia',
  'alex', 'sara', 'pablo', 'marta', 'jesus', 'pedro', 'angel', 'sergio', 'paula', 'andrea', 'ellysia', 'empresa',
  'company', 'servidor', 'server', 'router', 'wifi', 'internet', 'google', 'facebook', 'whatsapp', 'netflix',
  'amazon', 'apple', 'microsoft', 'windows', 'linux', 'ubuntu', 'debian', 'mysql', 'postgres', 'oracle', 'azerty',
  'asdf', 'zxcv', 'love', 'angel', 'baby', 'sexy', 'hello', 'freedom', 'whatever', 'starwars', 'pokemon', 'naruto',
  'batman', 'mario', 'zelda', 'minecraft', 'chocolate', 'cookie', 'banana', 'pepper', 'ginger', 'peanut',
]

/** Filas del teclado: se prueban en los dos sentidos. */
const KEYBOARD_ROWS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm', 'qazwsxedc', '1234567890', 'qweasdzxc']

/** Sustituciones habituales de letras por cifras y símbolos («p@ssw0rd»). */
const LEET = { '@': 'a', 4: 'a', 8: 'b', 3: 'e', 1: 'l', '!': 'i', 0: 'o', $: 's', 5: 's', 7: 't', '+': 't' }

/**
 * Tamaño del alfabeto del que se supone que sale cada carácter.
 *
 * @param {string} password - La contraseña.
 * @returns {{size: number, kinds: number}} `size` es la suma de los alfabetos que
 *   aparecen (26 minúsculas, 26 mayúsculas, 10 cifras, 33 símbolos ASCII y 100 por
 *   cualquier otro carácter); `kinds` cuántos de ellos hay.
 */
export function alphabetOf(password) {
  const pools = [
    [/[a-z]/, 26],
    [/[A-Z]/, 26],
    [/\d/, 10],
    [/[ -/:-@[-`{-~]/, 33],
    [/[^\x20-\x7e]/, 100],
  ]
  let size = 0
  let kinds = 0
  for (const [pattern, poolSize] of pools) {
    if (pattern.test(password)) {
      size += poolSize
      kinds += 1
    }
  }
  return { size, kinds }
}

/**
 * Busca los tramos de la contraseña que un atacante adivinaría con poco esfuerzo.
 *
 * @param {string} password - La contraseña.
 * @param {number} charBits - Bits de un carácter al azar de su alfabeto.
 * @returns {Array<{start: number, end: number, bits: number, code: string}>} Cada
 *   tramo cubre `password[start..end]` (ambos incluidos), cuesta `bits` bits y se
 *   explica con uno de `WEAKNESS_CODES`.
 */
function findPatterns(password, charBits) {
  const matches = []
  const lower = password.toLowerCase()
  const length = password.length

  // Palabras corrientes, también con sustituciones («p@ssw0rd») y mayúsculas.
  const deLeeted = [...lower].map((character) => LEET[character] ?? character).join('')
  COMMON_WORDS.forEach((word, rank) => {
    for (const [haystack, extraBits] of [[lower, 0], [deLeeted, 2]]) {
      let from = haystack.indexOf(word)
      while (from !== -1) {
        const wordBits = Math.log2(rank + 2) + 1 + extraBits
        matches.push({ start: from, end: from + word.length - 1, bits: Math.min(wordBits, word.length * charBits), code: 'commonWord' })
        from = haystack.indexOf(word, from + 1)
      }
    }
  })

  // Secuencias de tres o más caracteres seguidos (abc, 4321, mnop).
  for (let start = 0; start < length - 2; start += 1) {
    const step = lower.charCodeAt(start + 1) - lower.charCodeAt(start)
    if (Math.abs(step) !== 1) continue
    let end = start + 1
    while (end + 1 < length && lower.charCodeAt(end + 1) - lower.charCodeAt(end) === step) end += 1
    if (end - start >= 2) matches.push({ start, end, bits: Math.log2(26) + Math.log2(end - start + 1) + 1, code: 'sequence' })
  }

  // Un mismo carácter repetido o un bloque que se repite (aaaa, abcabc).
  for (let start = 0; start < length; start += 1) {
    let end = start
    while (end + 1 < length && password[end + 1] === password[start]) end += 1
    if (end - start >= 2) matches.push({ start, end, bits: charBits + Math.log2(end - start + 1), code: 'repeat' })
    for (let blockLength = 2; blockLength <= Math.floor((length - start) / 2); blockLength += 1) {
      const block = password.slice(start, start + blockLength)
      let repeats = 1
      while (password.startsWith(block, start + repeats * blockLength)) repeats += 1
      if (repeats >= 2) {
        matches.push({ start, end: start + repeats * blockLength - 1, bits: blockLength * charBits + Math.log2(repeats), code: 'repeat' })
      }
    }
  }

  // Filas del teclado, de cuatro caracteres en adelante.
  for (const row of KEYBOARD_ROWS) {
    for (const candidate of [row, [...row].reverse().join('')]) {
      for (let size = 4; size <= candidate.length; size += 1) {
        for (let from = 0; from + size <= candidate.length; from += 1) {
          const piece = candidate.slice(from, from + size)
          let at = lower.indexOf(piece)
          while (at !== -1) {
            matches.push({ start: at, end: at + size - 1, bits: Math.log2(KEYBOARD_ROWS.length * 2 * 8) + Math.log2(size), code: 'keyboard' })
            at = lower.indexOf(piece, at + 1)
          }
        }
      }
    }
  }

  // Años (1900-2099): unos cien valores posibles.
  for (const year of lower.matchAll(/(?:19|20)\d\d/g)) {
    matches.push({ start: year.index, end: year.index + 3, bits: Math.log2(200), code: 'year' })
  }
  return matches
}

/**
 * Estima cuántos bits de entropía tiene una contraseña y de qué se resiente.
 *
 * Elige la forma más barata de «escribirla» para un atacante: cada carácter suelto
 * cuesta lo que un carácter al azar de su alfabeto, y cada tramo reconocido, lo
 * que cuesta su patrón.
 *
 * @param {string} password - La contraseña. Una cadena vacía da 0 bits.
 * @returns {{length: number, bits: number, level: number, weaknesses: string[]}}
 *   `bits` es la entropía estimada (sin decimales); `level`, de 0 a 4, el escalón de
 *   `STRENGTH_LEVELS` que alcanza; `weaknesses`, los códigos de `WEAKNESS_CODES` que
 *   aplican, sin repetirse y en el orden de esa lista.
 */
export function estimateStrength(password) {
  const length = typeof password === 'string' ? [...password].length : 0
  if (length === 0) return { length: 0, bits: 0, level: 0, weaknesses: [] }

  const { size, kinds } = alphabetOf(password)
  const charBits = Math.log2(size)
  const matches = findPatterns(password, charBits)

  // best[i] = lo que cuesta la mejor forma de escribir los primeros i caracteres;
  // used[i] = el patrón que cierra esa forma, para saber de qué se resiente.
  const best = [0]
  const used = [[]]
  for (let index = 1; index <= password.length; index += 1) {
    best[index] = best[index - 1] + charBits
    used[index] = used[index - 1]
    for (const match of matches) {
      if (match.end + 1 !== index) continue
      const cost = best[match.start] + match.bits
      if (cost < best[index]) {
        best[index] = cost
        used[index] = [...used[match.start], match.code]
      }
    }
  }

  const bits = Math.round(best[password.length])
  const found = new Set(used[password.length])
  if (length < 12) found.add('short')
  if (kinds === 1) found.add('oneKind')
  const level = [...STRENGTH_LEVELS].reverse().find((step) => bits >= step.minBits).level
  return { length, bits, level, weaknesses: WEAKNESS_CODES.filter((code) => found.has(code)) }
}

/**
 * Tiempo medio que tardaría en dar con la contraseña quien la probara a ciegas.
 *
 * @param {number} bits - Entropía estimada (`estimateStrength`).
 * @returns {number} Segundos hasta acertar de media (la mitad del espacio de
 *   búsqueda a `GUESSES_PER_SECOND`); `Infinity` si el número no cabe en un `Number`.
 */
export function crackSeconds(bits) {
  if (!(bits > 0)) return 0
  return 2 ** (bits - 1) / GUESSES_PER_SECOND
}

/** Unidades en que se expresa un tiempo, de menor a mayor. */
export const CRACK_UNITS = Object.freeze(['instant', 'seconds', 'minutes', 'hours', 'days', 'months', 'years', 'centuries'])

/**
 * Pasa un tiempo en segundos a una cantidad redonda con su unidad.
 *
 * @param {number} seconds - Duración en segundos.
 * @returns {{unit: string, value: number|null}} `unit` es uno de `CRACK_UNITS`;
 *   `value` es la cantidad entera de esa unidad, o `null` para `instant` (menos de
 *   un segundo) y `centuries` (más de cien años, donde el número ya no dice nada).
 */
export function crackTimeParts(seconds) {
  const MINUTE = 60
  const HOUR = 3600
  const DAY = 86400
  const MONTH = DAY * 30
  const YEAR = DAY * 365
  if (!(seconds >= 1)) return { unit: 'instant', value: null }
  if (seconds < MINUTE) return { unit: 'seconds', value: Math.round(seconds) }
  if (seconds < HOUR) return { unit: 'minutes', value: Math.round(seconds / MINUTE) }
  if (seconds < DAY) return { unit: 'hours', value: Math.round(seconds / HOUR) }
  if (seconds < MONTH) return { unit: 'days', value: Math.round(seconds / DAY) }
  if (seconds < YEAR) return { unit: 'months', value: Math.round(seconds / MONTH) }
  if (seconds < YEAR * 100) return { unit: 'years', value: Math.round(seconds / YEAR) }
  return { unit: 'centuries', value: null }
}

/**
 * Posición (de 0 a 1) de un tiempo en la escala logarítmica de la pantalla.
 *
 * @param {number} seconds - Duración en segundos.
 * @returns {number} 0 para un segundo o menos, 1 para 10^12 segundos o más.
 */
export function crackScalePosition(seconds) {
  if (!(seconds > 1)) return 0
  return Math.min(1, Math.log10(seconds) / 12)
}

/**
 * Parte el hash de una contraseña como pide la consulta por rangos de filtraciones.
 *
 * @param {string} sha1Hex - SHA-1 de la contraseña en hexadecimal (40 caracteres).
 * @returns {{prefix: string, suffix: string}} Los cinco primeros caracteres, que son
 *   lo único que sale del navegador, y los 35 restantes, que se comparan aquí.
 */
export function splitHashForRange(sha1Hex) {
  const hash = sha1Hex.toUpperCase()
  return { prefix: hash.slice(0, 5), suffix: hash.slice(5) }
}

/**
 * Lee la respuesta de la consulta por rangos y busca el resto del hash.
 *
 * @param {string} body - Texto de la respuesta: una línea `SUFIJO:VECES` por hash.
 * @param {string} suffix - Los 35 caracteres finales del hash, en mayúsculas.
 * @returns {number} Cuántas veces aparece la contraseña en filtraciones; 0 si no está.
 */
export function pwnedCount(body, suffix) {
  for (const line of body.split(/\r?\n/)) {
    const [candidate, count] = line.trim().split(':')
    if (candidate === suffix) return Number.parseInt(count, 10) || 0
  }
  return 0
}

/**
 * Calcula el SHA-1 de un texto con la Web Crypto API.
 *
 * @param {string} text - Texto a resumir.
 * @returns {Promise<string>} El hash en hexadecimal y mayúsculas.
 */
export async function sha1Hex(text) {
  const digest = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(text))
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('').toUpperCase()
}

/**
 * Pregunta cuántas veces aparece una contraseña en filtraciones conocidas.
 *
 * Usa la consulta por rangos de Have I Been Pwned: solo viajan los cinco primeros
 * caracteres del hash, nunca la contraseña, y la respuesta trae todos los hashes
 * con ese prefijo, entre los que se busca aquí. `Add-Padding` mezcla líneas falsas
 * para que ni el tamaño de la respuesta delate el prefijo.
 *
 * @param {string} password - La contraseña.
 * @param {typeof fetch} [fetchImplementation] - `fetch`; se inyecta en los tests.
 * @returns {Promise<number>} Veces que aparece; 0 si no consta.
 * @throws {Error} Si el servicio no responde con éxito.
 */
export async function countInBreaches(password, fetchImplementation = fetch) {
  const { prefix, suffix } = splitHashForRange(await sha1Hex(password))
  const response = await fetchImplementation(`https://api.pwnedpasswords.com/range/${prefix}`, { headers: { 'Add-Padding': 'true' } })
  if (!response.ok) throw new Error(`rango de filtraciones: ${response.status}`)
  return pwnedCount(await response.text(), suffix)
}
