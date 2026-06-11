<template>
  <div class="page-wrapper">
    <div class="risk-grid">
      <div v-for="risk in store.riskSources" :key="risk.id" :class="['risk-card', `risk-card--${risk.level}`]">
        <div class="risk-card-hd">
          <div class="risk-card-hd-left">
            <span :class="['level-badge', `level-${risk.level}`]">{{ levelLabel(risk.level) }}</span>
            <span class="type-tag">{{ risk.type }}</span>
          </div>
          <span class="period-text">{{ risk.controlStart }} — {{ risk.controlEnd }}</span>
        </div>
        <div class="risk-name">{{ risk.name }}</div>
        <div class="risk-attrs">
          <div class="attr-item">
            <span class="attr-key">负责人</span>
            <span class="attr-val">{{ store.getMemberName(risk.responsibleId) }}</span>
          </div>
          <div class="attr-item">
            <span class="attr-key">确认人</span>
            <span class="attr-val">{{ store.getMemberName(risk.confirmatorId) }}</span>
          </div>
        </div>
        <div class="risk-section">
          <div class="section-label">所需材料</div>
          <div class="chips">
            <span v-for="(m, i) in risk.materials" :key="i" class="chip">{{ m }}</span>
          </div>
        </div>
        <div class="risk-section">
          <div class="section-label">关联 WBS</div>
          <div v-if="linkedWbs(risk.id).length" class="chips">
            <span v-for="wbs in linkedWbs(risk.id)" :key="wbs.id" class="chip chip--primary">{{ wbs.code }} {{ wbs.name }}</span>
          </div>
          <span v-else class="no-data">未关联</span>
        </div>
        <div class="risk-status-grid">
          <div class="risk-status-cell">
            <span>当前状态</span>
            <strong>{{ riskStatus(risk.id) }}</strong>
          </div>
          <div class="risk-status-cell">
            <span>触发规则</span>
            <strong>{{ triggerRule(risk.id) }}</strong>
          </div>
        </div>
        <div class="risk-section">
          <div class="section-label">相关日报与附件</div>
          <div class="chips">
            <span class="chip chip--success">2026-06-09 施工日报</span>
            <span class="chip">现场照片 2 张</span>
            <span class="chip chip--warning">缺项 {{ missingCount(risk.id) }} 项</span>
          </div>
        </div>
        <div class="risk-card-ft">
          <button class="btn-primary" @click="generateDraft(risk)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> 生成草稿
          </button>
          <button class="btn-ghost" @click="router.push('/drafts')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> 历史草稿
          </button>
          <button class="btn-ghost" @click="router.push('/filling')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg> 填报包
          </button>
        </div>
      </div>
    </div>

    <n-modal v-model:show="draftDialogVisible" preset="dialog" title="确认生成草稿" style="width:440px">
      <div v-if="selectedRisk" class="dialog-body">
        <div class="dialog-risk-name">{{ selectedRisk.name }}</div>
        <p class="dialog-desc">系统将根据风险等级和类型生成草稿，生成后可在草稿审核中编辑确认。</p>
      </div>
      <template #action>
        <n-button @click="draftDialogVisible = false">取消</n-button>
        <n-button type="primary" @click="confirmGenerateDraft">确认生成</n-button>
      </template>
    </n-modal>
  </div>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useMessage, NModal, NButton } from 'naive-ui'
