<template>
  <div class="section-field" :class="{ 'is-changed': field.changed, 'is-inline': inline || label === 'short' }" :data-field="field.name">
    <span class="section-field-label" :class="{ 'visually-hidden': label === 'hidden' }">{{ labelText }}</span>
    <div v-if="showBefore" class="section-field-value is-before"><span>现有</span><del>{{ valueText(field.before) }}</del></div>
    <div class="section-field-value" :class="{ 'is-after': showBefore }"><span v-if="showBefore">本次</span><strong>{{ valueText(field.after) }}</strong></div>
    <InitializationFieldIssues :issues="issues" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { InitializationChangeIssue, InitializationOperation } from '@/types/initializationChanges'
import InitializationFieldIssues from './InitializationFieldIssues.vue'
import type { InitializationComparisonField } from '@/utils/initializationSectionTable'
import { formatInitializationChangeValue } from '@/utils/initializationChangePresentation'
const props = withDefaults(defineProps<{ field: InitializationComparisonField; operation: InitializationOperation; baseline: boolean; label?: 'full' | 'short' | 'hidden'; inline?: boolean; issues?: InitializationChangeIssue[] }>(), { label: 'full', inline: false, issues: () => [] })
const showBefore = computed(() => props.field.changed && !['add', 'unchanged'].includes(props.operation) && (props.baseline || props.operation === 'update'))
const labelText = computed(() => props.label === 'short' ? /start/.test(props.field.name) ? '开始' : '结束' : props.field.label)
function valueText(value: unknown) {
  const text = formatInitializationChangeValue(value, props.field.name)
  if (props.label !== 'hidden' || text === '未填写') return text
  return props.field.name === 'duration_hours' ? `${text} 小时` : props.field.name === 'progress_percent' ? `${text}%` : text
}
</script>

<style scoped>
.section-field { display: grid; min-width: 0; gap: 2px; font-size: 12px; line-height: 1.6; }
.section-field.is-inline { display: flex; flex-wrap: wrap; align-items: baseline; gap: 3px 8px; }
.section-field-label { color: var(--text-muted); font-size: 12px; }
.section-field.is-inline .section-field-label { flex: 0 0 auto; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.section-field-value { display: flex; align-items: baseline; gap: 6px; min-width: 0; }
.section-field-value > span { flex: 0 0 auto; color: var(--text-muted); font-size: 12px; }
.section-field-value strong, .section-field-value del { min-width: 0; font-size: 13px; font-weight: 400; overflow-wrap: anywhere; white-space: pre-wrap; }
.section-field-value.is-before { color: var(--text-muted); }
.section-field-value.is-before del { text-decoration-color: var(--border-emphasis); }
.section-field-value.is-after strong { color: var(--color-accent); font-weight: 600; }
</style>
