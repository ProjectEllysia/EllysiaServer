<template>
  <ToolShell tool-id="phishingQuiz" more-to="/aegis/generador">
    <div class="pq">
      <template v-if="!isFinished">
        <header class="pq-top">
          <p class="pq-counter">{{ t('freeTools.items.phishingQuiz.counter', { current: index + 1, total }) }}</p>
          <ol class="pq-dots" aria-hidden="true">
            <li v-for="(quizCase, position) in order" :key="quizCase.id" class="pq-dot" :class="dotClass(position)"></li>
          </ol>
        </header>

        <!-- El correo se pinta como en un buzón: remitente, asunto, cuerpo y un enlace que no se puede pulsar. -->
        <article :key="current.id" class="pq-mail mo-rise" :class="{ 'pq-mail--wrong': answer && !wasCorrect, 'pq-mail--right': answer && wasCorrect }">
          <dl class="pq-head">
            <div class="pq-head-row">
              <dt>{{ t('freeTools.items.phishingQuiz.from') }}</dt>
              <dd>{{ text('name') }} <span class="pq-address">{{ current.address }}</span></dd>
            </div>
            <div class="pq-head-row">
              <dt>{{ t('freeTools.items.phishingQuiz.subjectLabel') }}</dt>
              <dd class="pq-subject">{{ text('subject') }}</dd>
            </div>
          </dl>
          <p class="pq-body">{{ text('body') }}</p>
          <p v-if="current.linkUrl" class="pq-link-row">
            <span class="pq-link-label">{{ t('freeTools.items.phishingQuiz.link') }}</span>
            <span class="pq-link">{{ text('linkText') }}</span>
          </p>
        </article>

        <div v-if="!answer" class="pq-ask">
          <p class="pq-prompt">{{ t('freeTools.items.phishingQuiz.prompt') }}</p>
          <div class="pq-actions">
            <button type="button" class="pq-btn pq-btn--danger" @click="reply('phishing')">{{ t('freeTools.items.phishingQuiz.phishing') }}</button>
            <button type="button" class="pq-btn pq-btn--safe" @click="reply('legit')">{{ t('freeTools.items.phishingQuiz.legit') }}</button>
          </div>
        </div>

        <section v-else class="pq-feedback mo-rise" :data-correct="wasCorrect" aria-live="polite">
          <p class="pq-verdict">
            {{ wasCorrect ? t('freeTools.items.phishingQuiz.correct') : t('freeTools.items.phishingQuiz.incorrect') }}
            <span class="pq-truth">{{ current.isPhishing ? t('freeTools.items.phishingQuiz.wasPhishing') : t('freeTools.items.phishingQuiz.wasLegit') }}</span>
          </p>
          <p class="pq-explanation">{{ text('explanation') }}</p>
          <p v-if="current.linkUrl" class="pq-real">
            {{ t('freeTools.items.phishingQuiz.realLink') }}
            <code class="pq-real-url" :class="{ 'pq-real-url--bad': current.isPhishing }">{{ current.linkUrl }}</code>
          </p>
          <h3 class="pq-clues-title">{{ current.isPhishing ? t('freeTools.items.phishingQuiz.cluesPhishing') : t('freeTools.items.phishingQuiz.cluesLegit') }}</h3>
          <ul class="pq-clues">
            <li v-for="clue in current.clueCount" :key="clue">{{ text(`clues.${clue}`) }}</li>
          </ul>
          <button ref="nextButton" type="button" class="pq-btn pq-btn--next" @click="next">
            {{ index + 1 === total ? t('freeTools.items.phishingQuiz.finish') : t('freeTools.items.phishingQuiz.next') }}
          </button>
        </section>
      </template>

      <section v-else class="pq-result" aria-live="polite">
        <!-- Un anillo que se llena hasta la fracción de aciertos. -->
        <div class="pq-ring" aria-hidden="true">
          <svg viewBox="0 0 120 120">
            <circle class="pq-ring-track" cx="60" cy="60" r="52" />
            <circle class="pq-ring-value" cx="60" cy="60" r="52" pathLength="1" :style="{ '--fill': correctCount / total }" />
          </svg>
          <span class="pq-ring-number"><CountUp :value="correctCount" :duration="900" /><span class="pq-ring-total">/{{ total }}</span></span>
        </div>
        <p class="pq-score">{{ t('freeTools.items.phishingQuiz.result', { correct: correctCount, total }) }}</p>
        <ol class="pq-dots pq-dots--big" aria-hidden="true">
          <li v-for="(quizCase, position) in order" :key="quizCase.id" class="pq-dot" :class="dotClass(position)"></li>
        </ol>
        <p class="pq-band">{{ t(`freeTools.items.phishingQuiz.bands.${band}`) }}</p>
        <button type="button" class="pq-btn pq-btn--next" @click="restart">{{ t('freeTools.items.phishingQuiz.again') }}</button>
      </section>
    </div>
  </ToolShell>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ToolShell from '@/components/shared/ToolShell.vue'
