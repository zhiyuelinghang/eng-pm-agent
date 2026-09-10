<template>
  <header class="app-header">
    <div class="header-left">
      <span class="section-badge">工程管理平台</span>
      <span class="page-title">{{ pageTitle }}</span>
    </div>

    <div class="header-right">
      <div class="header-popover">
        <button class="header-icon-btn" type="button" title="通知中心" aria-label="通知中心" :aria-expanded="noticeOpen" @click="toggleNotices">
          <n-icon :size="16"><Bell /></n-icon>
          <span v-if="noticeCount > 0">{{ noticeCount }}</span>
        </button>
        <div v-if="noticeOpen" class="header-dropdown notice-list" aria-label="通知中心">
          <header><strong>待关注事项</strong><span>{{ noticeCount }} 项</span></header>
          <button v-for="item in noticeItems" :key="item.key" type="button" @click="openNotice(item)"><span :class="item.tone"></span><div><strong>{{ item.title }}</strong><small>{{ item.meta }}</small></div></button>
          <p v-if="!noticeItems.length">当前项目没有待关注事项。</p>
          <router-link :to="{ path: '/tasks', query: { tab: 'history' } }" @click="noticeOpen = false">查看全部任务</router-link>
        </div>
      </div>
      <div class="project-switcher-group">
        <n-dropdown
          :options="projectOptions"
          :theme-overrides="dropdownTheme"
          :menu-props="projectMenuProps"
          :disabled="projectSwitching"
          @select="handleProjectChange"
          trigger="click"
        >
          <button class="project-switcher" type="button" :disabled="projectSwitching" :aria-busy="projectSwitching">
            <span class="proj-name">{{ currentProject?.name ?? '未选项目' }}</span>
            <n-icon v-if="projectSwitching" :size="14" class="project-switcher-spinner"><Loader /></n-icon>
            <n-icon v-else :size="13" style="color:var(--text-muted);flex-shrink:0"><ChevronDown /></n-icon>
          </button>
        </n-dropdown>
        <button v-if="isManagementUser" class="project-create-shortcut" type="button" title="新建项目" aria-label="新建项目" @click="openProjectCreate">
          <n-icon :size="18"><Plus /></n-icon>
          <span>新建项目</span>
        </button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { NDropdown, NIcon, useMessage } from 'naive-ui'
import { Bell, ChevronDown, Check, Loader, Plus } from '@vicons/tabler'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const message = useMessage()
const currentProject = computed(() => store.projects.find((p: any) => p.id === store.currentProjectId))
const isManagementUser = computed(() => sessionStorage.getItem('user_role') === 'admin')
const noticeCount = computed(() => store.overdueTasks.length + store.waitingConfirmTasks.length + store.pendingDrafts.length)
const noticeOpen = ref(false)
const projectSwitching = ref(false)

type HeaderLinkItem = {
  key: string
  kind: string
  title: string
  meta: string
  to: RouteLocationRaw
}

type HeaderNoticeItem = HeaderLinkItem & { tone: 'danger' | 'warning' | 'info' }

const noticeItems = computed<HeaderNoticeItem[]>(() => [
  ...store.overdueTasks.map(task => ({
    key: `overdue-${task.id}`,
    kind: '逾期',
    title: task.title,
    meta: `责任人：${store.getMemberName(task.responsibleId) || '未指定'}`,
    tone: 'danger' as const,
    to: { path: '/tasks', query: { tab: 'mine', taskId: task.id, view: 'disposition' } },
  })),
  ...store.waitingConfirmTasks.map(task => ({
    key: `review-${task.id}`,
    kind: '待确认',
    title: task.title,
    meta: '执行结果等待确认',
    tone: 'warning' as const,
    to: { path: '/tasks', query: { tab: 'mine', taskId: task.id, view: 'disposition' } },
  })),
  ...store.pendingDrafts.map(draft => ({
    key: `draft-${draft.id}`,
    kind: '草稿',
    title: draft.title,
    meta: '风险草稿等待审核',
    tone: 'info' as const,
    to: { path: '/project', query: { tab: 'riskQuality' } },
  })),
].slice(0, 12))

function toggleNotices() {
  noticeOpen.value = !noticeOpen.value
}

async function openNotice(item: HeaderNoticeItem) {
  noticeOpen.value = false
  await router.push(item.to)
}

const titleMap: Record<string, string> = {
  '/workbench': '工作首页',
  '/ai':        '智能协同',
  '/tasks':     '任务管理',
  '/project':   '项目状态',
  '/docs':      '工程资料',
  '/tools':     '业务智能体',
  '/profile':   '个人设置',
  '/settings':  '工程配置',
}
const pageTitle = computed(() => {
  for (const [prefix, title] of Object.entries(titleMap)) {
    if (route.path.startsWith(prefix)) return title
  }
  return ''
})

const projectOptions = computed(() =>
  store.projects.flatMap((p: any, index: number) => [
    ...(index > 0 ? [{ type: 'divider' as const, key: `project-divider-${p.id}` }] : []),
    {
      label: () => h('div', { style: 'display:flex;align-items:center;gap:12px;min-width:190px;padding:5px 0' }, [
        h('div', { style: 'flex:1;min-width:0;overflow:hidden;font-size:14px;font-weight:600;color:#1B2430;line-height:1.45;text-overflow:ellipsis;white-space:nowrap' }, p.name),
        p.id === store.currentProjectId
          ? h(NIcon, { size: 14, color: '#E8590C' }, { default: () => h(Check) })
          : h('div', { style: 'width:14px' }),
      ]),
      key: p.id,
    },
  ])
)

