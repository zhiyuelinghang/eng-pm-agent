<template>
  <div class="layout">
    <AppSidebar class="desktop-sidebar" />
    <div class="layout-body">
      <AppHeader />
      <main class="layout-content">
        <router-view />
      </main>
      <AppBottomNav class="mobile-bottom-nav" />
    </div>
  </div>
</template>

<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
import AppBottomNav from './AppBottomNav.vue'
</script>

<style scoped>
.layout { display: flex; height: 100vh; overflow: hidden; background: var(--bg-base); }
.layout-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }
.layout-content { flex: 1; overflow-y: auto; overflow-x: hidden; }

.mobile-bottom-nav { display: none; }

@media (max-width: 768px) {
  .desktop-sidebar { display: none; }
  .mobile-bottom-nav { display: flex; }
}
</style>
