<template>
  <Teleport to="body">
    <div v-if="open" class="change-review-backdrop" @click.self="close">
      <section ref="dialog" class="change-review" role="dialog" aria-modal="true" :aria-label="name + ' · 项目资料核对'" tabindex="-1" @keydown="handleDialogKeydown">
        <header class="change-review-header">
          <div class="change-review-summary" aria-label="变更概览">
            <span v-for="operation in summaryOperations" :key="operation" :class="'operation-' + operation"><strong>{{ preview?.summary[operation] ?? '—' }}</strong>{{ initializationOperationLabels[operation] }}</span>
          </div>
          <button class="change-review-close" type="button" aria-label="关闭资料核对" :disabled="applying" @click="close"><NIcon :size="20"><X /></NIcon></button>
        </header>

        <div class="change-review-toolbar">
          <div class="change-review-filters" aria-label="筛选记录">
            <button v-for="item in filters" :key="item.key" type="button" :class="{ active: filter === item.key }" :aria-pressed="filter === item.key" @click="filter = item.key">{{ item.label }}</button>
          </div>
          <label class="change-review-search"><NIcon :size="17"><Search /></NIcon><input v-model="query" type="search" aria-label="搜索草稿记录" placeholder="搜索名称或内容"></label>
          <button v-if="groups.length > 1" class="change-review-fold-all" type="button" @click="toggleAllSections">{{ allSectionsCollapsed ? '展开各分区' : '收起各分区' }}</button>
        </div>
        <nav v-if="groups.length > 1" class="change-review-sections" aria-label="跳转资料分区">
          <button v-for="group in groups" :key="group.key" type="button" :aria-controls="'review-section-' + group.key" @click="jumpToSection(group.key)">{{ group.label }} <span>{{ group.changes.length }}</span></button>
        </nav>

        <div v-if="notice" class="change-review-notice" role="status"><NIcon :size="18"><CircleCheck /></NIcon>{{ notice }}</div>
        <div v-if="error" class="change-review-error" role="alert"><span>{{ error }}</span><button type="button" :disabled="loading || applying" @click="refresh()">重新获取差异</button></div>
        <div v-if="!admin" class="change-review-readonly" role="status">你可以查看和核对资料，由管理员确认写入项目。</div>

        <main ref="body" class="change-review-body" :aria-busy="loading">
          <div v-if="loading && !preview" class="change-review-skeleton" aria-label="正在读取项目数据并生成差异"><i v-for="index in 4" :key="index"></i></div>
          <div v-else-if="!visibleChanges.length" class="change-review-empty">
            <NIcon :size="28"><FileSearch /></NIcon>
            <strong>{{ preview?.changes.length ? '没有符合条件的记录' : '暂时没有可核对的内容' }}</strong>
            <p>{{ preview?.changes.length ? '调整筛选条件，查看其他资料。' : '可以继续向配置助手补充资料，识别出一部分后就能在这里提交。' }}</p>
            <button v-if="preview?.changes.length" type="button" @click="resetFilters">查看全部资料</button>
          </div>
          <section v-for="group in groups" :id="'review-section-' + group.key" :key="group.key" class="change-review-group" :aria-label="group.label">
            <header class="change-review-group-header">
              <input type="checkbox" :aria-label="'选择' + group.label + '分区'" :checked="groupSelection(group.changes).all" :indeterminate="groupSelection(group.changes).some" :disabled="applying || !admin || !groupSelection(group.changes).available" @change="selectMany(group.changes, checked($event))">
              <button class="change-review-group-toggle" type="button" :aria-expanded="!collapsedSections.has(group.key)" :aria-controls="'review-section-body-' + group.key" @click="toggleSection(group.key)"><NIcon :size="17"><ChevronRight v-if="collapsedSections.has(group.key)" /><ChevronDown v-else /></NIcon><h3>{{ group.label }}</h3><span>{{ group.changes.length }} 项</span></button>
              <span class="change-review-group-selection">{{ selectedIn(group.changes) ? '已选 ' + selectedIn(group.changes) + ' 项' : group.changes.every(item => item.operation === 'applied') ? '已提交' : '' }}</span>
              <div v-if="group.key === 'wbs' && changeTree.groupKeys.length && !collapsedSections.has(group.key)" class="change-review-tree-actions"><button type="button" :disabled="!collapsedKeys.size" @click="collapsedKeys = new Set()">展开层级</button><button type="button" :disabled="changeTree.groupKeys.every(key => collapsedKeys.has(key))" @click="collapsedKeys = new Set(changeTree.groupKeys)">收起层级</button></div>
            </header>
            <div v-show="!collapsedSections.has(group.key)" :id="'review-section-body-' + group.key" class="change-review-group-body">
              <InitializationSectionTable :section="group.key" :rows="group.rows" :selected-keys="selectedKeys" :resolutions="resolutions" :issues="preview?.issues || []" :existing-accounts="preview?.existing_personnel_accounts" :admin="admin" :applying="applying" :collapsed-keys="collapsedKeys" @select="selectChange" @resolve="resolveChange" @toggle-node="toggleNode" />
            </div>
          </section>

          <section v-if="globalIssues.length" class="change-review-global-issues" aria-label="本次选择的核验提示"><h3>本次选择的核验提示 <span>{{ globalIssues.length }} 项</span></h3><div class="change-review-issues"><article v-for="(issue, index) in globalIssues" :key="index" :class="{ error: issue.level === 'error' }"><strong>{{ issue.level === 'error' ? '需要修正' : '需要核对' }} · {{ issue.title }}</strong><p>{{ issue.message }}</p><p v-if="issue.suggestion">{{ issue.suggestion }}</p></article></div></section>

          <section v-if="credentials.length && admin" class="change-review-credentials" aria-label="本次新增人员账号"><h3>本次新增人员账号 <span>{{ credentials.length }} 人</span></h3><p>系统已生成初始账号和密码，可在提交前调整。已有人员账号继续沿用。</p><article v-for="(credential, index) in credentials" :key="credential.identity_card_no"><header><strong>{{ credential.real_name }}</strong><span>{{ credential.position_name }}</span></header><div class="change-review-credential-fields"><label>登录账号<input v-model.trim="credential.username" :disabled="applying" autocomplete="off" maxlength="64" :aria-invalid="Boolean(credentialErrors[index])"></label><label>初始密码<span class="change-review-password"><input v-model="credential.initial_password" :disabled="applying" :type="showPasswords ? 'text' : 'password'" autocomplete="new-password" minlength="8" maxlength="12" :aria-invalid="Boolean(credentialErrors[index])"><button type="button" :disabled="applying" aria-label="重新生成初始密码" @click="credential.initial_password = generateInitializationPassword()"><NIcon :size="16"><Refresh /></NIcon></button></span></label></div><p v-if="credentialErrors[index]" class="change-review-credential-error" role="alert">{{ credentialErrors[index] }}</p></article><label class="change-review-show-password"><input v-model="showPasswords" type="checkbox">显示初始密码</label></section>
        </main>

        <footer class="change-review-footer">
          <label v-if="admin && hasApplicableChanges" class="change-review-select-all"><input type="checkbox" :checked="allVisibleSelected" :indeterminate="someVisibleSelected" :disabled="applying || !selectableVisible.length" @change="selectMany(visibleChanges, checked($event))">全选当前结果</label>
          <div class="change-review-footer-state" aria-live="polite"><strong><template v-if="loading">正在核验所选资料</template><template v-else-if="showCompletedState">{{ preview?.summary.applied ? '本次变更已提交' : '本次资料与现有数据一致' }}</template><template v-else-if="!admin">查看项目资料</template><template v-else>已选择 {{ selectedKeys.length }} 项<span v-if="stale"> · 等待重新核对</span><span v-else-if="hiddenSelectedCount"> · 含未显示的 {{ hiddenSelectedCount }} 项</span></template></strong><p v-if="showCompletedState">没有待提交的变更。</p><p v-else-if="!admin">当前为只读核对，需管理员提交。</p><p v-else-if="errors.length">所选内容有 {{ errors.length }} 项错误，可修正资料或取消相关记录的选择。</p><p v-else-if="preview?.validation.status === 'failed'">核验未完成，请重新获取差异。</p><p v-else-if="credentialErrors.some(Boolean)">请检查新增人员的账号和初始密码。</p><p v-else>只提交已选内容，其余资料可稍后继续处理。</p></div>
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
import { ChevronDown, ChevronRight, CircleCheck, FileSearch, Refresh, Search, X } from '@vicons/tabler'
import InitializationSectionTable from './InitializationSectionTable.vue'
import { useInitializationChangeReview } from '@/composables/useInitializationChangeReview'
import type { InitializationChange, InitializationDraftReference, InitializationOperation, InitializationSection } from '@/types/initializationChanges'
import { filterInitializationChanges, generateInitializationPassword, initializationChangeFilters, initializationOperationLabels, initializationSections, selectableInitializationChange, type InitializationChangeFilter } from '@/utils/initializationChangePresentation'
import { buildInitializationChangeTree, visibleInitializationChangeTreeRows } from '@/utils/initializationChangeTree'

