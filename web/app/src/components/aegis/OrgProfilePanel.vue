<template>
  <div class="org-profile-panel">
    <button type="button" class="op-header" @click="expanded = !expanded">
      <h2>{{ t('aegis.profile.title') }}</h2>
      <span
        class="op-chevron"
        :class="{ 'op-chevron--open': expanded }"
        aria-hidden="true"
        >▸</span
      >
    </button>

    <p v-if="!expanded" class="op-summary">
      {{ store.tweaks.company || t('aegis.profile.notConfigured') }} ·
      {{ productsSummary }}
    </p>

    <div class="op-collapse" :class="{ expanded }">
      <div class="op-collapse-inner">
        <div class="op-body">
          <div class="form-group">
            <label for="op-company">{{ t('aegis.profile.company') }}</label>
            <input
              id="op-company"
              v-model="store.tweaks.company"
              type="text"
              maxlength="60"
              class="input"
              :placeholder="t('aegis.profile.companyPlaceholder')"
            />
          </div>

          <div class="form-group">
            <label for="op-contact">{{ t('aegis.editor.contact') }}</label>
            <input
              id="op-contact"
              v-model="store.tweaks.mentionContact"
              type="email"
              maxlength="100"
              class="input"
              :placeholder="t('aegis.profile.contactPlaceholder')"
            />
          </div>

          <div class="form-row">
            <div class="form-group">
              <label for="op-lang">{{ t('aegis.profile.language') }}</label>
              <select
                id="op-lang"
                v-model="store.tweaks.language"
                class="input select"
              >
                <option v-for="language in GENERATION_LANGUAGES" :key="language.code" :value="language.code" :lang="language.code">{{ language.name }}</option>
              </select>
            </div>
            <div class="form-group">
              <label for="op-tone">{{ t('aegis.profile.tone') }}</label>
              <select
                id="op-tone"
                v-model="store.tweaks.tone"
                class="input select"
              >
                <option v-for="tone in TONES" :key="tone" :value="tone">{{ t(`aegis.profile.tones.${tone}`) }}</option>
              </select>
            </div>
          </div>

          <div class="form-group">
            <label for="op-sector">{{ t('aegis.profile.sector') }}</label>
            <input
              id="op-sector"
              v-model="store.tweaks.sector"
              type="text"
              maxlength="40"
              class="input"
              :placeholder="t('aegis.profile.sectorPlaceholder')"
            />
          </div>

          <div class="form-row">
            <div class="form-group">
              <label for="op-size">{{ t('aegis.profile.size') }}</label>
              <select
                id="op-size"
                v-model="store.tweaks.companySize"
                class="input select"
              >
                <option value="">{{ t('aegis.profile.unspecified') }}</option>
                <option value="micro">{{ t('aegis.profile.sizes.micro') }}</option>
                <option value="pequeña">{{ t('aegis.profile.sizes.small') }}</option>
                <option value="mediana">{{ t('aegis.profile.sizes.medium') }}</option>
              </select>
            </div>
            <div class="form-group">
              <label for="op-employees">{{ t('aegis.profile.employees') }}</label>
              <input
                id="op-employees"
                v-model.number="store.tweaks.employeeCount"
                type="number"
                min="1"
                class="input"
                :placeholder="t('aegis.profile.optional')"
              />
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label for="op-jurisdiction">{{ t('aegis.profile.jurisdiction') }}</label>
              <input
                id="op-jurisdiction"
                v-model="store.tweaks.jurisdiction"
                type="text"
                maxlength="256"
                class="input"
                :placeholder="t('aegis.profile.jurisdictionPlaceholder')"
              />
            </div>
            <div class="form-group">
              <label for="op-workmodel">{{ t('aegis.profile.workModel') }}</label>
              <select
                id="op-workmodel"
                v-model="store.tweaks.workModel"
                class="input select"
              >
                <option value="">{{ t('aegis.profile.unspecified') }}</option>
                <option value="remoto">{{ t('aegis.profile.workModels.remote') }}</option>
                <option value="híbrido">{{ t('aegis.profile.workModels.hybrid') }}</option>
                <option value="presencial">{{ t('aegis.profile.workModels.onSite') }}</option>
              </select>
            </div>
          </div>

          <!-- El buscador y el interruptor de inventario viven ahora en su
               propio modal: en 400 px de panel no cabían. La lista de
               seleccionados crecía sin tope y empujaba el buscador, y la de
               resultados desplazaba al botón de guardar. -->
          <div class="form-group">
            <label>{{ t('aegis.products.title') }}</label>
            <button
              type="button"
              class="products-btn"
              @click="productsModalOpen = true"
            >
              <span>{{ t('aegis.profile.manageProducts') }}</span>
              <span class="products-count">{{ productsSummary }}</span>
            </button>
          </div>

          <WhiteLabelFields
            v-model="store.whiteLabel"
            :max-level="store.maxWhiteLabelLevel"
          />

          <button
            type="button"
            class="btn-save-profile"
            :disabled="store.savingOrgProfile"
            @click="handleSave"
          >
            <span v-if="store.savingOrgProfile" class="spinner"></span>
            {{
              store.savingOrgProfile
                ? t('common.saving')
                : store.orgProfileConfigured
                  ? t('aegis.profile.update')
                  : t('aegis.profile.save')
            }}
          </button>
        </div>
      </div>
    </div>

    <TrackedProductsModal
      :show="productsModalOpen"
      @close="productsModalOpen = false"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { useAegisStore } from "@/stores/aegisStore";
