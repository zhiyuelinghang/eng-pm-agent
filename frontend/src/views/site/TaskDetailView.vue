<template>
  <div class="page-wrapper">
    <div class="detail-nav">
      <button class="back-btn" @click="router.back()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>返回任务列表</button>
    </div>
    <div v-if="task" class="detail-layout">
      <div class="detail-main">
        <div class="detail-header">
          <div class="detail-title-row">
            <span :class="['badge', levelClass(task.riskLevel)]">{{ levelLabel(task.riskLevel) }}</span>
            <h1 class="detail-title">{{ task.title }}</h1>
            <span :class="['badge', statusClass(task.status)]">{{ statusLabel(task.status) }}</span>
          </div>
          <div class="detail-actions">
            <button v-if="task.status === 'pending'" class="btn-primary" @click="store.updateTaskStatus(task.id, 'processing')">开始处理</button>
            <button v-if="task.status === 'processing'" class="btn-warning" @click="store.updateTaskStatus(task.id, 'waiting_confirm')">提交确认</button>
            <button v-if="task.status === 'waiting_confirm'" class="btn-success" @click="store.updateTaskStatus(task.id, 'done')">确认完成</button>
            <button v-if="['pending','processing'].includes(task.status)" class="btn-ghost" @click="store.updateTaskStatus(task.id, 'cancelled')">取消任务</button>
          </div>
        </div>

        <div class="info-grid">
          <div class="info-item"><span class="info-label">任务类型</span><span class="info-value">{{ typeLabel(task.type) }}</span></div>
          <div class="info-item"><span class="info-label">负责人</span><span class="info-value">{{ store.getMemberName(task.responsibleId) }}</span></div>
          <div class="info-item"><span class="info-label">确认人</span><span class="info-value">{{ store.getMemberName(task.confirmatorId) }}</span></div>
          <div class="info-item"><span class="info-label">截止时间</span><span class="info-value" :class="isOverdue(task.deadline) ? 'text-danger' : ''">{{ task.deadline }}</span></div>
          <div class="info-item"><span class="info-label">创建时间</span><span class="info-value">{{ task.createdAt }}</span></div>
          <div class="info-item"><span class="info-label">缺项数量</span><span class="info-value"><span v-if="task.missingCount" class="badge-danger">{{ task.missingCount }} 项</span><span v-else class="text-muted">无缺项</span></span></div>
        </div>

        <div class="detail-section">
          <div class="detail-section-title">触发原因</div>
          <div class="detail-text">{{ task.triggerReason }}</div>
        </div>

        <div class="detail-section">
          <div class="detail-section-title">关联 WBS 节点</div>
          <div class="wbs-tag-list">
            <span v-for="wid in task.linkedWbsIds" :key="wid" class="wbs-tag">{{ store.getWbsName(wid) }}</span>
            <span v-if="!task.linkedWbsIds?.length" class="text-muted">—</span>
          </div>
        </div>

        <div class="detail-section">
          <div class="detail-section-title">关联风险源</div>
          <div v-if="linkedRisk" class="risk-card-inline">
            <div class="risk-card-inline-header">
              <span :class="['badge', levelClass(linkedRisk.level)]">{{ levelLabel(linkedRisk.level) }}</span>
              <span class="risk-card-name">{{ linkedRisk.name }}</span>
              <span class="risk-card-type">{{ linkedRisk.type }}</span>
            </div>
            <div class="material-list">
              <div class="material-list-title">所需材料</div>
              <div v-for="(m, i) in linkedRisk.materials" :key="i" class="material-chip">{{ m }}</div>
            </div>
          </div>
          <span v-else class="text-muted">—</span>
        </div>
      </div>

      <div class="detail-side">
        <div class="side-card">
          <div class="side-card-title">操作日志</div>
          <div class="op-log">
            <div v-for="log in taskLogs" :key="log.id" class="op-log-item">
              <div class="op-log-dot"></div>
              <div class="op-log-body">
                <div class="op-log-action">{{ log.action }}</div>
                <div class="op-log-detail">{{ log.detail }}</div>
                <div class="op-log-time">{{ log.operator }} · {{ log.time }}</div>
              </div>
            </div>
            <div v-if="!taskLogs.length" class="text-muted" style="text-align:center;padding:16px">暂无操作记录</div>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="empty-hint">任务不存在</div>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import type { Task } from '@/types'
