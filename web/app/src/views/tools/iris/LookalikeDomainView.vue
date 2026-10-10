<template>
  <ToolShell tool-id="lookalikeDomain" more-to="/iris/analisis">
    <form class="ld-form" novalidate @submit.prevent="check()">
      <label class="ld-label" for="ld-input">{{ t('freeTools.items.lookalikeDomain.inputLabel') }}</label>
      <div class="ld-row">
        <input
          id="ld-input"
          v-model="rawDomain"
          class="ld-input"
          type="text"
          autocomplete="off"
          autocapitalize="none"
          spellcheck="false"
          :placeholder="t('freeTools.items.lookalikeDomain.placeholder')"
          :aria-invalid="status === 'invalid'"
          aria-describedby="ld-hint"
        />
        <button type="submit" class="ld-btn" :disabled="isLoading || !rawDomain.trim()">
          {{ isLoading ? t('freeTools.items.lookalikeDomain.checking') : t('freeTools.items.lookalikeDomain.check') }}
        </button>
      </div>
      <p id="ld-hint" class="ld-hint" :class="{ 'ld-hint--error': status === 'invalid' }">
        {{ status === 'invalid' ? t('freeTools.items.lookalikeDomain.invalid') : t('freeTools.items.lookalikeDomain.hint') }}
      </p>
      <div class="ld-examples">
        <span class="ld-label">{{ t('freeTools.items.lookalikeDomain.examplesLabel') }}</span>
        <button v-for="example in DOMAIN_EXAMPLES" :key="example" type="button" class="ld-example" @click="rawDomain = example; check()">
          {{ example }}
        </button>
      </div>
    </form>

    <div ref="outcome" class="ld-outcome" aria-live="polite">
      <p v-if="status === 'error'" class="ld-message ld-message--error">{{ t('freeTools.items.lookalikeDomain.failed') }}</p>
      <article v-else-if="status === 'done'" :key="result.domain" class="ld-card mo-rise" :data-verdict="verdict">
        <h2 class="ld-verdict">
          {{ t(`freeTools.items.lookalikeDomain.verdict.${verdict}`, { brand: result.ownBrand ?? result.findings[0]?.brand ?? '' }) }}
        </h2>

        <dl class="ld-facts">
          <div v-for="fact in facts" :key="fact.key" class="ld-fact">
            <dt>{{ t(`freeTools.items.lookalikeDomain.${fact.key}`) }}</dt>
            <!-- Un dominio largo se parte por sus puntos, nunca a mitad de una etiqueta. -->
            <dd class="ld-domain"><template v-for="(part, index) in fact.value.split('.')" :key="index"><wbr v-if="index" />{{ index ? '.' : '' }}{{ part }}</template></dd>
          </div>
        </dl>

        <ul v-if="result.findings.length" class="ld-findings">
          <li v-for="(finding, index) in result.findings" :key="`${finding.type}-${finding.label}`" class="mo-rise" :style="{ '--delay': `${0.2 + index * 0.08}s` }">
            {{ t(findingLabelKey(finding.type), {
              brand: finding.brand ?? '',
              label: finding.label ?? '',
              action: finding.action ?? '',
              scripts: finding.scripts.map((script) => scriptName(script, t)).join(', '),
            }) }}
          </li>
        </ul>

        <p class="ld-note">{{ t('freeTools.items.lookalikeDomain.note') }}</p>
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
import { DOMAIN_EXAMPLES, findingLabelKey, scriptName, verdictOf } from '@/components/freeTools/lookalikeDomain'

/**
 * Detector de dominios engañosos gratuito de Iris.
 *
 * Pregunta a `GET /iris/tools/domain`, que no pide sesión y pasa el dominio por las
 * mismas reglas que juzgan al remitente en un análisis de Iris. El dominio consultado
 * va en `?domain=` para que el resultado se pueda compartir con un enlace.
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const rawDomain = ref('')
const status = ref('idle') // idle | loading | done | invalid | error
const result = ref(null)
const outcome = ref(null)

const isLoading = computed(() => status.value === 'loading')
const verdict = computed(() => (result.value ? verdictOf(result.value) : null))
/** Cómo se lee el dominio, cómo viaja (solo si es distinto) y cuál es el que se compra. */
const facts = computed(() => {
  if (!result.value) return []
  const { unicodeDomain, domain, registrableDomain } = result.value
  return [
    { key: 'reads', value: unicodeDomain },
    ...(domain !== unicodeDomain ? [{ key: 'travels', value: domain }] : []),
    { key: 'registrable', value: registrableDomain },
  ]
})