import WhiteLabelFields from "@/components/shared/WhiteLabelFields.vue";
import TrackedProductsModal from "./TrackedProductsModal.vue";
import { useI18n } from "vue-i18n";

const { t } = useI18n();

const store = useAegisStore();

/**
 * Idiomas en los que la IA puede escribir la píldora, cada uno con su propio
 * nombre. Es el idioma del contenido, no el de la interfaz.
 */
const GENERATION_LANGUAGES = [
  { code: "es", name: "Español" },
  { code: "en", name: "English" },
  { code: "fr", name: "Français" },
  { code: "de", name: "Deutsch" },
];

/** Tonos que acepta la generación; el valor es el que entiende el servidor. */
const TONES = ["profesional", "formal", "cercano", "tecnico"];

// Colapsado por defecto si ya hay perfil guardado (nada que revisar cada
// mes); expandido si es la primera vez. Se ajusta tras cargar el perfil.
const expanded = ref(true);

const productsModalOpen = ref(false);

/** Origen efectivo de los productos: los agentes mandan cuando están activos. */
const usingInventory = computed(
  () => store.hygeiaInventoryAvailable && store.useHygeiaInventory,
);

/**
 * Qué se está vigilando, en una línea. Lo usan el resumen del acordeón
 * colapsado y el botón que abre el modal: antes cada uno lo calculaba por su
 * cuenta en el template.
 */
const productsSummary = computed(() => {
  if (usingInventory.value) return t('aegis.profile.agentProducts');
  const count = store.trackedProducts.length;
  if (!count) return t('aegis.profile.noProducts');
  return t('aegis.profile.productCount', { count }, count);
});

async function handleSave() {
  const ok = await store.saveOrgProfile();
  if (ok) expanded.value = false;
}

onMounted(async () => {
  await store.loadOrgProfile();
  expanded.value = !store.orgProfileConfigured;
});
</script>

<style scoped>
.org-profile-panel {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  padding: 1.1rem;
  border-bottom: 1px solid var(--border);
}
.op-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  width: 100%;
  text-align: left;
}
.op-header h2 {
  font-size: var(--fs-xl);
  font-weight: 700;
  color: var(--text);
  margin: 0;
  font-family: var(--font-display); font-size-adjust: var(--fsa-display);
}
.op-chevron {
  color: var(--text-muted);
  transition: transform 0.2s;
  font-size: var(--fs-2xl);
}
.op-chevron--open {
  transform: rotate(90deg);
}
.op-summary {
  font-size: var(--fs-md);
  color: var(--text-dim);
  margin: 0;
}
/* Colapso suave sin medir alturas a mano: mismo patrón que
   FolderAccordion.vue (grid-template-rows 0fr → 1fr + overflow:hidden en el
   contenedor interno), en vez del v-show original (aparecía/desaparecía de
   golpe). */
.op-collapse {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.op-collapse.expanded {
  grid-template-rows: 1fr;
}
.op-collapse-inner {
  overflow: hidden;
  min-height: 0;
}
.op-body {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
/* Una columna: a este ancho de panel, dos columnas dejaban etiquetas largas
   ("Tamaño de empresa") sin sitio y el input caía a la línea de abajo. */
.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.form-group label {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-dim);
}
.input {
  background: var(--bg);
  border: 1px solid var(--border-solid);
  border-radius: 6px;
  padding: 0.4rem 0.55rem;
  color: var(--text);
  font-size: var(--fs-input);
  outline: none;
  width: 100%;
  box-sizing: border-box;
  transition: border-color 0.2s;
  font-family: inherit;
}
.input:focus {
  border-color: var(--accent);
}
.select {
  cursor: pointer;
  appearance: auto;
}
.input[type="number"]::-webkit-inner-spin-button,
.input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.input[type="number"] {
  -moz-appearance: textfield;
}
/* ── Acceso al modal de productos vigilados ── */
.products-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  width: 100%;
  padding: 0.45rem 0.6rem;
  border-radius: 6px;
  border: 1px solid var(--border-solid);
  background: var(--bg);
  color: var(--text);
  font-family: inherit;
  font-size: var(--fs-input);
  cursor: pointer;
  transition: border-color 0.2s;
}
.products-btn:hover {
  border-color: var(--accent);
}
.products-count {
  flex: 0 0 auto;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--accent-bright);
}
.btn-save-profile {
  margin-top: 0.2rem;
  padding: 0.55rem;
  font-size: var(--fs-md);
  font-weight: 700;
  border-radius: 7px;
  border: 1px solid var(--accent);
  cursor: pointer;
  background: var(--accent-dim);
  color: var(--accent);
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
}
.btn-save-profile:hover:not(:disabled) {
  background: var(--accent);
  color: var(--on-accent);
}
.btn-save-profile:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(0, 0, 0, 0.15);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: seq-spin 0.6s linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  .op-collapse,
  .op-chevron {
    transition: none;
  }
}
</style>
