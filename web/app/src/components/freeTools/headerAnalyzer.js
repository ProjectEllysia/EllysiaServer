/**
 * Lógica sin Vue del analizador de cabeceras gratuito
 * (`views/tools/iris/HeaderAnalyzerView.vue`), para poder probarla con `node` a
 * secas. La lectura la hacen las reglas de Iris en `POST /iris/tools/headers`;
 * aquí solo se decide cómo enseñarla.
 */

/** Comprobaciones que devuelve el servidor, en el orden en que se enseñan. */
export const AUTH_CHECKS = Object.freeze(['spf', 'dkim', 'dmarc', 'alignment'])

/** Veredictos que pueden dar las reglas de autenticación de Iris, con su texto en `freeTools.items.headerAnalyzer.verdicts`. */
export const AUTH_VERDICTS = Object.freeze(['pass', 'fail', 'softfail', 'neutral', 'none', 'bestguess', 'policy', 'error', 'missing'])

/** Tamaño máximo que acepta el servidor, en caracteres. */
export const MAX_HEADERS_LENGTH = 65536

/** Tono de cada veredicto: verde si autentica, rojo si falla, ámbar si a medias; el resto, neutro. */
const VERDICT_TONES = Object.freeze({
  pass: 'good',
  bestguess: 'good',
  fail: 'bad',
  softfail: 'warn',
  none: 'warn',
  error: 'warn',
})

/**
 * Cabeceras de ejemplo para probar la herramienta sin pegar las de un correo propio:
 * un envío legítimo de tres saltos que pasa SPF, DKIM y DMARC, con un tramo sin TLS.
 */
export const SAMPLE_HEADERS = [
  'Received: from mail-sor-f41.google.com (mail-sor-f41.google.com [209.85.220.41])',
  '        by mx.example.com with ESMTPS id x12si1234567wrb',
  '        (version=TLS1_3 cipher=TLS_AES_256_GCM_SHA384 bits=256/256);',
  '        Thu, 09 Oct 2026 08:15:42 -0700 (PDT)',
  'Received: from relay.proveedor.example (relay.proveedor.example [203.0.113.25])',
  '        by mail-sor-f41.google.com with SMTP id abc123; Thu, 09 Oct 2026 08:15:40 -0700 (PDT)',
  'Received: from [192.168.1.20] (unknown [198.51.100.7])',
  '        by relay.proveedor.example (Postfix) with ESMTPSA id 4F2A1; Thu, 09 Oct 2026 17:15:38 +0200 (CEST)',
  'Authentication-Results: mx.example.com; spf=pass smtp.mailfrom=proveedor.example;',
  '        dkim=pass header.d=proveedor.example; dmarc=pass header.from=proveedor.example',
  'DKIM-Signature: v=1; a=rsa-sha256; d=proveedor.example; s=sel1; h=from:to:subject; bh=abc=; b=def=',
  'From: "Proveedor" <facturas@proveedor.example>',
  'To: cliente@example.com',
  'Subject: Factura de septiembre',
].join('\n')

/**
 * Tono con el que se pinta un veredicto.
 *
 * @param {unknown} verdict - Veredicto de la regla (`pass`, `fail`…).
 * @returns {'good'|'bad'|'warn'|'unknown'} `unknown` para lo que no dice nada
 *   (`missing`, `neutral`, `policy`) y para un veredicto desconocido.
 */
export function verdictTone(verdict) {
  return VERDICT_TONES[verdict] ?? 'unknown'
}

/**
 * Clave del texto de un veredicto.
 *
 * @param {unknown} verdict - Veredicto de la regla.
 * @returns {string} `freeTools.items.headerAnalyzer.verdicts.<veredicto>`; uno que la
 *   interfaz no conoce cae en `other`, en vez de enseñarse en crudo.
 */
export function verdictLabelKey(verdict) {
  return `freeTools.items.headerAnalyzer.verdicts.${AUTH_VERDICTS.includes(verdict) ? verdict : 'other'}`
}

/**
 * Qué decir cuando el servidor rechaza lo pegado.
 *
 * @param {number} status - Código HTTP de la respuesta.
 * @param {string} headers - Lo que se envió.
 * @returns {'tooLong'|'notHeaders'|'failed'} `tooLong` si un 422 se debe al tamaño;
 *   `notHeaders` si el servidor no encontró cabeceras suficientes (400) o el texto es
 *   demasiado corto (422); `failed` para cualquier otro error.
 */
export function rejectionReason(status, headers) {
  if (status === 422 && headers.length > MAX_HEADERS_LENGTH) return 'tooLong'
  if (status === 400 || status === 422) return 'notHeaders'
  return 'failed'
}
