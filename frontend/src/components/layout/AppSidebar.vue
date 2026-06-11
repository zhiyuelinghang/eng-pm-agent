<template>
  <aside class="sidebar">
    <!-- Logo -->
    <div class="sidebar-logo">
      <div class="logo-mark">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
          <path d="M2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
        </svg>
      </div>
      <div class="logo-text-wrapper">
        <span class="logo-name">工程智管家</span>
        <span class="logo-tag">{{ userRole === 'ops' ? '运维后台中心' : '现场智能终端' }}</span>
      </div>
    </div>

    <!-- Navigation -->
    <nav class="nav-list">
      <template v-if="userRole === 'site'">
        <router-link v-for="item in siteMenus" :key="item.path" :to="item.path" class="nav-item">
          <n-icon :size="15" class="nav-icon"><component :is="item.icon" /></n-icon>
          <span class="nav-label">{{ item.title }}</span>
          <span v-if="item.badge && item.badge > 0" class="nav-badge">{{ item.badge > 9 ? '9+' : item.badge }}</span>
        </router-link>
      </template>
      <template v-else-if="userRole === 'ops'">
        <router-link v-for="item in adminMenus" :key="item.path" :to="item.path" class="nav-item">
          <n-icon :size="15" class="nav-icon"><component :is="item.icon" /></n-icon>
          <span class="nav-label">{{ item.title }}</span>
        </router-link>
      </template>
    </nav>

    <!-- Footer User -->
    <div class="sidebar-footer">
      <div class="user-ava">{{ userRole === 'ops' ? '李' : '张' }}</div>
      <div class="user-info">
        <div class="user-name">{{ userRole === 'ops' ? '李明' : '张伟' }}</div>
        <div class="user-role">{{ userRole === 'ops' ? '系统运维员' : '项目现场负责人' }}</div>
      </div>
      <button class="logout-btn" @click="handleLogout" title="退出登录">
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
  Home, ListCheck, AlertTriangle, FileText,
  Edit, CloudUpload, Settings, Users,
  Notes, Logout, Table, ShieldCheck, Link,
  Folder, Bell
} from '@vicons/tabler'

const router = useRouter()
const store = useAppStore()

const userRole = computed(() => sessionStorage.getItem('user_role') || 'site')

const siteMenus = computed(() => [
  { path: '/dashboard',     title: '工地首页', icon: Home,         badge: store.overdueTasks.length + store.waitingConfirmTasks.length },
  { path: '/tasks',         title: '任务中心',  icon: ListCheck,    badge: store.pendingTasks.length + store.processingTasks.length },
  { path: '/risks',         title: '风险任务',  icon: AlertTriangle, badge: 0 },
  { path: '/daily-reports', title: '日报解析',  icon: FileText,     badge: store.pendingDailyReports.length },
  { path: '/drafts',        title: '草稿审核',  icon: Edit,         badge: store.pendingDrafts.length },
  { path: '/filling',       title: '填报助手',  icon: CloudUpload,  badge: store.pendingFills.length },
  { path: '/members',       title: '用户与班组', icon: Users,        badge: 0 },
])

const adminMenus = [
  { path: '/admin/project',       title: '项目注册/管理', icon: Settings },
  { path: '/admin/members',       title: '成员与责任',   icon: Users },
  { path: '/admin/wbs',           title: 'WBS 导入',     icon: Table },
  { path: '/admin/risk-sources',  title: '风险源管理',   icon: ShieldCheck },
  { path: '/admin/wbs-risk-link', title: 'WBS-风险关联', icon: Link },
  { path: '/admin/daily-dir',     title: '日报目录配置', icon: Folder },
  { path: '/admin/rules',         title: '提醒规则配置', icon: Bell },
  { path: '/admin/templates',     title: '上报模板配置', icon: FileText },
  { path: '/admin/field-mapping', title: '平台字段映射', icon: CloudUpload },
  { path: '/admin/logs',          title: '系统操作日志', icon: Notes },
]

const handleLogout = () => {
  sessionStorage.removeItem('logged_in')
  sessionStorage.removeItem('user_role')
  router.push('/login')
}
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-default);
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
  padding: 16px 16px 14px;
  border-bottom: 1px solid var(--border-default);
}
.logo-mark {
  width: 32px;
  height: 32px;
  background: var(--color-primary);
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
.logo-name { font-size: 14px; font-weight: 700; color: var(--text-primary); letter-spacing: 0.01em; line-height: 1.2; }
.logo-tag { font-size: 10px; color: var(--text-muted); margin-top: 2px; font-weight: 500; }

/* Section Tabs */
.section-tabs {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 10px 8px;
  border-bottom: 1px solid var(--border-default);
}
.tab-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: var(--transition);
  text-align: left;
}
.tab-btn:hover { background: var(--bg-hover); color: var(--text-secondary); }
.tab-btn.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}


/* Nav List */
.nav-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 450;
  transition: var(--transition);
  margin-bottom: 2px;
  position: relative;
}
.nav-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.nav-item.router-link-active {
  background: var(--bg-inverse);
  color: #fff;
  font-weight: 500;
}
.nav-item.router-link-active .nav-icon { color: var(--color-primary-light); }
.nav-icon { font-size: 15px; flex-shrink: 0; color: inherit; }
.nav-label { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nav-badge {
  margin-left: auto;
  background: var(--color-danger);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  min-width: 18px;
  height: 18px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 5px;
  flex-shrink: 0;
}

/* Footer */
.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 14px;
  border-top: 1px solid var(--border-default);
}
.user-ava {
  width: 30px;
  height: 30px;
  background: var(--bg-inverse);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.user-name  { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.user-role  { font-size: 11px; color: var(--text-muted); margin-top: 1px; }
.logout-btn {
  margin-left: auto;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  transition: var(--transition);
}
.logout-btn:hover { background: var(--bg-hover); color: var(--color-danger); }
</style>

