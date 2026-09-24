<template>
  <div class="engine-card">
    <!-- Cabecera con identidad de motor -->
    <div class="engine-head">
      <div class="engine-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M12 3v18M7 21h10M5 7h14M5 7l-2.5 5a3 3 0 0 0 5 0L5 7zM19 7l-2.5 5a3 3 0 0 0 5 0L19 7z"/>
        </svg>
      </div>
      <div class="engine-title-wrap">
        <span class="engine-title">Motor Lybra</span>
        <span class="engine-sub">Pesa cada amenaza antes de que golpee</span>
      </div>
      <Transition name="pop"><span v-if="props.launched" class="engine-launched"><span class="pulse" aria-hidden="true"></span>Motor en marcha</span></Transition>
    </div>

    <!-- Campos según modo -->
    <div class="engine-fields">
      <div class="field-row">
        <div class="field field-lg"><label for="lybra-target">Target (IP única)</label>
          <!-- El estado de autorización vive dentro del campo, como un sello
               junto a lo que se escribe: es una propiedad de ese objetivo, no un
               aviso aparte que empuje el resto del panel hacia abajo. -->
          <div class="target-wrap" :class="{ sealed: authState }">
            <input id="lybra-target" v-model="target" placeholder="192.168.1.1" @keyup.enter="handleLaunch" />
            <Transition name="fade-swap" mode="out-in">
              <span v-if="authState === 'ok'" key="ok" class="target-seal ok" title="Está en tu registro de objetivos autorizados">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>
                Autorizado
              </span>
              <button v-else-if="authState === 'missing'" key="missing" type="button" class="target-seal missing"
                :title="`Añadir '${target.trim()}' a tus objetivos autorizados`"
                @click="$emit('add-authorized-target', { target: target.trim() })">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><line x1="12" y1="9" x2="12" y2="15"/><line x1="9" y1="12" x2="15" y2="12"/></svg>
                Autorizar
              </button>
            </Transition>
          </div></div>
        <div class="field"><label>Puertos (opcional)</label>
          <input v-model="ports" placeholder="80,443 o 1-1000" /></div>
      </div>
      <Transition name="fade-swap">
        <p v-if="authState === 'missing'" class="auth-hint">
          No está en tu registro de objetivos autorizados: el autodescubrimiento se rechazará.
        </p>
      </Transition>

      <!-- Registro de objetivos autorizados -->
      <div class="auth-register">
        <!-- Misma inscripción que las secciones de LybraResults.vue: el panel
             y los veredictos hablan el mismo idioma visual. -->
        <button type="button" class="auth-register-toggle" :aria-expanded="showAuthRegister" @click="showAuthRegister = !showAuthRegister">
          <span class="inscription-mark" aria-hidden="true"></span>
          <span class="inscription-title">Objetivos autorizados</span>
          <span class="inscription-rule" aria-hidden="true"></span>
          <span class="inscription-tally">{{ authorizedTargets.length }}</span>
          <span class="chevron" :class="{ rot: showAuthRegister }" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          </span>
        </button>
        <!-- Mismo panel-slide que ScheduledScansPanel.vue: el registro se
             despliega deslizándose en vez de aparecer de golpe, igual que el
             panel de escaneos programados que está justo debajo. -->
        <Transition name="panel-slide">
        <div v-if="showAuthRegister" class="auth-register-body">
          <p class="auth-register-hint">
            Objetivos (IP o CIDR) que has declarado autorizados para el autodescubrimiento, el fingerprinting
            propio y las comprobaciones activas de Lybra.
          </p>
          <div v-if="authTargetsLoading" class="auth-loading">Cargando…</div>
          <TransitionGroup v-else-if="authorizedTargets.length" tag="ul" name="chip-item" class="auth-chip-list">
            <li v-for="t in authorizedTargets" :key="t.id" class="auth-chip">
              <span class="mono">{{ t.target }}</span>
              <span v-if="t.label" class="auth-chip-label">{{ t.label }}</span>
              <button type="button" class="auth-chip-remove" title="Eliminar" @click="$emit('remove-authorized-target', t.id)">×</button>
            </li>
          </TransitionGroup>
          <p v-else class="auth-empty">Aún no has autorizado ningún objetivo.</p>

          <div class="auth-add-row">
            <input v-model="newAuthTarget" placeholder="10.0.0.5 o 10.0.0.0/24" @keyup.enter="submitNewAuthTarget" />
            <input v-model="newAuthLabel" placeholder="Etiqueta (opcional)" @keyup.enter="submitNewAuthTarget" />
            <button type="button" class="btn-add-target" :disabled="!newAuthTarget.trim()" @click="submitNewAuthTarget">Añadir</button>
          </div>
        </div>
        </Transition>
      </div>

      <div class="engine-row">
        <div class="field field-sm"><label>Timeout (s)<span v-if="timeoutLabel" class="timeout-human"> · {{ timeoutLabel }}</span></label>
          <input v-model.number="timeout" type="number" min="1" max="86400" class="no-spin" /></div>

        <!-- Mientras se lanza, la balanza del botón se mece: el motor está
             pesando. Sustituye al spinner genérico y mantiene el ancho. -->
        <button class="btn-launch" :class="{ loading: launching }" :disabled="launching || !canLaunch" @click="handleLaunch">
          <span class="btn-balanza" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v18M7 21h10M5 7h14M5 7l-2.5 5a3 3 0 0 0 5 0L5 7zM19 7l-2.5 5a3 3 0 0 0 5 0L19 7z"/></svg></span>
          <span class="btn-label">{{ launching ? 'Pesando…' : 'Emitir veredicto' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  launching: { type: Boolean, default: false },
  // Q8: viene del padre (deriva del estado real de los escaneos), no de un
  // flag local que quedaba en true para siempre tras el primer lanzamiento.
  launched: { type: Boolean, default: false },
  authorizedTargets: { type: Array, default: () => [] },
  authTargetsLoading: { type: Boolean, default: false },
})
const emit = defineEmits(['launch', 'add-authorized-target', 'remove-authorized-target'])

