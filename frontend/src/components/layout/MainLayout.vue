<template>
  <div class="layout">
    <AppSidebar class="desktop-sidebar" />
    <div class="layout-body">
      <AppHeader />
      <main class="layout-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
</script>

<style scoped>
.layout { display: flex; height: 100dvh; overflow: hidden; background: var(--bg-base); }
.layout-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }
.layout-content { flex: 1; overflow-y: auto; overflow-x: hidden; }
</style>
