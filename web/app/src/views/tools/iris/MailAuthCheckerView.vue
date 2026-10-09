<template>
  <ToolShell tool-id="mailAuthChecker" more-to="/iris/analisis">
    <form class="ma-form" novalidate @submit.prevent="check()">
      <div class="ma-field">
        <label class="ma-label" for="ma-domain">{{ t('freeTools.items.mailAuthChecker.domainLabel') }}</label>
        <div class="ma-row">
          <input
            id="ma-domain"
            v-model="rawDomain"
            class="ma-input"
            type="text"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            :placeholder="t('freeTools.items.mailAuthChecker.placeholder')"
            :aria-invalid="hasInvalidDomain"
            aria-describedby="ma-hint"
          />
          <button type="submit" class="ma-btn" :disabled="isLoading">
            {{ isLoading ? t('freeTools.items.mailAuthChecker.checking') : t('freeTools.items.mailAuthChecker.check') }}
          </button>
        </div>
        <p id="ma-hint" class="ma-hint" :class="{ 'ma-hint--error': hasInvalidDomain }">
          {{ hasInvalidDomain ? t('freeTools.items.mailAuthChecker.invalidDomain') : t('freeTools.items.mailAuthChecker.hint') }}
        </p>
      </div>

      <label class="ma-check">
        <input v-model="withDkim" type="checkbox" />
        <span>{{ t('freeTools.items.mailAuthChecker.withDkim') }}</span>
      </label>
      <div v-if="withDkim" class="ma-field">
        <label class="ma-label" for="ma-selector">{{ t('freeTools.items.mailAuthChecker.selectorLabel') }}</label>
        <input
          id="ma-selector"
          v-model="rawSelector"
          class="ma-input ma-input--short"
          type="text"
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          :placeholder="t('freeTools.items.mailAuthChecker.selectorPlaceholder')"
          :aria-invalid="hasInvalidSelector"
        />
        <p class="ma-hint" :class="{ 'ma-hint--error': hasInvalidSelector }">
          {{ hasInvalidSelector ? t('freeTools.items.mailAuthChecker.invalidSelector') : t('freeTools.items.mailAuthChecker.selectorHint') }}
        </p>
      </div>

      <p class="ma-privacy">{{ t('freeTools.items.mailAuthChecker.privacy') }}</p>
    </form>

    <div ref="outcome" class="ma-outcome" aria-live="polite">
      <p v-if="status === 'error'" class="ma-message ma-message--error">{{ t('freeTools.items.mailAuthChecker.failed') }}</p>
      <p v-else-if="status === 'done' && !result.exists" class="ma-message ma-message--error">
        {{ t('freeTools.items.mailAuthChecker.findings.domainNotFound') }}
      </p>

      <template v-else-if="status === 'done'">
        <h2 class="ma-domain">{{ result.domain }}</h2>
        <section v-for="(section, sectionIndex) in sections" :key="`${result.domain}-${section.key}`" class="ma-section mo-rise" :style="{ '--delay': `${sectionIndex * 0.16}s` }" :data-level="section.chip">
          <header class="ma-section-head">
            <div>
              <h3 class="ma-section-title">{{ section.key.toUpperCase() }}</h3>
              <p class="ma-section-sub">{{ t(`freeTools.items.mailAuthChecker.sections.${section.key}`) }}</p>
            </div>
            <span class="ma-chip mo-pop" :style="{ '--delay': `${sectionIndex * 0.16 + 0.35}s` }">{{ t(`freeTools.items.mailAuthChecker.levels.${section.chip}`) }}</span>
          </header>
          <code v-if="section.record" class="ma-record">{{ section.record }}</code>
          <ul class="ma-findings">
            <li v-for="(finding, findingIndex) in section.findings" :key="finding.code" class="ma-finding mo-rise" :style="{ '--delay': `${sectionIndex * 0.16 + 0.3 + findingIndex * 0.09}s` }" :data-level="finding.level">
              <span class="ma-finding-level">{{ t(`freeTools.items.mailAuthChecker.levels.${finding.level}`) }}</span>
              <span>{{ t(`freeTools.items.mailAuthChecker.findings.${finding.code}`, finding.params ?? {}) }}</span>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import { revealResult } from '@/composables/revealResult'
import { checkMailAuthentication, normalizeDomain, normalizeSelector, worstLevel } from '@/components/freeTools/mailAuth'