// Un solo modo: Lybra descubre los puertos del objetivo con su propio
// transporte. No hay un modo que analice los servicios de un escaneo Nmap ya
// hecho, ni un interruptor de "segunda opinión" que lance Nmap, Nikto y
// Nuclei como corroboradores.
const target = ref('')
const ports = ref('')
const timeout = ref(120)

const canLaunch = computed(() => !!target.value.trim())

/**
 * Estado de autorización del objetivo escrito, para el sello del campo.
 *
 * @returns {''|'ok'|'missing'} Vacío si no hay objetivo; `ok` si está en el
 *          registro; `missing` si no lo está.
 */
const authState = computed(() => {
  if (!target.value.trim()) return ''
  return isTargetAuthorized(target.value) ? 'ok' : 'missing'
})

/**
 * El timeout en una unidad legible ("2 min", "1 h 30 min"), junto a su etiqueta.
 *
 * Sólo se muestra a partir de un minuto: por debajo, los segundos ya se leen.
 *
 * @returns {string} La duración legible, o cadena vacía si no aplica.
 */
const timeoutLabel = computed(() => {
  const seconds = Number(timeout.value)
  if (!Number.isFinite(seconds) || seconds < 60) return ''
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  if (!hours) return `${minutes} min`
  return minutes ? `${hours} h ${minutes} min` : `${hours} h`
})

/**
 * Heurística de coincidencia exacta contra el registro (el backend, que sí
 * entiende CIDR, es la fuente de verdad real). Las entradas de IP única se
 * normalizan a "x.x.x.x/32" en el servidor, así que se compara sin ese sufijo.
 */
