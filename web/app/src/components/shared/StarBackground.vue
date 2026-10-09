<template>
  <div class="bg" aria-hidden="true">
    <div class="bg-orb bg-orb--1"></div>
    <div class="bg-orb bg-orb--2"></div>
    <div class="bg-orb bg-orb--3"></div>
    <div class="bg-hex"></div>
    <div class="bg-scanlines"></div>
    <div class="bg-grain"></div>
    <div
      v-for="p in particles"
      :key="p.id"
      class="bg-particle"
      :style="{
        left: p.x + '%',
        top: p.y + '%',
        width: p.size + 'px',
        height: p.size + 'px',
        animationDelay: p.delay + 's',
        animationDuration: p.duration + 's',
        opacity: p.opacity
      }"
    ></div>
  </div>
</template>

<script setup>
const particles = Array.from({ length: 18 }, (_, i) => ({
  id: i,
  x: Math.random() * 100,
  y: Math.random() * 100,
  size: 1 + Math.random() * 2.5,
  delay: Math.random() * 8,
  duration: 6 + Math.random() * 10,
  opacity: 0.12 + Math.random() * 0.28
}))
</script>

<style scoped>
.bg {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
  background: var(--bg, #0b0c10);
}

/* Sin filtro de desenfoque: el degradado radial ya se funde con el fondo, y un desenfoque
   de 150 px sobre una capa que se mueve se recalcula en cada fotograma, que en una
   gráfica integrada es justo lo que hace ir a tirones una página tranquila. */
.bg-orb {
  position: absolute;
  border-radius: 50%;
  animation: orb-drift 24s ease-in-out infinite;
}
.bg-orb--1 {
  width: 700px;
  height: 700px;
  background: radial-gradient(circle, rgba(212,160,74,0.14) 0%, transparent 70%);
  top: -25%;
  left: -15%;
  animation-delay: 0s;
}
.bg-orb--2 {
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(76,183,130,0.10) 0%, transparent 70%);
  bottom: -15%;
  right: -10%;
  animation-delay: -9s;
}
.bg-orb--3 {
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, rgba(96,128,224,0.08) 0%, transparent 70%);
  top: 35%;
  left: 55%;
  animation-delay: -18s;
}

@keyframes orb-drift {
  0%, 100% { transform: translate(0, 0) scale(1); }
  25%      { transform: translate(40px, -25px) scale(1.06); }
  50%      { transform: translate(-25px, 35px) scale(0.94); }
  75%      { transform: translate(25px, 12px) scale(1.03); }
}

.bg-hex {
  position: absolute;
  inset: 0;
  opacity: 0.025;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='56' height='97' viewBox='0 0 56 97'%3E%3Cpath d='M28 0L56 16v32L28 64L0 48V16L28 0zM28 97L0 81V49l28 16 28-16v32L28 97z' fill='none' stroke='%23e8bc6a' stroke-width='0.6'/%3E%3C/svg%3E");
  background-size: 56px 97px;
}

.bg-scanlines {
  position: absolute;
  inset: 0;
  opacity: 0.015;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 3px,
    rgba(255,255,255,0.03) 3px,
    rgba(255,255,255,0.03) 4px
  );
}

.bg-grain {
  position: absolute;
  inset: 0;
  opacity: 0.025;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  background-repeat: repeat;
  background-size: 256px 256px;
}

.bg-particle {
  position: absolute;
  border-radius: 50%;
  background: var(--accent-bright, #e8bc6a);
  animation: particle-float linear infinite;
  pointer-events: none;
}

@keyframes particle-float {
  0%   { transform: translateY(0) translateX(0); opacity: 1; }
  25%  { transform: translateY(-120px) translateX(15px); opacity: 0.7; }
  50%  { transform: translateY(-240px) translateX(-10px); opacity: 0.3; }
  75%  { transform: translateY(-360px) translateX(8px); opacity: 0.5; }
  100% { transform: translateY(-500px) translateX(-5px); opacity: 0; }
}
</style>
