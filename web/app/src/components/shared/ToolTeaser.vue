<template>
  <section class="teaser" :data-module="tool.module">
    <ModuleAtmosphere :module-id="tool.module" strength="subtle" focus="sides" />

    <div class="teaser-inner">
      <header v-reveal class="teaser-head">
        <span class="teaser-kicker">{{ identity.numeral }} · {{ identity.name }} · {{ identity.epigraph }}</span>
        <h2 class="teaser-title">{{ t(HUB_COPY_KEYS[tool.module].claim) }}</h2>
        <p class="teaser-lead">{{ t('freeTools.teaser.lead', { name: identity.name }) }}</p>
        <p v-if="moreTo" class="teaser-hook">{{ t(`freeTools.items.${tool.id}.more`) }}</p>
        <div class="teaser-actions">
          <router-link v-if="moreTo" :to="moreTo" class="teaser-cta teaser-cta--solid">{{ t(`freeTools.items.${tool.id}.moreCta`) }}</router-link>
          <router-link :to="identity.route" class="teaser-cta teaser-cta--line">{{ t('freeTools.teaser.discover', { name: identity.name }) }}</router-link>
        </div>
      </header>

      <ul class="teaser-grid">
        <li v-for="(featureId, index) in featureIds" :key="featureId" v-reveal="staggerDelay(index, 110)" class="teaser-card">
          <span class="teaser-card-kicker">{{ t(`${hubNamespace}.features.${featureId}.kicker`) }}</span>
          <h3 class="teaser-card-title">{{ t(`${hubNamespace}.features.${featureId}.title`) }}</h3>
          <p class="teaser-card-desc">{{ t(`${hubNamespace}.features.${featureId}.desc`) }}</p>
        </li>
      </ul>

      <nav v-if="siblings.length" v-reveal="200" class="teaser-siblings" :aria-label="t('freeTools.teaser.otherTools', { name: identity.name })">
        <p class="teaser-siblings-label">{{ t('freeTools.teaser.otherTools', { name: identity.name }) }}</p>
        <ul class="teaser-siblings-list">
          <li v-for="sibling in siblings" :key="sibling.id">
            <router-link :to="sibling.path" class="sibling glyph-host">
              <ToolGlyph :tool-id="sibling.id" :size="46" />
              <span>{{ t(`freeTools.items.${sibling.id}.title`) }}</span>
            </router-link>
          </li>
        </ul>
      </nav>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ModuleAtmosphere from '@/components/decor/ModuleAtmosphere.vue'
import ToolGlyph from '@/components/decor/ToolGlyph.vue'
import { staggerDelay } from '@/composables/motionMath'
import { vReveal } from '@/directives/reveal'
import { FREE_TOOLS } from '@/freeTools/catalog'
import { useFreeTools } from '@/freeTools/useFreeTools'
import { HUB_COPY_KEYS, HUB_FEATURE_IDS, MODULE_IDENTITY } from './moduleIdentity'

/**
 * Pie de una página de herramienta gratuita: lo que hay detrás de ella.
 *
 * Presenta el módulo al que pertenece la herramienta —su lema, lo que hace entero y
 * las demás herramientas gratuitas que tiene— para que quien llegó buscando una
 * utilidad conozca el resto. Usa los mismos textos que el hub del módulo.
 */
const props = defineProps({
  /** `id` de la herramienta en el catálogo (`freeTools/catalog.js`). */
  toolId: { type: String, required: true },
  /** Ruta de la herramienta completa del módulo; `null` oculta el botón y el texto que lo acompaña. */
  moreTo: { type: String, default: null },
})

const { t } = useI18n()

const tool = computed(() => FREE_TOOLS.find((candidate) => candidate.id === props.toolId))
const identity = computed(() => MODULE_IDENTITY[tool.value.module])
const hubNamespace = computed(() => `${tool.value.module}Hub`)
/** Las tres primeras capacidades del hub: el resto está en el hub mismo. */
const featureIds = computed(() => HUB_FEATURE_IDS[tool.value.module].slice(0, 3))