const props = defineProps<{ open: boolean; projectId: string; name: string; draft: InitializationDraftReference | null; admin: boolean }>()
const emit = defineEmits<{ close: []; applied: [] }>()
const { preview, selectedKeys, resolutions, credentials, loading, applying, stale, error, notice, allowWarnings, warnings, errors, credentialErrors, canApply, refresh, selectChange, selectMany, resolveChange, apply } = useInitializationChangeReview(props, () => emit('applied'))
const dialog = ref<HTMLElement | null>(null)
const body = ref<HTMLElement | null>(null)
const filter = ref<InitializationChangeFilter>('all')
const query = ref('')
const showPasswords = ref(false)
const collapsedKeys = ref(new Set<string>())
const collapsedSections = ref(new Set<InitializationSection>())
const summaryOperations: InitializationOperation[] = ['add', 'update', 'conflict', 'unchanged', 'applied']
const filters = [...initializationChangeFilters].sort((a, b) => Number(b.key === 'all') - Number(a.key === 'all'))
const visibleChanges = computed(() => filterInitializationChanges(preview.value?.changes || [], 'all', filter.value, query.value))
const changeTree = computed(() => buildInitializationChangeTree(preview.value?.changes || [], visibleChanges.value))
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
const globalIssues = computed(() => preview.value?.issues.filter(issue => !issue.change_key) || [])
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
function toggleAllSections() {
  collapsedSections.value = allSectionsCollapsed.value ? new Set() : new Set(groups.value.map(group => group.key))
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
    filter.value = 'all'; query.value = ''; showPasswords.value = false; collapsedKeys.value = new Set(); collapsedSections.value = new Set()
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
