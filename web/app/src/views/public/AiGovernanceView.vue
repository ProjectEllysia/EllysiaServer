<template>
  <InfoPage :eyebrow="t('legal.eyebrow')" :title="t('aiGovernance.title')">
    <p v-if="locale !== 'es'" class="note">{{ t('legal.translationNotice') }}</p>
    <p>{{ t('aiGovernance.intro') }}</p>

    <h2>{{ t('aiGovernance.generalHeading') }}</h2>
    <ul>
      <li>{{ t('aiGovernance.noDecisions') }}</li>
      <li>{{ t('aiGovernance.marked') }}</li>
      <li>{{ t('aiGovernance.humanReview') }}</li>
    </ul>

    <h2>{{ t('aiGovernance.providerHeading') }}</h2>
    <i18n-t keypath="aiGovernance.provider" tag="p">
      <template #provider><strong>{{ AI_PROVIDER_NAME }}</strong></template>
      <template #model><strong>{{ AI_MODEL }}</strong></template>
    </i18n-t>
    <p>{{ t('aiGovernance.training') }}</p>

    <!-- Un apartado por herramienta, con su ancla: los avisos «generado con IA»
         de cada pantalla, PDF y correo enlazan a /gobierno-ia#<herramienta>. -->
    <section v-for="tool in TOOLS" :key="tool">
      <h2 :id="tool">{{ t(`aiGovernance.${tool}.heading`) }}</h2>
      <p>{{ t(`aiGovernance.${tool}.what`) }}</p>
      <ul>
        <li><strong>{{ t('aiGovernance.dataLabel') }}</strong> {{ t(`aiGovernance.${tool}.data`) }}</li>
        <li v-if="te(`aiGovernance.${tool}.notReceived`)">
          <strong>{{ t('aiGovernance.notReceivedLabel') }}</strong> {{ t(`aiGovernance.${tool}.notReceived`) }}
        </li>
        <li v-if="te(`aiGovernance.${tool}.search`)">
          <strong>{{ t('aiGovernance.searchLabel') }}</strong> {{ t(`aiGovernance.${tool}.search`) }}
        </li>
        <li><strong>{{ t('aiGovernance.markingLabel') }}</strong> {{ t(`aiGovernance.${tool}.marking`) }}</li>
      </ul>
    </section>

    <p class="note">{{ t('aiGovernance.version', { date: formatDate(LAST_UPDATED, { day: 'numeric', month: 'long', year: 'numeric' }) }) }}</p>
  </InfoPage>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import InfoPage from '@/components/shared/InfoPage.vue'
import { formatDate } from '@/i18n/format'

const { t, te, locale } = useI18n()

/**
 * Herramientas que usan IA, en el orden en que se explican. Cada una es a la
 * vez la clave de su texto (`aiGovernance.<herramienta>`) y el ancla de su
 * apartado.
 */
const TOOLS = ['aegis', 'themis', 'iris']

/**
 * Proveedor y modelo por defecto que se anuncian. Tienen que coincidir con
 * `tools.scribe.defaultStrategy` y `tools.scribe.strategies.openai.model` de la
 * configuración que se despliega; si se cambian allí, se cambian aquí.
 * `test_ai_governance_matches_config.py` lo comprueba.
 */
const AI_PROVIDER_NAME = 'OpenAI'
const AI_MODEL = 'gpt-4.1-2025-04-14'

/**
 * Fecha de la versión vigente de esta página, en ISO; se pinta en el idioma
 * activo. El texto describe cómo funciona la aplicación hoy y está pendiente de
 * revisión jurídica: no lo trates como texto legal definitivo.
 */
const LAST_UPDATED = '2026-10-07T12:00:00'
</script>
