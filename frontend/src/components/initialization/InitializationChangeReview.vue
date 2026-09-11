<template>
  <Teleport to="body">
    <div v-if="open" class="change-review-backdrop" @click.self="close">
      <section ref="dialog" class="change-review" role="dialog" aria-modal="true" :aria-label="name + ' · 项目资料核对'" tabindex="-1" @keydown="handleDialogKeydown">
        <header class="change-review-header">
          <div class="change-review-summary" aria-label="变更概览">
            <span v-if="preview?.mode === 'initialization'"><strong>{{ remainingChanges.length }}</strong> 项待确认资料</span>
            <template v-else><span v-for="operation in summaryOperations" :key="operation" :class="'operation-' + operation"><strong>{{ preview?.summary[operation] ?? '—' }}</strong>{{ initializationOperationLabels[operation] }}</span></template>
          </div>
          <button class="change-review-close" type="button" aria-label="关闭资料核对" :disabled="applying" @click="close"><NIcon :size="20"><X /></NIcon></button>
        </header>

        <div class="change-review-toolbar">
          <div class="change-review-filters" aria-label="筛选记录">
            <button v-for="item in filters" :key="item.key" type="button" :class="{ active: filter === item.key }" :aria-pressed="filter === item.key" @click="filter = item.key">{{ item.label }}</button>
          </div>
          <label class="change-review-search"><NIcon :size="17"><Search /></NIcon><input v-model="query" type="search" aria-label="搜索草稿记录" placeholder="搜索名称或内容"></label>
          <div v-if="groups.length > 1" class="change-review-section-actions" aria-label="分区显示">
            <button type="button" :disabled="opening" :aria-expanded="!allSectionsCollapsed" @click="collapsedSections = allSectionsCollapsed ? new Set() : new Set(groups.map(group => group.key))"><NIcon :size="16"><ChevronDown v-if="allSectionsCollapsed" /><ChevronUp v-else /></NIcon>{{ allSectionsCollapsed ? '展开各分区' : '收起各分区' }}</button>
          </div>
        </div>
        <nav v-if="groups.length > 1" class="change-review-sections" aria-label="跳转资料分区">
          <button v-for="group in groups" :key="group.key" type="button" :aria-controls="'review-section-' + group.key" @click="jumpToSection(group.key)">{{ group.label }} <span>{{ group.changes.length }}</span></button>
        </nav>

        <div v-if="notice" class="change-review-notice" role="status"><NIcon :size="18"><CircleCheck /></NIcon>{{ notice }}</div>
        <div v-if="error" class="change-review-error" role="alert"><span>{{ error }}</span><button type="button" :disabled="loading || applying" @click="refresh()">重新获取差异</button></div>
        <div v-if="panelValidation?.status === 'failed'" class="change-review-error" role="alert">{{ panelValidation.error || '核验服务未完成检查，请稍后重新打开草稿。' }}</div>
        <div v-if="!admin" class="change-review-readonly" role="status">你可以查看和核对资料，由管理员确认写入项目。</div>

        <main ref="body" class="change-review-body" :aria-busy="loading || opening">
          <div v-if="opening || (loading && !preview)" class="change-review-loading" role="status" aria-live="polite"><NIcon :size="28" class="change-review-spinner" aria-hidden="true"><Loader /></NIcon><span>正在加载草稿…</span></div>
          <template v-else>
            <div v-if="!visibleChanges.length" class="change-review-empty">
              <NIcon :size="28"><FileSearch /></NIcon>
              <strong>{{ !remainingChanges.length && preview?.summary.applied ? '本次资料已全部提交' : remainingChanges.length ? '没有符合条件的记录' : '暂时没有可核对的内容' }}</strong>
              <p>{{ !remainingChanges.length && preview?.summary.applied ? '可到项目配置中查看已入库内容。' : remainingChanges.length ? '调整筛选条件，查看其他资料。' : '可以继续向配置助手补充资料，识别出一部分后就能在这里提交。' }}</p>
              <button v-if="remainingChanges.length" type="button" @click="resetFilters">查看全部资料</button>
            </div>
            <section v-for="group in groups" :id="'review-section-' + group.key" :key="group.key" class="change-review-group" :aria-label="group.label">
              <header class="change-review-group-header">
                <input type="checkbox" :aria-label="'选择' + group.label + '分区'" :checked="groupSelection(group.changes).all" :indeterminate="groupSelection(group.changes).some" :disabled="applying || !admin || !groupSelection(group.changes).available" @change="selectMany(group.changes, checked($event))">
                <button class="change-review-group-toggle" type="button" :aria-expanded="!collapsedSections.has(group.key)" :aria-controls="'review-section-body-' + group.key" @click="toggleSection(group.key)"><NIcon :size="17"><ChevronRight v-if="collapsedSections.has(group.key)" /><ChevronDown v-else /></NIcon><h3>{{ group.label }}</h3><span>{{ group.changes.length }} 项</span></button>
                <span class="change-review-group-selection">{{ selectedIn(group.changes) ? '已选 ' + selectedIn(group.changes) + ' 项' : '' }}</span>
                <div v-if="group.key === 'wbs' && changeTree.groupKeys.length && !collapsedSections.has(group.key)" class="change-review-tree-actions"><button type="button" :disabled="!collapsedKeys.size" @click="collapsedKeys = new Set()">展开层级</button><button type="button" :disabled="changeTree.groupKeys.every(key => collapsedKeys.has(key))" @click="collapsedKeys = new Set(changeTree.groupKeys)">收起层级</button></div>
              </header>
              <div v-show="!collapsedSections.has(group.key)" :id="'review-section-body-' + group.key" class="change-review-group-body">
                <InitializationSectionTable :section="group.key" :rows="group.rows" :selected-keys="selectedKeys" :resolutions="resolutions" :issues="reviewIssues" :existing-accounts="preview?.existing_personnel_accounts" :credentials="admin ? credentials : []" :credential-errors="credentialErrorsByIdentity" :credentials-loading="loading" :admin="admin" :applying="applying" :collapsed-keys="collapsedKeys" @select="selectChange" @toggle-node="toggleNode" @credential-change="updateCredential" />
              </div>
            </section>
          </template>
        </main>

        <footer class="change-review-footer">
          <label v-if="admin && hasApplicableChanges" class="change-review-select-all"><input type="checkbox" :checked="allVisibleSelected" :indeterminate="someVisibleSelected" :disabled="opening || applying || !selectableVisible.length" @change="selectMany(visibleChanges, checked($event))">全选当前结果</label>
          <div class="change-review-footer-state" aria-live="polite"><strong><template v-if="loading">正在读取核验结果</template><template v-else-if="showCompletedState">{{ preview?.summary.applied ? '本次变更已提交' : '本次资料与现有数据一致' }}</template><template v-else-if="!admin">查看项目资料</template><template v-else>已选择 {{ selectedKeys.length }} 项<span v-if="stale"> · 等待重新核对</span><span v-else-if="hiddenSelectedCount"> · 含未显示的 {{ hiddenSelectedCount }} 项</span></template></strong><p v-if="showCompletedState">没有待提交的变更。</p><p v-else-if="!admin">当前为只读核对，需管理员提交。</p><p v-else-if="errors.length">所选内容有 {{ errors.length }} 项错误，请修改原始资料后重新上传；有错误的记录无法入库。</p><p v-else-if="preview?.validation.status === 'failed'">核验未完成，请重新获取差异。</p><p v-else-if="credentialErrors.some(Boolean)">请检查新增人员的账号和初始密码。</p><p v-else>只提交已选内容，其余资料可稍后继续处理。</p></div>
          <label v-if="warnings.length && admin" class="change-review-warnings"><input v-model="allowWarnings" type="checkbox" :disabled="loading || stale || applying">已核对 {{ warnings.length }} 项提示，确认继续</label>
          <div class="change-review-footer-actions"><button type="button" :disabled="applying" @click="close">{{ notice || showCompletedState ? '完成' : '稍后继续' }}</button><button v-if="admin && hasApplicableChanges" type="button" class="change-review-submit" :disabled="!canApply" :aria-busy="applying" @click="apply">{{ applying ? '正在提交…' : '确认提交 ' + selectedKeys.length + ' 项' }}</button></div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { ChevronDown, ChevronRight, ChevronUp, CircleCheck, FileSearch, Loader, Search, X } from '@vicons/tabler'
