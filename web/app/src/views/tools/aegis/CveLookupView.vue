<template>
  <ToolShell tool-id="cveLookup" more-to="/aegis/generador">
    <form class="cve-form" novalidate @submit.prevent="lookup()">
      <label class="cve-label" for="cve-input">{{ t('freeTools.items.cveLookup.idLabel') }}</label>
      <div class="cve-row">
        <input
          id="cve-input"
          v-model="rawId"
          class="cve-input"
          type="text"
          autocomplete="off"
          autocapitalize="characters"
          spellcheck="false"
          :placeholder="CVE_EXAMPLE"
          :aria-invalid="hasInvalidId"
          aria-describedby="cve-hint"
        />
        <button type="submit" class="cve-btn" :disabled="isLoading">
          {{ isLoading ? t('freeTools.items.cveLookup.searching') : t('freeTools.items.cveLookup.search') }}
        </button>
      </div>
      <p id="cve-hint" class="cve-hint" :class="{ 'cve-hint--error': hasInvalidId }">
        {{ hasInvalidId ? t('freeTools.items.cveLookup.invalidId') : t('freeTools.items.cveLookup.hint') }}
      </p>
    </form>

    <div ref="outcome" class="cve-outcome" aria-live="polite">
      <p v-if="status === 'unknown'" class="cve-message">
        {{ t('freeTools.items.cveLookup.unknown', { id: searchedId }) }}
      </p>
      <p v-else-if="status === 'error'" class="cve-message cve-message--error">{{ errorMessage }}</p>

      <article v-else-if="status === 'found'" :key="cve.cveId" class="cve-card mo-rise" :data-severity="level">
        <header class="cve-card-head">
          <h2 class="cve-id">{{ cve.cveId }}</h2>
          <span class="cve-badge">{{ t(severityLabelKey(cve.severity)) }}</span>
        </header>

        <dl class="cve-facts">
          <div class="cve-fact mo-rise" style="--delay: 0.25s">
            <dt>{{ t('freeTools.items.cveLookup.facts.cvss') }}</dt>
            <dd><CountUp v-if="typeof cve.cvssScore === 'number'" :value="cve.cvssScore" :decimals="1" :duration="900" /><template v-else>{{ t('freeTools.items.cveLookup.notScored') }}</template></dd>
          </div>
          <div class="cve-fact mo-rise" style="--delay: 0.32s">
            <dt>{{ t('freeTools.items.cveLookup.facts.published') }}</dt>
            <dd>{{ cve.published ? formatDate(cve.published) : t('freeTools.items.cveLookup.notScored') }}</dd>
          </div>
          <div class="cve-fact mo-rise" style="--delay: 0.39s">
            <dt>{{ t('freeTools.items.cveLookup.facts.exploited') }}</dt>
            <dd :class="{ 'cve-yes': cve.inKev }">
              {{ cve.inKev ? t('freeTools.items.cveLookup.exploitedYes') : t('freeTools.items.cveLookup.exploitedNo') }}
            </dd>
          </div>
          <div class="cve-fact mo-rise" style="--delay: 0.46s">
            <dt>{{ t('freeTools.items.cveLookup.facts.epss') }}</dt>
            <dd :title="epssTitle">
              {{ epss === null ? t('freeTools.items.cveLookup.notScored') : `${formatNumber(epss)} %` }}
            </dd>
          </div>
        </dl>

        <p v-if="cve.description" class="cve-description" lang="en">{{ cve.description }}</p>

        <section v-if="cve.products.length" class="cve-section">
          <h3 class="cve-section-title">{{ t('freeTools.items.cveLookup.products') }}</h3>
          <ul class="cve-products">
            <li v-for="(product, index) in visibleProducts" :key="`${product.vendor}/${product.product}`" class="mo-rise" :style="{ '--delay': `${0.55 + index * 0.04}s` }">
              {{ product.vendor }} · {{ product.product }}
            </li>
          </ul>
          <p v-if="hiddenProducts" class="cve-more">{{ t('freeTools.items.cveLookup.andMore', { count: hiddenProducts }) }}</p>
        </section>

        <details v-if="cve.distroStatuses.length" class="cve-section">
          <summary class="cve-section-title">{{ t('freeTools.items.cveLookup.distros') }}</summary>
          <table class="cve-table">
            <thead>
              <tr>
                <th scope="col">{{ t('freeTools.items.cveLookup.distroColumns.distribution') }}</th>
                <th scope="col">{{ t('freeTools.items.cveLookup.distroColumns.package') }}</th>
                <th scope="col">{{ t('freeTools.items.cveLookup.distroColumns.status') }}</th>
                <th scope="col">{{ t('freeTools.items.cveLookup.distroColumns.fixedIn') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in cve.distroStatuses" :key="`${row.vendor}/${row.release}/${row.package}`">
                <td>{{ row.vendor }}{{ row.release ? ` ${row.release}` : '' }}</td>
                <td>{{ row.package }}</td>
                <td>{{ t(distroStatusLabelKey(row.status)) }}</td>
                <td>{{ row.fixedIn || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="hiddenDistros" class="cve-more">{{ t('freeTools.items.cveLookup.andMoreDistros', { count: hiddenDistros }) }}</p>
        </details>

        <p class="cve-sources">{{ t('freeTools.items.cveLookup.sources') }}</p>
      </article>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import CountUp from '@/components/shared/CountUp.vue'
import { revealResult } from '@/composables/revealResult'
import { apiError } from '@/composables/useApi'
import { formatDate, formatNumber } from '@/i18n/format'
import {
  distroStatusLabelKey,
  epssPercent,
  hiddenCount,
  isCveId,
  normalizeCveId,
  severityLabelKey,
  severityLevel,
} from '@/components/freeTools/cveLookup'

/**
 * Consulta de CVE gratuita de Aegis.
 *
 * Pregunta a `GET /themis/kb/cve`, que no pide sesión: lee la base local de NVD,
 * KEV y EPSS. La CVE consultada va en `?id=` para que el resultado se pueda
 * compartir con un enlace.
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

/** Ejemplo que se enseña mientras el campo está vacío: un identificador real y conocido. */
const CVE_EXAMPLE = 'CVE-2024-6387'

/** Cuántos productos afectados se enseñan antes del «y N más». */
const PRODUCTS_SHOWN = 12

const rawId = ref('')
const status = ref('idle') // idle | loading | found | unknown | error
const cve = ref(null)
const searchedId = ref('')
const errorMessage = ref('')
const hasAttempted = ref(false)
const outcome = ref(null)

const isLoading = computed(() => status.value === 'loading')
// El aviso de formato solo aparece tras un intento, no mientras se escribe.
const hasInvalidId = computed(() => hasAttempted.value && !isCveId(rawId.value))
const level = computed(() => severityLevel(cve.value?.severity))
const epss = computed(() => epssPercent(cve.value?.epssScore))
const epssTitle = computed(() => {
  const percentile = epssPercent(cve.value?.epssPercentile)
  return percentile === null ? '' : t('freeTools.items.cveLookup.epssPercentile', { percentile: formatNumber(percentile) })
})
// El servidor manda hasta 50 productos; en pantalla bastan los primeros.
const visibleProducts = computed(() => (cve.value?.products ?? []).slice(0, PRODUCTS_SHOWN))
const hiddenProducts = computed(() => hiddenCount(visibleProducts.value, cve.value?.productsTotal))
const hiddenDistros = computed(() => hiddenCount(cve.value?.distroStatuses, cve.value?.distroStatusesTotal))

/**
 * Consulta la CVE escrita y enseña el resultado, llevándolo a la vista si quedó por
 * debajo.
 *
 * @param {boolean} [isFromLink=false] - Si la consulta la lanza un enlace compartido al
 *   abrir la página; entonces no se desplaza nada.
 */
async function lookup(isFromLink = false) {
  hasAttempted.value = true
  const id = normalizeCveId(rawId.value)
  if (!isCveId(id)) return

  rawId.value = id
  searchedId.value = id
  status.value = 'loading'
  router.replace({ query: { id } })
  try {
    const response = await fetch(`/themis/kb/cve?id=${encodeURIComponent(id)}`)
    if (!response.ok) {
      errorMessage.value = await apiError(response, t('freeTools.items.cveLookup.failed'))
      status.value = 'error'
      return
    }
    const body = await response.json()
    cve.value = body.cve
    status.value = body.cve ? 'found' : 'unknown'
  } catch {
    errorMessage.value = t('freeTools.items.cveLookup.failed')
    status.value = 'error'
  }
  if (isFromLink) return
  await nextTick()
  revealResult(outcome.value)
}

// Un enlace compartido (`?id=CVE-…`) abre la página ya con el resultado.
onMounted(() => {
  const fromLink = route.query.id
  if (typeof fromLink === 'string' && isCveId(fromLink)) {
    rawId.value = fromLink
    lookup(true)
  }
})
</script>

<style scoped>
.cve-label, .cve-section-title, .cve-fact dt {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Formulario ── */
.cve-form { display: flex; flex-direction: column; gap: 0.6rem; }
.cve-row { display: flex; gap: 0.8rem; flex-wrap: wrap; }
.cve-input {
  flex: 1 1 14rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  letter-spacing: 0.04em;
  padding: 0.75rem 0.9rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
}
.cve-input::placeholder { color: var(--text-muted); }
.cve-input:focus-visible, .cve-btn:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }
.cve-input[aria-invalid="true"] { border-color: var(--danger); }
.cve-btn {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase;
  padding: 0.7rem 1.6rem;
  border-radius: 3px;
  border: 1px solid var(--accent);
  background: var(--accent);
  color: var(--on-accent);
  transition: all var(--transition);
}
.cve-btn:hover:not(:disabled) { background: var(--accent-bright); border-color: var(--accent-bright); }
.cve-btn:disabled { opacity: 0.6; cursor: progress; }
.cve-hint { font-size: var(--fs-sm); color: var(--text-muted); }
.cve-hint--error { color: var(--danger); }

/* ── Resultado ── */
.cve-outcome { margin-top: 1.6rem; }
.cve-message { font-size: var(--fs-md); color: var(--text-dim); }
.cve-message--error { color: var(--danger); }

/* El color de la gravedad solo lo lleva la insignia y el filete: el resto de la ficha se queda neutro. */
.cve-card {
  --severity: var(--text-muted);
  padding-top: 1.2rem;
  border-top: 2px solid var(--severity);
}
.cve-card[data-severity="critical"] { --severity: var(--danger); }
.cve-card[data-severity="high"] { --severity: var(--warn); }
.cve-card[data-severity="medium"] { --severity: var(--accent-bright); }
.cve-card[data-severity="low"] { --severity: var(--success); }

.cve-card-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.cve-id {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-2xl); font-weight: 600;
  color: var(--text);
  word-break: break-all;
}
.cve-badge {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--severity);
  border-radius: 3px;
  color: var(--severity);
}

.cve-facts {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
  gap: 1rem 1.5rem;
  margin: 1.3rem 0;
}
.cve-fact dd { font-size: var(--fs-lg); color: var(--text); margin-top: 0.2rem; }
.cve-yes { color: var(--danger); font-weight: 600; }

.cve-description { font-size: var(--fs-md); color: var(--text-dim); line-height: 1.7; }

.cve-section { margin-top: 1.5rem; }
.cve-section-title { cursor: default; }
details > .cve-section-title { cursor: pointer; }
.cve-products {
  list-style: none;
  display: flex; flex-wrap: wrap; gap: 0.5rem;
  margin-top: 0.7rem;
}
.cve-products li {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  padding: 0.25rem 0.6rem;
  border: 1px solid var(--border-med);
  border-radius: 3px;
  color: var(--text-dim);
}
.cve-more { font-size: var(--fs-sm); color: var(--text-muted); margin-top: 0.6rem; }

.cve-table { width: 100%; border-collapse: collapse; margin-top: 0.8rem; font-size: var(--fs-sm); }
.cve-table th {
  text-align: left; font-weight: 600; color: var(--text-muted);
  padding: 0.4rem 0.6rem 0.4rem 0;
  border-bottom: 1px solid var(--border-med);
}
.cve-table td { padding: 0.45rem 0.6rem 0.45rem 0; color: var(--text-dim); border-bottom: 1px solid var(--border); word-break: break-word; }

.cve-sources { margin-top: 1.5rem; font-size: var(--fs-sm); color: var(--text-muted); }

@media (max-width: 520px) {
  .cve-btn { width: 100%; }
}
</style>
