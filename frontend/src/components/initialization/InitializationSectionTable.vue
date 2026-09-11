<template>
  <div class="initialization-section-table" :class="`section-${section}`">
    <label v-if="section === 'wbs'" class="wbs-extra-toggle"><input v-model="showExtraFields" type="checkbox">显示更多字段（来源、工时、成本等）</label>
    <table v-if="tableRows.length" :aria-label="`${sectionLabel}变更比较`">
      <colgroup><col class="selection-col"><template v-if="section === 'project'"><col class="project-name-col"><col v-if="projectHasComparison"><col></template><col v-for="column in columns" v-else :key="column.key" :class="`column-${column.key}`"><col class="operation-col"></colgroup>
      <thead><tr><th scope="col" class="selection-cell">选择</th><template v-if="section === 'project'"><th scope="col">字段</th><th v-if="projectHasComparison" scope="col">现有数据</th><th scope="col">本次资料</th></template><th v-for="column in columns" v-else :key="column.key" scope="col">{{ column.label }}</th><th scope="col">状态</th></tr></thead>
      <tbody v-for="group in tableGroups" :key="group.key" :data-change-key="section !== 'personnel' ? group.key : undefined" :data-person-key="section === 'personnel' ? group.key : undefined" :data-depth="section === 'wbs' ? group.rows[0].depth : undefined" tabindex="-1" :class="{ 'is-selected': groupSelected(group), 'is-context': group.rows[0].contextOnly, 'is-parent': group.rows[0].hasChildren, 'is-root': section === 'wbs' && group.rows[0].depth === 0 }">
        <tr v-if="section === 'personnel'" class="person-header"><td></td><th :colspan="columnCount - 1" scope="rowgroup"><div><strong>{{ group.name }}</strong><span v-if="group.identity">身份证号 {{ group.identity }}</span><span v-if="group.rows.length > 1" class="person-position-count">{{ group.rows.length }} 个岗位</span></div></th></tr>
        <tr v-if="section === 'personnel' && group.issues.length" class="person-issues-row"><td></td><td :colspan="columnCount - 1"><InitializationFieldIssues :issues="group.issues" aria-label="人员核验问题" /></td></tr>
        <template v-for="row in group.rows" :key="row.change.key">
        <tr class="record-row" :data-change-key="section === 'personnel' ? row.change.key : undefined" :class="{ 'is-selected': isSelected(row) }">
          <td class="selection-cell" :rowspan="section === 'wbs' && hasSupplementary(row) ? 2 : 1"><input type="checkbox" :aria-label="`选择${initializationChangeTitle(row.change)}`" :checked="isSelected(row)" :disabled="!canSelect(row)" @change="selectRow(row, $event)"></td>
          <template v-if="section === 'project'">
            <th scope="row" class="project-field-name">{{ initializationChangeTitle(row.change) }}</th>
            <td v-if="projectHasComparison" class="project-before"><div v-for="field in row.fields" :key="field.name" :data-field="field.name">{{ row.change.operation === 'add' && (field.before === null || field.before === undefined || field.before === '') ? '—' : formatInitializationChangeValue(field.before, field.name) }}</div></td>
            <td class="project-after"><div v-for="field in row.fields" :key="field.name" :data-field="field.name" :class="{ 'is-changed': field.changed }">{{ formatInitializationChangeValue(field.after, field.name) }}<InitializationFieldIssues :issues="field.issues" /></div></td>
          </template>
          <td v-for="(cell, index) in row.cells" v-else :key="cell.key" :rowspan="section === 'wbs' && index === 0 && hasSupplementary(row) ? 2 : 1" :class="[`cell-${cell.key}`, { 'hierarchy-cell': section === 'wbs' && index === 0 }]">
            <div v-if="section === 'wbs' && index === 0" class="tree-branches" aria-hidden="true"><i v-for="(continues, level) in row.ancestorBranches" v-show="continues && level > 0" :key="level" class="tree-trunk" :style="{ left: `${12 + (level - 1) * 24 + 11}px` }"></i><i v-if="row.depth" class="tree-elbow" :class="{ 'is-last': row.lastSibling }" :style="{ left: `${12 + (row.depth - 1) * 24 + 11}px` }"></i><i v-if="row.hasChildren && !collapsedKeys.has(row.change.key)" class="tree-child-line" :style="{ left: `${12 + row.depth * 24 + 11}px` }"></i></div>
            <div class="cell-layout" :style="section === 'wbs' && index === 0 ? { paddingLeft: `${row.depth * 24}px` } : undefined">
              <template v-if="section === 'wbs' && index === 0"><button v-if="row.hasChildren" type="button" class="node-toggle" :aria-expanded="!collapsedKeys.has(row.change.key)" :aria-label="`${collapsedKeys.has(row.change.key) ? '展开' : '收起'}${initializationChangeTitle(row.change)}的下级`" :disabled="applying" @click="emit('toggleNode', row.change.key)"><NIcon :size="15"><ChevronRight v-if="collapsedKeys.has(row.change.key)" /><ChevronDown v-else /></NIcon></button><span v-else class="node-leaf" aria-hidden="true"></span></template>
              <div class="cell-fields"><span v-if="section === 'wbs' && index === 0" class="tree-level">第 {{ row.change.after.level || row.depth + 1 }} 级<span v-if="row.hasChildren"> · {{ row.childCount }} 个直接下级</span></span><InitializationFieldDiff v-for="field in fieldsInCell(group, row, cell)" :key="field.name" :field="field" :operation="row.change.operation" :baseline="row.change.before !== null" :label="fieldLabel(cell.key)" :issues="field.issues" /><span v-if="!fieldsInCell(group, row, cell).length" class="empty-value">未填写</span><span v-if="section === 'wbs' && index === 0 && row.contextOnly" class="context-label">上级路径</span></div>
            </div>
          </td>
          <td class="operation-cell"><span class="operation-label" :class="`operation-${row.change.operation}`">{{ initializationOperationLabels[row.change.operation] }}</span><span v-if="row.change.operation === 'update' && row.change.fields.length" class="change-count">{{ row.change.fields.length }} 项变化</span></td>
        </tr>
        <tr v-if="hasSupplementary(row)" class="record-supplementary"><td v-if="section !== 'wbs'"></td><td :colspan="columnCount - (section === 'wbs' ? 2 : 1)">
          <div v-if="supplementaryFields(row).length" class="supplementary-fields" aria-label="补充信息"><InitializationFieldDiff v-for="field in supplementaryFields(row)" :key="field.name" :field="field" :operation="row.change.operation" :baseline="row.change.before !== null" :issues="field.issues" inline /></div>
        </td></tr>
        </template>
        <tr v-if="section === 'personnel'" class="person-account-row"><td></td><td :colspan="columnCount - 1"><InitializationPersonnelAccount :name="group.name" :credential="credentialByIdentity.get(group.identity)" :existing-account="group.rows[0].account" :admin="admin" :disabled="applying || credentialsLoading || !groupSelected(group)" :selected="groupSelected(group)" :loading="credentialsLoading" :error="credentialErrors?.[group.identity]" @change="(field, value) => editCredential(group, field, value)" /></td></tr>
      </tbody>
    </table>
    <p v-else class="section-table-empty">暂无符合当前筛选的{{ sectionLabel }}。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { ChevronDown, ChevronRight } from '@vicons/tabler'
