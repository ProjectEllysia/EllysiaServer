<template>
  <ToolShell tool-id="cidrCalculator" more-to="/themis/escaneos">
    <div class="cd">
      <div class="cd-field">
        <label class="cd-label" for="cd-input">{{ t('freeTools.items.cidrCalculator.inputLabel') }}</label>
        <input
          id="cd-input"
          v-model="rawNetwork"
          class="cd-input"
          type="text"
          autocomplete="off"
          spellcheck="false"
          :placeholder="EXAMPLE"
          :aria-invalid="hasError"
          aria-describedby="cd-hint"
        />
        <p id="cd-hint" class="cd-hint" :class="{ 'cd-hint--error': hasError }">
          {{ hasError ? t(`freeTools.items.cidrCalculator.errors.${parsed.reason}`) : t('freeTools.items.cidrCalculator.hint') }}
        </p>
      </div>

      <template v-if="network">
        <header ref="resultHead" class="cd-head">
          <p class="cd-cidr">{{ network.cidr }}</p>
          <span class="cd-kind">{{ t(`freeTools.items.cidrCalculator.kinds.${network.kind}`) }}</span>
        </header>

        <!-- Los 32 bits de la dirección: rellenos, los de red; vacíos, los de equipo. -->
        <figure class="cd-ribbon" :aria-label="t('freeTools.items.cidrCalculator.ribbonLabel', { network: network.prefix, hosts: 32 - network.prefix })">
          <div class="cd-bits" aria-hidden="true">
            <span
              v-for="bit in 32"
              :key="bit"
              class="cd-bit"
              :class="{ 'cd-bit--network': bit <= network.prefix, 'cd-bit--gap': bit % 8 === 1 && bit > 1 }"
              :style="{ '--bit': bit }"
            ></span>
          </div>
          <div class="cd-octets" aria-hidden="true">
            <span v-for="(octet, index) in networkOctets" :key="index" class="cd-octet">{{ octet }}</span>
          </div>
          <figcaption class="cd-legend">
            <span class="cd-legend-item cd-legend-item--network">{{ t('freeTools.items.cidrCalculator.networkBits', { count: network.prefix }) }}</span>
            <span class="cd-legend-item">{{ t('freeTools.items.cidrCalculator.hostBits', { count: 32 - network.prefix }) }}</span>
          </figcaption>
        </figure>

        <dl class="cd-facts">
          <div v-for="(fact, index) in facts" :key="fact.key" class="cd-fact mo-rise" :style="{ '--delay': `${0.1 + index * 0.06}s` }">
            <dt>{{ t(`freeTools.items.cidrCalculator.facts.${fact.key}`) }}</dt>
            <dd>{{ fact.value }}</dd>
          </div>
        </dl>

        <section v-if="canSplit" class="cd-split">
          <label class="cd-label" for="cd-split-select">{{ t('freeTools.items.cidrCalculator.splitLabel') }}</label>
          <select id="cd-split-select" v-model.number="splitPrefix" class="cd-select">
            <option :value="0">{{ t('freeTools.items.cidrCalculator.splitNone') }}</option>
            <option v-for="option in splitOptions" :key="option" :value="option">
              {{ t('freeTools.items.cidrCalculator.splitOption', { prefix: option, count: formatNumber(2 ** (option - network.prefix)) }) }}
            </option>
          </select>
          <template v-if="subnets">
            <ul class="cd-subnets">
              <li v-for="subnet in subnets.subnets" :key="subnet">{{ subnet }}</li>
            </ul>
            <p v-if="subnets.hidden" class="cd-more">{{ t('freeTools.items.cidrCalculator.andMore', { count: formatNumber(subnets.hidden) }) }}</p>
          </template>
        </section>
      </template>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import { revealResult } from '@/composables/revealResult'
import { formatNumber } from '@/i18n/format'
import { describeNetwork, parseNetwork, splitNetwork } from '@/components/freeTools/cidr'

/**
 * Calculadora de rangos de red gratuita de Themis.
 *
 * Todo se calcula en el navegador, según se escribe. La red va en `?q=` para
 * poder compartir el resultado con un enlace.
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

/** Ejemplo que se enseña mientras el campo está vacío. */
const EXAMPLE = '10.0.0.0/22'
/** Cuántas subredes se listan como mucho al dividir. */
const SPLIT_LIST_LIMIT = 32
/** Cuántos prefijos más largos se ofrecen al dividir. */
const SPLIT_DEPTH = 8

const rawNetwork = ref('')
const splitPrefix = ref(0)
const resultHead = ref(null)
/** Mientras se rellena el campo desde un enlace compartido, el resultado no se lleva a la vista. */
let isRestoring = false

const parsed = computed(() => parseNetwork(rawNetwork.value))
// Un campo vacío no es un error: todavía no se ha escrito nada.
const hasError = computed(() => rawNetwork.value.trim() !== '' && !parsed.value.ok)
const network = computed(() => (parsed.value.ok ? describeNetwork(parsed.value.address, parsed.value.prefix) : null))
const networkOctets = computed(() => network.value.network.split('.'))

