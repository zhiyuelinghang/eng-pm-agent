<template>
  <div class="page-wrapper">
    <!-- Filter Bar -->
    <div class="filter-bar">
      <div class="filter-tabs">
        <button v-for="tab in tabs" :key="tab.key" :class="['filter-tab', { active: activeTab === tab.key }]" @click="activeTab = tab.key">
          {{ tab.label }}
          <span v-if="tab.count > 0" :class="['tab-badge', activeTab === tab.key ? 'tab-badge--active' : '']">{{ tab.count }}</span>
        </button>
      </div>
      <div class="filter-right">
        <n-select v-model:value="filterType" :options="typeOptions" placeholder="任务类型" clearable size="small" style="width:130px" />
        <n-select v-model:value="filterLevel" :options="levelOptions" placeholder="风险等级" clearable size="small" style="width:120px" />
      </div>
    </div>

    <!-- Task List (Card layout replacing NDataTable) -->
    <div class="task-grid">
      <div v-for="row in filteredTasks" :key="row.id" class="task-card" @click="openDetail(row.id)">
        <div class="tc-header">
          <div class="tc-title">
            <span :class="`rdot rdot--${row.riskLevel}`"></span>
            <span class="tc-title-text">{{ row.title }}</span>
          </div>
          <span :class="`badge ${statusClass(row.status)}`">{{ statusLabel(row.status) }}</span>
        </div>
        
        <div class="tc-body">
          <div class="tc-meta">
            <span class="tc-label">类型：</span><span class="badge badge-info">{{ typeLabel(row.type) }}</span>
          </div>
          <div class="tc-meta">
            <span class="tc-label">风险：</span><span :class="`badge ${levelClass(row.riskLevel)}`">{{ levelLabel(row.riskLevel) }}</span>
          </div>
          <div class="tc-meta">
            <span class="tc-label">负责人：</span><span class="tc-value">{{ store.getMemberName(row.responsibleId) }}</span>
          </div>
          <div class="tc-meta">
            <span class="tc-label">截止：</span>
            <span :class="isOverdue(row.deadline) ? 'overdue-date' : 'normal-date'">{{ row.deadline }}</span>
          </div>
          <div class="tc-meta" v-if="row.missingCount > 0">
            <span class="tc-label">缺项：</span><span class="badge badge-danger">{{ row.missingCount }}项</span>
          </div>
        </div>

        <div class="tc-footer">
          <button class="action-btn-primary" @click.stop="handleAction(row)">{{ actionLabel(row) }}</button>
        </div>
      </div>
      <div v-if="filteredTasks.length === 0" class="empty-state">
        暂无任务
      </div>
    </div>

    <!-- 任务详情抽屉 -->
    <TaskDetailDrawer v-model:show="drawerShow" :task-id="activeTaskId" />
  </div>
</template>
<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { NSelect } from 'naive-ui'
import TaskDetailDrawer from '@/components/business/TaskDetailDrawer.vue'
import type { Task } from '@/types'
const router = useRouter()
const route = useRoute()
const store = useAppStore()
const activeTab = ref('all')
const filterType = ref<string | null>(null)
const filterLevel = ref<string | null>(null)
const drawerShow = ref(false)
const activeTaskId = ref<string | null>(null)

const openDetail = (id: string) => {
  activeTaskId.value = id
  drawerShow.value = true
}

onMounted(() => {
  const id = route.query.id
  if (typeof id === 'string' && store.tasks.some(t => t.id === id)) openDetail(id)
})

