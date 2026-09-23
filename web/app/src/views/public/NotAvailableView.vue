<template>
  <InfoPage eyebrow="Ellysia" title="Todavía no disponible">
    <p>
      {{ featureLabel ? `${featureLabel} todavía no está disponible.` : 'Esta función todavía no está disponible.' }}
      Ellysia está en vista previa y abrimos cada parte a medida que completamos lo necesario para
      ofrecerla con garantías.
    </p>
    <p>Desde aquí puedes:</p>
    <ul>
      <li><router-link to="/">volver a la portada</router-link></li>
      <li><router-link to="/sobre">conocer Ellysia</router-link></li>
    </ul>
  </InfoPage>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import InfoPage from '@/components/shared/InfoPage.vue'

/**
 * Nombre de la función de cada ruta que puede cerrarse, para decir qué no
 * está disponible en vez de un mensaje genérico. Una ruta sin entrada cae en
 * el texto genérico.
 */
const FEATURE_LABELS = {
  '/planes': 'La página de planes y precios',
  '/iris/conexiones': 'La conexión de buzones de correo',
}

const route = useRoute()

/** Nombre de la función que se pidió, o cadena vacía si no se conoce. */
const featureLabel = computed(() => {
  const requestedPath = String(route.query.desde || '').split('?')[0]
  return FEATURE_LABELS[requestedPath] || ''
})
</script>
