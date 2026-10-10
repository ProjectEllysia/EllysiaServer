<template>
  <ToolShell tool-id="headerAnalyzer" more-to="/iris/analisis">
    <form class="ha-form" novalidate @submit.prevent="analyze()">
      <div class="ha-label-row">
        <label class="ha-label" for="ha-input">{{ t('freeTools.items.headerAnalyzer.inputLabel') }}</label>
        <button type="button" class="ha-sample" @click="rawHeaders = SAMPLE_HEADERS">{{ t('freeTools.items.headerAnalyzer.useSample') }}</button>
      </div>
      <textarea
        id="ha-input"
        v-model="rawHeaders"
        class="ha-input"
        rows="9"
        autocomplete="off"
        autocapitalize="none"
        spellcheck="false"
        :aria-invalid="Boolean(rejection)"
        aria-describedby="ha-hint"
      ></textarea>
      <p id="ha-hint" class="ha-hint" :class="{ 'ha-hint--error': rejection }">
        {{ rejection ? t(`freeTools.items.headerAnalyzer.errors.${rejection}`) : t('freeTools.items.headerAnalyzer.hint') }}
      </p>
      <button type="submit" class="ha-btn" :disabled="isLoading || !rawHeaders.trim()">
        {{ isLoading ? t('freeTools.items.headerAnalyzer.reading') : t('freeTools.items.headerAnalyzer.read') }}
      </button>
    </form>

    <div ref="outcome" class="ha-outcome" aria-live="polite">
      <article v-if="result" class="ha-result mo-rise">
        <dl v-if="result.sender || result.subject" class="ha-envelope">
          <div v-if="result.sender"><dt>{{ t('freeTools.items.headerAnalyzer.sender') }}</dt><dd>{{ result.sender }}</dd></div>
          <div v-if="result.subject"><dt>{{ t('freeTools.items.headerAnalyzer.subject') }}</dt><dd>{{ result.subject }}</dd></div>
        </dl>

        <!-- Las tres comprobaciones y la alineación: qué es cada una y qué dijo para este correo. -->
        <section class="ha-section" aria-labelledby="ha-auth-title">
          <h2 id="ha-auth-title" class="ha-section-title">{{ t('freeTools.items.headerAnalyzer.authTitle') }}</h2>
          <ul class="ha-checks">
            <li
              v-for="(check, index) in result.auth"
              :key="check.check"
              class="ha-check mo-rise"
              :data-tone="verdictTone(check.verdict)"
              :style="{ '--delay': `${0.1 + index * 0.07}s` }"
            >
              <div class="ha-check-head">
                <span class="ha-check-name">{{ t(`freeTools.items.headerAnalyzer.checks.${check.check}.name`) }}</span>
                <span class="ha-badge">{{ t(verdictLabelKey(check.verdict)) }}</span>
              </div>
              <p class="ha-check-what">{{ t(`freeTools.items.headerAnalyzer.checks.${check.check}.what`) }}</p>
              <p v-if="check.check === 'alignment' && check.domains.length" class="ha-check-domains">
                {{ t('freeTools.items.headerAnalyzer.authenticated', { domains: check.domains.join(', '), from: result.fromDomain ?? '—' }) }}
              </p>
            </li>
          </ul>
        </section>

        <section class="ha-section" aria-labelledby="ha-path-title">
          <h2 id="ha-path-title" class="ha-section-title">{{ t('freeTools.items.headerAnalyzer.pathTitle') }}</h2>
          <p class="ha-section-lead">{{ t('freeTools.items.headerAnalyzer.pathLead') }}</p>
          <IrisEmailPath :hops="result.path.hops" :transitions="result.path.transitions" />
        </section>

        <p class="ha-note">{{ t('freeTools.items.headerAnalyzer.note') }}</p>
      </article>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import IrisEmailPath from '@/components/iris/IrisEmailPath.vue'
import { revealResult } from '@/composables/revealResult'
import { SAMPLE_HEADERS, rejectionReason, verdictLabelKey, verdictTone } from '@/components/freeTools/headerAnalyzer'

