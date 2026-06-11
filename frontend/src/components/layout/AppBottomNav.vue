<template>
  <nav class="bottom-nav" v-if="!isAdminSection">
    <router-link v-for="item in siteMenus" :key="item.path" :to="item.path" class="nav-item">
      <div class="icon-wrap">
        <n-icon :size="20"><component :is="item.icon" /></n-icon>
        <span v-if="item.badge && item.badge > 0" class="badge">{{ item.badge > 9 ? '9+' : item.badge }}</span>
      </div>
      <span class="label">{{ item.title }}</span>
    </router-link>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { NIcon } from 'naive-ui'
import { Home, ListCheck, Edit, CloudUpload } from '@vicons/tabler'

const route = useRoute()
const store = useAppStore()

const isAdminSection = computed(() => route.path.startsWith('/admin'))

const siteMenus = computed(() => [
  { path: '/dashboard',     title: '首页', icon: Home,         badge: store.overdueTasks.length + store.waitingConfirmTasks.length },
  { path: '/tasks',         title: '任务', icon: ListCheck,    badge: store.pendingTasks.length + store.processingTasks.length },
  { path: '/drafts',        title: '草稿', icon: Edit,         badge: store.pendingDrafts.length },
  { path: '/filling',       title: '填报', icon: CloudUpload,  badge: store.pendingFills.length },
])
</script>

<style scoped>
.bottom-nav {
  display: flex;
  background: var(--bg-surface);
  border-top: 1px solid var(--border-default);
  padding: 6px 0;
  padding-bottom: env(safe-area-inset-bottom, 6px);
  justify-content: space-around;
  z-index: 100;
}

.nav-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-decoration: none;
  color: var(--text-muted);
  gap: 4px;
  flex: 1;
}

.nav-item.router-link-active {
  color: var(--color-primary);
}

.icon-wrap {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
}

.badge {
  position: absolute;
  top: -4px;
  right: -8px;
  background: var(--color-danger);
  color: white;
  font-size: 10px;
  padding: 0 4px;
  border-radius: 8px;
  border: 1px solid var(--bg-surface);
  line-height: 1.2;
}

.label {
  font-size: 10px;
  font-weight: 500;
}
</style>