import type { RiskSource } from '@/types'
const store = useAppStore()
const message = useMessage()
const router = useRouter()
const draftDialogVisible = ref(false)
const selectedRisk = ref<RiskSource | null>(null)
const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const linkedWbs = (riskId: string) => {
  const ids = store.wbsRiskLinks.filter(l => l.riskId === riskId).map(l => l.wbsId)
  return store.wbsItems.filter(w => ids.includes(w.id))
}
const linkedTask = (riskId: string) => store.tasks.find(task => task.linkedRiskId === riskId)
const riskStatus = (riskId: string) => {
  const task = linkedTask(riskId)
  if (!task) return '待生成任务'
  return task.status === 'overdue' ? '任务逾期' : task.status === 'processing' ? '处理中' : task.status === 'waiting_confirm' ? '待确认' : '待处理'
}
const triggerRule = (riskId: string) => {
  const link = store.wbsRiskLinks.find(item => item.riskId === riskId)
  return link ? `开工前 ${link.alertDays} 天` : '未配置'
}
const missingCount = (riskId: string) => linkedTask(riskId)?.missingCount ?? 0
const generateDraft = (risk: RiskSource) => { selectedRisk.value = risk; draftDialogVisible.value = true }
const confirmGenerateDraft = () => {
  store.addLog({ id: `log-${Date.now()}`, time: new Date().toISOString().slice(0,19).replace('T',' '), operator: '张伟', level: 'success', action: '生成草稿', detail: `为风险源"${selectedRisk.value?.name}"触发草稿生成`, relatedId: selectedRisk.value?.id })
  draftDialogVisible.value = false
  message.success('草稿已触发生成，请前往草稿审核查看')
}
</script>
<style scoped>
.page-wrapper { padding: 20px 24px; }
.risk-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }

.risk-card {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: 18px;
  border-left: 3px solid transparent;
  transition: var(--transition-slow);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.risk-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); border-color: var(--border-emphasis); }
.risk-card--critical { border-left-color: var(--color-danger); }
.risk-card--high     { border-left-color: var(--color-warning); }
.risk-card--medium   { border-left-color: var(--color-info); }
.risk-card--low      { border-left-color: var(--color-success); }

.risk-card-hd { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.risk-card-hd-left { display: flex; align-items: center; gap: 7px; }
.level-badge { padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; }
.level-critical { background: var(--color-danger-soft);  color: var(--color-danger); }
.level-high     { background: var(--color-warning-soft); color: var(--color-warning); }
.level-medium   { background: var(--color-info-soft);    color: var(--color-info); }
.level-low      { background: var(--color-success-soft); color: var(--color-success); }
.type-tag { font-size: 11px; color: var(--color-primary); background: var(--color-primary-dim); padding: 2px 8px; border-radius: 4px; }
.period-text { font-size: 11px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }

.risk-name { font-size: 14px; font-weight: 700; color: var(--text-primary); line-height: 1.5; }

.risk-attrs { display: flex; gap: 20px; }
.attr-item { display: flex; align-items: center; gap: 6px; }
.attr-key { font-size: 11px; color: var(--text-muted); }
.attr-val { font-size: 12px; color: var(--text-primary); font-weight: 500; }

.risk-section { }
.section-label { font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }
.chips { display: flex; flex-wrap: wrap; gap: 5px; }
.chip {
  padding: 2px 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 4px;
  font-size: 11px;
  color: var(--text-secondary);
}
.chip--primary { background: var(--color-primary-dim); color: var(--color-primary); border-color: var(--border-primary); }
.chip--success { background: var(--color-success-soft); color: var(--color-success); border-color: rgba(4,120,87,.15); }
.chip--warning { background: var(--color-warning-soft); color: var(--color-warning); border-color: rgba(180,83,9,.15); }
.no-data { font-size: 12px; color: var(--text-disabled); }

.risk-status-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.risk-status-cell { padding: 8px 10px; border-radius: var(--radius-sm); background: var(--bg-elevated); border: 1px solid var(--border-subtle); }
.risk-status-cell span { display: block; font-size: 11px; color: var(--text-muted); margin-bottom: 3px; }
.risk-status-cell strong { font-size: 12px; color: var(--text-primary); }

.risk-card-ft { display: flex; gap: 8px; padding-top: 10px; border-top: 1px solid var(--border-default); margin-top: auto; flex-wrap: wrap; }

.dialog-body { display: flex; flex-direction: column; gap: 10px; }
.dialog-risk-name { font-size: 15px; font-weight: 700; color: var(--text-primary); }
.dialog-desc { font-size: 13px; color: var(--text-secondary); line-height: 1.6; }
</style>
