<template>
  <Teleport to="body">
    <div v-if="open" class="change-review-backdrop" @click.self="close">
      <section ref="dialog" class="change-review" role="dialog" aria-modal="true" :aria-label="`${name} · 项目资料核对`" tabindex="-1" @keydown="handleDialogKeydown">
        <header class="change-review-header">
          <div class="change-review-summary" aria-label="变更概览">
            <span v-for="operation in summaryOperations" :key="operation" :class="`operation-${operation}`"><strong>{{ preview?.summary[operation] ?? '—' }}</strong>{{ initializationOperationLabels[operation] }}</span>
          </div>
          <button class="change-review-close" type="button" aria-label="关闭资料核对" :disabled="applying" @click="close"><NIcon :size="20"><X /></NIcon></button>
        </header>

        <nav class="change-review-sections" aria-label="资料分区">
          <button type="button" :class="{ active: section === 'all' }" :aria-current="section === 'all' ? 'true' : undefined" @click="section = 'all'">全部资料 <span>{{ preview?.changes.length ?? 0 }}</span></button>
          <button v-for="item in initializationSections" :key="item.key" type="button" :class="{ active: section === item.key }" :aria-current="section === item.key ? 'true' : undefined" @click="section = item.key">{{ item.label }} <span>{{ sectionCount(item.key) }}</span></button>
        </nav>

        <div v-if="notice" class="change-review-notice" role="status"><NIcon :size="18"><CircleCheck /></NIcon>{{ notice }}</div>
        <div v-if="error" class="change-review-error" role="alert"><span>{{ error }}</span><button type="button" :disabled="loading || applying" @click="refresh()">重新获取差异</button></div>
        <div v-if="!admin" class="change-review-readonly" role="status">你可以查看和核对资料，由管理员确认写入项目。</div>

        <div class="change-review-body" :aria-busy="loading">
          <aside class="change-review-list-pane" aria-label="草稿记录">
            <div class="change-review-list-tools">
              <label class="change-review-search"><NIcon :size="17"><Search /></NIcon><input v-model="query" type="search" aria-label="搜索草稿记录" placeholder="搜索名称或内容"></label>
              <div class="change-review-filters" aria-label="筛选记录">
                <button v-for="item in initializationChangeFilters" :key="item.key" type="button" :class="{ active: filter === item.key }" :aria-pressed="filter === item.key" @click="filter = item.key">{{ item.label }}</button>
              </div>
              <div class="change-review-select-all"><label><input type="checkbox" :checked="allVisibleSelected" :indeterminate="someVisibleSelected" :disabled="applying || !selectableVisible.length || !admin" @change="selectMany(visibleChanges, checked($event))">选择当前列表</label><span>{{ visibleChanges.length }} 项</span></div>
              <div v-if="changeTree.groupKeys.length" class="change-review-tree-actions"><button type="button" :disabled="!collapsedKeys.size" @click="collapsedKeys = new Set()">展开全部</button><button type="button" :disabled="changeTree.groupKeys.every(key => collapsedKeys.has(key))" @click="collapsedKeys = new Set(changeTree.groupKeys)">收起全部</button></div>
            </div>
            <div v-if="loading && !preview" class="change-review-skeleton" aria-label="正在读取项目数据并生成差异"><i v-for="index in 5" :key="index"></i></div>
            <div v-else-if="!visibleChanges.length" class="change-review-empty"><NIcon :size="28"><CircleCheck v-if="showCompletedState" /><FileSearch v-else /></NIcon><strong>{{ showCompletedState ? '本次资料已处理完成' : preview?.changes.length ? '没有符合条件的记录' : '暂时没有可核对的内容' }}</strong><p>{{ showCompletedState ? '全部变更已提交，无变化内容已保留。' : preview?.changes.length ? '切换资料分区或筛选条件，查看其他记录。' : '可以继续向配置助手补充资料，识别出一部分后就能在这里提交。' }}</p><button v-if="preview?.changes.length" type="button" @click="resetFilters">查看全部资料</button></div>
            <div v-else class="change-review-records">
              <article v-for="row in displayedRows" :key="row.change.key" class="change-review-record" :class="{ active: activeKey === row.change.key, selected: selectedKeys.includes(row.change.key), 'change-review-tree-record': row.change.section === 'wbs', 'change-review-tree-context': row.contextOnly }" :style="{ '--tree-depth': Math.min(row.depth, 6) }">
                <button v-if="row.hasChildren" class="change-review-tree-toggle" type="button" :aria-label="`${collapsedKeys.has(row.change.key) ? '展开' : '收起'}${initializationChangeTitle(row.change)}的子节点`" :aria-expanded="!collapsedKeys.has(row.change.key)" @click="toggleNode(row.change.key)"><NIcon :size="16"><ChevronRight v-if="collapsedKeys.has(row.change.key)" /><ChevronDown v-else /></NIcon></button><span v-else-if="row.change.section === 'wbs'" class="change-review-tree-spacer" aria-hidden="true"></span>
                <input type="checkbox" :aria-label="`选择${initializationChangeTitle(row.change)}`" :checked="selectedKeys.includes(row.change.key)" :disabled="row.contextOnly || !admin || applying || !selectableInitializationChange(row.change)" @change="selectChange(row.change, checked($event))">
                <button class="change-review-record-content" type="button" :aria-pressed="activeKey === row.change.key" @click="activeKey = row.change.key"><span class="change-review-record-top"><span class="change-review-operation" :class="`operation-${row.change.operation}`">{{ initializationOperationLabels[row.change.operation] }}</span><small>{{ row.contextOnly ? '上级节点' : sectionLabel(row.change.section) }}</small></span><strong>{{ initializationChangeTitle(row.change) }}</strong><span class="change-review-record-hint">{{ changeHint(row.change) }}<span v-if="recordIssues(row.change).length"> · {{ recordIssues(row.change).length }} 项核验提示</span></span></button>
              </article>
            </div>
          </aside>

          <main ref="detailPane" class="change-review-detail">
            <div v-if="loading && !preview" class="change-review-detail-loading" role="status"><h3>正在核对项目资料</h3><p>读取项目现有数据，识别本次新增与更新。</p><div class="change-review-skeleton"><i v-for="index in 4" :key="index"></i></div></div>
            <template v-else-if="activeChange">
              <header class="change-review-detail-heading"><div><span>{{ sectionLabel(activeChange.section) }}<span v-if="activeChange.target_id"> · 已匹配现有记录</span></span><h3>{{ initializationChangeTitle(activeChange) }}</h3></div><span class="change-review-operation" :class="`operation-${activeChange.operation}`">{{ initializationOperationLabels[activeChange.operation] }}</span></header>
              <p v-if="activeChange.operation === 'applied'" class="change-review-applied-note">此项已写入项目，后续提交会保留这项结果。</p>
              <p v-if="activeExistingAccount" class="change-review-existing-account"><span>已有登录账号</span><strong>{{ activeExistingAccount.username }}</strong><span>继续沿用当前账号和密码。</span></p>
              <section v-if="activeChange.operation === 'conflict' || hasResolution(activeChange.key)" class="change-review-match">
                <h4>确认这条资料对应的记录</h4><p>找到相同记录时更新原数据；如果是另一条资料，可以明确新建。</p>
                <label>匹配结果<select :value="resolutionValue(activeChange.key)" :disabled="!admin || applying" @change="resolveActive($event)"><option value="">请选择处理方式</option><option v-for="candidate in activeChange.candidates" :key="candidate.id" :value="String(candidate.id)">更新：{{ candidate.title }}</option><option v-if="resolvedCandidateMissing" :value="String(activeChange.target_id)">更新当前匹配记录</option><option value="new">作为新记录添加</option></select></label>
              </section>
              <section v-if="recordIssues(activeChange).length" class="change-review-issues" aria-label="当前记录核验提示"><article v-for="(issue, index) in recordIssues(activeChange)" :key="index" :class="{ error: issue.level === 'error' }"><strong>{{ issue.level === 'error' ? '需要修正' : '需要核对' }} · {{ issue.title }}</strong><p>{{ issue.message }}</p><p v-if="issue.suggestion">{{ issue.suggestion }}</p></article></section>

              <div class="change-review-comparison-heading"><h4>字段对比</h4><label><input v-model="onlyChangedFields" type="checkbox">仅看变化字段</label></div>
              <table class="change-review-comparison"><thead><tr><th scope="col">字段</th><th scope="col">项目现有数据</th><th scope="col">本次资料</th></tr></thead><tbody><tr v-for="field in comparisonFields" :key="field.name" :class="{ changed: field.changed }"><th scope="row">{{ field.label }}<span v-if="field.changed" class="change-review-field-mark">{{ activeChange.operation === 'add' ? '新增' : '变化' }}</span></th><td data-label="现有">{{ activeChange.before ? formatInitializationChangeValue(field.before, field.name) : '—' }}</td><td data-label="本次">{{ formatInitializationChangeValue(field.after, field.name) }}</td></tr><tr v-if="!comparisonFields.length"><td colspan="3" class="change-review-comparison-empty">{{ onlyChangedFields ? '此项没有变化字段，可取消“仅看变化字段”查看完整内容。' : '此项暂时没有可展示的字段。' }}</td></tr></tbody></table>
            </template>
            <div v-else class="change-review-empty change-review-detail-empty"><NIcon :size="32"><CircleCheck v-if="showCompletedState" /><ListDetails v-else /></NIcon><strong>{{ showCompletedState ? '没有待提交的变更' : '逐项确认这次的变化' }}</strong><p>{{ showCompletedState ? '可切换到“全部”或“已提交”查看记录。' : '从列表中选择资料查看新旧内容。可以只提交已核对的记录，其他资料会留在草稿中。' }}</p></div>

            <details v-if="globalIssues.length" class="change-review-global-issues" open><summary>本次选择的核验提示 <span>{{ globalIssues.length }} 项</span></summary><div class="change-review-issues"><article v-for="(issue, index) in globalIssues" :key="index" :class="{ error: issue.level === 'error' }"><strong>{{ issue.level === 'error' ? '需要修正' : '需要核对' }} · {{ issue.title }}</strong><p>{{ issue.message }}</p><p v-if="issue.suggestion">{{ issue.suggestion }}</p></article></div></details>

            <details v-if="credentials.length && admin" class="change-review-credentials" open><summary>本次新增人员账号 <span>{{ credentials.length }} 人</span></summary><p>系统已生成初始账号和密码，可在提交前调整。已有人员账号继续沿用。</p><article v-for="(credential, index) in credentials" :key="credential.identity_card_no"><header><strong>{{ credential.real_name }}</strong><span>{{ credential.position_name }}</span></header><div class="change-review-credential-fields"><label>登录账号<input v-model.trim="credential.username" :disabled="applying" autocomplete="off" maxlength="64" :aria-invalid="Boolean(credentialErrors[index])"></label><label>初始密码<span class="change-review-password"><input v-model="credential.initial_password" :disabled="applying" :type="showPasswords ? 'text' : 'password'" autocomplete="new-password" minlength="8" maxlength="12" :aria-invalid="Boolean(credentialErrors[index])"><button type="button" :disabled="applying" aria-label="重新生成初始密码" @click="credential.initial_password = generateInitializationPassword()"><NIcon :size="16"><Refresh /></NIcon></button></span></label></div><p v-if="credentialErrors[index]" class="change-review-credential-error" role="alert">{{ credentialErrors[index] }}</p></article><label class="change-review-show-password"><input v-model="showPasswords" type="checkbox">显示初始密码</label></details>
          </main>
        </div>

        <footer class="change-review-footer">
          <div class="change-review-footer-state" aria-live="polite"><strong>已选择 {{ selectedKeys.length }} 项<span v-if="loading"> · 正在核验</span><span v-else-if="stale"> · 等待重新核对</span></strong><p v-if="!admin">当前为只读核对，需管理员提交。</p><p v-else-if="errors.length">所选内容有 {{ errors.length }} 项错误，可修正资料或取消相关记录的选择。</p><p v-else-if="preview?.validation.status === 'failed'">核验未完成，请重新获取差异。</p><p v-else-if="credentialErrors.some(Boolean)">请检查新增人员的账号和初始密码。</p><p v-else>只写入本次选择的新增和更新；未提供的项目数据会保留。</p></div>
          <label v-if="warnings.length && admin" class="change-review-warnings"><input v-model="allowWarnings" type="checkbox" :disabled="loading || stale || applying">已核对 {{ warnings.length }} 项提示，确认继续</label>
          <div class="change-review-footer-actions"><button type="button" :disabled="applying" @click="close">{{ notice ? '完成' : '稍后继续' }}</button><button v-if="admin" type="button" class="change-review-submit" :disabled="!canApply" :aria-busy="applying" @click="apply">{{ applying ? '正在提交…' : `确认提交 ${selectedKeys.length} 项` }}</button></div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { ChevronDown, ChevronRight, CircleCheck, FileSearch, ListDetails, Refresh, Search, X } from '@vicons/tabler'
