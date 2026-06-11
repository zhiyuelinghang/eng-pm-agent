<template>
  <n-drawer :show="show" :width="drawerWidth" placement="right" @update:show="emit('update:show', $event)">
    <n-drawer-content v-if="task" closable body-content-style="padding:0">
      <template #header>
        <div class="drawer-hd">
          <span :class="['badge', levelClass(task.riskLevel)]">{{ levelLabel(task.riskLevel) }}</span>
          <span class="drawer-title">{{ task.title }}</span>
        </div>
      </template>

      <template #footer>
        <div class="drawer-footer">
          <n-button v-if="task.status === 'pending'" type="primary" @click="store.updateTaskStatus(task.id, 'processing')">开始处理</n-button>
          <n-button v-if="task.status === 'processing'" type="warning" @click="store.updateTaskStatus(task.id, 'waiting_confirm')">提交确认</n-button>
          <n-button v-if="task.status === 'waiting_confirm'" type="success" @click="store.updateTaskStatus(task.id, 'done')">确认完成</n-button>
          <n-button v-if="task.status === 'waiting_confirm'" @click="store.updateTaskStatus(task.id, 'processing')">退回补充</n-button>
          <n-button v-if="['pending','processing'].includes(task.status)" quaternary @click="store.updateTaskStatus(task.id, 'cancelled')">取消任务</n-button>
        </div>
      </template>

      <div class="drawer-body">
        <!-- 状态 -->
        <div class="status-bar">
          <span :class="['badge', statusClass(task.status)]">{{ statusLabel(task.status) }}</span>
        </div>

        <!-- 基本信息 -->
        <div class="info-grid">
          <div class="info-item"><span class="info-label">任务类型</span><span class="info-value">{{ typeLabel(task.type) }}</span></div>
          <div class="info-item"><span class="info-label">负责人</span><span class="info-value">{{ store.getMemberName(task.responsibleId) }}</span></div>
          <div class="info-item"><span class="info-label">确认人</span><span class="info-value">{{ store.getMemberName(task.confirmatorId) }}</span></div>
          <div class="info-item"><span class="info-label">截止时间</span><span class="info-value" :class="isOverdue(task.deadline) ? 'overdue' : ''">{{ task.deadline }}</span></div>
          <div class="info-item"><span class="info-label">创建时间</span><span class="info-value">{{ task.createdAt }}</span></div>
          <div class="info-item"><span class="info-label">缺项数量</span><span class="info-value"><span v-if="task.missingCount" class="badge badge-danger">{{ task.missingCount }} 项</span><span v-else class="muted">无缺项</span></span></div>
        </div>

        <!-- 触发原因 -->
        <div class="section">
          <div class="section-title">触发原因</div>
          <div class="section-text">{{ task.triggerReason }}</div>
        </div>

        <!-- 关联 WBS -->
        <div class="section">
          <div class="section-title">关联 WBS 节点</div>
          <div class="tag-list">
            <span v-for="wid in task.linkedWbsIds" :key="wid" class="wbs-tag">{{ store.getWbsName(wid) }}</span>
            <span v-if="!task.linkedWbsIds?.length" class="muted">—</span>
          </div>
        </div>

        <!-- 关联风险源 -->
        <div class="section">
          <div class="section-title">关联风险源</div>
          <div v-if="linkedRisk" class="risk-inline">
            <div class="risk-inline-hd">
              <span :class="['badge', levelClass(linkedRisk.level)]">{{ levelLabel(linkedRisk.level) }}</span>
              <span class="risk-name">{{ linkedRisk.name }}</span>
              <span class="risk-type">{{ linkedRisk.type }}</span>
            </div>
            <div class="material-title">所需材料</div>
            <div class="tag-list">
              <span v-for="(m, i) in linkedRisk.materials" :key="i" class="material-chip">{{ m }}</span>
            </div>
          </div>
          <span v-else class="muted">—</span>
        </div>

        <div class="section">
          <div class="section-title">材料补充</div>
          <div class="material-submit-panel">
            <div class="submitted-list">
              <div v-for="item in submittedMaterials" :key="item.name" class="submitted-row">
                <span>{{ item.name }}</span>
                <em>{{ item.status }}</em>
              </div>
            </div>
            <button v-if="task.missingCount > 0" class="material-upload-btn" @click="message.info('原型演示：已打开材料补充面板')">
              补充缺失材料
            </button>
          </div>
        </div>

        <!-- 操作日志 -->
        <div class="section">
          <div class="section-title">操作日志</div>
          <div class="op-log">
            <div v-for="log in taskLogs" :key="log.id" class="op-log-item">
              <div class="op-log-dot"></div>
              <div class="op-log-body">
                <div class="op-log-action">{{ log.action }}</div>
                <div class="op-log-detail">{{ log.detail }}</div>
                <div class="op-log-time">{{ log.operator }} · {{ log.time }}</div>
              </div>
            </div>
            <div v-if="!taskLogs.length" class="muted" style="text-align:center;padding:12px 0">暂无操作记录</div>
          </div>
        </div>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'