/**
 * Analizador de cabeceras gratuito de Iris.
 *
 * Manda lo pegado a `POST /iris/tools/headers`, que no pide sesión y lo lee con las
 * mismas reglas que un análisis de Iris: la ruta salto a salto y lo que dicen SPF,
 * DKIM y DMARC. No hay veredicto ni se guarda nada. A diferencia de las otras
 * herramientas, lo consultado no va en la URL: unas cabeceras llevan direcciones de
 * correo y no deben acabar en un enlace ni en el historial.
 */
const { t } = useI18n()

const rawHeaders = ref('')
const isLoading = ref(false)
const result = ref(null)
const rejection = ref(null) // null | tooLong | notHeaders | failed
const outcome = ref(null)

/** Lee las cabeceras pegadas y lleva el resultado a la vista. */
async function analyze() {
  const headers = rawHeaders.value
  if (!headers.trim()) return

  isLoading.value = true
  rejection.value = null
  try {
    const response = await fetch('/iris/tools/headers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ headers }),
    })
    if (!response.ok) {
      rejection.value = rejectionReason(response.status, headers)
      result.value = null
      return
    }
    result.value = await response.json()
  } catch {
    rejection.value = 'failed'
    result.value = null
  } finally {
    isLoading.value = false
  }
  await nextTick()
  revealResult(outcome.value)
}
</script>

<style scoped>
.ha-label, .ha-envelope dt {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Formulario ── */
.ha-form { display: flex; flex-direction: column; gap: 0.6rem; }
.ha-label-row { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.ha-sample { font-size: var(--fs-sm); color: var(--accent-bright); text-decoration: underline; text-underline-offset: 3px; }
.ha-sample:hover { color: var(--text); }
.ha-input {
  width: 100%;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  line-height: 1.55;
  padding: 0.75rem 0.9rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
  resize: vertical;
}
.ha-input[aria-invalid="true"] { border-color: var(--danger); }
.ha-input:focus-visible, .ha-btn:focus-visible, .ha-sample:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }
.ha-hint { font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }
.ha-hint--error { color: var(--danger); }
.ha-btn {
  align-self: flex-start;
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
.ha-btn:hover:not(:disabled) { background: var(--accent-bright); border-color: var(--accent-bright); }
.ha-btn:disabled { opacity: 0.6; cursor: not-allowed; }

/* ── Resultado ── */
.ha-outcome { margin-top: 1.6rem; }
.ha-result { padding-top: 1.2rem; border-top: 1px solid var(--border-med); }
.ha-envelope { display: flex; flex-direction: column; gap: 0.7rem; }
.ha-envelope dd { margin-top: 0.15rem; font-size: var(--fs-md); color: var(--text); overflow-wrap: anywhere; }

.ha-section { margin-top: 1.8rem; }
.ha-section-title {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-xl); font-weight: 600;
  color: var(--text);
}
.ha-section-lead { margin: 0.3rem 0 1rem; font-size: var(--fs-md); color: var(--text-dim); line-height: 1.6; }

/* El tono del veredicto solo lo llevan la insignia y el filete de la izquierda. */
.ha-checks { list-style: none; display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: 0.9rem; margin-top: 0.9rem; }
.ha-check { --tone: var(--text-muted); padding: 0.8rem 1rem; border-left: 2px solid var(--tone); background: var(--bg); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
.ha-check[data-tone="good"] { --tone: var(--success); }
.ha-check[data-tone="bad"] { --tone: var(--danger); }
.ha-check[data-tone="warn"] { --tone: var(--warn); }
.ha-check-head { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; }
.ha-check-name { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.ha-badge {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-xs, 0.75rem);
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.15rem 0.5rem;
  border: 1px solid var(--tone);
  border-radius: 3px;
  color: var(--tone);
}
.ha-check-what { margin-top: 0.45rem; font-size: var(--fs-sm); color: var(--text-dim); line-height: 1.5; }
.ha-check-domains { margin-top: 0.4rem; font-size: var(--fs-sm); color: var(--text); line-height: 1.5; overflow-wrap: anywhere; }

.ha-note { margin-top: 1.6rem; font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }

@media (max-width: 520px) {
  .ha-btn { width: 100%; }
}
</style>