/**
 * Consulta el dominio escrito y enseña el resultado, llevándolo a la vista si quedó
 * por debajo.
 *
 * @param {boolean} [isFromLink=false] - Si la consulta la lanza un enlace compartido
 *   al abrir la página; entonces no se desplaza nada.
 */
async function check(isFromLink = false) {
  const domain = rawDomain.value.trim()
  if (!domain) return

  status.value = 'loading'
  router.replace({ query: { domain } })
  try {
    const response = await fetch(`/iris/tools/domain?domain=${encodeURIComponent(domain)}`)
    // 400 y 422 son siempre «eso no es un dominio»: se dice con el texto de la
    // interfaz, en el idioma de quien la usa, y no con el del servidor.
    if (response.status === 400 || response.status === 422) {
      status.value = 'invalid'
      return
    }
    if (!response.ok) {
      status.value = 'error'
      return
    }
    result.value = await response.json()
    status.value = 'done'
  } catch {
    status.value = 'error'
  }
  if (isFromLink) return
  await nextTick()
  revealResult(outcome.value)
}

// Un enlace compartido (`?domain=…`) abre la página ya con el resultado.
onMounted(() => {
  if (typeof route.query.domain === 'string' && route.query.domain.trim()) {
    rawDomain.value = route.query.domain
    check(true)
  }
})
</script>

<style scoped>
.ld-label, .ld-fact dt {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Formulario ── */
.ld-form { display: flex; flex-direction: column; gap: 0.6rem; }
.ld-row { display: flex; gap: 0.8rem; flex-wrap: wrap; }
.ld-input {
  flex: 1 1 14rem;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  padding: 0.75rem 0.9rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
}
.ld-input::placeholder { color: var(--text-muted); }
.ld-input[aria-invalid="true"] { border-color: var(--danger); }
.ld-input:focus-visible, .ld-btn:focus-visible, .ld-example:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }
.ld-btn {
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
.ld-btn:hover:not(:disabled) { background: var(--accent-bright); border-color: var(--accent-bright); }
.ld-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.ld-hint { font-size: var(--fs-sm); color: var(--text-muted); }
.ld-hint--error { color: var(--danger); }

/* Los ejemplos se escriben como el dominio que son: el cirílico no se distingue a simple vista, y de eso va la herramienta. */
.ld-examples { display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.3rem; }
.ld-example {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  padding: 0.3rem 0.7rem;
  color: var(--text-dim);
  border: 1px solid var(--border-med);
  border-radius: 3px;
  transition: all var(--transition);
}
.ld-example:hover { border-color: var(--accent); color: var(--text); }

/* ── Resultado ── */
.ld-outcome { margin-top: 1.6rem; }
.ld-message { font-size: var(--fs-md); color: var(--text-dim); }
.ld-message--error { color: var(--danger); }

/* El color del veredicto solo lo lleva el filete y el titular. */
.ld-card { --verdict: var(--text-muted); padding-top: 1.2rem; border-top: 2px solid var(--verdict); }
.ld-card[data-verdict="suspicious"] { --verdict: var(--danger); }
.ld-card[data-verdict="ownBrand"] { --verdict: var(--success); }
.ld-verdict {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-2xl); font-weight: 600; line-height: 1.25;
  color: var(--verdict);
}
.ld-card[data-verdict="clean"] .ld-verdict { color: var(--text); }

.ld-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: 1rem 1.5rem; margin: 1.3rem 0; }
.ld-fact dd { margin-top: 0.2rem; }
.ld-domain { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-lg); color: var(--text); overflow-wrap: anywhere; }

.ld-findings { display: flex; flex-direction: column; gap: 0.6rem; padding-left: 1.1rem; }
.ld-findings li { font-size: var(--fs-md); color: var(--text-dim); line-height: 1.6; }
.ld-findings li::marker { color: var(--danger); }

.ld-note { margin-top: 1.5rem; font-size: var(--fs-sm); color: var(--text-muted); line-height: 1.5; }

@media (max-width: 520px) {
  .ld-btn { width: 100%; }
}
</style>
