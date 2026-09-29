<template>
  <div class="beyond">
    <!-- Superficie de API: lo que el escaneo encontró expuesto en las APIs de
         sus servicios web, agrupado por servicio, que es como se corrige. Se
         pide al abrir la placa, como los hallazgos. -->
    <section v-if="showsApiSurface" class="beyond-chapter">
      <h4 class="chapter-h">
        <button type="button" class="chapter-plate chapter-toggle" :class="{ open: isApiOpen }"
          :aria-expanded="isApiOpen" @click="toggleApi">
          <span class="chapter-head">
            <span class="chapter-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/><line x1="14" y1="4" x2="10" y2="20"/></svg>
            </span>
            <span class="chapter-text">
              <span class="chapter-title">{{ t('lybra.categories.api_exposure') }}
                <span v-if="apiSurface && !apiSurface.loading" class="chapter-count">{{ apiSurface.totalFindings }}</span></span>
              <span class="chapter-sub">{{ t('lybra.apiSurface.subtitle') }}</span>
            </span>
            <span class="chapter-action">
              {{ isApiOpen ? t('lybra.results.collapse') : t('lybra.results.expand') }}
              <span class="chevron" :class="{ rot: isApiOpen }" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
              </span>
            </span>
          </span>
        </button>
      </h4>
      <Transition name="chapter-panel">
        <div v-if="isApiOpen" class="chapter-body">
          <p v-if="apiSurface?.error" class="beyond-note error">{{ apiSurface.error }}</p>
          <p v-else-if="!apiSurface || (apiSurface.loading && !apiSurface.services.length)" class="beyond-note">{{ t('common.loading') }}</p>
          <p v-else-if="!apiSurface.services.length" class="beyond-note clean">{{ t('lybra.apiSurface.empty') }}</p>
          <div v-else class="api-services">
            <section v-for="service in apiSurface.services" :key="`${service.target}:${service.port}`" class="api-service">
              <header class="inscription">
                <span class="inscription-mark" aria-hidden="true"></span>
                <h5 class="inscription-title mono">{{ service.target }}:{{ service.port }}</h5>
                <span class="inscription-rule" aria-hidden="true"></span>
                <span class="inscription-tally">{{ service.service || t('lybra.apiSurface.unnamedService') }}</span>
              </header>
              <ul class="api-findings">
                <li v-for="finding in service.findings" :key="finding.id" class="api-finding">
                  <span class="f-prio" :class="(finding.severity || 'INFO').toLowerCase()">{{ priorityLabel(finding.severity) }}</span>
                  <span class="api-title">{{ finding.title }}</span>
                  <span v-if="finding.state && finding.state !== 'open'" class="api-state">{{ findingStateLabel(finding.state) }}</span>
                </li>
              </ul>
            </section>
          </div>
        </div>
      </Transition>
    </section>

    <!-- Riesgo lateral: solo en un escaneo de red, que es el único que tiene
         varios equipos entre los que moverse. No se guarda: se calcula al
         abrir la placa, sobre el último estado de cada equipo. -->
    <section v-if="showsLateral" class="beyond-chapter">
      <h4 class="chapter-h">
        <button type="button" class="chapter-plate chapter-toggle" :class="{ open: isLateralOpen }"
          :aria-expanded="isLateralOpen" @click="toggleLateral">
          <span class="chapter-head">
            <span class="chapter-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M7.3 11 16.7 6M7.3 13l9.4 5"/></svg>
            </span>
            <span class="chapter-text">
              <span class="chapter-title">{{ t('lybra.categories.lateral_risk') }}
                <span v-if="lateral && !lateral.loading && lateral.hostCount >= 2" class="chapter-count">{{ lateral.risks.length }}</span></span>
              <span class="chapter-sub">{{ t('lybra.lateral.subtitle') }}</span>
            </span>
            <span class="chapter-action">
              {{ isLateralOpen ? t('lybra.results.collapse') : t('lybra.results.expand') }}
              <span class="chevron" :class="{ rot: isLateralOpen }" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
              </span>
            </span>
          </span>
        </button>
      </h4>
      <Transition name="chapter-panel">
        <div v-if="isLateralOpen" class="chapter-body">
          <LateralRiskList :risks="lateral?.risks || []" :host-count="lateral?.hostCount || 0"
            :loading="!lateral || lateral.loading" :error="lateral?.error || null" />
        </div>
      </Transition>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useThemisStore } from '@/stores/themisStore'
import { useThemisNetworkStore } from '@/stores/themisNetworkStore'
import { priorityLabel, findingStateLabel } from '../labels'
import { isNetworkScan } from './beyondHost'
import LateralRiskList from './LateralRiskList.vue'

const { t } = useI18n()
const themisStore = useThemisStore()
const networkStore = useThemisNetworkStore()

const props = defineProps({
  /** El escaneo Lybra de la tarjeta, tal como llega del listado. */
  scan: { type: Object, required: true },
})

const isNetwork = computed(() => isNetworkScan(props.scan))

/**
 * Solo un escaneo terminado con hallazgos puede tener superficie de API. Un
 * escaneo de red la suma de sus equipos, y sus hallazgos no cuentan en su
 * propio recuento, así que ese se ofrece siempre.
 */
const showsApiSurface = computed(() => props.scan.status === 'finished' && (props.scan.totalFindings > 0 || isNetwork.value))
const showsLateral = computed(() => props.scan.status === 'finished' && isNetwork.value)

