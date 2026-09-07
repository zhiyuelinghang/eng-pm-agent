<template>
  <section class="member-table-picker" :aria-label="label">
    <header class="member-table-toolbar">
      <div class="member-table-controls"><slot name="toolbar"><strong>{{ label }}</strong><span>{{ selectable ? `已选 ${selectedIds.length} 人` : `${rows.length} 人` }}</span></slot></div>
      <label class="member-table-search"><n-icon :size="16"><Search /></n-icon><input v-model="search" type="search" :aria-label="`搜索${label}`" placeholder="搜索姓名或岗位"></label>
    </header>
    <div class="member-table-scroll" tabindex="0" :aria-label="`${label}列表，可滚动查看`">
      <table>
        <thead><tr>
          <th v-if="selectable" class="member-check-column"><label title="选择全部人员，包含搜索结果之外的人员"><input type="checkbox" :checked="allSelected" :indeterminate="partSelected" :disabled="disabled || loading || !rows.length" @change="selectAll(($event.target as HTMLInputElement).checked)">全选</label></th>
          <th>姓名</th><th>岗位</th><th v-if="showRole" class="member-role-column">群内角色</th><th v-if="$slots.actions" class="member-actions-column">操作</th>
        </tr></thead>
        <tbody>
          <tr v-if="loading || error || !filteredRows.length"><td :colspan="2 + Number(selectable) + Number(showRole) + Number(Boolean($slots.actions))" class="member-table-empty" :role="error ? 'alert' : 'status'">{{ loading ? '正在加载项目成员…' : error || '没有符合条件的成员' }}</td></tr>
          <tr v-for="member in loading || error ? [] : filteredRows" :key="member.user_id" :class="{ selected: selectable && selectedIds.includes(member.user_id) }">
            <td v-if="selectable" class="member-check-column"><input v-model="selectedIds" type="checkbox" :value="member.user_id" :disabled="disabled || lockedIds.includes(member.user_id)" :title="lockedIds.includes(member.user_id) ? '当前群主保留在群内' : undefined" :aria-label="`选择${member.name}`"></td>
            <td><strong>{{ member.name }}</strong><small v-if="member.user_id === currentUserId" class="member-self">我</small></td>
            <td class="member-position"><div v-if="positionsOf(member).length" class="member-positions"><span v-for="position in expandedIds.includes(member.user_id) ? positionsOf(member) : positionsOf(member).slice(0, 2)" :key="position" class="member-position-tag">{{ position }}</span><button v-if="positionsOf(member).length > 2" type="button" class="member-position-more" :aria-expanded="expandedIds.includes(member.user_id)" @click="togglePositions(member.user_id)">{{ expandedIds.includes(member.user_id) ? '收起' : `+${positionsOf(member).length - 2}` }}</button></div><span v-else>—</span></td>
            <td v-if="showRole"><span :class="{ 'member-owner': member.member_role === 'owner' }">{{ member.member_role === 'owner' ? '群主' : member.member_role === 'candidate' ? '未加入' : '成员' }}</span></td>
            <td v-if="$slots.actions"><div class="member-table-actions"><slot name="actions" :member="member" /></div></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Search } from '@vicons/tabler'

type MemberRow = { user_id: number; name: string; title: string; positions?: string[]; member_role?: string }
const props = withDefaults(defineProps<{ rows: MemberRow[]; label: string; selectable?: boolean; showRole?: boolean; currentUserId?: number; loading?: boolean; error?: string; disabled?: boolean; lockedIds?: number[] }>(), { error: '', lockedIds: () => [] })
const selectedIds = defineModel<number[]>('selectedIds', { default: () => [] })
const search = defineModel<string>('search', { default: '' })
const filteredRows = computed(() => props.rows.filter(member => `${member.name} ${member.title} ${positionsOf(member).join(' ')}`.toLowerCase().includes(search.value.trim().toLowerCase())))
const allSelected = computed(() => props.rows.length > 0 && props.rows.every(member => selectedIds.value.includes(member.user_id)))
const partSelected = computed(() => !allSelected.value && props.rows.some(member => selectedIds.value.includes(member.user_id)))
function selectAll(checked: boolean) { selectedIds.value = checked ? props.rows.map(member => member.user_id) : props.lockedIds.filter(id => props.rows.some(member => member.user_id === id)) }
const expandedIds = ref<number[]>([])
function positionsOf(member: MemberRow) { return member.positions ?? (member.title ? [member.title] : []) }
function togglePositions(id: number) { expandedIds.value = expandedIds.value.includes(id) ? expandedIds.value.filter(value => value !== id) : [...expandedIds.value, id] }
</script>
<style scoped>
.member-table-picker { min-width: 0; overflow: hidden; border: 1px solid #dce6e3; border-radius: 9px; color: #294b4e; font-size: 13px; }
.member-table-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 12px; background: #f7faf9; border-bottom: 1px solid #e4ece8; }
.member-table-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.member-table-controls strong { font-size: 13px; font-weight: 600; }
.member-table-controls > span { color: #718780; font-size: 12px; }
.member-table-search { display: flex; align-items: center; gap: 7px; width: 210px; max-width: 100%; padding: 6px 10px; border: 1px solid #d9e4df; border-radius: 6px; background: white; color: #718780; }
.member-table-search input { min-width: 0; width: 100%; border: 0; outline: 0; background: transparent; color: #294b4e; font: inherit; font-size: 13px; }
.member-table-search:focus-within { border-color: #218e81; box-shadow: 0 0 0 2px #218e8114; }
.member-table-scroll { height: min(380px, 44dvh); min-height: 180px; overflow: auto; scrollbar-gutter: stable; }
table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; text-align: left; }
th { position: sticky; top: 0; z-index: 1; padding: 9px 12px; background: #f9fbfa; border-bottom: 1px solid #e3ebe7; color: #718780; font-size: 12px; font-weight: 500; }
td { padding: 11px 12px; border-bottom: 1px solid #edf1ef; font-size: 13px; overflow-wrap: anywhere; }
td strong { font-weight: 600; }
tbody tr:hover { background: #f7faf9; }
tbody tr.selected { background: #edf7f3; }
.member-check-column { width: 76px; }
.member-check-column label { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
input[type=checkbox] { width: 14px; height: 14px; margin: 0; accent-color: #08776f; cursor: pointer; vertical-align: middle; }
.member-role-column { width: 88px; white-space: nowrap; }
.member-actions-column { width: 100px; }
.member-table-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.member-position, .member-self { color: #718780; }
.member-self { margin-left: 6px; font-size: 12px; }
.member-owner { color: #08776f; }
.member-table-empty { padding: 42px 12px; text-align: center; color: #718780; }
input:focus-visible, .member-table-scroll:focus-visible { outline: 2px solid #13968c; outline-offset: -2px; }
@media (max-width: 600px) { table { min-width: 560px; } .member-table-search { flex: 1 1 180px; width: auto; } }
.member-positions { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.member-position-tag { padding: 2px 6px; border-radius: 4px; color: #5b7f75; background: #edf4f1; font-size: 12px; }
.member-position-more { padding: 2px 5px; border: 1px solid #d9e6df; border-radius: 4px; color: #168178; background: white; font: inherit; font-size: 12px; cursor: pointer; }
</style>