import CountUp from '@/components/shared/CountUp.vue'
import { QUIZ_CASES, isCorrect, resultBand, shuffled } from '@/components/freeTools/phishingQuiz'

/**
 * Mini quiz de phishing gratuito de Aegis.
 *
 * Seis correos ficticios y fijos, sin servidor ni cuenta. El orden cambia en cada
 * partida. Tras cada respuesta se enseña qué delataba al correo (o por qué era de
 * fiar) y, si lo llevaba, adónde iba de verdad el enlace.
 */
const { t } = useI18n()

const total = QUIZ_CASES.length
const order = ref(shuffled(QUIZ_CASES))
const index = ref(0)
const answer = ref(null) // null hasta que se responde: 'phishing' | 'legit'
const results = ref([]) // un booleano por correo ya respondido
const nextButton = ref(null)

const isFinished = computed(() => index.value >= total)
const current = computed(() => order.value[Math.min(index.value, total - 1)])
const wasCorrect = computed(() => answer.value !== null && isCorrect(current.value, answer.value))
const correctCount = computed(() => results.value.filter(Boolean).length)
const band = computed(() => resultBand(correctCount.value, total))

/**
 * Texto del correo actual en el idioma activo.
 *
 * @param {string} key - Ruta dentro de `cases.<id>` (`subject`, `clues.2`…).
 * @returns {string} El texto del diccionario.
 */
function text(key) {
  return t(`freeTools.items.phishingQuiz.cases.${current.value.id}.${key}`)
}

/**
 * Clase de la bolita de progreso de un correo.
 *
 * @param {number} position - Posición del correo en el orden de esta partida.
 * @returns {string} `pq-dot--right` o `pq-dot--wrong` si ya se respondió, `pq-dot--now` si
 *   es el actual y `pq-dot--todo` si falta.
 */
function dotClass(position) {
  if (position < results.value.length) return results.value[position] ? 'pq-dot--right' : 'pq-dot--wrong'
  return position === index.value ? 'pq-dot--now' : 'pq-dot--todo'
}

/**
 * Registra la respuesta al correo actual y lleva el foco al botón de seguir.
 *
 * @param {'phishing'|'legit'} choice - Lo que contesta el usuario.
 */
async function reply(choice) {
  answer.value = choice
  results.value.push(isCorrect(current.value, choice))
  await nextTick()
  nextButton.value?.focus()
}

/** Pasa al siguiente correo, o al resultado tras el último. */
function next() {
  index.value += 1
  answer.value = null
}

/** Empieza otra partida con los correos en otro orden. */
function restart() {
  order.value = shuffled(QUIZ_CASES)
  index.value = 0
  answer.value = null
  results.value = []
}
</script>

<style scoped>
.pq { display: flex; flex-direction: column; gap: 1.3rem; }

.pq-top { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.pq-counter, .pq-link-label, .pq-head dt, .pq-clues-title {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted);
}
.pq-dots { list-style: none; display: flex; gap: 0.45rem; }
.pq-dot { width: 0.8rem; height: 0.8rem; border-radius: 50%; border: 1px solid var(--border-med); }
.pq-dot--now { border-color: var(--accent-bright); background: var(--accent-dim); }
.pq-dot--right { background: var(--success); border-color: var(--success); }
.pq-dot--wrong { background: var(--danger); border-color: var(--danger); }
.pq-dots--big { justify-content: center; }
.pq-dots--big .pq-dot { width: 1.1rem; height: 1.1rem; }
.pq-dot { transition: background 0.3s ease, border-color 0.3s ease, transform 0.4s var(--ease-settle); }
.pq-dot--now { animation: dot-beat 1.6s ease-in-out infinite; }
@keyframes dot-beat { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.35); } }

/* Una respuesta falsa sacude el correo; una acertada lo rodea con un halo. */
.pq-mail--wrong { animation: mo-rise 0.8s var(--ease-settle) both, mail-shake 0.5s ease-in-out 0.1s; border-color: var(--danger); }
.pq-mail--right { border-color: var(--success); box-shadow: 0 0 0 3px var(--success-dim), 0 0 30px var(--success-dim); }
.pq-mail { transition: border-color 0.3s ease, box-shadow 0.4s ease; }
@keyframes mail-shake { 0%, 100% { transform: translateX(0); } 20% { transform: translateX(-8px); } 40% { transform: translateX(7px); } 60% { transform: translateX(-5px); } 80% { transform: translateX(3px); } }