import { useMessage, NDrawer, NDrawerContent, NButton } from 'naive-ui'
import type { Task } from '@/types'

const props = defineProps<{ show: boolean; taskId: string | null }>()
const emit = defineEmits<{ (e: 'update:show', v: boolean): void }>()

const store = useAppStore()
const message = useMessage()
const drawerWidth = computed(() => window.innerWidth < 640 ? "100%" : 560)
const task = computed(() => store.tasks.find(t => t.id === props.taskId))
const linkedRisk = computed(() => task.value?.linkedRiskId ? store.riskSources.find(r => r.id === task.value!.linkedRiskId) : null)
const taskLogs = computed(() => store.logs.filter(l => l.relatedId === task.value?.id))
const submittedMaterials = computed(() => {
  if (!linkedRisk.value) return [{ name: '日报解析结果', status: '已关联' }]
  return linkedRisk.value.materials.slice(0, 3).map((name, index) => ({ name, status: index < 1 ? '已提交' : '待补充' }))
})

const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const statusLabel = (s: Task['status']) => ({ pending: '待处理', processing: '处理中', waiting_confirm: '待确认', done: '已完成', overdue: '已逾期', cancelled: '已取消' }[s] ?? s)
const typeLabel = (type: Task['type']) => ({ risk_alert: '风险预警', material_missing: '材料缺项', daily_confirm: '日报确认', draft_review: '草稿审核', fill_platform: '平台填报' }[type] ?? type)
const levelClass = (l: string) => ({ critical: 'badge-danger', high: 'badge-warning', medium: 'badge-primary', low: 'badge-success' }[l] ?? '')
const statusClass = (s: Task['status']) => ({ pending: 'badge-info', processing: 'badge-primary', waiting_confirm: 'badge-warning', done: 'badge-success', overdue: 'badge-danger', cancelled: 'badge-muted' }[s] ?? '')
const isOverdue = (date: string) => new Date(date) < new Date()
</script>

<style scoped>
.drawer-hd { display: flex; align-items: center; gap: 10px; min-width: 0; }
.drawer-title { font-size: 15px; font-weight: 600; color: var(--text-primary); line-height: 1.4; }

.drawer-body { padding: 20px 24px 12px; }
.status-bar { margin-bottom: 20px; }
.drawer-footer { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; padding: 0; }
.footer-actions { display: flex; gap: 8px; flex-wrap: wrap; }

.info-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 16px;
  margin-bottom: 20px;
}
.info-item { display: flex; flex-direction: column; gap: 4px; }
.info-label { font-size: 11px; color: var(--text-muted); }
.info-value { font-size: 13px; color: var(--text-primary); font-weight: 500; }
.info-value.overdue { color: var(--color-danger); }

.section { margin-bottom: 20px; }
.section-title { font-size: 12px; font-weight: 600; color: var(--text-muted); letter-spacing: 0.03em; margin-bottom: 8px; }
.section-text { font-size: 13px; color: var(--text-primary); line-height: 1.7; }

.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.wbs-tag { padding: 3px 10px; background: var(--color-primary-soft); color: var(--color-primary-dark); border-radius: 4px; font-size: 12px; }
.material-chip { padding: 2px 8px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 4px; font-size: 11px; color: var(--text-secondary); }
.material-submit-panel { padding: 12px; border-radius: var(--radius-sm); background: var(--bg-elevated); border: 1px solid var(--border-subtle); }
.submitted-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
.submitted-row { display: flex; justify-content: space-between; gap: 10px; padding: 7px 8px; border-radius: var(--radius-xs); background: var(--bg-card); font-size: 12px; color: var(--text-primary); }
.submitted-row em { font-style: normal; color: var(--text-muted); white-space: nowrap; }
.material-upload-btn { width: 100%; padding: 8px 12px; border-radius: var(--radius-sm); border: 1px solid var(--border-primary); background: var(--color-primary-soft); color: var(--color-primary); font-size: 13px; font-weight: 700; cursor: pointer; }
.material-upload-btn:hover { background: var(--color-primary); color: #fff; }

.risk-inline { background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; }
.risk-inline-hd { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.risk-name { font-size: 13px; font-weight: 600; color: var(--text-primary); flex: 1; }
.risk-type { font-size: 12px; color: var(--text-muted); }
.material-title { font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }

.op-log { display: flex; flex-direction: column; gap: 12px; }
.op-log-item { display: flex; gap: 10px; }
.op-log-dot { width: 8px; height: 8px; background: var(--color-primary); border-radius: 50%; margin-top: 4px; flex-shrink: 0; }
.op-log-action { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.op-log-detail { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.op-log-time { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

.muted { color: var(--text-muted); font-size: 12px; }
</style>
