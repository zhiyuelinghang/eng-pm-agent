<template>
  <div class="admin-view">
    <AdminPageHeader
      title="风险源底座管理"
      subtitle="维护全项目风险源及其等级、管控周期、负责人与所需材料。"
    >
      <template #actions>
        <n-button type="primary" @click="openAdd">
          <template #icon>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </template>
          添加风险源
        </n-button>
      </template>
    </AdminPageHeader>
    <div class="risk-import-panel">
      <div class="risk-import-main">
        <div class="import-icon-box">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        </div>
        <div>
          <div class="import-title">导入风险源清单</div>
          <div class="import-subtitle">支持 Excel / CSV，解析后可补充控制要求、材料要求、责任人和确认人。</div>
        </div>
      </div>
      <div class="import-actions">
        <button class="tbtn" @click="showPreview">预览样例清单</button>
        <button class="tbtn tbtn--primary" @click="showPreview">选择文件导入</button>
      </div>
    </div>

    <div v-if="previewVisible" class="admin-panel risk-preview-panel">
      <div class="preview-head">
        <div>
          <div class="preview-title">风险源解析预览</div>
          <div class="preview-subtitle">系统已识别风险名称、等级、类型和管控周期，黄色项需要人工补齐材料要求。</div>
        </div>
        <div class="preview-actions">
          <button class="tbtn" @click="previewVisible = false">取消</button>
          <button class="tbtn tbtn--primary" @click="confirmPreview">确认导入</button>
        </div>
      </div>
      <div class="preview-grid">
        <div v-for="item in previewRisks" :key="item.name" class="preview-risk-card">
          <div class="preview-risk-head">
            <span :class="['level-badge', `level-${item.level}`]">{{ levelLabel(item.level) }}</span>
            <span class="preview-confidence">{{ item.confidence }}%</span>
          </div>
          <input v-model="item.name" class="preview-input risk-name-input" />
          <div class="preview-two-col">
            <label>类型<input v-model="item.type" class="preview-input" /></label>
            <label>管控期<input v-model="item.period" class="preview-input" /></label>
          </div>
          <label class="preview-field">材料要求<textarea v-model="item.materials" rows="2" class="preview-textarea" /></label>
          <label class="preview-field">控制要求<textarea v-model="item.measure" rows="2" class="preview-textarea" /></label>
        </div>
      </div>
    </div>

    <div class="risk-source-grid">
      <div v-for="risk in store.riskSources" :key="risk.id" :class="['rs-card', `rs-card--${risk.level}`]">
        <div class="rs-header">
          <span :class="['level-badge', `level-${risk.level}`]">{{ levelLabel(risk.level) }}</span>
          <span class="rs-type">{{ risk.type }}</span>
          <button class="tbtn" style="margin-left:auto" @click="editRisk(risk)">编辑</button>
        </div>
        <div class="rs-name">{{ risk.name }}</div>
        <div class="rs-period"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>{{ risk.controlStart }} — {{ risk.controlEnd }}</div>
        <div class="rs-members">
          <div class="rs-member"><span class="rs-member-label">负责人</span><span class="rs-member-name">{{ store.getMemberName(risk.responsibleId) }}</span></div>
          <div class="rs-member"><span class="rs-member-label">确认人</span><span class="rs-member-name">{{ store.getMemberName(risk.confirmatorId) }}</span></div>
        </div>
        <div class="rs-materials">
          <div class="rs-mat-label">所需材料（{{ risk.materials.length }}）</div>
          <div class="rs-mat-chips"><span v-for="(m, i) in risk.materials" :key="i" class="mat-chip">{{ m }}</span></div>
        </div>
      </div>
    </div>

    <n-modal v-model:show="dialogVisible" preset="dialog" :title="isEdit ? '编辑风险源' : '添加风险源'" style="width:560px">
      <n-form :model="form" label-width="100px" label-placement="left">
        <n-form-item label="风险名称"><n-input v-model:value="form.name" /></n-form-item>
        <n-form-item label="风险类型"><n-input v-model:value="form.type" /></n-form-item>
        <n-form-item label="风险等级">
          <n-select v-model:value="form.level" :options="levelOptions" />
        </n-form-item>
        <n-form-item label="管控开始"><n-date-picker v-model:formatted-value="form.controlStart" type="date" value-format="yyyy-MM-dd" style="width:100%" /></n-form-item>
        <n-form-item label="管控截止"><n-date-picker v-model:formatted-value="form.controlEnd" type="date" value-format="yyyy-MM-dd" style="width:100%" /></n-form-item>
        <n-form-item label="负责人">
          <n-select v-model:value="form.responsibleId" :options="memberOptions" style="width:100%" />
        </n-form-item>
        <n-form-item label="确认人">
          <n-select v-model:value="form.confirmatorId" :options="memberOptions" style="width:100%" />
        </n-form-item>
        <n-form-item label="控制要求">
          <n-input v-model:value="form.controlMeasures" type="textarea" :rows="3" placeholder="请输入风险控制要求，用于生成草稿和任务说明" />
        </n-form-item>
        <n-form-item label="材料要求">
          <n-input v-model:value="materialText" type="textarea" :rows="3" placeholder="例如：监测日报、现场照片、审批资料" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-button @click="dialogVisible = false">取消</n-button>
        <n-button type="primary" @click="saveRisk">保存</n-button>
      </template>
    </n-modal>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useAppStore } from '@/stores/app'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import { useMessage, NModal, NForm, NFormItem, NInput, NSelect, NDatePicker, NButton } from 'naive-ui'