const { tools: moduleTools } = useFreeTools(() => tool.value.module)
const siblings = computed(() => moduleTools.value.filter((candidate) => candidate.id !== props.toolId))
</script>

<style scoped>
.teaser {
  position: relative;
  z-index: 1;
  overflow: hidden;
  margin-top: 3rem;
  background: linear-gradient(to bottom, transparent, color-mix(in srgb, var(--surface) 70%, transparent));
  border-top: 1px solid var(--border-med);
}
.teaser-inner { position: relative; max-width: 1060px; margin: 0 auto; padding: 4.2rem 2rem 4.6rem; }

.teaser-head { text-align: center; max-width: 720px; margin: 0 auto 3rem; }
.teaser-kicker {
  display: block;
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.3em; text-transform: uppercase;
  color: var(--accent);
}
.teaser-title {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: clamp(1.9rem, 4.4vw, 2.8rem); font-weight: 600;
  line-height: 1.15;
  color: var(--text);
  margin-top: 0.7rem;
  text-shadow: 0 0 40px var(--accent-dim);
  text-wrap: balance;
}
.teaser-lead { font-size: var(--fs-lg); color: var(--text-dim); margin-top: 0.8rem; }
.teaser-hook { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-style: italic; font-size: var(--fs-xl); color: var(--text); margin-top: 1.4rem; text-wrap: balance; }
.teaser-actions { display: flex; justify-content: center; gap: 1rem; flex-wrap: wrap; margin-top: 1.6rem; }
.teaser-cta {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.16em; text-transform: uppercase;
  padding: 0.85rem 1.8rem;
  border-radius: 3px;
  border: 1px solid var(--accent);
  transition: all var(--transition);
}
.teaser-cta--solid { background: var(--accent); color: var(--on-accent); }
.teaser-cta--solid:hover { background: var(--accent-bright); border-color: var(--accent-bright); box-shadow: 0 0 26px var(--accent-dim); }
.teaser-cta--line { background: var(--accent-dim); color: var(--text); }
.teaser-cta--line:hover { background: var(--accent); color: var(--on-accent); }
.teaser-cta:focus-visible, .sibling:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 3px; }

/* ── Capacidades: el mismo texto que en el hub, con el filete que se traza al aparecer ── */
.teaser-grid { list-style: none; display: grid; grid-template-columns: repeat(3, 1fr); gap: 2.4rem 3rem; }
.teaser-card { position: relative; padding-top: 1.3rem; }
.teaser-card::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: var(--accent);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 1.1s var(--ease-settle) calc(var(--reveal-delay, 0s) + 0.3s);
}
.teaser-card.is-in::before { transform: scaleX(1); }
.teaser-card-kicker {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600;
  letter-spacing: 0.26em; text-transform: uppercase;
  color: var(--accent);
}
.teaser-card-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); font-weight: 600; line-height: 1.25; color: var(--text); margin-top: 0.45rem; }
.teaser-card-desc { font-size: var(--fs-md); color: var(--text-dim); line-height: 1.65; margin-top: 0.5rem; }

/* ── Otras herramientas del módulo ── */
.teaser-siblings { margin-top: 3.4rem; text-align: center; }
.teaser-siblings-label {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm);
  letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--text-muted);
}
.teaser-siblings-list { list-style: none; display: flex; justify-content: center; gap: 1rem; flex-wrap: wrap; margin-top: 1.1rem; }
.sibling {
  display: flex; align-items: center; gap: 0.85rem;
  padding: 0.6rem 1.3rem 0.6rem 0.7rem;
  background: var(--surface);
  border: 1px solid var(--border-med);
  border-radius: 999px;
  color: var(--text-dim);
  font-size: var(--fs-md);
  transition: all var(--transition);
}
.sibling:hover { border-color: var(--accent); color: var(--text); transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18); }

@media (max-width: 860px) {
  .teaser-grid { grid-template-columns: 1fr; }
  .teaser-inner { padding: 3.2rem 1.4rem 3.4rem; }
}
@media (prefers-reduced-motion: reduce) {
  .teaser-card::before { transform: scaleX(1); transition: none; }
  .sibling:hover { transform: none; }
}
</style>