function isTargetAuthorized(ip) {
  const needle = (ip || '').trim()
  if (!needle) return false
  return props.authorizedTargets.some(t => t.target.replace(/\/32$/, '') === needle)
}

const showAuthRegister = ref(false)
const newAuthTarget = ref('')
const newAuthLabel = ref('')
function submitNewAuthTarget() {
  if (!newAuthTarget.value.trim()) return
  emit('add-authorized-target', { target: newAuthTarget.value.trim(), label: newAuthLabel.value.trim() })
  newAuthTarget.value = ''
  newAuthLabel.value = ''
}

function handleLaunch() {
  if (!canLaunch.value || props.launching) return
  const payload = { target: target.value.trim(), timeout: timeout.value }
  if (ports.value.trim()) payload.ports = ports.value.trim()
  emit('launch', payload)
}
</script>

<style scoped>
.engine-card {
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 220%);
  border: 1px solid var(--accent);
  border-radius: 12px;
  padding: 1.2rem 1.35rem;
  margin-bottom: 1.1rem;
  box-shadow: 0 0 0 1px var(--accent-dim), 0 12px 34px rgba(0,0,0,0.16);
}

/* ── Cabecera ── */
.engine-head { display: flex; align-items: center; gap: 0.8rem; margin-bottom: 1rem; }
.engine-mark {
  width: 40px; height: 40px; border-radius: 50%;
  display: grid; place-items: center; flex-shrink: 0;
  color: var(--accent-bright);
  background: var(--accent-dim);
  border: 1px solid var(--accent);
}
.engine-mark svg { width: 21px; height: 21px; }
.engine-title-wrap { display: flex; flex-direction: column; gap: 0.05rem; margin-right: auto; }
.engine-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-weight: 600; font-size: var(--fs-xl); color: var(--text); }
.engine-sub { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-style: italic; font-size: var(--fs-md); color: var(--text-muted); }
.engine-launched { display: inline-flex; align-items: center; gap: 0.45rem; font-size: var(--fs-md); color: var(--success); background: var(--success-dim); padding: 0.2rem 0.6rem; border-radius: 6px; }
.pulse { position: relative; width: 7px; height: 7px; border-radius: 50%; background: var(--success); }
.pulse::after { content: ''; position: absolute; inset: 0; border-radius: 50%; background: var(--success); animation: pulse-ring 1.6s ease-out infinite; }
@keyframes pulse-ring { from { transform: scale(1); opacity: 0.6; } to { transform: scale(2.6); opacity: 0; } }
.pop-enter-active { transition: opacity 0.2s ease, transform 0.25s cubic-bezier(0.34,1.56,0.64,1); }
.pop-enter-from { opacity: 0; transform: scale(0.8); }
.pop-leave-active { transition: opacity 0.15s ease; }
.pop-leave-to { opacity: 0; }

/* ── Campos ── */
/* Escala del panel: título en --fs-xl (el mismo que el lanzador de terceros),
   y todo lo demás —subtítulo, etiquetas, encabezado del registro, avisos,
   etiquetas de objetivo— en --fs-md. Todo lo que se escribe, en --fs-input, sea
   el campo que sea: un mismo texto tecleado no cambia de tamaño según dónde. */
.engine-fields { display: flex; flex-direction: column; gap: 0.8rem; }
.field-row { display: flex; align-items: flex-end; gap: 0.6rem; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 0.25rem; flex: 1; min-width: 130px; }
.field label { font-size: var(--fs-md); color: var(--text-muted); font-weight: 500; }
.field input, .field select { padding: 0.5rem 0.65rem; background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 6px; color: var(--text); font-size: var(--fs-input); outline: none; transition: border-color 0.2s; }
.field input:focus, .field select:focus { border-color: var(--accent); }
.field-lg { flex: 2; min-width: 200px; }
.field-sm { flex: 0 0 96px; min-width: 84px; }
/* La etiqueta del timeout lleva la duración legible y puede ser más ancha que
   el campo: se desborda hacia la derecha, donde la fila tiene hueco. */
