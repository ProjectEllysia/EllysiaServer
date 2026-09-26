<template>
  <InfoPage :eyebrow="t('legal.eyebrow')" :title="t('privacy.title')">
    <p v-if="locale !== 'es'" class="note">{{ t('legal.translationNotice') }}</p>
    <i18n-t keypath="privacy.intro" tag="p">
      <template #project><strong>{{ t('privacy.introProject') }}</strong></template>
    </i18n-t>

    <h2>{{ t('privacy.controllerHeading') }}</h2>
    <i18n-t keypath="privacy.controller" tag="p">
      <template #link>
        <a :href="`https://${CONTROLLER_PROFILE}`" target="_blank" rel="noopener noreferrer">{{ CONTROLLER_PROFILE }}</a>
      </template>
    </i18n-t>

    <h2>{{ t('privacy.dataHeading') }}</h2>
    <i18n-t keypath="privacy.data" tag="p">
      <template #ip><strong>{{ t('privacy.dataIp') }}</strong></template>
    </i18n-t>
    <ul>
      <li><strong>{{ t('privacy.purposeLabel') }}</strong> {{ t('privacy.purpose') }}</li>
      <li><strong>{{ t('privacy.legalBasisLabel') }}</strong> {{ t('privacy.legalBasis') }}</li>
      <li><strong>{{ t('privacy.retentionLabel') }}</strong> {{ t('privacy.retention', { days: LOG_RETENTION_DAYS }) }}</li>
      <li><strong>{{ t('privacy.accessLabel') }}</strong> {{ t('privacy.access') }}</li>
    </ul>

    <h2>{{ t('privacy.cookiesHeading') }}</h2>
    <i18n-t keypath="privacy.cookies" tag="p">
      <template #noCookies><strong>{{ t('privacy.cookiesNone') }}</strong></template>
    </i18n-t>
    <p>{{ t('privacy.storage') }}</p>

    <h2>{{ t('privacy.rightsHeading') }}</h2>
    <i18n-t keypath="privacy.rights" tag="p">
      <template #authority>
        <a href="https://www.aepd.es" target="_blank" rel="noopener noreferrer">{{ t('privacy.rightsAuthority') }}</a>
      </template>
    </i18n-t>

    <p class="note">{{ t('privacy.version', { date: formatDate(LAST_UPDATED, { day: 'numeric', month: 'long', year: 'numeric' }) }) }}</p>
  </InfoPage>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import InfoPage from '@/components/shared/InfoPage.vue'
import { formatDate } from '@/i18n/format'

const { t, locale } = useI18n()

/**
 * Plazo de conservación del registro de actividad que se anuncia. Tiene que
 * coincidir con `general.logs.retentionDays` de la configuración que se
 * despliega; si se cambia allí, se cambia aquí.
 */
const LOG_RETENTION_DAYS = 30

/** Fecha de la versión vigente de esta nota, en ISO; se pinta en el idioma activo. */
const LAST_UPDATED = '2026-09-23T12:00:00'

/** Perfil público por el que se contacta con el responsable. */
const CONTROLLER_PROFILE = 'github.com/gamustea'
</script>