import InitializationFieldDiff from './InitializationFieldDiff.vue'
import InitializationFieldIssues from './InitializationFieldIssues.vue'
import InitializationPersonnelAccount from './InitializationPersonnelAccount.vue'
import type { InitializationChange, InitializationChangeCredential, InitializationChangeIssue, InitializationChangePreview, InitializationCredentialField, InitializationSection } from '@/types/initializationChanges'
import type { InitializationChangeTreeRow } from '@/utils/initializationChangeTree'
import { formatInitializationChangeValue, initializationChangeTitle, initializationOperationLabels, initializationSections, selectableInitializationChange } from '@/utils/initializationChangePresentation'
import { groupInitializationTableRows, initializationSectionTableRows, initializationTableColumns } from '@/utils/initializationSectionTable'

const props = defineProps<{
  section: InitializationSection; rows: InitializationChangeTreeRow[]; selectedKeys: string[];
  resolutions: Record<string, number | null>; issues: InitializationChangeIssue[];
  existingAccounts?: InitializationChangePreview['existing_personnel_accounts'];
  credentials?: InitializationChangeCredential[]; credentialErrors?: Record<string, string>; credentialsLoading?: boolean;
  admin: boolean; applying: boolean; collapsedKeys: ReadonlySet<string>;
}>()
const emit = defineEmits<{ select: [change: InitializationChange, checked: boolean]; toggleNode: [key: string]; credentialChange: [identity: string, field: InitializationCredentialField, value: string] }>()
const columns = computed(() => initializationTableColumns(props.section).map(column => props.section === 'personnel' ? { ...column, label: column.key === 'identity' ? '岗位' : column.key === 'certificate' ? '证书编号' : column.label } : column))
const projectHasComparison = computed(() => tableRows.value.some(row => row.change.operation === 'update' || (row.change.operation === 'conflict' && row.change.before !== null)))
const columnCount = computed(() => props.section === 'project' ? projectHasComparison.value ? 5 : 4 : columns.value.length + 2)
const sectionLabel = computed(() => initializationSections.find(item => item.key === props.section)?.label || '')
const tableRows = computed(() => initializationSectionTableRows(props.rows, props.section, props.collapsedKeys, props.issues, props.existingAccounts))
const tableGroups = computed(() => groupInitializationTableRows(tableRows.value, props.section))
const showExtraFields = ref(false)
type TableRow = ReturnType<typeof initializationSectionTableRows>[number]
type TableGroup = (typeof tableGroups.value)[number]
const selected = computed(() => new Set(props.selectedKeys))
const credentialByIdentity = computed(() => new Map((props.admin ? props.credentials || [] : []).map(item => [item.identity_card_no, item])))
const isSelected = (row: InitializationChangeTreeRow) => !row.contextOnly && selectableInitializationChange(row.change) && selected.value.has(row.change.key)
const canSelect = (row: InitializationChangeTreeRow) => props.admin && !props.applying && !row.contextOnly && selectableInitializationChange(row.change)
const supplementaryFields = (row: TableRow) => props.section !== 'wbs' || showExtraFields.value ? row.supplementary : row.supplementary.filter(field => field.issues.length || (field.changed && row.change.before !== null) || ['description', 'deadline_at'].includes(field.name))
const hasSupplementary = (row: TableRow) => supplementaryFields(row).length > 0
function fieldLabel(column: string) {
  if (column === 'schedule' || column === 'window') return 'short'
  return props.section === 'wbs' && ['duration', 'status', 'dependencies'].includes(column) ? 'full' : 'hidden'
}
function selectRow(row: InitializationChangeTreeRow, event: Event) { if (canSelect(row)) emit('select', row.change, (event.target as HTMLInputElement).checked) }
function groupSelected(group: TableGroup) { return group.rows.some(isSelected) }
function fieldsInCell(group: TableGroup, row: TableRow, cell: TableRow['cells'][number]) {
  if (props.section !== 'personnel') return cell.values
  return cell.values.filter(field => {
    if (!['real_name', 'identity_card_no'].includes(field.name) || field.issues.length || (field.changed && row.change.operation !== 'add')) return true
    return String(field.after || '').trim() !== (field.name === 'real_name' ? group.name : group.identity)
  })
}
function editCredential(group: TableGroup, field: InitializationCredentialField, value: string) {
  if (!props.admin || props.applying || props.credentialsLoading || !groupSelected(group)) return
  if (credentialByIdentity.value.has(group.identity)) emit('credentialChange', group.identity, field, value)
}
</script>

<style scoped src="./InitializationSectionTable.css"></style>