.field-sm label { white-space: nowrap; }
.no-spin::-webkit-outer-spin-button, .no-spin::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.no-spin { -moz-appearance: textfield; }

/* ── Fila de lanzamiento ── */
.engine-row { display: flex; align-items: flex-end; gap: 0.9rem; flex-wrap: wrap; }
.engine-row .field-sm { margin-right: auto; }

.btn-launch { height: 36px; padding: 0 1.2rem 0 1rem; background: var(--accent); border: 1px solid var(--accent); color: var(--on-accent); font-weight: 600; font-size: var(--fs-lg); border-radius: 7px; cursor: pointer; display: flex; align-items: center; gap: 0.35rem; transition: all 0.2s; white-space: nowrap; position: relative; }
.btn-launch:hover:not(:disabled) { background: var(--accent-bright); border-color: var(--accent-bright); }
.btn-launch:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-launch { gap: 0.5rem; }
.btn-launch.loading:disabled { opacity: 0.85; cursor: progress; }
.btn-balanza { display: grid; place-items: center; }
.btn-balanza svg { width: 17px; height: 17px; transform-origin: 50% 15%; }
.btn-launch:hover:not(:disabled) .btn-balanza svg { animation: balanza-sway 0.9s ease-in-out; }
.btn-launch.loading .btn-balanza svg { animation: balanza-sway 1.1s ease-in-out infinite; }
/* Mismo vaivén que el sello del capítulo "Hallazgos" de LybraResults.vue. */
@keyframes balanza-sway {
  0%, 100% { transform: rotate(0); }
  30% { transform: rotate(-9deg); }
  60% { transform: rotate(6deg); }
  82% { transform: rotate(-2deg); }
}
.timeout-human { color: var(--text-dim); font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); }

/* ── Sello de autorización dentro del campo de objetivo ── */
.target-wrap { position: relative; display: flex; }
.target-wrap input { flex: 1; min-width: 0; }
.target-wrap.sealed input { padding-right: 7.2rem; }
.target-seal {
  position: absolute; right: 0.35rem; top: 50%; transform: translateY(-50%);
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: 0.18rem 0.55rem; border-radius: 999px; white-space: nowrap;
  font-size: var(--fs-sm); font-weight: 600;
}
.target-seal svg { width: 13px; height: 13px; flex: none; }
.target-seal.ok { color: var(--success); background: var(--success-dim); border: 1px solid var(--success); }
.target-seal.missing {
  color: var(--accent-bright); background: var(--accent-dim); border: 1px dashed var(--accent);
  cursor: pointer; transition: background 0.2s ease, color 0.2s ease;
}
.target-seal.missing:hover { background: var(--accent); color: var(--on-accent); border-style: solid; }
.target-seal.missing:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.auth-hint { margin: -0.35rem 0 0; font-size: var(--fs-md); color: var(--warn); }
.fade-swap-enter-active, .fade-swap-leave-active { transition: opacity 0.18s ease; }
.fade-swap-enter-from, .fade-swap-leave-to { opacity: 0; }
.panel-slide-enter-active, .panel-slide-leave-active { transition: all 0.25s ease; overflow: hidden; }
.panel-slide-enter-from, .panel-slide-leave-to { max-height: 0; opacity: 0; }
.panel-slide-enter-to, .panel-slide-leave-from { max-height: 2000px; opacity: 1; }