const handleProjectChange = async (id: string) => {
  if (projectSwitching.value || id === store.currentProjectId) return
  projectSwitching.value = true
  try {
    await store.selectProject(id)
    noticeOpen.value = false
    const query = { ...route.query }
    ;['taskId', 'messageId', 'channelId', 'documentId', 'recordId', 'folderId', 'search', 'conversationId'].forEach(key => delete query[key])
    await router.replace({ path: route.path, query })
  } catch (error: any) {
    message.error(error?.response?.data?.detail || error?.message || '项目切换失败，请稍后重试。')
  } finally {
    projectSwitching.value = false
  }
}
const projectMenuProps = () => ({
  class: 'project-switcher-dropdown',
  style: 'max-height:min(520px, calc(100vh - 88px));overflow-y:auto',
})

async function openProjectCreate() {
  await router.push({ path: '/settings', query: { createProject: '1' } })
}

watch(() => route.fullPath, () => {
  noticeOpen.value = false
})

const dropdownTheme = {
  borderRadius: '8px',
  boxShadow: '0 8px 24px rgba(23,32,46,0.14), 0 0 0 1px rgba(23,32,46,0.05)',
}
</script>

<style scoped>
.app-header {
  height: var(--header-height);
  background: rgba(255,255,255,0.92);
  border-bottom: 1px solid rgba(27,36,48,0.08);
  backdrop-filter: blur(18px);
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
  padding: 4px 8px;
  border-radius: 5px;
  font-size: 12px;
  line-height: 1.4;
  font-weight: 750;
  background: #edf5f1;
  color: #0f766e;
}
.page-title { font-size: 15px; font-weight: 750; color: var(--text-primary); }

.header-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.header-icon-btn {
  width: 38px;
  height: 38px;
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  transition: var(--transition);
  position: relative;
}
.header-icon-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.header-icon-btn span {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  padding: 0 4px;
  border-radius: 5px;
  background: var(--color-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 800;
}
.project-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
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
.project-switcher:disabled { opacity:.68; cursor:wait; }
.project-switcher-spinner { flex:0 0 auto; color:var(--color-primary); animation:project-switcher-spin .75s linear infinite; }
.project-switcher-group { display:flex; align-items:stretch; gap:6px; min-width:0; }
.project-create-shortcut {
  display:flex;
  flex:0 0 auto;
  min-height:38px;
  align-items:center;
  justify-content:center;
  gap:6px;
  border:1px solid var(--color-primary);
  border-radius:var(--radius-sm);
  padding:0 13px;
  color:#fff;
  background:var(--color-primary);
  font:inherit;
  font-size:13px;
  font-weight:750;
  white-space:nowrap;
  cursor:pointer;
  transition:var(--transition);
}
.project-create-shortcut:hover { background:#0b675f; border-color:#0b675f; }
.project-create-shortcut:focus-visible { outline:3px solid rgba(15,118,110,.22); outline-offset:2px; }
.proj-name { flex:1; overflow:hidden; max-width:100%; color:var(--text-primary); font-size:13px; font-weight:650; line-height:1.4; text-align:left; text-overflow:ellipsis; white-space:nowrap; }

:global(.project-switcher-dropdown .n-dropdown-divider) {
  margin: 9px 0;
}

@media (max-width: 1100px) { .project-switcher { max-width: 230px; } }
.header-popover { position: relative; }
.header-dropdown {
  position: absolute;
  top: calc(100% + 9px);
  right: 0;
  z-index: 80;
  width: min(420px, calc(100vw - 32px));
  overflow: hidden;
  border: 1px solid rgba(27,36,48,.12);
  border-radius: 9px;
  background: #fff;
  box-shadow: 0 18px 50px rgba(23,32,46,.18);
}
.header-dropdown > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 13px; border-bottom: 1px solid #e7ecea; background: #f7faf9; }
.header-dropdown > header strong { color: #243a3b; font-size: 13px; }
.header-dropdown > header span { color: #71817d; font-size: 12px; }
.header-dropdown > button { display: grid; width: 100%; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 10px; border: 0; border-bottom: 1px solid #edf1ef; padding: 10px 13px; color: #263c3d; background: #fff; text-align: left; cursor: pointer; }
.header-dropdown > button:hover,.header-dropdown > button:focus-visible { background: #f3f8f6; outline: 0; }
.header-dropdown > button > span { min-width: 48px; border-radius: 4px; padding: 3px 5px; color: #0f766e; background: #e8f3ef; font-size: 12px; font-weight: 750; text-align: center; }
.header-dropdown > button > span.danger { width: 8px; min-width: 8px; height: 8px; border-radius: 50%; padding: 0; background: #dc2626; }
.header-dropdown > button > span.warning { width: 8px; min-width: 8px; height: 8px; border-radius: 50%; padding: 0; background: #d97706; }
.header-dropdown > button > span.info { width: 8px; min-width: 8px; height: 8px; border-radius: 50%; padding: 0; background: #0f766e; }
.header-dropdown > button div { display: grid; min-width: 0; gap: 3px; }
.header-dropdown > button strong,.header-dropdown > button small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.header-dropdown > button strong { font-size: 13px; }
.header-dropdown > button small { color: #71817d; font-size: 12px; }
.header-dropdown > p { margin: 0; padding: 24px 14px; color: #71817d; font-size: 12px; text-align: center; }
.notice-list > a { display: block; padding: 10px 13px; color: #0f766e; background: #f7faf9; font-size: 12px; font-weight: 750; text-align: center; text-decoration: none; }

@media (max-width: 860px) {
  .project-switcher { min-width: 0; max-width: 180px; }
}
@keyframes project-switcher-spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .project-switcher-spinner { animation:none; } }
</style>

