<template>
  <div class="tool-page" :data-module="tool.module">
    <StarBackground />
    <SiteHeader />

    <!-- Cabecera: la escena mitológica del módulo detrás, y el medallón de la herramienta. -->
    <header class="stage">
      <ModuleAtmosphere :module-id="tool.module" focus="right" fit="wide" />

      <div class="stage-inner">
        <router-link :to="identity.route" class="stage-back mo-rise" style="--delay: 0.05s">
          <span aria-hidden="true">←</span> {{ t('freeTools.backTo', { name: identity.name }) }}
        </router-link>

        <div class="stage-head">
          <div class="stage-text">
            <span class="stage-eyebrow mo-track" style="--delay: 0.15s">{{ t('freeTools.eyebrow') }} · {{ t(`freeTools.access.${tool.access}`) }}</span>
            <h1 class="stage-title"><span class="mo-mask"><span class="mo-mask-inner" style="--delay: 0.3s">{{ t(`freeTools.items.${tool.id}.title`) }}</span></span></h1>
            <p class="stage-subtitle mo-rise" style="--delay: 0.7s">{{ t(`freeTools.items.${tool.id}.subtitle`) }}</p>
          </div>

          <div class="stage-crest glyph-draw-on-load mo-rise" style="--delay: 0.4s">
            <span class="crest-glow"></span>
            <span class="crest-halo"></span>
            <ToolGlyph :tool-id="tool.id" :size="148" live />
          </div>
        </div>
      </div>
    </header>
    <Frieze />

    <main class="tool-main">
      <!-- Herramienta con cuenta y visitante sin sesión: se enseña qué es y se invita a entrar. -->
      <div v-if="!canUse" class="tool-gate mo-rise" style="--delay: 0.9s">
        <h2 class="tool-gate-title">{{ t('freeTools.gate.title') }}</h2>
        <p class="tool-gate-body">{{ t('freeTools.gate.body') }}</p>
        <router-link :to="{ path: '/login', query: { redirect: tool.path } }" class="tool-cta">{{ t('freeTools.gate.signIn') }}</router-link>
      </div>
      <div v-else class="tool-panel mo-rise" style="--delay: 0.85s">
        <slot />
      </div>
    </main>

    <ToolTeaser :tool-id="tool.id" :more-to="moreTo" />

    <SiteFooter />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { FREE_TOOLS, freeToolPath } from '@/freeTools/catalog'
import SiteHeader from '@/components/shared/SiteHeader.vue'
import SiteFooter from '@/components/shared/SiteFooter.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ToolTeaser from '@/components/shared/ToolTeaser.vue'
import ModuleAtmosphere from '@/components/decor/ModuleAtmosphere.vue'
import ToolGlyph from '@/components/decor/ToolGlyph.vue'
import Frieze from '@/components/decor/Frieze.vue'
import { MODULE_IDENTITY } from './moduleIdentity'

/**
 * Marco común de las páginas de herramientas gratuitas.
 *
 * Es la cara pública del módulo: una cabecera con su escena mitológica y el medallón
 * de la herramienta, la herramienta en un panel (slot por defecto) y, debajo, lo que
 * hay detrás de ella (`ToolTeaser`): el módulo entero y las demás herramientas
 * gratuitas. Todo entra con una secuencia: la ruta de vuelta, el rótulo, el título,
 * la entradilla, el medallón y el panel.
 *
 * Los textos salen de `freeTools.items.<id>` (`title`, `subtitle` y, si hay `moreTo`,
 * `more` y `moreCta`). La herramienta solo aporta lo suyo.
 */
const props = defineProps({
  /** `id` de la herramienta en el catálogo (`freeTools/catalog.js`). */
  toolId: { type: String, required: true },
  /** Ruta de la herramienta completa a la que invita el pie; `null` no pinta ese botón. */
  moreTo: { type: String, default: null },
})

const { t } = useI18n()
const auth = useAuthStore()

const tool = computed(() => {
  const entry = FREE_TOOLS.find((candidate) => candidate.id === props.toolId)
  if (!entry) throw new Error(`Herramienta gratuita desconocida: ${props.toolId}`)
  return { ...entry, path: freeToolPath(entry) }
})
const identity = computed(() => MODULE_IDENTITY[tool.value.module])

/** Una herramienta con cuenta se bloquea sin sesión; las públicas, nunca. */
const canUse = computed(() => tool.value.access === 'public' || auth.isAuthenticated)
</script>

<style scoped>
.tool-page { position: relative; min-height: 100vh; background: var(--bg); display: flex; flex-direction: column; }