const isApiOpen = ref(false)
const isLateralOpen = ref(false)
const apiSurface = computed(() => themisStore.lybraApiSurface[props.scan.id] || null)
const lateral = computed(() => networkStore.riskByScope[`scan:${props.scan.id}`] || null)

function toggleApi() {
  isApiOpen.value = !isApiOpen.value
  if (isApiOpen.value && !apiSurface.value) themisStore.loadApiSurface(props.scan.id)
}

function toggleLateral() {
  isLateralOpen.value = !isLateralOpen.value
  if (isLateralOpen.value && !lateral.value) networkStore.loadRisk('scan', props.scan.id)
}
</script>

<style scoped>
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
.beyond { display: flex; flex-direction: column; gap: 0.6rem; }
.beyond:empty { display: none; }
.beyond-chapter { display: flex; flex-direction: column; }

/* Misma placa que los capítulos «Hallazgos» y «Documentos» de LybraResults.vue:
   son capítulos del mismo escaneo y se tienen que leer como tales. */
.chapter-h { margin: 0.35rem 0 0; font: inherit; }
.chapter-plate {
  position: relative; display: block; width: 100%; padding: 0;
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 220%);
  border: 1px solid var(--border-med); border-radius: 10px; overflow: hidden;
  color: inherit; font: inherit; text-align: left;
}
.chapter-toggle { cursor: pointer; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.chapter-toggle:hover { border-color: var(--accent); }
.chapter-toggle.open { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent-dim); }
.chapter-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.chapter-head { display: flex; align-items: center; gap: 0.8rem; padding: 0.75rem 0.95rem; }
.chapter-mark {
  width: 36px; height: 36px; flex: none; border-radius: 50%; display: grid; place-items: center;
  color: var(--accent-bright); background: var(--accent-dim); border: 1px solid var(--accent);
}
.chapter-mark svg { width: 18px; height: 18px; }
.chapter-text { display: flex; flex-direction: column; gap: 0.05rem; min-width: 0; margin-right: auto; }
.chapter-title {
  margin: 0; display: flex; align-items: baseline; gap: 0.5rem;
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-lg); font-weight: 600; color: var(--text);
}
.chapter-count {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); font-weight: 600;
  color: var(--text-dim); background: var(--surface-2); border: 1px solid var(--border-med);
  padding: 0 0.45rem; border-radius: 999px;
}
.chapter-sub {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-style: italic; font-size: var(--fs-md); color: var(--text-muted);
}
.chapter-action {
  display: inline-flex; align-items: center; gap: 0.35rem; flex: none;
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-sm); font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--text-dim); transition: color 0.2s ease;
}
.chapter-toggle:hover .chapter-action, .chapter-toggle.open .chapter-action { color: var(--accent); }
.chevron { display: grid; place-items: center; transition: transform 0.2s ease; }
.chevron svg { width: 12px; height: 12px; }
.chevron.rot { transform: rotate(90deg); }
.chapter-body { padding: 0.9rem 0.2rem 0.3rem; }

.beyond-note { margin: 0; font-size: var(--fs-md); color: var(--text-muted); }
.beyond-note.clean { color: var(--success); }
.beyond-note.error { color: var(--danger); }

.api-services { display: flex; flex-direction: column; gap: 1rem; }
.inscription { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.45rem; }
.inscription-mark { width: 8px; height: 8px; flex: none; transform: rotate(45deg); border: 1px solid var(--accent); background: var(--accent-dim); }
.inscription-title { margin: 0; font-size: var(--fs-md); font-weight: 600; color: var(--accent); white-space: nowrap; }
.inscription-rule { flex: 1; min-width: 1.5rem; height: 1px; background: linear-gradient(to right, var(--accent), transparent); opacity: 0.45; }
.inscription-tally { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-dim); white-space: nowrap; }
.api-findings { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.api-finding { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap; padding: 0.45rem 0.6rem; background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 7px; }
.api-title { flex: 1; min-width: 12rem; font-size: var(--fs-md); color: var(--text); }
.api-state { font-size: var(--fs-sm); color: var(--text-muted); font-style: italic; }
.f-prio { flex: 0 0 4.4em; box-sizing: border-box; font-size: var(--fs-sm); font-weight: 700; letter-spacing: 0.02em; text-transform: uppercase; padding: 0.12rem 0.3rem; border-radius: 5px; text-align: center; white-space: nowrap; }
.critical { color: var(--danger); background: var(--danger-dim); }
.high     { color: var(--warn);   background: var(--warn-dim); }
.medium   { color: var(--info);   background: var(--info-dim); }
.low      { color: var(--success);background: var(--success-dim); }
.info     { color: var(--text-muted); background: var(--surface); }

.chapter-panel-enter-active, .chapter-panel-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.chapter-panel-enter-from, .chapter-panel-leave-to { opacity: 0; transform: translateY(-4px); }

@media (max-width: 640px) {
  .chapter-action { display: none; }
  .inscription { flex-wrap: wrap; row-gap: 0.25rem; }
  .inscription-title { white-space: normal; }
}
@media (prefers-reduced-motion: reduce) {
  .chapter-panel-enter-active, .chapter-panel-leave-active, .chevron, .chapter-toggle { transition: none; }
}
</style>
