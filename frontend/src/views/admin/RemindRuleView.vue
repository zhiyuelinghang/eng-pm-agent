<template>
  <div class="admin-view">
    <AdminPageHeader
      title="提醒预警规则"
      subtitle="按风险等级配置提前预警天数，系统在 WBS 节点计划开工前自动生成风险预警任务并分配给责任人。"
    />
    <div class="rules-grid">
      <div v-for="rule in store.remindRules" :key="rule.id" :class="['rule-card', `rule-card--${rule.level}`]">
        <div class="rule-level-badge" :class="`level-${rule.level}`">{{ levelLabel(rule.level) }}</div>
        <div class="rule-days-display">
          <span class="days-big">{{ rule.days }}</span>
          <span class="days-unit">天</span>
        </div>
        <div class="rule-desc">在 WBS 节点计划开工前 {{ rule.days }} 天，系统自动生成风险预警任务，分配给对应责任人</div>
        <div class="rule-actions">
          <button class="tbtn" @click="editRule(rule)">修改天数</button>
          <n-switch v-model:value="rule.enabled" />
        </div>
      </div>
    </div>

    <n-modal v-model:show="dialogVisible" preset="dialog" :title="`修改「${levelLabel(editingRule?.level ?? '')}」提醒天数`" style="width:360px">
      <div class="dialog-days-editor">
        <n-input-number v-model:value="editDays" :min="1" :max="180" size="large" style="width:100%" />
        <div class="days-hint">天前提醒（1-180 天）</div>
      </div>
      <template #action>
        <n-button @click="dialogVisible = false">取消</n-button>
        <n-button type="primary" @click="saveDays">保存</n-button>
      </template>
    </n-modal>
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '@/stores/app'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import { useMessage, NModal, NInputNumber, NSwitch, NButton } from 'naive-ui'
import type { RemindRule } from '@/types'
const store = useAppStore()
const message = useMessage()
const dialogVisible = ref(false)
const editingRule = ref<RemindRule | null>(null)
const editDays = ref(14)
const levelLabel = (l: string) => ({ critical: '重大', high: '较大', medium: '一般', low: '较小' }[l] ?? l)
const editRule = (rule: RemindRule) => { editingRule.value = rule; editDays.value = rule.days; dialogVisible.value = true }
const saveDays = () => { if (editingRule.value) editingRule.value.days = editDays.value; message.success('提醒天数已更新'); dialogVisible.value = false }
</script>
<style scoped>
.rules-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.rule-card { background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 24px; display: flex; flex-direction: column; align-items: center; gap: 12px; border-top: 3px solid transparent; transition: var(--transition); }
.rule-card--critical { border-top-color: var(--color-danger); }
.rule-card--high { border-top-color: var(--color-warning); }
.rule-card--medium { border-top-color: var(--color-warning); }
.rule-card--low { border-top-color: var(--color-success); }
.rule-level-badge { padding: 3px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; }
.level-critical { background: var(--color-danger-soft); color: var(--color-danger); }
.level-high { background: var(--color-warning-soft); color: var(--color-warning); }
.level-medium { background: var(--color-warning-soft); color: var(--color-warning); }
.level-low { background: var(--color-success-soft); color: var(--color-success); }
.rule-days-display { display: flex; align-items: baseline; gap: 4px; }
.days-big { font-size: 56px; font-weight: 900; color: var(--text-primary); line-height: 1; font-family: 'JetBrains Mono', monospace; }
.days-unit { font-size: 20px; color: var(--text-secondary); }
.rule-desc { font-size: 12px; color: var(--text-secondary); text-align: center; line-height: 1.6; }
.rule-actions { display: flex; align-items: center; gap: 12px; }
.dialog-days-editor { padding: 12px 0; text-align: center; }
.days-hint { font-size: 12px; color: var(--text-muted); margin-top: 8px; }
</style>
