<template>
  <div class="admin-view">
    <AdminPageHeader
      title="平台字段映射"
      subtitle="配置内部草稿字段与外部平台表单字段的对应关系，并维护附件类型映射。"
    >
      <template #actions>
        <button class="tbtn" @click="runCheck">校验映射</button>
        <button class="tbtn tbtn--primary" @click="saveMapping">保存映射</button>
      </template>
    </AdminPageHeader>

    <div class="mapping-summary">
      <div v-for="item in summary" :key="item.label" class="summary-card">
        <span class="summary-label">{{ item.label }}</span>
        <strong class="summary-value">{{ item.value }}</strong>
        <span class="summary-desc">{{ item.desc }}</span>
      </div>
    </div>

    <div class="mapping-layout">
      <section class="admin-panel mapping-panel">
        <div class="panel-headline">
          <div>
            <div class="panel-title">字段映射表</div>
            <div class="panel-subtitle">演示目标平台：股份安全管理平台 · 业务流程：重大风险动态管控月报</div>
          </div>
          <span :class="['check-chip', checkPassed ? 'check-ok' : 'check-idle']">
            {{ checkPassed ? '校验通过' : '待校验' }}
          </span>
        </div>

        <table class="mapping-table">
          <thead>
            <tr>
              <th>内部字段</th>
              <th>平台字段</th>
              <th>来源模块</th>
              <th>状态</th>
              <th>失败兜底</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in fieldMappings" :key="row.internalKey">
              <td>
                <div class="field-name">{{ row.internalLabel }}</div>
                <div class="field-key font-mono">{{ row.internalKey }}</div>
              </td>
              <td>
                <input v-model="row.platformLabel" class="table-input" />
              </td>
              <td><span class="source-pill">{{ row.source }}</span></td>
              <td>
                <span :class="['state-badge', row.status === 'mapped' ? 'state-ok' : row.status === 'warning' ? 'state-warn' : 'state-empty']">
                  {{ statusLabel(row.status) }}
                </span>
              </td>
              <td>
                <span class="fallback-text">{{ row.fallback }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <aside class="mapping-side">
        <section class="admin-panel side-card">
          <div class="side-title">附件类型映射</div>
          <div class="attach-map-list">
            <div v-for="item in attachmentMappings" :key="item.type" class="attach-map-row">
              <div>
                <div class="attach-type">{{ item.type }}</div>
                <div class="attach-rule">{{ item.rule }}</div>
              </div>
              <span :class="['attach-state', item.required ? 'attach-required' : 'attach-optional']">
                {{ item.required ? '必传' : '选传' }}
              </span>
            </div>
          </div>
        </section>

        <section class="admin-panel side-card">
          <div class="side-title">填报助手执行边界</div>
          <div class="boundary-list">
            <div v-for="item in boundaries" :key="item" class="boundary-item">
              <span class="boundary-icon">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="20 6 9 17 4 12" /></svg>
              </span>
              <span>{{ item }}</span>
            </div>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'

type MappingStatus = 'mapped' | 'warning' | 'empty'

const message = useMessage()
const checkPassed = ref(false)

const fieldMappings = reactive<Array<{ internalKey: string; internalLabel: string; platformLabel: string; source: string; status: MappingStatus; fallback: string }>>([
  { internalKey: 'project.name', internalLabel: '项目名称', platformLabel: '工程项目名称', source: '项目配置', status: 'mapped', fallback: '人工复制' },
  { internalKey: 'risk.name', internalLabel: '风险源名称', platformLabel: '重大风险名称', source: '风险源清单', status: 'mapped', fallback: '人工复制' },
  { internalKey: 'risk.level', internalLabel: '风险等级', platformLabel: '风险等级', source: '风险源清单', status: 'mapped', fallback: '下拉手选' },
  { internalKey: 'wbs.name', internalLabel: '关联工序', platformLabel: '当前施工部位', source: 'WBS-风险关联', status: 'mapped', fallback: '人工复制' },
  { internalKey: 'draft.progress', internalLabel: '当前进展描述', platformLabel: '风险动态情况', source: '草稿审核', status: 'mapped', fallback: '人工复制' },
  { internalKey: 'draft.monitor', internalLabel: '监测数据摘要', platformLabel: '监测情况说明', source: '日报/附件', status: 'mapped', fallback: '人工复制' },
  { internalKey: 'draft.measure', internalLabel: '管控措施', platformLabel: '已采取措施', source: '上报模板', status: 'mapped', fallback: '人工复制' },
  { internalKey: 'reporter.name', internalLabel: '上报人', platformLabel: '填报人', source: '成员配置', status: 'warning', fallback: '用户手填' },
])

const attachmentMappings = reactive([
  { type: '现场照片', rule: '映射到平台附件分类：图片佐证', required: true },
  { type: '监测日报', rule: '映射到平台附件分类：监测资料', required: true },
  { type: '审批资料', rule: '映射到平台附件分类：审批文件', required: false },
  { type: '施工记录', rule: '映射到平台附件分类：过程记录', required: false },
])

const boundaries = [
  '账号、密码和验证码只在目标平台页面输入。',
  '系统只辅助录入字段和上传附件，不自动最终提交。',
  '字段定位失败时暂停并显示失败原因。',
  '保存平台草稿后由用户人工确认提交。',
]

const summary = computed(() => {
  const total = fieldMappings.length
  const mapped = fieldMappings.filter(item => item.status === 'mapped').length
  const warning = fieldMappings.filter(item => item.status === 'warning').length
  return [
    { label: '字段总数', value: total, desc: '覆盖填报包预览字段' },
    { label: '已映射', value: mapped, desc: '可由助手自动填入' },
    { label: '需人工确认', value: warning, desc: '登录后手动核对' },
    { label: '附件分类', value: attachmentMappings.length, desc: '用于上传归类' },
  ]
})

const statusLabel = (status: MappingStatus) => ({ mapped: '已映射', warning: '需确认', empty: '未配置' }[status])

const runCheck = () => {
  checkPassed.value = true
  message.success('字段映射校验通过，1 个字段需用户登录后手动确认')
}

const saveMapping = () => {
  message.success('平台字段映射已保存到原型状态')
}
</script>

<style scoped>
.mapping-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-card { display: flex; flex-direction: column; gap: 4px; padding: 14px 16px; border-radius: var(--radius-md); background: var(--bg-card); border: 1px solid var(--border-default); }
.summary-label { font-size: 12px; color: var(--text-muted); }
.summary-value { font-size: 24px; line-height: 1; color: var(--text-primary); font-family: 'JetBrains Mono', monospace; }
.summary-desc { font-size: 12px; color: var(--text-secondary); }
.mapping-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
.mapping-panel { padding: 18px 20px; overflow: hidden; }
.panel-headline { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 14px; }
.panel-title { font-size: 15px; font-weight: 750; color: var(--text-primary); }
.panel-subtitle { margin-top: 3px; font-size: 12px; color: var(--text-muted); }
.check-chip { flex-shrink: 0; padding: 3px 9px; border-radius: 12px; font-size: 12px; font-weight: 700; }
.check-idle { background: var(--bg-elevated); color: var(--text-secondary); }
.check-ok { background: var(--color-success-soft); color: var(--color-success); }
.mapping-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.mapping-table th { text-align: left; padding: 9px 10px; font-size: 11px; color: var(--text-muted); background: var(--bg-hover); border-bottom: 1px solid var(--border-default); }
.mapping-table td { padding: 10px; border-bottom: 1px solid var(--border-subtle); vertical-align: middle; }
.mapping-table tr:hover td { background: var(--bg-elevated); }
.field-name { font-weight: 700; color: var(--text-primary); }
.field-key { margin-top: 2px; font-size: 11px; color: var(--text-muted); }
.table-input { width: 100%; min-width: 150px; box-sizing: border-box; border: 1px solid var(--border-default); border-radius: var(--radius-xs); background: var(--bg-card); color: var(--text-primary); font: inherit; font-size: 13px; padding: 7px 9px; outline: none; }
.table-input:focus { border-color: var(--color-primary); box-shadow: 0 0 0 2px var(--color-primary-dim); }
.source-pill { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 4px; background: var(--color-primary-dim); color: var(--color-primary); font-size: 11px; font-weight: 700; white-space: nowrap; }
.state-badge { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 700; white-space: nowrap; }
.state-ok { background: var(--color-success-soft); color: var(--color-success); }
.state-warn { background: var(--color-warning-soft); color: var(--color-warning); }
.state-empty { background: var(--color-danger-soft); color: var(--color-danger); }
.fallback-text { color: var(--text-secondary); font-size: 12px; }
.mapping-side { display: flex; flex-direction: column; gap: 14px; }
.side-card { padding: 16px 18px; }
.side-title { font-size: 13px; font-weight: 750; color: var(--text-primary); margin-bottom: 10px; }
.attach-map-list { display: flex; flex-direction: column; gap: 8px; }
.attach-map-row { display: flex; justify-content: space-between; gap: 10px; padding: 10px; border-radius: var(--radius-sm); background: var(--bg-elevated); }
.attach-type { font-size: 12px; font-weight: 750; color: var(--text-primary); }
.attach-rule { margin-top: 3px; font-size: 11px; color: var(--text-muted); line-height: 1.4; }
.attach-state { flex-shrink: 0; align-self: flex-start; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700; }
.attach-required { background: var(--color-danger-soft); color: var(--color-danger); }
.attach-optional { background: var(--bg-card); color: var(--text-secondary); border: 1px solid var(--border-default); }
.boundary-list { display: flex; flex-direction: column; gap: 8px; }
.boundary-item { display: flex; gap: 8px; font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.boundary-icon { width: 18px; height: 18px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; color: var(--color-success); background: var(--color-success-soft); flex-shrink: 0; }
@media (max-width: 1160px) { .mapping-layout { grid-template-columns: 1fr; } }
@media (max-width: 860px) { .mapping-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } .mapping-panel { overflow-x: auto; } .mapping-table { min-width: 760px; } }
@media (max-width: 520px) { .mapping-summary { grid-template-columns: 1fr; } }
</style>