const router = useRouter()
const route = useRoute()
const store = useAppStore()
const task = computed(() => store.tasks.find(t => t.id === route.params.id))
const linkedRisk = computed(() => task.value?.linkedRiskId ? store.riskSources.find(r => r.id === task.value!.linkedRiskId) : null)
const taskLogs = computed(() => store.logs.filter(l => l.relatedId === task.value?.id))
const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const statusLabel = (s: Task['status']) => ({ pending: '待处理', processing: '处理中', waiting_confirm: '待确认', done: '已完成', overdue: '已逾期', cancelled: '已取消' }[s] ?? s)
const typeLabel = (type: Task['type']) => ({ risk_alert: '风险预警', material_missing: '材料缺项', daily_confirm: '日报确认', draft_review: '草稿审核', fill_platform: '平台填报' }[type] ?? type)
const levelClass = (l: string) => ({ critical: 'badge-danger', high: 'badge-warning', medium: 'badge-primary', low: 'badge-success' }[l] ?? '')
const statusClass = (s: Task['status']) => ({ pending: 'badge-info', processing: 'badge-primary', waiting_confirm: 'badge-warning', done: 'badge-success', overdue: 'badge-danger', cancelled: '' }[s] ?? '')
const isOverdue = (date: string) => new Date(date) < new Date()
</script>
<style scoped>
.detail-nav { margin-bottom: 20px; }
.back-btn { display: flex; align-items: center; gap: 6px; background: transparent; border: 1px solid var(--border-default); color: var(--text-secondary); padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; transition: var(--transition); }
.back-btn:hover { color: var(--text-primary); border-color: var(--color-primary); }
.detail-layout { display: grid; grid-template-columns: 1fr 340px; gap: 20px; }
.detail-header { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 20px; margin-bottom: 16px; }
.detail-title-row { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
.detail-title { font-size: 18px; font-weight: 700; color: var(--text-primary); flex: 1; }
.detail-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.info-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 16px; margin-bottom: 16px; }
.info-item { display: flex; flex-direction: column; gap: 4px; }
.info-label { font-size: 11px; color: var(--text-muted); }
.info-value { font-size: 13px; color: var(--text-primary); font-weight: 500; }
.detail-section { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 16px; margin-bottom: 16px; }
.detail-section-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); margin-bottom: 10px; }
.detail-text { font-size: 13px; color: var(--text-primary); line-height: 1.7; }
.wbs-tag-list { display: flex; flex-wrap: wrap; gap: 8px; }
.wbs-tag { padding: 3px 10px; background: var(--color-primary-dim); color: var(--color-primary); border-radius: 4px; font-size: 12px; border: 1px solid rgba(0,212,255,.2); }
.risk-card-inline { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-sm); padding: 12px; }
.risk-card-inline-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.risk-card-name { font-size: 13px; font-weight: 600; color: var(--text-primary); flex: 1; }
.risk-card-type { font-size: 12px; color: var(--text-muted); }
.material-list-title { font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }
.material-list { display: flex; flex-wrap: wrap; gap: 6px; }
.material-chip { padding: 2px 8px; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: 4px; font-size: 11px; color: var(--text-secondary); }
.side-card { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 16px; }
.side-card-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); margin-bottom: 14px; }
.op-log { display: flex; flex-direction: column; gap: 12px; }
.op-log-item { display: flex; gap: 10px; }
.op-log-dot { width: 8px; height: 8px; background: var(--color-primary); border-radius: 50%; margin-top: 4px; flex-shrink: 0; box-shadow: 0 0 6px var(--color-primary); }
.op-log-action { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.op-log-detail { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.op-log-time { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

@media (max-width: 1024px) {
  .detail-layout { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .info-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 480px) {
  .info-grid { grid-template-columns: 1fr; }
}

</style>
