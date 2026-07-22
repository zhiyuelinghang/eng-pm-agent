<template>
  <aside class="sidebar">
    <div class="sidebar-logo">
      <div class="logo-mark">
        <n-icon :size="20"><Robot /></n-icon>
      </div>
      <div class="logo-text-wrapper">
        <span class="logo-name">Dobby</span>
        <span class="logo-tag">工程管理平台</span>
      </div>
    </div>

    <nav class="nav-list">
      <router-link v-for="item in menus" :key="item.path" :to="item.path" class="nav-item">
        <n-icon :size="16" class="nav-icon"><component :is="item.icon" /></n-icon>
        <span class="nav-label">{{ item.title }}</span>
        <span v-if="item.badge && item.badge > 0" class="nav-badge">{{ item.badge > 9 ? '9+' : item.badge }}</span>
      </router-link>
    </nav>

    <div class="sidebar-footer">
      <div class="user-ava">{{ userInitial }}</div>
      <div class="user-info">
        <div class="user-name">{{ currentUserName }}</div>
        <div class="user-role">{{ currentUserTitle }}</div>
      </div>
      <button class="logout-btn" title="退出登录" @click="handleLogout">
        <n-icon :size="15"><Logout /></n-icon>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { NIcon } from 'naive-ui'
import {
  ChartBar, Folder, Home, ListCheck, Logout, MessageCircle, Robot, Settings, Tools, UserCircle,
} from '@vicons/tabler'

const router = useRouter()
const store = useAppStore()
const currentUserId = computed(() => sessionStorage.getItem('current_user_id') || '')
const currentMember = computed(() => store.members.find(member => member.id === currentUserId.value))
const currentUserName = computed(() => sessionStorage.getItem('current_user_name') || currentMember.value?.name || '当前用户')
const currentUserTitle = computed(() => currentMember.value?.title || '项目成员')
const userInitial = computed(() => currentUserName.value.trim().slice(0, 1) || '用')

const menus = computed(() => [
  { path: '/workbench', title: '工作首页', icon: Home, badge: store.overdueTasks.length + store.waitingConfirmTasks.length },
  { path: '/ai', title: '智能协同', icon: MessageCircle, badge: store.pendingDrafts.length },
  { path: '/tasks', title: '任务管理', icon: ListCheck, badge: store.pendingTasks.length + store.processingTasks.length },
  { path: '/project', title: '项目状态', icon: ChartBar, badge: 0 },
  { path: '/docs', title: '工程资料', icon: Folder, badge: store.pendingDailyReports.length + store.pendingFills.length },
  { path: '/tools', title: '业务工具', icon: Tools, badge: 0 },
  { path: '/profile', title: '个人设置', icon: UserCircle, badge: 0 },
  { path: '/settings', title: '工程配置', icon: Settings, badge: 0 },
])

const handleLogout = () => {
  sessionStorage.removeItem('logged_in')
  sessionStorage.removeItem('access_token')
  sessionStorage.removeItem('user_role')
  sessionStorage.removeItem('current_user_id')
  sessionStorage.removeItem('current_user_name')
  router.push('/login')
}
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  background: #102528;
  border-right: 1px solid rgba(255,255,255,0.08);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
}

/* Logo */
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px 14px;
}
.logo-mark {
  width: 34px;
  height: 34px;
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.logo-text-wrapper {
  display: flex;
  flex-direction: column;
}
.logo-name { font-size: 14px; font-weight: 750; color: #fff; letter-spacing: 0; line-height: 1.2; }
.logo-tag { font-size: 12px; color: rgba(255,255,255,0.68); margin-top: 3px; font-weight: 500; line-height: 1.4; }

.nav-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 10px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 42px;
  padding: 10px 10px;
  border-radius: 7px;
  color: rgba(255,255,255,0.68);
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  transition: var(--transition);
  margin-bottom: 4px;
  position: relative;
}
.nav-item:hover { background: rgba(255,255,255,0.08); color: #fff; }
.nav-item.router-link-active {
  background: #f1f6f2;
  color: #102528;
  font-weight: 750;
}
.nav-item.router-link-active .nav-icon { color: var(--color-primary); }
.nav-icon { font-size: 15px; flex-shrink: 0; color: inherit; }
.nav-label { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nav-badge {
  margin-left: auto;
  background: var(--color-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  min-width: 20px;
  height: 20px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 5px;
  flex-shrink: 0;
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 14px;
  border-top: 1px solid rgba(255,255,255,0.08);
}
.user-ava {
  width: 30px;
  height: 30px;
  background: rgba(255,255,255,0.12);
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.user-name  { font-size: 13px; font-weight: 650; color: #fff; line-height: 1.4; }
.user-role  { font-size: 12px; color: rgba(255,255,255,0.66); margin-top: 2px; line-height: 1.4; }
.user-info { display: grid; flex: 1 1 auto; min-width: 0; }
.user-name,.user-role { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.logout-btn {
  display: flex;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: var(--radius-sm);
  color: rgba(255,255,255,0.56);
  background: transparent;
  cursor: pointer;
  transition: var(--transition);
}
.logout-btn:hover { color: #fff; background: rgba(255,255,255,0.08); }
</style>