import type { RiskSource } from '@/types'
const store = useAppStore()
const message = useMessage()
const levelOptions = [
  { label: '重大', value: 'critical' }, { label: '较大', value: 'high' },
  { label: '一般', value: 'medium' }, { label: '较小', value: 'low' },
]
const memberOptions = computed(() => store.members.map((m: any) => ({ label: m.name, value: m.id })))
const dialogVisible = ref(false)
const previewVisible = ref(false)
const isEdit = ref(false)
const materialText = ref('')
const form = reactive<Partial<RiskSource>>({ name: '', type: '', level: 'medium', controlStart: '', controlEnd: '', responsibleId: '', confirmatorId: '', controlMeasures: '' })
const previewRisks = reactive([
  { name: '深基坑坍塌风险', level: 'critical', type: '安全风险', period: '2026-05-31 至 2026-06-20', materials: '基坑监测日报、围护桩检测报告、应急预案审批件', measure: '每日监测围护桩位移，超警戒值立即暂停并上报。', confidence: 96 },
  { name: '顶管机掘进偏差风险', level: 'high', type: '质量风险', period: '2026-06-26 至 2026-08-15', materials: '顶管推进记录表、轴线测量报告、纠偏记录', measure: '每推进 5 环记录轴线偏差，超限立即纠偏。', confidence: 91 },
  { name: '施工降水导致地面沉降风险', level: 'high', type: '环境风险', period: '待确认', materials: '地表沉降监测报告、周边建筑物监测报告', measure: '结合降水井水位记录进行连续监测。', confidence: 78 },
])
const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const showPreview = () => { previewVisible.value = true; message.info('风险源清单已解析，请确认预览内容') }
const confirmPreview = () => { previewVisible.value = false; message.success('风险源预览已确认，原型中展示为已导入') }
const openAdd = () => { isEdit.value = false; materialText.value = ''; Object.assign(form, { id: undefined, name: '', type: '', level: 'medium', controlStart: '', controlEnd: '', responsibleId: '', confirmatorId: '', controlMeasures: '' }); dialogVisible.value = true }
const editRisk = (r: RiskSource) => { isEdit.value = true; materialText.value = r.materials.join('、'); Object.assign(form, { ...r }); dialogVisible.value = true }
const saveRisk = () => {
  const materials = materialText.value.split(/[、,，\n]/).map(item => item.trim()).filter(Boolean)
  store.saveRiskSource({ ...form, materials })
  message.success(isEdit.value ? '风险源、控制要求和材料要求已更新' : '风险源已添加')
  dialogVisible.value = false
}
</script>
<style scoped>
.risk-import-panel { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 16px 18px; margin-bottom: 16px; border: 1px dashed var(--border-emphasis); border-radius: var(--radius-md); background: var(--bg-card); }
.risk-import-main { display: flex; align-items: center; gap: 12px; }
.import-icon-box { width: 38px; height: 38px; border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center; background: var(--color-primary-soft); color: var(--color-primary); flex-shrink: 0; }
.import-title { font-size: 14px; font-weight: 750; color: var(--text-primary); }
.import-subtitle { margin-top: 3px; font-size: 12px; color: var(--text-muted); }
.import-actions { display: flex; gap: 8px; flex-shrink: 0; }
.risk-preview-panel { padding: 18px 20px; margin-bottom: 16px; }
.preview-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 14px; }
.preview-title { font-size: 15px; font-weight: 750; color: var(--text-primary); }
.preview-subtitle { margin-top: 3px; font-size: 12px; color: var(--text-muted); }
.preview-actions { display: flex; gap: 8px; }
.preview-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.preview-risk-card { padding: 12px; border-radius: var(--radius-sm); background: var(--bg-elevated); border: 1px solid var(--border-subtle); }
.preview-risk-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.preview-confidence { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; color: var(--color-success); }
.preview-two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
.preview-two-col label, .preview-field { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--text-muted); font-weight: 600; }
.preview-field { margin-top: 8px; }
.preview-input, .preview-textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--border-default); border-radius: var(--radius-xs); background: var(--bg-card); color: var(--text-primary); font: inherit; font-size: 12px; padding: 6px 8px; outline: none; }
.risk-name-input { font-size: 13px; font-weight: 700; }
.preview-input:focus, .preview-textarea:focus { border-color: var(--color-primary); box-shadow: 0 0 0 2px var(--color-primary-dim); }
.preview-textarea { resize: vertical; line-height: 1.5; }
.risk-source-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.rs-card { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 16px; border-left: 3px solid transparent; }
.rs-card--critical { border-left-color: var(--color-danger); }
.rs-card--high { border-left-color: var(--color-warning); }
.rs-card--medium { border-left-color: var(--color-warning); }
.rs-card--low { border-left-color: var(--color-success); }
.rs-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.level-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
.level-critical { background: var(--color-danger-soft); color: var(--color-danger); }
.level-high { background: var(--color-warning-soft); color: var(--color-warning); }
.level-medium { background: var(--color-warning-soft); color: var(--color-warning); }
.level-low { background: var(--color-success-soft); color: var(--color-success); }
.rs-type { font-size: 12px; color: var(--color-primary); }
.rs-name { font-size: 14px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; line-height: 1.4; }
.rs-period { font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 4px; margin-bottom: 10px; }
.rs-members { display: flex; gap: 20px; margin-bottom: 10px; }
.rs-member-label { font-size: 11px; color: var(--text-muted); margin-right: 4px; }
.rs-member-name { font-size: 12px; color: var(--text-primary); font-weight: 500; }
.rs-mat-label { font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }
.rs-mat-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.mat-chip { padding: 2px 8px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 4px; font-size: 11px; color: var(--text-secondary); }
@media (max-width: 1180px) { .preview-grid { grid-template-columns: 1fr; } }
@media (max-width: 780px) { .risk-import-panel, .preview-head { flex-direction: column; align-items: stretch; } .import-actions, .preview-actions { width: 100%; } .import-actions .tbtn, .preview-actions .tbtn { flex: 1; } .risk-source-grid { grid-template-columns: 1fr; } }
</style>
