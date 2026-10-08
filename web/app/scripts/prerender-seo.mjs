/**
 * Paso final de `npm run build`: prerenderiza el `<head>` de las páginas
 * públicas sobre `dist/`. Qué hace y por qué: `scripts/seoPrerender.mjs`.
 */

import { fileURLToPath } from 'node:url'
import { prerenderSeoPages } from './seoPrerender.mjs'

const distDirectory = fileURLToPath(new URL('../dist/', import.meta.url))
const written = prerenderSeoPages({ distDirectory })
console.log(`seo: ${written.length} páginas públicas prerenderizadas en dist/`)
