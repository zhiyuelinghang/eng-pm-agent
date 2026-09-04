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
import { onBeforeUnmount, onMounted, watch } from 'vue'

import { useAppStore } from '@/stores/app'
import {
  resetRealtimeSession,
  setRealtimeSessionProject,
} from '@/services/realtimeSession'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'

const store = useAppStore()

watch(
  () => store.currentProjectId,
  projectId => setRealtimeSessionProject(projectId),
  { immediate: true },
)

onMounted(() => {
  // Load the transport after login without folding Centrifuge into the initial
  // login bundle. The module registers itself against the selected project.
  void import('@/api/projectChat').catch(() => undefined)
})

onBeforeUnmount(resetRealtimeSession)
</script>

<style scoped>
.layout { display: flex; height: 100dvh; overflow: hidden; background: var(--bg-base); }
.layout-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }
.layout-content { flex: 1; overflow-y: auto; overflow-x: hidden; }
</style>
