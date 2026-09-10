<template>
  <div class="initialization-section-table" :class="`section-${section}`">
    <table v-if="tableRows.length" :aria-label="`${sectionLabel}变更比较`">
      <colgroup><col class="selection-col"><template v-if="section === 'project'"><col class="project-name-col"><col v-if="projectHasComparison"><col></template><col v-for="column in columns" v-else :key="column.key" :class="`column-${column.key}`"><col class="operation-col"></colgroup>
      <thead><tr><th scope="col" class="selection-cell">选择</th><template v-if="section === 'project'"><th scope="col">字段</th><th v-if="projectHasComparison" scope="col">现有数据</th><th scope="col">本次资料</th></template><th v-for="column in columns" v-else :key="column.key" scope="col">{{ column.label }}</th><th scope="col">状态</th></tr></thead>
      <tbody v-for="row in tableRows" :key="row.change.key" :class="{ 'is-selected': isSelected(row), 'is-context': row.contextOnly }">
        <tr class="record-row">
          <td class="selection-cell"><input type="checkbox" :aria-label="`选择${initializationChangeTitle(row.change)}`" :checked="isSelected(row)" :disabled="!canSelect(row)" @change="selectRow(row, $event)"></td>
          <template v-if="section === 'project'">
            <th scope="row" class="project-field-name">{{ initializationChangeTitle(row.change) }}</th>
            <td v-if="projectHasComparison" class="project-before"><div v-for="field in row.fields" :key="field.name" :data-field="field.name">{{ row.change.operation === 'add' && (field.before === null || field.before === undefined || field.before === '') ? '—' : formatInitializationChangeValue(field.before, field.name) }}</div></td>
            <td class="project-after"><div v-for="field in row.fields" :key="field.name" :data-field="field.name" :class="{ 'is-changed': field.changed }">{{ formatInitializationChangeValue(field.after, field.name) }}</div></td>
          </template>
          <td v-for="(cell, index) in row.cells" v-else :key="cell.key" :class="[`cell-${cell.key}`, { 'hierarchy-cell': section === 'wbs' && index === 0 }]">
            <div v-if="cell.account" class="existing-account"><strong>{{ row.account?.username || '暂无已有账号' }}</strong><span v-if="row.account">沿用此账号</span></div>
            <div v-else class="cell-layout" :style="section === 'wbs' && index === 0 ? { paddingLeft: `${row.depth * 18}px` } : undefined">
              <template v-if="section === 'wbs' && index === 0"><button v-if="row.hasChildren" type="button" class="node-toggle" :aria-expanded="!collapsedKeys.has(row.change.key)" :aria-label="`${collapsedKeys.has(row.change.key) ? '展开' : '收起'}${initializationChangeTitle(row.change)}的下级`" :disabled="applying" @click="emit('toggleNode', row.change.key)"><NIcon :size="15"><ChevronRight v-if="collapsedKeys.has(row.change.key)" /><ChevronDown v-else /></NIcon></button><span v-else class="node-leaf" aria-hidden="true"></span></template>
              <div class="cell-fields"><InitializationFieldDiff v-for="field in cell.values" :key="field.name" :field="field" :operation="row.change.operation" :baseline="row.change.before !== null" :label="cell.key === 'schedule' || cell.key === 'window' ? 'short' : 'hidden'" /><span v-if="!cell.values.length" class="empty-value">未填写</span><span v-if="section === 'wbs' && index === 0 && row.contextOnly" class="context-label">上级路径</span></div>
            </div>
          </td>
          <td class="operation-cell"><span class="operation-label" :class="`operation-${row.change.operation}`">{{ initializationOperationLabels[row.change.operation] }}</span><span v-if="row.change.operation === 'update' && row.change.fields.length" class="change-count">{{ row.change.fields.length }} 项变化</span></td>
        </tr>
        <tr v-if="row.supplementary.length || showMatching(row.change) || row.issues.length" class="record-supplementary"><td></td><td :colspan="columnCount - 1">
          <div v-if="row.supplementary.length" class="supplementary-fields" aria-label="补充信息"><InitializationFieldDiff v-for="field in row.supplementary" :key="field.name" :field="field" :operation="row.change.operation" :baseline="row.change.before !== null" inline /></div>
          <div v-if="showMatching(row.change)" class="record-matching"><label>匹配已有记录<select :aria-label="`匹配${initializationChangeTitle(row.change)}`" :value="initializationResolutionValue(row.change, resolutions)" :disabled="!canResolve(row)" @change="resolveRow(row, $event)"><option value="">{{ row.change.target_id ? '使用自动匹配结果' : '请选择对应记录' }}</option><option v-for="candidate in row.change.candidates" :key="candidate.id" :value="String(candidate.id)">{{ candidate.title }}</option><option v-if="missingCandidate(row.change)" :value="String(row.change.target_id)">当前匹配的原记录</option><option value="new">作为新增记录</option></select></label><p>选择对应的原记录进行更新，或明确作为新增记录。</p></div>
          <ul v-if="row.issues.length" class="record-issues" aria-label="本条资料核验问题"><li v-for="(issue, index) in row.issues" :key="index" :class="`issue-${issue.level}`"><span class="issue-level">{{ issue.level === 'error' ? '需处理' : '提示' }}</span><div><strong>{{ issue.title }}</strong><span v-if="issue.field_name" class="issue-field">{{ initializationFieldLabel(issue.field_name) }}</span><p>{{ issue.message }}</p><p v-if="issue.suggestion" class="issue-suggestion">{{ issue.suggestion }}</p></div></li></ul>
        </td></tr>
      </tbody>
    </table>
    <p v-else class="section-table-empty">暂无符合当前筛选的{{ sectionLabel }}。</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { ChevronDown, ChevronRight } from '@vicons/tabler'