/* Anillo del resultado */
.pq-ring { position: relative; width: 150px; height: 150px; display: grid; place-items: center; }
.pq-ring svg { position: absolute; inset: 0; transform: rotate(-90deg); }
.pq-ring-track { fill: none; stroke: var(--border-med); stroke-width: 6; }
.pq-ring-value {
  fill: none; stroke: var(--accent-bright); stroke-width: 6; stroke-linecap: round;
  stroke-dasharray: 1; stroke-dashoffset: calc(1 - var(--fill));
  animation: ring-fill 1.4s var(--ease-settle) 0.2s backwards;
  filter: drop-shadow(0 0 6px var(--accent-dim));
}
@keyframes ring-fill { from { stroke-dashoffset: 1; } }
.pq-ring-number { position: relative; font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-3xl); font-weight: 600; color: var(--text); }
.pq-ring-total { font-size: var(--fs-lg); color: var(--text-muted); }

/* ── El correo ── */
.pq-mail { background: var(--bg); border: 1px solid var(--border-med); border-radius: var(--radius-sm); overflow: hidden; }
.pq-head { padding: 0.9rem 1.1rem; border-bottom: 1px solid var(--border-med); display: flex; flex-direction: column; gap: 0.45rem; }
.pq-head-row { display: grid; grid-template-columns: 4.6rem 1fr; gap: 0.6rem; align-items: baseline; }
.pq-head dd { font-size: var(--fs-md); color: var(--text); word-break: break-word; }
.pq-subject { font-weight: 600; }
/* La dirección real va aparte y en mono: es lo primero que hay que mirar. */
.pq-address {
  display: inline-block;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  color: var(--text-dim);
}
.pq-address::before { content: '<'; }
.pq-address::after { content: '>'; }
.pq-body { padding: 1.1rem; font-size: var(--fs-md); color: var(--text-dim); line-height: 1.7; white-space: pre-line; }
.pq-link-row { display: flex; align-items: baseline; gap: 0.8rem; padding: 0 1.1rem 1.1rem; }
/* Parece un enlace pero no se puede pulsar: el quiz nunca lleva a ninguna parte. */
.pq-link { color: var(--accent-bright); text-decoration: underline; text-underline-offset: 3px; cursor: default; }

/* ── Respuesta ── */
.pq-prompt { font-size: var(--fs-md); color: var(--text-dim); margin-bottom: 0.7rem; }
.pq-actions { display: flex; gap: 0.8rem; flex-wrap: wrap; }
.pq-btn {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.12em; text-transform: uppercase;
  padding: 0.75rem 1.5rem;
  border-radius: 3px;
  border: 1px solid var(--accent);
  color: var(--text);
  background: var(--accent-dim);
  transition: all var(--transition);
}
.pq-btn:hover { background: var(--accent); color: var(--on-accent); }
.pq-btn:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 3px; }
.pq-btn--danger { border-color: var(--danger); background: var(--danger-dim); }
.pq-btn--danger:hover { background: var(--danger); }
.pq-btn--safe { border-color: var(--success); background: var(--success-dim); }
.pq-btn--safe:hover { background: var(--success); }
.pq-btn--next { background: var(--accent); color: var(--on-accent); align-self: flex-start; margin-top: 0.4rem; }
.pq-btn--next:hover { background: var(--accent-bright); border-color: var(--accent-bright); }

/* ── Explicación ── */
.pq-feedback { --tone: var(--danger); display: flex; flex-direction: column; gap: 0.8rem; padding-top: 1.1rem; border-top: 2px solid var(--tone); }
.pq-feedback[data-correct="true"] { --tone: var(--success); }
.pq-verdict { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); font-weight: 600; color: var(--tone); }
.pq-truth { font-family: var(--font-body, inherit); font-size: var(--fs-md); font-weight: 400; color: var(--text-dim); margin-left: 0.6rem; }
.pq-explanation { font-size: var(--fs-md); color: var(--text); line-height: 1.6; }
.pq-real { font-size: var(--fs-sm); color: var(--text-muted); display: flex; flex-direction: column; gap: 0.3rem; }
.pq-real-url {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  color: var(--text-dim);
  word-break: break-all;
}
.pq-real-url--bad { color: var(--danger); }
.pq-clues { list-style: none; display: flex; flex-direction: column; gap: 0.5rem; }
.pq-clues li { position: relative; padding-left: 1.1rem; font-size: var(--fs-md); color: var(--text-dim); line-height: 1.6; }
.pq-clues li::before { content: ''; position: absolute; left: 0; top: 0.7em; width: 0.5rem; height: 2px; background: var(--tone); }

/* ── Resultado ── */
.pq-result { display: flex; flex-direction: column; align-items: center; gap: 1.2rem; text-align: center; padding: 1rem 0; }
.pq-score { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-3xl); font-weight: 600; color: var(--text); }
.pq-band { font-size: var(--fs-lg); color: var(--text-dim); max-width: 44ch; line-height: 1.6; }
.pq-result .pq-btn--next { align-self: center; }

@media (max-width: 520px) {
  .pq-head-row { grid-template-columns: 1fr; gap: 0.1rem; }
  .pq-btn { width: 100%; }
}
</style>
