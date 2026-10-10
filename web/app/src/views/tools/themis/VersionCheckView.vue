<template>
  <ToolShell tool-id="versionCheck" more-to="/themis/escaneos">
    <form class="vc-form" novalidate @submit.prevent="check()">
      <div class="vc-fields">
        <div class="vc-field">
          <label class="vc-label" for="vc-product">{{ t('freeTools.items.versionCheck.productLabel') }}</label>
          <input
            id="vc-product"
            v-model="product"
            class="vc-input"
            type="text"
            autocomplete="off"
            spellcheck="false"
            :maxlength="MAX_PRODUCT_LENGTH"
            :placeholder="t('freeTools.items.versionCheck.productPlaceholder')"
          />
        </div>
        <div class="vc-field">
          <label class="vc-label" for="vc-version">{{ t('freeTools.items.versionCheck.versionLabel') }}</label>
          <input
            id="vc-version"
            v-model="version"
            class="vc-input"
            type="text"
            autocomplete="off"
            autocapitalize="none"
            spellcheck="false"
            placeholder="1.18.0"
            :aria-invalid="hasInvalidVersion"
            aria-describedby="vc-version-hint"
          />
        </div>
      </div>
      <p id="vc-version-hint" class="vc-hint" :class="{ 'vc-hint--error': hasInvalidVersion }">
        {{ hasInvalidVersion ? t('freeTools.items.versionCheck.invalidVersion') : t('freeTools.items.versionCheck.hint') }}
      </p>
      <div class="vc-actions">
        <button type="submit" class="vc-btn" :disabled="isLoading || !canCheck">
          {{ isLoading ? t('freeTools.items.versionCheck.checking') : t('freeTools.items.versionCheck.check') }}
        </button>
        <div class="vc-examples">
          <span class="vc-label">{{ t('freeTools.items.versionCheck.examplesLabel') }}</span>
          <button
            v-for="example in VERSION_EXAMPLES"
            :key="example.product"
            type="button"
            class="vc-example"
            @click="product = example.product; version = example.version; check()"
          >
            {{ example.product }} {{ example.version }}
          </button>
        </div>
      </div>
    </form>

    <div ref="outcome" class="vc-outcome" aria-live="polite">
      <p v-if="status === 'error'" class="vc-message vc-message--error">{{ t('freeTools.items.versionCheck.failed') }}</p>
      <p v-else-if="status === 'done' && !result.recognized" class="vc-message">
        {{ t('freeTools.items.versionCheck.unknown', { product: checked.product }) }}
      </p>
      <article v-else-if="status === 'done'" :key="`${checked.product}@${checked.version}`" class="vc-card mo-rise">
        <header class="vc-card-head">
          <h2 class="vc-title">{{ checked.product }} {{ checked.version }}</h2>
          <p v-if="result.vendor" class="vc-cpe">{{ t('freeTools.items.versionCheck.identifiedAs', { cpe: `${result.vendor}:${result.product}:${result.version}` }) }}</p>
        </header>

        <p v-if="eolState" class="vc-eol" :data-state="eolState">
          {{ t(`freeTools.items.versionCheck.endOfLife.${eolState}`, { date: formatDate(result.endOfLife.date), cycle: result.endOfLife.cycle }) }}
        </p>

        <p class="vc-summary">
          {{ result.cvesTotal ? t('freeTools.items.versionCheck.found', { count: formatNumber(result.cvesTotal) }) : t('freeTools.items.versionCheck.none') }}
        </p>

        <table v-if="result.cves.length" class="vc-table">
          <thead>
            <tr>
              <th scope="col">{{ t('freeTools.items.versionCheck.columns.cve') }}</th>
              <th scope="col">{{ t('freeTools.items.versionCheck.columns.severity') }}</th>
              <th scope="col">{{ t('freeTools.items.versionCheck.columns.exploited') }}</th>
              <th scope="col">{{ t('freeTools.items.versionCheck.columns.epss') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="cve in result.cves" :key="cve.cveId" :data-severity="cvssSeverity(cve.cvssScore)">
              <th scope="row"><router-link :to="{ path: CVE_TOOL_PATH, query: { id: cve.cveId } }" class="vc-cve">{{ cve.cveId }}</router-link></th>
              <td>
                <span class="vc-badge">{{ t(severityLabelKey(cvssSeverity(cve.cvssScore))) }}</span>
                <span v-if="typeof cve.cvssScore === 'number'" class="vc-score">{{ formatNumber(cve.cvssScore, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) }}</span>
              </td>
              <td :class="{ 'vc-yes': cve.inKev }">{{ cve.inKev ? t('freeTools.items.versionCheck.exploitedYes') : '—' }}</td>
              <td>{{ epssPercent(cve.epssScore) === null ? '—' : `${formatNumber(epssPercent(cve.epssScore))} %` }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="hiddenCves" class="vc-more">{{ t('freeTools.items.versionCheck.andMore', { count: formatNumber(hiddenCves) }) }}</p>

        <p class="vc-note">{{ t('freeTools.items.versionCheck.backportsNote') }}</p>
      </article>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import { revealResult } from '@/composables/revealResult'
import { formatDate, formatNumber } from '@/i18n/format'
import { FREE_TOOLS, freeToolPath } from '@/freeTools/catalog'
import { epssPercent, hiddenCount, severityLabelKey } from '@/components/freeTools/cveLookup'
import {
  MAX_PRODUCT_LENGTH,
  VERSION_EXAMPLES,
  cvssSeverity,
  endOfLifeState,
  isProduct,
  isVersion,
} from '@/components/freeTools/versionCheck'

/**
 * «¿Es vulnerable mi versión?», la herramienta gratuita de Themis.
 *
 * Pregunta a `GET /themis/kb/version`, que no pide sesión y pasa el producto y la
 * versión por el motor de Lybra contra la base local de NVD, KEV y EPSS, más el
 * catálogo de fin de soporte. Lo consultado va en la URL para poder compartirlo, y
 * cada CVE enlaza a la consulta de CVE con su ficha.
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const CVE_TOOL_PATH = freeToolPath(FREE_TOOLS.find((tool) => tool.id === 'cveLookup'))

const product = ref('')
const version = ref('')
const status = ref('idle') // idle | loading | done | error
const result = ref(null)
const checked = ref({ product: '', version: '' })
const hasAttempted = ref(false)
const outcome = ref(null)

const isLoading = computed(() => status.value === 'loading')
const canCheck = computed(() => isProduct(product.value) && version.value.trim() !== '')
// El aviso de formato solo aparece tras un intento, no mientras se escribe.
const hasInvalidVersion = computed(() => hasAttempted.value && !isVersion(version.value))
const eolState = computed(() => endOfLifeState(result.value?.endOfLife))
const hiddenCves = computed(() => hiddenCount(result.value?.cves, result.value?.cvesTotal))

/**
 * Consulta el producto y la versión escritos y enseña el resultado, llevándolo a la
 * vista si quedó por debajo.
 *
 * @param {boolean} [isFromLink=false] - Si la consulta la lanza un enlace compartido
 *   al abrir la página; entonces no se desplaza nada.
 */
async function check(isFromLink = false) {
  hasAttempted.value = true
  if (!isProduct(product.value) || !isVersion(version.value)) return

  const query = { product: product.value.trim(), version: version.value.trim() }
  status.value = 'loading'
  router.replace({ query })
  try {
    const response = await fetch(`/themis/kb/version?${new URLSearchParams(query)}`)
    if (!response.ok) {
      status.value = 'error'
      return
    }
    result.value = await response.json()
    checked.value = query
    status.value = 'done'
  } catch {
    status.value = 'error'
  }
  if (isFromLink) return
  await nextTick()
  revealResult(outcome.value)
}

// Un enlace compartido (`?product=…&version=…`) abre la página ya con el resultado.
onMounted(() => {
  const { product: fromLinkProduct, version: fromLinkVersion } = route.query
  if (typeof fromLinkProduct === 'string' && typeof fromLinkVersion === 'string') {
    product.value = fromLinkProduct
    version.value = fromLinkVersion
    check(true)
  }
})
</script>

<style scoped>
.vc-label, .vc-table thead th {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Formulario ── */
.vc-form { display: flex; flex-direction: column; gap: 0.6rem; }
.vc-fields { display: grid; grid-template-columns: 3fr 2fr; gap: 1rem 1.2rem; }
.vc-field { display: flex; flex-direction: column; gap: 0.45rem; }
.vc-input {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  padding: 0.75rem 0.9rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  min-width: 0;
}
.vc-input::placeholder { color: var(--text-muted); }
.vc-input[aria-invalid="true"] { border-color: var(--danger); }
.vc-input:focus-visible, .vc-btn:focus-visible, .vc-example:focus-visible, .vc-cve:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }
.vc-hint { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
.vc-hint--error { color: var(--danger); }
.vc-actions { display: flex; align-items: center; gap: 1rem 1.4rem; flex-wrap: wrap; margin-top: 0.3rem; }
.vc-btn {
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
.vc-btn:hover:not(:disabled) { background: var(--accent-bright); border-color: var(--accent-bright); }
.vc-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.vc-examples { display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem; }
.vc-example {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  padding: 0.3rem 0.7rem;
  color: var(--text-dim);
  border: 1px solid var(--border-med);
  border-radius: 3px;
  transition: all var(--transition);
}
.vc-example:hover { border-color: var(--accent); color: var(--text); }

/* ── Resultado ── */
.vc-outcome { margin-top: 1.6rem; }
.vc-message { font-size: var(--fs-md); color: var(--text-dim); line-height: 1.6; }
.vc-message--error { color: var(--danger); }
.vc-card { padding-top: 1.2rem; border-top: 2px solid var(--accent); }
.vc-title {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-2xl); font-weight: 600;
  color: var(--text);
  overflow-wrap: anywhere;
}
.vc-cpe { margin-top: 0.3rem; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-muted); }

/* El fin de soporte es lo primero que hay que leer cuando ya pasó: ningún parche llegará. */
.vc-eol { margin-top: 1.1rem; padding: 0.7rem 0.9rem; border-left: 2px solid var(--success); font-size: var(--fs-md); color: var(--text); background: var(--bg); }
.vc-eol[data-state="past"] { border-left-color: var(--danger); color: var(--danger); font-weight: 600; }
.vc-summary { margin-top: 1.1rem; font-size: var(--fs-lg); color: var(--text); }

.vc-table { width: 100%; border-collapse: collapse; margin-top: 0.8rem; }
.vc-table th, .vc-table td { text-align: left; padding: 0.55rem 0.8rem 0.55rem 0; border-bottom: 1px solid var(--border); }
.vc-table thead th { font-weight: 400; border-bottom-color: var(--border-med); }
.vc-table td { font-size: var(--fs-md); color: var(--text-dim); }
.vc-table tbody tr { --severity: var(--text-muted); }
.vc-table tbody tr[data-severity="critical"] { --severity: var(--danger); }
.vc-table tbody tr[data-severity="high"] { --severity: var(--warn); }
.vc-table tbody tr[data-severity="medium"] { --severity: var(--accent-bright); }
.vc-table tbody tr[data-severity="low"] { --severity: var(--success); }
.vc-cve { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-md); font-weight: 400; color: var(--text); text-decoration: underline; text-decoration-color: var(--border-med); text-underline-offset: 3px; }
.vc-cve:hover { text-decoration-color: var(--accent); }
.vc-badge {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-xs, 0.75rem);
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.15rem 0.5rem;
  border: 1px solid var(--severity);
  border-radius: 3px;
  color: var(--severity);
}
.vc-score { margin-left: 0.5rem; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); color: var(--text); }
.vc-table td.vc-yes { color: var(--danger); font-weight: 600; }
.vc-more { margin-top: 0.6rem; font-size: var(--fs-sm); color: var(--text-muted); }
.vc-note { margin-top: 1.4rem; font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }

@media (max-width: 560px) {
  .vc-fields { grid-template-columns: 1fr; }
  .vc-btn { width: 100%; }
  .vc-table th:nth-child(4), .vc-table td:nth-child(4) { display: none; }
}
</style>