import InitializationFieldDiff from './InitializationFieldDiff.vue'
import type { InitializationChange, InitializationChangeIssue, InitializationChangePreview, InitializationSection } from '@/types/initializationChanges'
import type { InitializationChangeTreeRow } from '@/utils/initializationChangeTree'
import { formatInitializationChangeValue, initializationChangeTitle, initializationFieldLabel, initializationOperationLabels, initializationSections, selectableInitializationChange } from '@/utils/initializationChangePresentation'
import { initializationResolutionValue, initializationSectionTableRows, initializationTableColumns, parseInitializationResolution } from '@/utils/initializationSectionTable'

const props = defineProps<{
  section: InitializationSection; rows: InitializationChangeTreeRow[]; selectedKeys: string[];
  resolutions: Record<string, number | null>; issues: InitializationChangeIssue[];
  existingAccounts?: InitializationChangePreview['existing_personnel_accounts'];
  admin: boolean; applying: boolean; collapsedKeys: ReadonlySet<string>;
}>()
const emit = defineEmits<{ select: [change: InitializationChange, checked: boolean]; resolve: [change: InitializationChange, target: number | null | undefined]; toggleNode: [key: string] }>()
const columns = computed(() => initializationTableColumns(props.section))
const projectHasComparison = computed(() => tableRows.value.some(row => row.change.operation === 'update' || (row.change.operation === 'conflict' && row.change.before !== null)))
const columnCount = computed(() => props.section === 'project' ? projectHasComparison.value ? 5 : 4 : columns.value.length + 2)
const sectionLabel = computed(() => initializationSections.find(item => item.key === props.section)?.label || '')
const tableRows = computed(() => initializationSectionTableRows(props.rows, props.section, props.collapsedKeys, props.issues, props.existingAccounts))
const selected = computed(() => new Set(props.selectedKeys))
const isSelected = (row: InitializationChangeTreeRow) => !row.contextOnly && selectableInitializationChange(row.change) && selected.value.has(row.change.key)
const canSelect = (row: InitializationChangeTreeRow) => props.admin && !props.applying && !row.contextOnly && selectableInitializationChange(row.change)
const canResolve = (row: InitializationChangeTreeRow) => props.admin && !props.applying && !row.contextOnly && row.change.operation !== 'applied'
const showMatching = (change: InitializationChange) => change.operation !== 'applied' && (Object.prototype.hasOwnProperty.call(props.resolutions, change.key) || change.operation === 'conflict' || (change.operation !== 'unchanged' && change.candidates.length > 0))
const missingCandidate = (change: InitializationChange) => change.target_id !== null && !change.candidates.some(candidate => candidate.id === change.target_id)
function selectRow(row: InitializationChangeTreeRow, event: Event) { if (canSelect(row)) emit('select', row.change, (event.target as HTMLInputElement).checked) }
function resolveRow(row: InitializationChangeTreeRow, event: Event) { if (canResolve(row)) emit('resolve', row.change, parseInitializationResolution((event.target as HTMLSelectElement).value)) }
</script>

<style scoped src="./InitializationSectionTable.css"></style>
