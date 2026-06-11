<template>
  <header class="app-header">
    <!-- Left: section badge + page title -->
    <div class="header-left">
      <span class="section-badge" :class="isAdmin ? 'badge-admin' : 'badge-site'">
        {{ isAdmin ? '后台配置' : '工地端' }}
      </span>
      <span class="page-title">{{ pageTitle }}</span>
    </div>

    <!-- Right: notifications + project context -->
    <div class="header-right">
      <button class="header-icon-btn" title="通知">
        <n-icon :size="16"><Bell /></n-icon>
      </button>
      <!-- 工地端：项目切换器 -->
      <n-dropdown
        v-if="!isAdmin"
        :options="projectOptions"
        :theme-overrides="dropdownTheme"
        @select="handleProjectChange"
        trigger="click"
      >
        <button class="project-switcher">
          <div class="proj-status-dot"></div>
          <div class="proj-info">
            <span class="proj-name">{{ currentProject?.name ?? '未选项目' }}</span>
            <span class="proj-meta">{{ currentProject?.ownerUnit ?? '—' }}</span>
          </div>
          <n-icon :size="13" style="color:var(--text-muted);flex-shrink:0"><ChevronDown /></n-icon>
        </button>
      </n-dropdown>

    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { NDropdown, NIcon } from 'naive-ui'
import { Bell, ChevronDown, Check } from '@vicons/tabler'

const route = useRoute()
const store = useAppStore()
const isAdmin = computed(() => route.path.startsWith('/admin'))
const currentProject = computed(() => store.projects.find((p: any) => p.id === store.currentProjectId))

const titleMap: Record<string, string> = {
  '/dashboard':           '工地首页',
  '/tasks':               '任务中心',
  '/risks':               '风险任务',
  '/daily-reports':       '日报解析',
  '/drafts':              '草稿审核',
  '/filling':             '填报助手',
  '/admin/project':       '项目注册/管理',
  '/admin/members':       '成员与责任',
  '/admin/wbs':           'WBS 导入',
  '/admin/risk-sources':  '风险源管理',
  '/admin/wbs-risk-link': 'WBS-风险关联',
  '/admin/daily-dir':     '日报目录',
  '/admin/rules':         '提醒规则',
  '/admin/templates':     '上报模板配置',
  '/admin/field-mapping': '平台字段映射',
  '/admin/logs':          '操作日志',
}
const pageTitle = computed(() => {
  for (const [prefix, title] of Object.entries(titleMap)) {
    if (route.path.startsWith(prefix)) return title
  }
  return ''
})

const projectOptions = computed(() =>
  store.projects.map((p: any) => ({
    label: () => h('div', { style: 'display:flex;align-items:center;gap:10px;min-width:190px;padding:3px 0' }, [
      h('div', { style: 'width:6px;height:6px;border-radius:50%;background:#047857;flex-shrink:0;margin-top:2px' }),
      h('div', { style: 'flex:1;min-width:0' }, [
        h('div', { style: 'font-size:13px;font-weight:500;color:#1B2430;line-height:1.4' }, p.name),
        h('div', { style: 'font-size:11px;color:#8792A2;line-height:1.4' }, p.ownerUnit),
      ]),
      p.id === store.currentProjectId
        ? h(NIcon, { size: 14, color: '#E8590C' }, { default: () => h(Check) })
        : h('div', { style: 'width:14px' }),
    ]),
    key: p.id,
  }))
)

const handleProjectChange = (id: string) => { store.currentProjectId = id }

const dropdownTheme = {
  borderRadius: '8px',
  boxShadow: '0 8px 24px rgba(23,32,46,0.14), 0 0 0 1px rgba(23,32,46,0.05)',
}
</script>

<style scoped>
.app-header {
  height: var(--header-height);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  flex-shrink: 0;
  gap: 12px;
}
.header-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.section-badge {
  flex-shrink: 0;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
}
.badge-site  { background: var(--color-primary-soft); color: var(--color-primary-dark); }
.badge-admin { background: var(--color-accent-soft);  color: var(--color-accent); }
.page-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }

.header-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.header-icon-btn {
  width: 34px;
  height: 34px;
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  transition: var(--transition);
}
.header-icon-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.project-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 6px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
  min-width: 160px;
  max-width: none;
}
.project-switcher:hover { border-color: var(--color-primary); background: var(--bg-elevated); }
.proj-status-dot {
  width: 7px; height: 7px;
  background: var(--color-success);
  border-radius: 50%;
  flex-shrink: 0;
}
.proj-info { display: flex; flex-direction: column; align-items: flex-start; flex: 1; min-width: 0; }
.proj-name { font-size: 12px; font-weight: 600; color: var(--text-primary); white-space: nowrap; }
.proj-meta { font-size: 11px; color: var(--text-muted); }
</style>

