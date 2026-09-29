<template>
  <div class="lateral" :aria-busy="loading">
    <p v-if="error" class="lateral-note error">{{ error }}</p>
    <p v-else-if="loading && !risks.length" class="lateral-note">{{ t('lybra.lateral.loading') }}</p>
    <!-- Con menos de dos equipos no hay por dónde moverse: se dice por qué no
         hay nada, en vez de un «sin riesgos» que sonaría a buena noticia. -->
    <p v-else-if="hostCount < 2" class="lateral-note">{{ t('lybra.lateral.tooFew') }}</p>
    <template v-else>
      <p class="lateral-intro">{{ t('lybra.lateral.intro', { count: hostCount }, hostCount) }}</p>
      <p v-if="!risks.length" class="lateral-note clean">{{ t('lybra.lateral.empty') }}</p>

      <TransitionGroup v-else tag="ol" name="risk-item" class="risk-list">
        <li v-for="risk in risks" :key="risk.dedupKey || risk.title" class="risk" :data-sev="(risk.severity || 'INFO').toLowerCase()">
          <div class="risk-head">
            <span class="risk-sev" :class="(risk.severity || 'INFO').toLowerCase()">{{ priorityLabel(risk.severity) }}</span>
            <span class="risk-rule">{{ t(`lybra.lateral.rules.${lateralRuleKey(risk.rule)}.label`) }}</span>
          </div>
          <p class="risk-title">{{ risk.title }}</p>

          <!-- El alcance, con un rombo por equipo de la red: los rellenos son
               los implicados. Es el mismo rombo que separa los capítulos de
               un escaneo, y aquí cada uno es una máquina. -->
          <div class="reach" role="img"
            :aria-label="t('lybra.lateral.reach', { involved: reachOf(risk).involved, total: hostCount })">
            <span class="reach-marks" aria-hidden="true">
              <span v-for="(isInvolved, index) in reachOf(risk).marks" :key="index" class="reach-mark"
                :class="{ on: isInvolved }" :style="{ '--i': index }"></span>
              <span v-if="reachOf(risk).hidden" class="reach-more">{{ t('lybra.lateral.more', { count: reachOf(risk).hidden }) }}</span>
            </span>
            <span class="reach-text">{{ t('lybra.lateral.reach', { involved: reachOf(risk).involved, total: hostCount }) }}</span>
          </div>

          <ul class="risk-hosts" :aria-label="t('lybra.lateral.hosts')">
            <li v-for="host in risk.hosts || []" :key="host.hostId" class="risk-host mono">{{ host.name }}</li>
          </ul>
          <p class="risk-hint">{{ t(`lybra.lateral.rules.${lateralRuleKey(risk.rule)}.hint`) }}</p>
        </li>
      </TransitionGroup>
    </template>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { priorityLabel } from '../labels'
import { lateralRuleKey, reachMarks } from './beyondHost'

const { t } = useI18n()

const props = defineProps({
  /** Riesgos de `GET /themis/network-risk`, de mayor a menor puntuación. */
  risks: { type: Array, default: () => [] },
  /** Equipos de la red analizada. */
  hostCount: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})

/** Rombos de alcance de un riesgo dentro de esta red. */
function reachOf(risk) { return reachMarks(risk, props.hostCount) }
</script>

<style scoped>
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
.lateral { display: flex; flex-direction: column; gap: 0.7rem; }
.lateral-intro, .lateral-note { margin: 0; font-size: var(--fs-md); color: var(--text-muted); line-height: 1.45; }
.lateral-note.clean { color: var(--success); }
.lateral-note.error { color: var(--danger); }

.risk-list { position: relative; list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.risk {
  --sev: var(--text-muted);
  position: relative; padding: 0.75rem 0.9rem 0.75rem 1.05rem;
  background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 9px;
  display: flex; flex-direction: column; gap: 0.45rem;
}
/* El filo del color de su gravedad, igual que los grupos de hallazgos. */
.risk::before { content: ''; position: absolute; left: 0; top: 0.6rem; bottom: 0.6rem; width: 3px; border-radius: 0 3px 3px 0; background: var(--sev); }
.risk[data-sev="critical"] { --sev: var(--danger); }
.risk[data-sev="high"] { --sev: var(--warn); }
.risk[data-sev="medium"] { --sev: var(--info); }
.risk[data-sev="low"] { --sev: var(--success); }

.risk-head { display: flex; align-items: center; gap: 0.55rem; flex-wrap: wrap; }
.risk-sev { font-size: var(--fs-sm); font-weight: 700; letter-spacing: 0.02em; text-transform: uppercase; padding: 0.12rem 0.4rem; border-radius: 5px; }
.risk-rule {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-sm); font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent);
}
.risk-title { margin: 0; font-size: var(--fs-lg); color: var(--text); line-height: 1.4; }
.risk-hint { margin: 0; font-size: var(--fs-md); color: var(--text-dim); line-height: 1.45; }

.reach { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
.reach-marks { display: inline-flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.reach-mark {
  width: 8px; height: 8px; transform: rotate(45deg); flex: none;
  border: 1px solid var(--border-med); background: transparent;
  animation: mark-in 0.35s ease-out backwards; animation-delay: calc(var(--i) * 18ms);
}
.reach-mark.on { border-color: var(--sev); background: var(--sev); }
.reach-more { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-muted); }
.reach-text { font-size: var(--fs-md); color: var(--text-dim); }
@keyframes mark-in { from { opacity: 0; transform: rotate(45deg) scale(0.4); } }

.risk-hosts { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 0.3rem; }
.risk-host { font-size: var(--fs-sm); padding: 0.1rem 0.45rem; border-radius: 4px; background: var(--surface); border: 1px solid var(--border-solid); color: var(--text-dim); }

/* Escala de gravedad, la misma de las píldoras de LybraResults.vue. */
.critical { color: var(--danger); background: var(--danger-dim); }
.high     { color: var(--warn);   background: var(--warn-dim); }
.medium   { color: var(--info);   background: var(--info-dim); }
.low      { color: var(--success);background: var(--success-dim); }
.info     { color: var(--text-muted); background: var(--surface); }

.risk-item-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.risk-item-enter-from { opacity: 0; transform: translateY(4px); }
.risk-item-leave-active { transition: opacity 0.15s ease; position: absolute; inset-inline: 0; }
.risk-item-leave-to { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .reach-mark { animation: none; }
  .risk-item-enter-active, .risk-item-leave-active { transition: none; }
}
</style>