const typeOptions = [
  { label: '风险预警', value: 'risk_alert' }, { label: '材料缺项', value: 'material_missing' },
  { label: '日报确认', value: 'daily_confirm' }, { label: '草稿审核', value: 'draft_review' },
  { label: '平台填报', value: 'fill_platform' },
]
const levelOptions = [
  { label: '重大', value: 'critical' }, { label: '较大', value: 'high' },
  { label: '一般', value: 'medium' }, { label: '较小', value: 'low' },
]
const tabs = computed(() => [
  { key: 'all', label: '全部', count: store.tasks.length },
  { key: 'today', label: '今日任务', count: store.tasks.filter(t => ['pending','processing','waiting_confirm'].includes(t.status)).length },
  { key: 'overdue', label: '逾期任务', count: store.overdueTasks.length },
  { key: 'material_missing', label: '待补充材料', count: store.tasks.filter(t => t.type === 'material_missing' || t.missingCount > 0).length },
  { key: 'daily_confirm', label: '待确认日报', count: store.tasks.filter(t => t.type === 'daily_confirm').length },
  { key: 'draft_review', label: '待审核草稿', count: store.tasks.filter(t => t.type === 'draft_review').length },
  { key: 'fill_platform', label: '待填报事项', count: store.tasks.filter(t => t.type === 'fill_platform').length },
])
const filteredTasks = computed(() => {
  let list = store.tasks
  if (activeTab.value === 'today') list = list.filter(t => ['pending','processing','waiting_confirm'].includes(t.status))
  else if (activeTab.value === 'overdue') list = list.filter(t => t.status === 'overdue')
  else if (activeTab.value === 'material_missing') list = list.filter(t => t.type === 'material_missing' || t.missingCount > 0)
  else if (['daily_confirm','draft_review','fill_platform'].includes(activeTab.value)) list = list.filter(t => t.type === activeTab.value)
  if (filterType.value) list = list.filter(t => t.type === filterType.value)
  if (filterLevel.value) list = list.filter(t => t.riskLevel === filterLevel.value)
  return list
})
const typeLabel = (type: Task['type']) => ({ risk_alert: '风险预警', material_missing: '材料缺项', daily_confirm: '日报确认', draft_review: '草稿审核', fill_platform: '平台填报' }[type] ?? type)
const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const statusLabel = (s: Task['status']) => ({ pending: '待处理', processing: '处理中', waiting_confirm: '待确认', done: '已完成', overdue: '已逾期', cancelled: '已取消' }[s] ?? s)
const levelClass = (l: string) => ({ critical: 'badge-danger', high: 'badge-warning', medium: 'badge-primary', low: 'badge-success' }[l] ?? '')
const statusClass = (s: Task['status']) => ({ pending: 'badge-info', processing: 'badge-primary', waiting_confirm: 'badge-warning', done: 'badge-success', overdue: 'badge-danger', cancelled: '' }[s] ?? '')
const isOverdue = (date: string) => new Date(date) < new Date()
const actionLabel = (row: Task) => {
  if (row.type === 'daily_confirm') return '去确认'
  if (row.type === 'draft_review') return '去审核'
  if (row.type === 'fill_platform') return '去填报'
  return row.status === 'pending' ? '开始处理' : '查看详情'
}
const handleAction = (row: Task) => {
  if (row.type === 'daily_confirm') router.push('/daily-reports')
  else if (row.type === 'draft_review') router.push('/drafts')
  else if (row.type === 'fill_platform') router.push('/filling')
  else openDetail(row.id)
}
const rowProps = (row: Task) => ({ style: 'cursor:pointer', onClick: () => openDetail(row.id) })
const columns = [
  { title: '任务标题', key: 'title', minWidth: 260, render: (row: Task) =>
    h('div', { class: 'title-cell' }, [
      h('span', { class: `rdot rdot--${row.riskLevel}` }),
      h('span', { class: 'title-text' }, row.title),
    ])
  },
  { title: '类型', key: 'type', width: 100, render: (row: Task) =>
    h('span', { class: 'badge badge-info' }, typeLabel(row.type))
  },
  { title: '风险等级', key: 'riskLevel', width: 90, render: (row: Task) =>
    h('span', { class: `badge ${levelClass(row.riskLevel)}` }, levelLabel(row.riskLevel))
  },
  { title: '负责人', key: 'responsibleId', width: 90, render: (row: Task) =>
    h('span', { class: 'member-name' }, store.getMemberName(row.responsibleId))
  },
  { title: '截止日期', key: 'deadline', width: 110, render: (row: Task) =>
    h('span', { class: isOverdue(row.deadline) ? 'overdue-date' : 'normal-date' }, row.deadline)
  },
  { title: '缺项', key: 'missingCount', width: 70, align: 'center' as const, render: (row: Task) =>
    row.missingCount > 0 ? h('span', { class: 'badge badge-danger' }, String(row.missingCount)) : h('span', { class: 'dash' }, '—')
  },
  { title: '状态', key: 'status', width: 100, render: (row: Task) =>
    h('span', { class: `badge ${statusClass(row.status)}` }, statusLabel(row.status))
  },
  { title: '操作', key: 'action', width: 110, render: (row: Task) =>
    h('button', { class: 'action-btn', onClick: (e: Event) => { e.stopPropagation(); handleAction(row) } }, actionLabel(row))
  },
]
</script>
<style scoped>
.page-wrapper { padding: 20px 24px; }
.filter-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; gap: 12px; flex-wrap: wrap; }
.filter-tabs { display: flex; gap: 4px; }
.filter-tab {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: var(--transition);
  display: flex;
  align-items: center;
  gap: 6px;
}
.filter-tab:hover { background: var(--bg-hover); color: var(--text-primary); }
.filter-tab.active { background: var(--color-primary-soft); color: var(--color-primary); border-color: var(--border-primary); }
.tab-badge { background: var(--bg-elevated); color: var(--text-muted); font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 10px; min-width: 18px; text-align: center; border: 1px solid var(--border-default); }
.tab-badge--active { background: var(--color-primary); color: #fff; border-color: transparent; }
.filter-right { display: flex; gap: 8px; }

.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
  align-items: start;
}
.task-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.task-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.tc-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.tc-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tc-title-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}
.tc-body {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  font-size: 13px;
  background: var(--bg-elevated);
  padding: 12px;
  border-radius: var(--radius-sm);
}
.tc-meta {
  display: flex;
  align-items: center;
  gap: 4px;
}
.tc-label {
  color: var(--text-muted);
}
.tc-value {
  color: var(--text-secondary);
  font-weight: 500;
}
.tc-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}
.action-btn-primary {
  padding: 6px 16px;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  border: none;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition);
}
.action-btn-primary:hover {
  background: var(--color-primary-dark);
}
.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
  background: var(--bg-surface);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-md);
}

.table-wrap {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.title-cell { display: flex; align-items: center; gap: 8px; }
.rdot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.rdot--critical { background: var(--color-danger); }
.rdot--high     { background: var(--color-warning); }
.rdot--medium   { background: var(--color-info); }
.rdot--low      { background: var(--color-success); }
.title-text { font-size: 13px; color: var(--text-primary); }
.member-name { font-size: 12px; color: var(--text-secondary); }
.overdue-date { color: var(--color-danger); font-size: 12px; font-family: 'JetBrains Mono', monospace; }
.normal-date  { color: var(--text-secondary); font-size: 12px; font-family: 'JetBrains Mono', monospace; }
.dash { color: var(--text-disabled); }

@media (max-width: 768px) {
  .filter-bar { flex-direction: column; align-items: flex-start; gap: 10px; }
  .filter-tabs { width: 100%; overflow-x: auto; padding-bottom: 4px; display: flex; }
  .filter-tab { padding: 5px 10px; font-size: 11px; flex-shrink: 0; }
  .filter-right { width: 100%; justify-content: flex-start; }
  .task-grid { grid-template-columns: 1fr; gap: 12px; }
  .page-wrapper { padding: 12px 16px; }
}
</style>
