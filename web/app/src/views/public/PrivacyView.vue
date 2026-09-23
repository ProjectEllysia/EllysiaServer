<template>
  <InfoPage eyebrow="Legal" title="Privacidad">
    <p>
      Ellysia es un <strong>proyecto personal</strong> y no un servicio: no se ofrecen cuentas a otras
      personas ni se contrata nada. Esta nota explica qué datos se tratan de quien visita la web, que es
      lo único que Ellysia sabe de alguien que no sea su autor.
    </p>

    <h2>Quién es el responsable</h2>
    <p>
      Gabriel Musteata, autor del proyecto, como persona física. Puedes contactar a través de su perfil de
      GitHub,
      <a href="https://github.com/gamustea" target="_blank" rel="noopener noreferrer">github.com/gamustea</a>.
    </p>

    <h2>Qué datos se guardan de quien visita la web</h2>
    <p>
      Cada vez que tu navegador pide algo a Ellysia, el servidor lo anota en su registro de actividad:
      la <strong>dirección IP</strong> desde la que se hace la petición, la fecha y la hora, qué se pidió,
      la respuesta que se dio y cuánto tardó.
    </p>
    <ul>
      <li><strong>Para qué:</strong> para mantener el servidor seguro y diagnosticar errores.</li>
      <li><strong>Por qué se puede:</strong> por el interés legítimo en proteger el servidor (artículo 6.1.f del Reglamento General de Protección de Datos).</li>
      <li><strong>Cuánto tiempo:</strong> cada día se archiva por separado y se borra a los {{ LOG_RETENTION_DAYS }} días.</li>
      <li><strong>Quién lo ve:</strong> solo el autor. No se comparte con nadie ni sale del servidor, que está en España.</li>
    </ul>

    <h2>Cookies y almacenamiento del navegador</h2>
    <p>
      Ellysia <strong>no usa cookies</strong>, ni herramientas de analítica, ni publicidad, ni ningún
      sistema de seguimiento. Tampoco carga recursos de otras webs: las tipografías se sirven desde el
      propio servidor. Por eso no hay aviso de cookies que aceptar.
    </p>
    <p>
      El navegador solo guarda, en su almacenamiento local, lo imprescindible para que la web funcione:
      que has cerrado el aviso de proyecto personal (hasta que cierres la pestaña), el tema de color si lo
      cambias y, si inicias sesión, la sesión. Puedes borrarlo en cualquier momento desde los ajustes del
      navegador.
    </p>

    <h2>Tus derechos</h2>
    <p>
      Puedes pedir acceder a los datos que se guardan sobre ti, que se borren o que se dejen de tratar.
      Como el registro solo guarda direcciones IP, indica desde qué dirección y en qué fechas visitaste
      la web. También puedes reclamar ante la
      <a href="https://www.aepd.es" target="_blank" rel="noopener noreferrer">Agencia Española de Protección de Datos</a>.
    </p>

    <p class="note">
      Versión de {{ LAST_UPDATED }}. Si Ellysia llegara a ofrecerse a otras personas, esta nota se
      sustituiría antes por una política de privacidad completa.
    </p>
  </InfoPage>
</template>

<script setup>
import InfoPage from '@/components/shared/InfoPage.vue'

/**
 * Plazo de conservación del registro de actividad que se anuncia. Tiene que
 * coincidir con `general.logs.retentionDays` de la configuración que se
 * despliega; si se cambia allí, se cambia aquí.
 */
const LOG_RETENTION_DAYS = 30

/** Fecha de la versión vigente de esta nota. */
const LAST_UPDATED = '23 de septiembre de 2026'
</script>