/**
 * Comprobador de SPF, DKIM y DMARC gratuito de Iris.
 *
 * Las consultas de DNS las hace el navegador a un servicio público de DNS sobre
 * HTTPS; no pasan por Ellysia. El dominio y el selector van en `?d=` y `?s=` para
 * poder compartir el resultado.
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const rawDomain = ref('')
const rawSelector = ref('')
const withDkim = ref(false)
const hasAttempted = ref(false)
const status = ref('idle') // idle | loading | done | error
const result = ref(null)
const outcome = ref(null)

const isLoading = computed(() => status.value === 'loading')
const hasInvalidDomain = computed(() => hasAttempted.value && normalizeDomain(rawDomain.value) === null)
const hasInvalidSelector = computed(() => hasAttempted.value && withDkim.value && normalizeSelector(rawSelector.value) === null)

// «Información» no es un problema: en la etiqueta de la sección cuenta como «Bien».
const chipOf = (findings) => {
  const worst = worstLevel(findings)
  return worst === 'info' ? 'ok' : worst
}
const sections = computed(() => {
  if (!result.value?.exists) return []
  const { spf, dkim, dmarc } = result.value
  return [['spf', spf], ['dkim', dkim], ['dmarc', dmarc]]
    .filter(([, analysis]) => analysis)
    .map(([key, analysis]) => ({ key, record: analysis.record, findings: analysis.findings, chip: chipOf(analysis.findings) }))
})

/**
 * Comprueba el dominio escrito y enseña el resultado, llevándolo a la vista si quedó
 * por debajo.
 *
 * @param {boolean} [isFromLink=false] - Si la comprobación la lanza un enlace compartido
 *   al abrir la página; entonces no se desplaza nada.
 */
async function check(isFromLink = false) {
  hasAttempted.value = true
  const domain = normalizeDomain(rawDomain.value)
  const selector = withDkim.value ? normalizeSelector(rawSelector.value) : null
  if (!domain || (withDkim.value && !selector)) return

  rawDomain.value = domain
  status.value = 'loading'
  router.replace({ query: { d: domain, ...(selector ? { s: selector } : {}) } })
  try {
    result.value = await checkMailAuthentication({ domain, selector })
    status.value = 'done'
  } catch {
    status.value = 'error'
  }
  if (isFromLink) return
  await nextTick()
  revealResult(outcome.value)
}

// Un enlace compartido abre la página ya con el resultado.
onMounted(() => {
  if (typeof route.query.d !== 'string' || !normalizeDomain(route.query.d)) return
  rawDomain.value = route.query.d
  if (typeof route.query.s === 'string' && normalizeSelector(route.query.s)) {
    rawSelector.value = route.query.s
    withDkim.value = true
  }
  check(true)
})
</script>

<style scoped>
.ma-label, .ma-finding-level {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Formulario ── */
.ma-form { display: flex; flex-direction: column; gap: 1rem; }
.ma-field { display: flex; flex-direction: column; gap: 0.55rem; }
.ma-row { display: flex; gap: 0.8rem; flex-wrap: wrap; }
.ma-input {
  flex: 1 1 14rem; min-width: 0;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  padding: 0.75rem 0.9rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
}
.ma-input--short { max-width: 18rem; }
.ma-input::placeholder { color: var(--text-muted); }
.ma-input:focus-visible, .ma-btn:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }
.ma-input[aria-invalid="true"] { border-color: var(--danger); }
.ma-btn {
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
.ma-btn:hover:not(:disabled) { background: var(--accent-bright); border-color: var(--accent-bright); }
.ma-btn:disabled { opacity: 0.6; cursor: progress; }
.ma-check { display: flex; align-items: center; gap: 0.6rem; font-size: var(--fs-md); color: var(--text-dim); cursor: pointer; }
.ma-check input { width: 1.05rem; height: 1.05rem; accent-color: var(--accent); }
.ma-hint, .ma-privacy { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.55; }
.ma-hint--error { color: var(--danger); }

/* ── Resultado ── */
.ma-outcome { margin-top: 1.6rem; display: flex; flex-direction: column; gap: 1.2rem; }
.ma-message { font-size: var(--fs-md); color: var(--text-dim); }
.ma-message--error { color: var(--danger); }
.ma-domain {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-xl); font-weight: 600;
  color: var(--text);
  word-break: break-all;
}

/* Cada protocolo es una tarjeta con su filete de color: lo único que cambia es el veredicto. */
.ma-section { --tone: var(--success); padding: 1.1rem 0 0; border-top: 2px solid var(--tone); }
.ma-section[data-level="warn"] { --tone: var(--warn); }
.ma-section[data-level="bad"] { --tone: var(--danger); }
.ma-section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.ma-section-title {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-xl); font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--text);
}
.ma-section-sub { font-size: var(--fs-sm); color: var(--text-muted); margin-top: 0.15rem; }
.ma-chip {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--tone);
  border-radius: 3px;
  color: var(--tone);
  white-space: nowrap;
}
.ma-record {
  display: block;
  margin-top: 0.9rem;
  padding: 0.7rem 0.9rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  color: var(--text-dim);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  word-break: break-all;
  white-space: pre-wrap;
}
.ma-findings { list-style: none; display: flex; flex-direction: column; gap: 0.6rem; margin-top: 0.9rem; }
.ma-finding { display: grid; grid-template-columns: 6.2rem 1fr; gap: 0.8rem; align-items: baseline; font-size: var(--fs-md); color: var(--text-dim); line-height: 1.55; }
.ma-finding[data-level="ok"] .ma-finding-level { color: var(--success); }
.ma-finding[data-level="warn"] .ma-finding-level { color: var(--warn); }
.ma-finding[data-level="bad"] .ma-finding-level { color: var(--danger); }

@media (max-width: 520px) {
  .ma-btn { width: 100%; }
  .ma-finding { grid-template-columns: 1fr; gap: 0.1rem; }
}
</style>