import InitializationSectionTable from './InitializationSectionTable.vue'
import { initializationReviewIssues } from '@/utils/initializationReviewIssues'
import { useInitializationChangeReview } from '@/composables/useInitializationChangeReview'
import type { InitializationChange, InitializationDraftReference, InitializationOperation, InitializationSection } from '@/types/initializationChanges'
import { filterInitializationChanges, initializationChangeFilters, initializationOperationLabels, initializationSections, selectableInitializationChange, type InitializationChangeFilter } from '@/utils/initializationChangePresentation'
import { buildInitializationChangeTree, visibleInitializationChangeTreeRows } from '@/utils/initializationChangeTree'

const props = defineProps<{ open: boolean; projectId: string; name: string; draft: InitializationDraftReference | null; admin: boolean }>()
const emit = defineEmits<{ close: []; applied: []; 'loading-change': [value: boolean] }>()
const { preview, remainingChanges, selectedKeys, resolutions, credentials, loading, opening, applying, stale, error, notice, allowWarnings, warnings, errors, credentialErrors, canApply, refresh, selectChange, selectMany, updateCredential, apply } = useInitializationChangeReview(props, () => emit('applied'))
watch([loading, opening], () => emit('loading-change', loading.value || opening.value), { immediate: true, flush: 'sync' })
const dialog = ref<HTMLElement | null>(null)
const body = ref<HTMLElement | null>(null)
const filter = ref<InitializationChangeFilter>('all')
const query = ref('')
const credentialErrorsByIdentity = computed(() => Object.fromEntries(credentials.value.map((item, index) => [item.identity_card_no, credentialErrors.value[index] || ''])))
const collapsedKeys = ref(new Set<string>())
const collapsedSections = ref(new Set<InitializationSection>())
const summaryOperations: InitializationOperation[] = ['add', 'update', 'unchanged']
const filters = [...initializationChangeFilters].sort((a, b) => Number(b.key === 'all') - Number(a.key === 'all'))
const visibleChanges = computed(() => filterInitializationChanges(remainingChanges.value, 'all', filter.value, query.value))
const changeTree = computed(() => buildInitializationChangeTree(remainingChanges.value, visibleChanges.value))
const displayedRows = computed(() => visibleInitializationChangeTreeRows(changeTree.value.rows, collapsedKeys.value))
const groups = computed(() => initializationSections.map(item => ({
  ...item, changes: visibleChanges.value.filter(change => change.section === item.key),
  rows: displayedRows.value.filter(row => row.change.section === item.key),
})).filter(group => group.changes.length))
const hasApplicableChanges = computed(() => Boolean(preview.value?.changes.some(selectableInitializationChange)))
const showCompletedState = computed(() => Boolean(preview.value?.changes.length) && !hasApplicableChanges.value)
const selectableVisible = computed(() => visibleChanges.value.filter(selectableInitializationChange))
const allVisibleSelected = computed(() => groupSelection(visibleChanges.value).all)
const someVisibleSelected = computed(() => groupSelection(visibleChanges.value).some)
const hiddenSelectedCount = computed(() => selectedKeys.value.filter(key => !visibleChanges.value.some(change => change.key === key)).length)
const allSectionsCollapsed = computed(() => groups.value.length > 0 && groups.value.every(group => collapsedSections.value.has(group.key)))
const reviewIssues = computed(() => initializationReviewIssues(props.draft, preview.value?.changes || [], [...(preview.value?.issues || []), ...(preview.value?.operation_issues || [])], selectedKeys.value, preview.value?.validation.status === 'completed'))
const panelValidation = computed(() => preview.value?.validation.status === 'failed' || preview.value?.validation.package_version ? preview.value.validation : props.draft?.validation || preview.value?.validation)
const checked = (event: Event) => (event.target as HTMLInputElement).checked
const selectedIn = (changes: InitializationChange[]) => changes.filter(change => selectedKeys.value.includes(change.key)).length
function groupSelection(changes: InitializationChange[]) {
  const available = changes.filter(selectableInitializationChange)
  const selected = selectedIn(available)
  return { available: available.length, all: available.length > 0 && selected === available.length, some: selected > 0 && selected < available.length }
}
function resetFilters() { filter.value = 'all'; query.value = '' }
function toggleNode(key: string) {
  const next = new Set(collapsedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedKeys.value = next
}
function toggleSection(key: InitializationSection) {
  const next = new Set(collapsedSections.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedSections.value = next
}
async function jumpToSection(key: InitializationSection) {
  if (collapsedSections.value.has(key)) toggleSection(key)
  await nextTick()
  const target = dialog.value?.querySelector<HTMLElement>('#review-section-' + key)
  if (target && body.value) body.value.scrollTo({ top: body.value.scrollTop + target.getBoundingClientRect().top - body.value.getBoundingClientRect().top - 12 })
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
    filter.value = 'all'; query.value = ''; collapsedKeys.value = new Set(); collapsedSections.value = new Set()
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await nextTick()
    dialog.value?.focus()
  } else restoreFocus()
}, { immediate: true })
watch([filter, query], () => { collapsedKeys.value = new Set(); collapsedSections.value = new Set() })
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