import { useInitializationChangeReview } from '@/composables/useInitializationChangeReview'
import type { InitializationChange, InitializationDraftReference, InitializationOperation, InitializationSection } from '@/types/initializationChanges'
import { filterInitializationChanges, formatInitializationChangeValue, generateInitializationPassword, initializationChangeFilters, initializationChangeTitle, initializationComparisonFields, initializationOperationLabels, initializationSections, selectableInitializationChange, type InitializationChangeFilter } from '@/utils/initializationChangePresentation'
import { buildInitializationChangeTree, visibleInitializationChangeTreeRows } from '@/utils/initializationChangeTree'

const props = defineProps<{ open: boolean; projectId: string; name: string; draft: InitializationDraftReference | null; admin: boolean }>()
const emit = defineEmits<{ close: []; applied: [] }>()
const { preview, selectedKeys, resolutions, credentials, loading, applying, stale, error, notice, allowWarnings, warnings, errors, credentialErrors, canApply, refresh, selectChange, selectMany, resolveChange, apply } = useInitializationChangeReview(props, () => emit('applied'))
const dialog = ref<HTMLElement | null>(null)
const detailPane = ref<HTMLElement | null>(null)
const section = ref<InitializationSection | 'all'>('all')
const filter = ref<InitializationChangeFilter>('changes')
const query = ref('')
const activeKey = ref('')
const onlyChangedFields = ref(false)
const showPasswords = ref(false)
const collapsedKeys = ref(new Set<string>())
const summaryOperations: InitializationOperation[] = ['add', 'update', 'conflict', 'unchanged', 'applied']
const visibleChanges = computed(() => filterInitializationChanges(preview.value?.changes || [], section.value, filter.value, query.value))
const changeTree = computed(() => buildInitializationChangeTree(preview.value?.changes || [], visibleChanges.value))
const displayedRows = computed(() => visibleInitializationChangeTreeRows(changeTree.value.rows, collapsedKeys.value))
const showCompletedState = computed(() => filter.value === 'changes' && Boolean(preview.value?.changes.length) && preview.value!.changes.every(change => change.operation === 'applied' || change.operation === 'unchanged'))
const selectableVisible = computed(() => visibleChanges.value.filter(selectableInitializationChange))
const allVisibleSelected = computed(() => selectableVisible.value.length > 0 && selectableVisible.value.every(change => selectedKeys.value.includes(change.key)))
const someVisibleSelected = computed(() => !allVisibleSelected.value && selectableVisible.value.some(change => selectedKeys.value.includes(change.key)))
const activeChange = computed(() => displayedRows.value.find(row => row.change.key === activeKey.value)?.change || null)
const activeExistingAccount = computed(() => activeChange.value?.section === 'personnel' ? preview.value?.existing_personnel_accounts?.find(account => account.identity_card_no === activeChange.value?.after.identity_card_no) : undefined)
const comparisonFields = computed(() => activeChange.value ? initializationComparisonFields(activeChange.value).filter(field => !onlyChangedFields.value || field.changed) : [])
const globalIssues = computed(() => preview.value?.issues.filter(issue => !issue.change_key) || [])
const resolvedCandidateMissing = computed(() => activeChange.value?.target_id && !activeChange.value.candidates.some(candidate => candidate.id === activeChange.value?.target_id))
const sectionLabel = (key: InitializationSection) => initializationSections.find(item => item.key === key)?.label
const sectionCount = (key: InitializationSection) => preview.value?.changes.filter(change => change.section === key).length || 0
const checked = (event: Event) => (event.target as HTMLInputElement).checked
const hasResolution = (key: string) => Object.prototype.hasOwnProperty.call(resolutions.value, key)
const resolutionValue = (key: string) => hasResolution(key) ? resolutions.value[key] === null ? 'new' : String(resolutions.value[key]) : ''
const recordIssues = (change: InitializationChange) => preview.value?.issues.filter(issue => issue.change_key === change.key) || []
function changeHint(change: InitializationChange) {
  if (change.operation === 'conflict') return '选择对应的原记录或新建'
  if (change.operation === 'applied') return '已写入项目'
  if (change.operation === 'unchanged') return '与项目数据一致'
  return change.operation === 'add' ? '将添加到项目' : `${change.fields.length} 个字段变化`
}
function resolveActive(event: Event) {
  if (!activeChange.value) return
  const value = (event.target as HTMLSelectElement).value
  resolveChange(activeChange.value, value === '' ? undefined : value === 'new' ? null : Number(value))
}
function resetFilters() { section.value = 'all'; filter.value = 'all'; query.value = '' }
function toggleNode(key: string) {
  const next = new Set(collapsedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedKeys.value = next
}
function close() { if (!applying.value) emit('close') }

let previousFocus: HTMLElement | null = null
let previousOverflow: string | undefined
function restoreFocus() {
  if (previousOverflow !== undefined) { document.body.style.overflow = previousOverflow; previousOverflow = undefined }
  if (previousFocus?.isConnected) previousFocus.focus()
  previousFocus = null
}
watch(() => props.open, async open => {
  if (open) {
    section.value = 'all'; filter.value = 'changes'; query.value = ''; activeKey.value = ''; onlyChangedFields.value = false; showPasswords.value = false; collapsedKeys.value = new Set()
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await nextTick()
    dialog.value?.focus()
  } else restoreFocus()
}, { immediate: true })
// A new search/filter reveals its matches; folding only controls visibility,
// while the filtered selection remains unchanged across expand/collapse.
watch([section, filter, query], () => {
  collapsedKeys.value = new Set()
  if (!visibleChanges.value.some(change => change.key === activeKey.value)) activeKey.value = visibleChanges.value[0]?.key || ''
})
watch(displayedRows, rows => { if (!rows.some(row => row.change.key === activeKey.value)) activeKey.value = rows.find(row => !row.contextOnly)?.change.key || rows[0]?.change.key || '' })
watch(activeKey, () => { detailPane.value?.scrollTo({ top: 0 }) })
function handleDialogKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); close(); return }
  if (event.key !== 'Tab' || !dialog.value) return
  const elements = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex="0"]')].filter(item => item.getClientRects().length)
  const first = elements[0], last = elements[elements.length - 1]
  if (!first) { event.preventDefault(); return }
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.value)) { event.preventDefault(); first.focus() }
}
onBeforeUnmount(restoreFocus)
</script>

<style scoped src="./InitializationChangeReview.css"></style>
