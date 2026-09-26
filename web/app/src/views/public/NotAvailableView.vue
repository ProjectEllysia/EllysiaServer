<template>
  <InfoPage eyebrow="Ellysia" :title="t('notAvailable.title')">
    <p>
      {{ featureKey ? t('notAvailable.feature', { feature: t(`notAvailable.features.${featureKey}`) }) : t('notAvailable.generic') }}
      {{ t('notAvailable.preview') }}
    </p>
    <p>{{ t('notAvailable.fromHere') }}</p>
    <ul>
      <li><router-link to="/">{{ t('notAvailable.home') }}</router-link></li>
      <li><router-link to="/sobre">{{ t('notAvailable.about') }}</router-link></li>
    </ul>
  </InfoPage>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import InfoPage from '@/components/shared/InfoPage.vue'

const { t } = useI18n()

/**
 * Función de cada ruta que puede cerrarse, para decir qué no está disponible
 * en vez de un mensaje genérico. El nombre sale de
 * `notAvailable.features.<clave>`; una ruta sin entrada cae en el texto
 * genérico.
 */
const FEATURE_KEYS = {
  '/planes': 'plans',
  '/iris/conexiones': 'mailboxConnections',
}

const route = useRoute()

/** Clave de la función que se pidió, o cadena vacía si no se conoce. */
const featureKey = computed(() => {
  const requestedPath = String(route.query.desde || '').split('?')[0]
  return FEATURE_KEYS[requestedPath] || ''
})
</script>
