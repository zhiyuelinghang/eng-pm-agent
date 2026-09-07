<template>
  <section v-if="preview" class="business-preview" aria-label="本次业务变更">
    <strong>{{ preview.operation_label }}：{{ preview.target_name }}<span v-if="preview.record_id != null">（记录 {{ preview.record_id }}）</span></strong>
    <p>{{ preview.project_name }} · {{ preview.scope }} · {{ preview.impact }}</p>
    <div class="preview-scroll">
      <table>
        <thead><tr><th>字段</th><th>修改前</th><th>修改后</th></tr></thead>
        <tbody><tr v-for="change in preview.changes" :key="change.field">
          <th>{{ fieldLabels[change.field] || change.field }}</th>
          <td>{{ formatValue(change.before) }}</td><td>{{ formatValue(change.after) }}</td>
        </tr></tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { BusinessConfirmationPreview } from '@/types/agentRuntime'
defineProps<{ preview?: BusinessConfirmationPreview | null }>()
const fieldLabels: Record<string, string> = {
  title: '标题', name: '名称', category: '分类', status: '状态', content: '内容',
  description: '说明', project_id: '项目编号', user_id: '用户编号',
  department_id: '部门编号', document_type: '资料类型', task_type: '任务类型',
}
function formatValue(value: unknown): string {
  if (value == null || value === '') return '—'
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
}
</script>

<style scoped>
.business-preview { padding: 12px; color: #334155; background: #f8fafc; font-size: 12px; }
.business-preview p { margin: 6px 0 10px; line-height: 1.6; }
.preview-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12px; }
th, td { border: 1px solid #cbd5e1; padding: 8px; text-align: left; vertical-align: top;
  white-space: pre-wrap; overflow-wrap: anywhere; }
thead { background: #eef2f6; }
</style>