const facts = computed(() => [
  { key: 'netmask', value: network.value.netmask },
  { key: 'wildcard', value: network.value.wildcard },
  { key: 'network', value: network.value.network },
  { key: 'broadcast', value: network.value.broadcast },
  { key: 'firstHost', value: network.value.firstHost },
  { key: 'lastHost', value: network.value.lastHost },
  { key: 'total', value: formatNumber(network.value.total) },
  { key: 'usable', value: formatNumber(network.value.usable) },
])

const canSplit = computed(() => network.value !== null && network.value.prefix < 32)
const splitOptions = computed(() => {
  const first = network.value.prefix + 1
  return Array.from({ length: Math.min(SPLIT_DEPTH, 32 - network.value.prefix) }, (_, index) => first + index)
})
const subnets = computed(() => {
  if (!network.value || !splitPrefix.value) return null
  return splitNetwork(parsed.value.address, network.value.prefix, splitPrefix.value, SPLIT_LIST_LIMIT)
})

// Otra red, otra división: la elegida puede no existir ya.
watch(() => network.value?.prefix, () => { splitPrefix.value = 0 })

// La red válida va a la URL, para compartirla. Cuando el resultado aparece (la red
// escrita pasa a ser válida), se lleva a la vista si quedó por debajo.
watch(network, async (current, previous) => {
  router.replace({ query: current ? { q: current.cidr } : {} })
  if (!current || previous || isRestoring) return
  await nextTick()
  revealResult(resultHead.value)
})

onMounted(async () => {
  if (typeof route.query.q !== 'string') return
  isRestoring = true
  rawNetwork.value = route.query.q
  await nextTick()
  isRestoring = false
})
</script>

<style scoped>
.cd { display: flex; flex-direction: column; gap: 1.5rem; }

.cd-label, .cd-fact dt {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}

.cd-field { display: flex; flex-direction: column; gap: 0.55rem; }
.cd-input, .cd-select {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  letter-spacing: 0.04em;
  padding: 0.75rem 0.9rem;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
}
.cd-select { font-size: var(--fs-md); }
.cd-input::placeholder { color: var(--text-muted); }
.cd-input:focus-visible, .cd-select:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; }
.cd-input[aria-invalid="true"] { border-color: var(--danger); }
.cd-hint, .cd-more { font-size: var(--fs-sm); color: var(--text-muted); }
.cd-hint--error { color: var(--danger); }

/* ── Cabecera ── */
.cd-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding-top: 1.2rem; border-top: 1px solid var(--border-med); }
.cd-cidr {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-2xl); font-weight: 600;
  color: var(--text);
  word-break: break-all;
}
.cd-kind {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--accent);
  border-radius: 3px;
  color: var(--accent-bright);
}

/* ── Cinta de bits: lo que distingue esta herramienta ── */
.cd-ribbon { margin: 0; }
.cd-bits { display: grid; grid-template-columns: repeat(32, 1fr); gap: 2px; }
.cd-bit {
  height: 1.7rem;
  border: 1px solid var(--border-med);
  border-radius: 2px;
  /* Al mover la frontera entre red y equipo, los bits cambian en cascada, de izquierda a derecha. */
  transition: background-color 0.35s ease calc(var(--bit) * 16ms), border-color 0.35s ease calc(var(--bit) * 16ms), transform 0.35s var(--ease-settle) calc(var(--bit) * 16ms);
}
.cd-bit--network { background: var(--accent); border-color: var(--accent); }
/* Cada octeto empieza con un hueco, para contar de ocho en ocho. */
.cd-bit--gap { margin-left: 0.35rem; }
.cd-octets { display: grid; grid-template-columns: repeat(4, 1fr); margin-top: 0.5rem; }
.cd-octet {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-md);
  text-align: center;
  color: var(--text-dim);
}
.cd-legend { display: flex; gap: 1.4rem; flex-wrap: wrap; margin-top: 0.8rem; }
.cd-legend-item {
  display: inline-flex; align-items: center; gap: 0.5rem;
  font-size: var(--fs-sm); color: var(--text-muted);
}
.cd-legend-item::before { content: ''; width: 0.8rem; height: 0.8rem; border: 1px solid var(--border-med); border-radius: 2px; }
.cd-legend-item--network::before { background: var(--accent); border-color: var(--accent); }

/* ── Datos ── */
.cd-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 1rem 1.5rem; }
.cd-fact dd {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-lg);
  color: var(--text);
  margin-top: 0.2rem;
  word-break: break-all;
}

/* ── División en subredes ── */
.cd-split { display: flex; flex-direction: column; align-items: flex-start; gap: 0.6rem; padding-top: 1.2rem; border-top: 1px solid var(--border-med); }
.cd-subnets { list-style: none; display: flex; flex-wrap: wrap; gap: 0.5rem; }
.cd-subnets li {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  padding: 0.25rem 0.6rem;
  border: 1px solid var(--border-med);
  border-radius: 3px;
  color: var(--text-dim);
}

@media (max-width: 520px) {
  .cd-bit { height: 1.3rem; }
  .cd-bit--gap { margin-left: 0.2rem; }
}
</style>