/* ── Registro de objetivos autorizados ── */
.auth-register { border-top: 1px solid var(--border-solid); padding-top: 0.7rem; margin-top: 0.2rem; }
.auth-register-toggle {
  display: flex; align-items: center; gap: 0.6rem; width: 100%;
  background: none; border: none; cursor: pointer; padding: 0.15rem 0;
}
.auth-register-toggle:hover .inscription-title { color: var(--accent-bright); }
.auth-register-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }
/* Inscripción: la misma que las secciones de LybraResults.vue. */
.inscription-mark { width: 8px; height: 8px; flex: none; transform: rotate(45deg); border: 1px solid var(--accent); background: var(--accent-dim); }
.inscription-title {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600; letter-spacing: 0.24em; text-transform: uppercase;
  color: var(--accent); white-space: nowrap; transition: color 0.2s ease;
}
.inscription-rule { flex: 1; min-width: 1.5rem; height: 1px; background: linear-gradient(to right, var(--accent), transparent); opacity: 0.45; }
.inscription-tally { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-dim); }
.auth-register-toggle .chevron { display: grid; place-items: center; color: var(--text-muted); transition: transform 0.2s; }
.auth-register-toggle .chevron svg { width: 13px; height: 13px; }
.auth-register-toggle .chevron.rot { transform: rotate(90deg); }
.auth-register-body { padding-top: 0.6rem; display: flex; flex-direction: column; gap: 0.55rem; }
.auth-register-hint { margin: 0; font-size: var(--fs-md); color: var(--text-muted); line-height: 1.4; }
.auth-loading, .auth-empty { font-size: var(--fs-md); color: var(--text-muted); }

.auth-chip-list { position: relative; list-style: none; display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0; padding: 0; }
.auth-chip {
  display: flex; align-items: center; gap: 0.4rem;
  padding: 0.25rem 0.3rem 0.25rem 0.6rem; background: var(--surface-2); border: 1px solid var(--border-solid);
  border-radius: 999px; font-size: var(--fs-md); color: var(--text);
}
/* Misma familia que .doc-item/.finding-item de LybraResults.vue: la etiqueta
   nueva entra con un fundido y las demás se recolocan; al quitar una, sale
   sin dejar un hueco brusco. */
.chip-item-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.chip-item-enter-from { opacity: 0; transform: scale(0.85); }
.chip-item-leave-active { transition: opacity 0.15s ease; position: absolute; }
.chip-item-leave-to { opacity: 0; }
.chip-item-move { transition: transform 0.2s ease; }
.auth-chip-label { color: var(--text-muted); font-style: italic; }
.auth-chip-remove {
  width: 18px; height: 18px; display: grid; place-items: center; border-radius: 50%;
  background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: var(--fs-xl); line-height: 1;
  transition: all 0.2s;
}
.auth-chip-remove:hover { background: var(--danger-dim); color: var(--danger); }

.auth-add-row { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.auth-add-row input {
  flex: 1; min-width: 130px; padding: 0.4rem 0.6rem; background: var(--surface-2);
  border: 1px solid var(--border-solid); border-radius: 6px; color: var(--text); font-size: var(--fs-input); outline: none;
}
.auth-add-row input:focus { border-color: var(--accent); }
.btn-add-target {
  padding: 0.4rem 0.8rem; background: var(--surface-2); border: 1px solid var(--accent); color: var(--accent-bright);
  font-size: var(--fs-md); font-weight: 600; border-radius: 6px; cursor: pointer; transition: all 0.2s; white-space: nowrap;
}
.btn-add-target:hover:not(:disabled) { background: var(--accent-dim); }
.btn-add-target:disabled { opacity: 0.4; cursor: not-allowed; }

@media (prefers-reduced-motion: reduce) {
  .pop-enter-active, .pop-leave-active, .btn-launch,
  .auth-register-toggle .chevron, .btn-add-target, .auth-chip-remove,
  .target-seal, .inscription-title, .fade-swap-enter-active, .fade-swap-leave-active,
  .panel-slide-enter-active, .panel-slide-leave-active,
  .chip-item-enter-active, .chip-item-leave-active, .chip-item-move { transition: none !important; }
  .pulse::after, .btn-balanza svg { animation: none !important; }
}
@media (max-width: 520px) {
  .inscription-title { white-space: normal; letter-spacing: 0.16em; }
}
</style>