/* ═══════════ Cabecera ═══════════ */
.stage {
  position: relative;
  z-index: 1;
  overflow: hidden;
  min-height: clamp(340px, 32vw, 460px);
  display: flex;
  align-items: center;
  /* El color del módulo baña la cabecera desde lo alto, como en el hub. */
  background: radial-gradient(ellipse 90% 70% at 50% 0%, var(--accent-dim), transparent 72%);
}
.stage-inner { position: relative; width: 100%; max-width: 1060px; margin: 0 auto; padding: 2.4rem 2rem 3rem; }

.stage-back {
  display: inline-block;
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-md);
  color: var(--text-dim);
  margin-bottom: 1.8rem;
  transition: color var(--transition);
}
.stage-back:hover { color: var(--accent-bright); }
.stage-back:focus-visible, .tool-cta:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 3px; }

/* El medallón va a la izquierda del título (order: -1) y la derecha queda para la escena. */
.stage-head { display: grid; grid-template-columns: auto minmax(0, 560px); justify-content: start; align-items: center; gap: 2rem 2.6rem; }
.stage-eyebrow {
  display: block;
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.3em; text-transform: uppercase;
  color: var(--accent);
}
.stage-title {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: clamp(2.2rem, 5vw, 3.5rem);
  font-weight: 600;
  line-height: 1.12;
  color: var(--text);
  margin-top: 0.6rem;
  text-shadow: 0 0 46px var(--accent-dim);
  text-wrap: balance;
}
.stage-subtitle {
  font-size: var(--fs-lg);
  color: var(--text-dim);
  line-height: 1.6;
  margin-top: 0.9rem;
  max-width: 52ch;
}

/* ── Medallón de la herramienta: el mismo grabado que en la tarjeta del hub ── */
.stage-crest { position: relative; order: -1; width: 132px; height: 132px; display: grid; place-items: center; }
.stage-crest :deep(.tool-glyph) { width: 132px !important; height: 132px !important; }
.crest-glow {
  position: absolute; inset: -28px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--accent-dim), transparent 68%);
  animation: crest-breathe 6s ease-in-out infinite;
}
.crest-halo {
  position: absolute; inset: -12px;
  border-radius: 50%;
  border: 1px dashed var(--accent);
  opacity: 0.4;
  animation: crest-turn 90s linear infinite;
}
@keyframes crest-breathe { 0%, 100% { opacity: 0.55; transform: scale(0.94); } 50% { opacity: 1; transform: scale(1.06); } }
@keyframes crest-turn { to { transform: rotate(360deg); } }

/* ═══════════ Panel ═══════════ */
.tool-main { position: relative; z-index: 1; flex: 1; width: 100%; max-width: 760px; margin: 0 auto; padding: 2.6rem 2rem 1rem; }
.tool-panel, .tool-gate {
  position: relative;
  padding: 1.7rem 1.8rem;
  background: var(--surface);
  border: 1px solid var(--border-med);
  border-radius: var(--radius);
  box-shadow: 0 24px 60px -30px rgba(0, 0, 0, 0.55);
}
/* El filete superior se traza una vez que el panel ya está en su sitio. */
.tool-panel::before {
  content: '';
  position: absolute; top: -1px; left: 14px; right: 14px; height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent-bright), transparent);
  transform: scaleX(0);
  animation: panel-line 1.4s var(--ease-settle) 1.3s forwards;
}
@keyframes panel-line { to { transform: scaleX(1); } }

.tool-gate-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); font-weight: 600; color: var(--text); }
.tool-gate-body { color: var(--text-dim); font-size: var(--fs-md); margin-top: 0.5rem; }
.tool-cta {
  display: inline-block;
  margin-top: 1.2rem;
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.16em; text-transform: uppercase;
  padding: 0.8rem 1.8rem;
  border-radius: 3px;
  background: var(--accent);
  color: var(--on-accent);
  transition: all var(--transition);
}
.tool-cta:hover { background: var(--accent-bright); box-shadow: 0 0 24px var(--accent-dim); }

@media (max-width: 720px) {
  .stage-inner { padding: 1.8rem 1.4rem 2.4rem; }
  .stage-head { grid-template-columns: 1fr; }
  .stage-crest { width: 104px; height: 104px; }
  .stage-crest :deep(.tool-glyph) { width: 104px !important; height: 104px !important; }
  .tool-main { padding: 2rem 1.2rem 1rem; }
  .tool-panel, .tool-gate { padding: 1.3rem 1.2rem; }
}
@media (prefers-reduced-motion: reduce) {
  .crest-glow, .crest-halo { animation: none; }
  .tool-panel::before { animation: none; transform: scaleX(1); }
}
</style>
