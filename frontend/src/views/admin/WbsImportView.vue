<template>
  <div class="admin-view">
    <AdminPageHeader
      title="WBS 导入中心"
      subtitle="导入工程分解结构（WBS）节点，系统据此建立进度与风险关联的底座数据。"
    />
    <div class="upload-zone" @dragover.prevent @drop.prevent="onDrop">
      <svg class="upload-icon" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
      <div class="upload-text">拖拽 Excel / CSV 文件至此处</div>
      <div class="upload-sub">或</div>
      <n-button type="primary" ghost @click="simulateImport">选择文件导入</n-button>
      <div class="upload-hint">支持 .xlsx .xls .csv，单次最大 10MB</div>
    </div>

    <div v-if="previewVisible" class="admin-panel preview-panel">
      <div class="preview-head">
        <div>
          <div class="preview-title">WBS 解析预览</div>
          <div class="preview-subtitle">已识别工序层级、计划时间和负责人，确认前可直接修改。</div>
        </div>
        <div class="preview-actions">
          <button class="tbtn" @click="previewVisible = false">取消导入</button>
          <button class="tbtn tbtn--primary" @click="confirmImport">确认导入</button>
        </div>
      </div>
      <div class="import-steps">
        <div class="import-step step-done"><span>1</span>文件接收</div>
        <div class="import-step step-done"><span>2</span>解析字段</div>
        <div class="import-step step-active"><span>3</span>人工确认</div>
        <div class="import-step"><span>4</span>写入底图</div>
      </div>
      <div class="preview-table-wrap">
        <table class="preview-table">
          <thead>
            <tr>
              <th>编码</th>
              <th>工序名称</th>
              <th>层级</th>
              <th>计划开始</th>
              <th>计划完成</th>
              <th>匹配状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in previewRows" :key="row.code">
              <td><input v-model="row.code" class="cell-input code-input" /></td>
              <td><input v-model="row.name" class="cell-input" /></td>
              <td><input v-model.number="row.level" type="number" min="1" max="6" class="cell-input level-input" /></td>
              <td><input v-model="row.planStart" class="cell-input date-input" /></td>
              <td><input v-model="row.planEnd" class="cell-input date-input" /></td>
              <td><span :class="['match-chip', row.confidence >= 0.85 ? 'match-ok' : 'match-warn']">{{ row.confidence >= 0.85 ? '高置信' : '需确认' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="admin-panel">
      <div class="admin-panel-head">
        <span class="admin-panel-title">WBS 节点列表（{{ store.wbsItems.length }} 个）</span>
        <div class="admin-panel-tools">
          <n-input v-model:value="search" placeholder="搜索节点" size="small" style="width:200px" clearable />
        </div>
      </div>
      <n-data-table :columns="columns" :data="filteredWbs" :bordered="false" size="small" class="admin-table" />
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, h, reactive } from 'vue'
import { useAppStore } from '@/stores/app'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import { useMessage, NInput, NButton, NDataTable } from 'naive-ui'
import type { WbsItem } from '@/types'
const store = useAppStore()
const message = useMessage()
const search = ref('')
const previewVisible = ref(false)
const previewRows = reactive([
  { code: '1.2.2', name: '基坑开挖', level: 3, planStart: '2026-05-31', planEnd: '2026-06-10', confidence: 0.94 },
  { code: '1.2.3', name: '底板及井壁施工', level: 3, planStart: '2026-06-11', planEnd: '2026-06-20', confidence: 0.9 },
  { code: '1.3.1', name: '顶管机下井调试', level: 3, planStart: '2026-06-21', planEnd: '2026-06-25', confidence: 0.82 },
])
const filteredWbs = computed(() => store.wbsItems.filter(w => !search.value || w.name.includes(search.value) || w.code.includes(search.value)))
const wbsStatusLabel = (s: string) => ({ not_started: '未开始', in_progress: '进行中', done: '已完成', delayed: '已延期' }[s] ?? s)
const simulateImport = () => { previewVisible.value = true; message.info('文件已解析，请确认预览结果') }
const onDrop = () => { previewVisible.value = true; message.info('文件已接收，正在展示解析预览') }
const confirmImport = () => { previewVisible.value = false; message.success('WBS 预览已确认，原型中展示为已导入') }
const columns = [
  { title: 'WBS 编码', key: 'code', width: 130 },
  { title: '节点名称', key: 'name', minWidth: 180 },
  { title: '层级', key: 'level', width: 70, align: 'center' as const, render: (row: WbsItem) => h('span', { class: 'level-chip' }, `L${row.level}`) },
  { title: '计划开始', key: 'planStart', width: 110 },
  { title: '计划完工', key: 'planEnd', width: 110 },
  { title: '进度', key: 'progress', width: 140, render: (row: WbsItem) =>
    h('div', { class: 'progress-cell' }, [
      h('div', { class: 'mini-bar' }, [h('div', { class: 'mini-fill', style: { width: row.progress + '%' } })]),
      h('span', { class: 'progress-pct' }, `${row.progress}%`),
    ])
  },
  { title: '状态', key: 'status', width: 100, render: (row: WbsItem) => h('span', { class: `wbs-status ws-${row.status}` }, wbsStatusLabel(row.status)) },
  { title: '负责人', key: 'responsibleId', width: 90, render: (row: WbsItem) => h('span', {}, store.getMemberName(row.responsibleId)) },
]
</script>
<style scoped>
.upload-zone { border: 2px dashed var(--border-default); border-radius: var(--radius-md); padding: 40px; text-align: center; background: var(--bg-card); transition: var(--transition); cursor: pointer; }
.upload-zone:hover { border-color: var(--color-primary); background: var(--bg-hover); }
.upload-icon { font-size: 40px; color: var(--color-primary); margin-bottom: 12px; }
.upload-text { font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.upload-sub { font-size: 12px; color: var(--text-muted); margin-bottom: 12px; }
.upload-hint { font-size: 11px; color: var(--text-muted); margin-top: 10px; }
.preview-panel { margin-top: 16px; padding: 18px 20px; }
.preview-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.preview-title { font-size: 15px; font-weight: 750; color: var(--text-primary); }
.preview-subtitle { margin-top: 3px; font-size: 12px; color: var(--text-muted); }
.preview-actions { display: flex; gap: 8px; flex-shrink: 0; }
.import-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 14px; }
.import-step { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: var(--radius-sm); background: var(--bg-elevated); color: var(--text-secondary); font-size: 12px; font-weight: 600; }
.import-step span { width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--bg-card); border: 1px solid var(--border-default); font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.step-done { color: var(--color-success); background: var(--color-success-soft); }
.step-done span { background: var(--color-success); color: #fff; border-color: transparent; }
.step-active { color: var(--color-primary); background: var(--color-primary-soft); }
.step-active span { background: var(--color-primary); color: #fff; border-color: transparent; }
.preview-table-wrap { overflow-x: auto; border: 1px solid var(--border-default); border-radius: var(--radius-sm); }
.preview-table { width: 100%; min-width: 760px; border-collapse: collapse; font-size: 13px; }
.preview-table th { text-align: left; padding: 9px 10px; font-size: 11px; color: var(--text-muted); background: var(--bg-hover); border-bottom: 1px solid var(--border-default); }
.preview-table td { padding: 8px 10px; border-bottom: 1px solid var(--border-subtle); }
.preview-table tr:last-child td { border-bottom: none; }
.cell-input { width: 100%; box-sizing: border-box; border: 1px solid var(--border-default); border-radius: var(--radius-xs); background: var(--bg-card); color: var(--text-primary); font: inherit; font-size: 13px; padding: 6px 8px; outline: none; }
.cell-input:focus { border-color: var(--color-primary); box-shadow: 0 0 0 2px var(--color-primary-dim); }
.code-input { font-family: 'JetBrains Mono', monospace; width: 86px; }
.level-input { width: 58px; }
.date-input { font-family: 'JetBrains Mono', monospace; width: 112px; }
.match-chip { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 700; white-space: nowrap; }
.match-ok { background: var(--color-success-soft); color: var(--color-success); }
.match-warn { background: var(--color-warning-soft); color: var(--color-warning); }
.level-chip { font-size: 10px; font-family: 'JetBrains Mono', monospace; padding: 1px 6px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 4px; color: var(--text-secondary); }
.progress-cell { display: flex; align-items: center; gap: 8px; }
.mini-bar { flex: 1; height: 4px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
.mini-fill { height: 100%; background: var(--color-primary); border-radius: 2px; }
.progress-pct { font-size: 11px; font-family: 'JetBrains Mono', monospace; color: var(--text-secondary); width: 32px; text-align: right; }
.wbs-status { font-size: 11px; padding: 2px 6px; border-radius: 4px; }
.ws-done { background: var(--color-success-soft); color: var(--color-success); }
.ws-in_progress { background: var(--color-primary-soft); color: var(--color-primary); }
.ws-not_started { background: var(--bg-hover); color: var(--text-muted); }
.ws-delayed { background: var(--color-danger-soft); color: var(--color-danger); }
@media (max-width: 768px) {
  .preview-head { flex-direction: column; }
  .preview-actions { width: 100%; }
  .preview-actions .tbtn { flex: 1; }
  .import-steps { grid-template-columns: 1fr 1fr; }
}
</style>
