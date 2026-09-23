<template>
  <InfoPage eyebrow="Ellysia" title="Sobre Ellysia">
    <p>
      Ellysia es un <strong>proyecto personal</strong>: un banco de pruebas donde su autor construye y
      experimenta con herramientas de ciberseguridad. <strong>No es un servicio ni un producto
      comercial.</strong> No se ofrecen cuentas, no se contrata nada y no hay ninguna empresa detrás.
    </p>

    <h2>Qué contiene</h2>
    <ul>
      <li><strong>Themis</strong> — detección de vulnerabilidades con un motor propio (Lybra) y escáneres clásicos como contraste.</li>
      <li><strong>Aegis</strong> — formaciones de concienciación en seguridad generadas con inteligencia artificial.</li>
      <li><strong>Iris</strong> — análisis de correos electrónicos para detectar fraudes (phishing), con el veredicto explicado.</li>
      <li><strong>Acheron</strong> — caja fuerte de contraseñas cifrada en el navegador: la llave nunca viaja al servidor.</li>
      <li><strong>Hygeia</strong> — vigilancia del estado de servidores y equipos.</li>
    </ul>

    <h2>La idea de fondo</h2>
    <p>
      La motivación es aprender y explorar qué haría falta para que protegerse no fuera un privilegio
      de quien puede pagar un equipo de seguridad. Si Ellysia llegara a ofrecerse algún día a otras
      personas, esta página y las condiciones legales cambiarían antes.
    </p>

    <p class="note">
      El código se puede consultar en
      <a href="https://github.com/ProjectEllysia/EllysiaServer" target="_blank" rel="noopener noreferrer">GitHub</a>,
      con todos los derechos reservados.
    </p>
  </InfoPage>
</template>

<script setup>
import InfoPage from '@/components/shared/InfoPage.vue'
</script>
