<template>
  <section :id="section.id" class="doc-section">
    <h2 class="doc-heading">{{ section.heading }}</h2>

    <template v-for="(block, index) in section.blocks" :key="index">
      <p v-if="block.type === 'p'" class="doc-p"><DocInline :text="block.text" /></p>

      <ul v-else-if="block.type === 'list'" class="doc-list">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex"><DocInline :text="item" /></li>
      </ul>

      <ol v-else-if="block.type === 'steps'" class="doc-steps">
        <li v-for="(step, stepIndex) in block.items" :key="stepIndex" class="doc-step">
          <span class="doc-step-title"><DocInline :text="step.title" /></span>
          <span class="doc-step-text"><DocInline :text="step.text" /></span>
        </li>
      </ol>

      <dl v-else-if="block.type === 'terms'" class="doc-terms">
        <div v-for="(entry, entryIndex) in block.items" :key="entryIndex" class="doc-term">
          <dt><DocInline :text="entry.term" /></dt>
          <dd><DocInline :text="entry.text" /></dd>
        </div>
      </dl>

      <aside v-else-if="block.type === 'callout'" class="doc-callout"><DocInline :text="block.text" /></aside>
    </template>

    <figure v-for="figure in visibleFigures" :key="figure.image" class="doc-figure">
      <img :src="figure.url" :alt="figure.alt" loading="lazy" decoding="async" />
      <figcaption v-if="figure.caption"><DocInline :text="figure.caption" /></figcaption>
    </figure>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import DocInline from '@/components/documentation/DocInline.vue'
import { resolveFigureUrl } from '@/content/documentation'

/**
 * Una sección de una página de documentación: su título, sus bloques
 * de texto y, si las tiene, sus figuras. La forma de `section` está descrita
 * en `content/documentation/index.js`.
 */
const props = defineProps({
  /** La sección tal como viene del fichero de contenido. */
  section: { type: Object, required: true },
})

/**
 * Las figuras cuya imagen existe. Una figura declarada sin fichero no deja
 * hueco: la página se lee igual que sin ella.
 */
const visibleFigures = computed(() => (props.section.figures ?? [])
  .map((figure) => ({ ...figure, url: resolveFigureUrl(figure.image) }))
  .filter((figure) => figure.url))
</script>

<style scoped>
.doc-section { scroll-margin-top: 5.5rem; }

.doc-heading {
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
  font-size: var(--fs-3xl); font-weight: 600; line-height: 1.2;
  color: var(--text);
  margin-bottom: 1.3rem;
}

.doc-p { margin-bottom: 1.1rem; }

.doc-list { margin: 0 0 1.2rem 1.2rem; display: flex; flex-direction: column; gap: 0.55rem; }
.doc-list li::marker { color: var(--accent); }

.doc-steps { list-style: none; counter-reset: doc-step; margin: 0.4rem 0 1.4rem; display: flex; flex-direction: column; gap: 1rem; }
.doc-step {
  counter-increment: doc-step;
  position: relative;
  padding: 0.2rem 0 0 3.1rem;
  display: flex; flex-direction: column; gap: 0.25rem;
}
.doc-step::before {
  content: counter(doc-step);
  position: absolute; left: 0; top: 0;
  width: 2.1rem; height: 2.1rem;
  display: grid; place-items: center;
  border: 1px solid var(--border-med);
  border-radius: 50%;
  font-family: var(--font-epic); font-size: var(--fs-sm);
  color: var(--accent);
  background: var(--accent-dim);
}
.doc-step-title { color: var(--text); font-weight: 600; }

.doc-terms { margin: 0.4rem 0 1.4rem; display: grid; gap: 0.2rem; }
.doc-term {
  display: grid; grid-template-columns: minmax(9rem, 13rem) 1fr; gap: 1.2rem;
  padding: 0.85rem 0;
  border-bottom: 1px solid var(--border);
}
.doc-term:last-child { border-bottom: none; }
.doc-term dt { color: var(--text); font-weight: 600; }
.doc-term dd { margin: 0; }

.doc-callout {
  margin: 1.6rem 0;
  padding: 1.1rem 1.3rem;
  border-left: 2px solid var(--accent);
  background: var(--accent-dim);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  font-size: var(--fs-md);
}

.doc-figure { margin: 2rem 0 1rem; }
.doc-figure img {
  display: block; width: 100%; height: auto;
  border: 1px solid var(--border-med);
  border-radius: var(--radius-sm);
}
.doc-figure figcaption { margin-top: 0.6rem; font-size: var(--fs-sm); color: var(--text-muted); }

.doc-section :deep(strong) { color: var(--text); font-weight: 600; }
.doc-section :deep(code) {
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: 0.88em;
  padding: 0.08em 0.38em;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--accent-bright);
  overflow-wrap: anywhere;
}

@media (max-width: 640px) {
  .doc-heading { font-size: var(--fs-2xl); }
  .doc-term { grid-template-columns: 1fr; gap: 0.3rem; }
}
</style>
