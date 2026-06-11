<template>
  <div class="admin-view">
    <AdminPageHeader
      title="系统操作日志"
      subtitle="记录运维人员在系统底座的各项配置与管理操作，可按级别与关键词检索。"
    >
      <template #actions>
        <n-select v-model:value="filterLevel" :options="levelOptions" placeholder="日志级别" clearable size="small" style="width:120px" />
        <n-input v-model:value="keyword" placeholder="搜索关键词..." size="small" style="width:200px" clearable>
          <template #prefix><n-icon><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></n-icon></template>
        </n-input>
      </template>
    </AdminPageHeader>
    
    <div class="admin-panel admin-panel--pad">
      <n-data-table 
        :columns="columns" 
        :data="filteredLogs" 
        :bordered="true" 
        :striped="true" 
        size="small" 
        class="admin-table"
      />
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, h } from 'vue'
import { useAppStore } from '@/stores/app'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import { NSelect, NInput, NDataTable, NIcon } from 'naive-ui'
import type { OperationLog } from '@/types'
const store = useAppStore()
const filterLevel = ref<string | null>(null)
const keyword = ref('')
const levelOptions = [
  { label: '信息', value: 'info' }, { label: '成功', value: 'success' },
  { label: '警告', value: 'warning' }, { label: '错误', value: 'error' },
]
const filteredLogs = computed(() => {
  let list = [...store.logs].reverse()
  if (filterLevel.value) list = list.filter(l => l.level === filterLevel.value)
  if (keyword.value) list = list.filter(l => l.action.includes(keyword.value) || l.detail.includes(keyword.value))
  return list
})
const columns = [
  { title: '级别', key: 'level', width: 80, align: 'center' as const, render: (row: OperationLog) => h('span', { class: `log-level-dot dot-${row.level}` }) },
  { title: '时间', key: 'time', width: 160, render: (row: OperationLog) => h('span', { class: 'log-time-cell' }, row.time) },
  { title: '操作人', key: 'operator', width: 90 },
  { title: '操作', key: 'action', width: 140, render: (row: OperationLog) => h('span', { class: 'log-action-cell' }, row.action) },
  { title: '详情', key: 'detail', minWidth: 300, render: (row: OperationLog) => h('span', { class: 'log-detail-cell' }, row.detail) },
  { title: '关联 ID', key: 'relatedId', width: 140, render: (row: OperationLog) =>
    row.relatedId ? h('span', { class: 'related-id' }, row.relatedId) : h('span', { class: 'text-muted' }, '—')
  },
]
</script>
<style scoped>
@media (max-width: 768px) {
  .admin-panel--pad { padding: 0; border: none; box-shadow: none; background: transparent; }
}

/* Base styles for table elements */
.log-level-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.dot-info { background: var(--color-info); }
.dot-success { background: var(--color-success); }
.dot-warning { background: var(--color-warning); }
.dot-error { background: var(--color-danger); }
.log-time-cell { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-secondary); }
.log-action-cell { font-weight: 600; color: var(--text-primary); }
.log-detail-cell { color: var(--text-secondary); }
.related-id { font-family: 'JetBrains Mono', monospace; font-size: 11px; background: var(--bg-elevated); padding: 2px 6px; border-radius: 4px; color: var(--text-muted); }
.text-muted { color: var(--text-muted); }
</style>
