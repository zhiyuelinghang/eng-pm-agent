import { computed, onScopeDispose, ref, watch } from 'vue'
import { applyInitializationChanges, initializationChangeError, previewInitializationChanges } from '@/api/initializationChanges'
import type { InitializationChange, InitializationChangeCredential, InitializationChangePreview, InitializationCredentialField, InitializationDraftReference, InitializationPreviewInput } from '@/types/initializationChanges'
import { generateInitializationPassword, initializationCredentialError, reconcileInitializationCredentials, selectableInitializationChange } from '@/utils/initializationChangePresentation'

type ReviewProps = { open: boolean; projectId: string; draft: InitializationDraftReference | null; admin: boolean }
type ReviewDependencies = {
  preview: typeof previewInitializationChanges
  apply: typeof applyInitializationChanges
  password: () => string
  debounceMs: number
  beforeReveal: () => Promise<void>
}
function paintLoadingState() {
  return typeof requestAnimationFrame === 'function'
    ? new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
    : Promise.resolve()
}
const defaults: ReviewDependencies = { preview: previewInitializationChanges, apply: applyInitializationChanges, password: generateInitializationPassword, debounceMs: 200, beforeReveal: paintLoadingState }

export function useInitializationChangeReview(props: ReviewProps, onApplied: () => void, dependencies: Partial<ReviewDependencies> = {}) {
  const deps = { ...defaults, ...dependencies }
  const preview = ref<InitializationChangePreview | null>(null)
  const selectedKeys = ref<string[]>([])
  const resolutions = ref<Record<string, number | null>>({})
  const credentials = ref<InitializationChangeCredential[]>([])
  const loading = ref(false)
  const opening = ref(false)
  const applying = ref(false)
  const stale = ref(true)
  const error = ref('')
  const notice = ref('')
  const allowWarnings = ref(false)
  const remainingChanges = computed(() => (preview.value?.changes || []).filter(change => change.operation !== 'applied'))
  let sequence = 0
  let controller: AbortController | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let hasSelection = false
  let disposed = false

  const warnings = computed(() => [...(preview.value?.issues || []), ...(preview.value?.operation_issues || [])].filter(issue => issue.level === 'warning'))
  const errors = computed(() => [...(preview.value?.issues || []), ...(preview.value?.operation_issues || [])].filter(issue => issue.level === 'error'))
  const credentialErrors = computed(() => credentials.value.map(item => initializationCredentialError(item, credentials.value)))
  const canApply = computed(() => Boolean(
    props.open && props.admin && !loading.value && !applying.value && !stale.value
    && preview.value?.can_apply && preview.value.validation.status === 'completed'
    && selectedKeys.value.length && !errors.value.length
    && (!warnings.value.length || allowWarnings.value) && !credentialErrors.value.some(Boolean),
  ))

  function invalidate() {
    sequence += 1
    controller?.abort()
    controller = null
    if (timer) clearTimeout(timer)
    timer = undefined
    stale.value = true
    loading.value = false
    allowWarnings.value = false
  }

  async function refresh(resetSelection = false, forceValidation = false) {
    invalidate()
    if (disposed || !props.open || !props.projectId || !props.draft || applying.value) { opening.value = false; return }
    if (resetSelection) hasSelection = false
    const requestSequence = sequence
    const draftId = props.draft.id
    const projectId = props.projectId
    const requestController = new AbortController()
    controller = requestController
    loading.value = true
    error.value = ''
    const input: InitializationPreviewInput = {
      ...(hasSelection ? { selected_keys: [...selectedKeys.value] } : {}),
      resolutions: { ...resolutions.value },
      ...(forceValidation ? { force_validation: true } : {}),
    }
    try {
      const result = await deps.preview(projectId, draftId, input, requestController.signal)
      if (disposed || requestSequence !== sequence || !props.open) return
      // Paint the lightweight dialog before mounting a full draft, even when
      // the response is already cached. Reopening must not mount old rows first.
      if (opening.value) await deps.beforeReveal()
      if (disposed || requestSequence !== sequence || !props.open) return
      preview.value = result
      selectedKeys.value = [...result.selected_keys]
      hasSelection = true
      credentials.value = reconcileInitializationCredentials(result.required_personnel_credentials, credentials.value, deps.password)
      stale.value = false
      if (result.validation.status === 'failed') error.value = result.validation.error || '核验服务未完成检查，请稍后重新打开草稿。'
    } catch (failure: unknown) {
      if (requestSequence !== sequence) return
      const failureState = initializationChangeError(failure)
      if (!failureState.cancelled) error.value = failureState.message
    } finally {
      if (requestSequence === sequence) { loading.value = false; opening.value = false }
    }
  }

  function schedulePreview() {
    invalidate()
    error.value = ''
    timer = setTimeout(() => { void refresh() }, deps.debounceMs)
  }
  function selectChange(change: InitializationChange, selected: boolean) {
    if (applying.value || !selectableInitializationChange(change)) return
    const next = new Set(selectedKeys.value)
    if (selected) next.add(change.key)
    else next.delete(change.key)
    selectedKeys.value = [...next]
    hasSelection = true
    schedulePreview()
  }
  function selectMany(changes: InitializationChange[], selected: boolean) {
    if (applying.value) return
    const next = new Set(selectedKeys.value)
    for (const change of changes.filter(selectableInitializationChange)) {
      if (selected) next.add(change.key)
      else next.delete(change.key)
    }
    selectedKeys.value = [...next]
    hasSelection = true
    schedulePreview()
  }
  function resolveChange(change: InitializationChange, target: number | null | undefined) {
    if (applying.value) return
    const next = { ...resolutions.value }
    if (target === undefined) delete next[change.key]
    else next[change.key] = target
    resolutions.value = next
    if (target !== undefined && !selectedKeys.value.includes(change.key)) selectedKeys.value = [...selectedKeys.value, change.key]
    hasSelection = true
    schedulePreview()
  }

  async function apply() {
    if (!canApply.value || !preview.value || !props.draft) return
    applying.value = true
    error.value = ''
    notice.value = ''
    const count = selectedKeys.value.length
    const submittedKeys = new Set(selectedKeys.value)
    try {
      const applied = await deps.apply(props.projectId, props.draft.id, {
        preview_id: preview.value.preview_id, allow_warnings: allowWarnings.value,
        personnel_credentials: credentials.value.map(item => ({ identity_card_no: item.identity_card_no, username: item.username.trim(), initial_password: item.initial_password })),
      })
      if (disposed) return
      notice.value = applied.result.status === 'applied'
        ? `已提交 ${count} 项变更，本次资料已全部提交。`
        : `已提交 ${count} 项变更，可以继续核对剩余内容。`
      credentials.value = []
      resolutions.value = Object.fromEntries(Object.entries(resolutions.value).filter(([key]) => !submittedKeys.has(key)))
      selectedKeys.value = selectedKeys.value.filter(key => !submittedKeys.has(key))
      hasSelection = true
      onApplied()
    } catch (failure: unknown) {
      const failureState = initializationChangeError(failure)
      error.value = failureState.stale ? '项目数据或草稿已经变化，请重新获取差异并核对后提交。' : failureState.message
    } finally {
      applying.value = false
      invalidate()
    }
    // A failed apply never reuses its preview. Refresh is explicit so an uncertain network
    // response cannot lead to an unnoticed second submission.
    if (notice.value) await refresh()
  }

  function updateCredential(identity: string, field: InitializationCredentialField, value: string) {
    if (!props.admin || applying.value || !props.open) return
    const credential = credentials.value.find(item => item.identity_card_no === identity)
    if (credential) credential[field] = field === 'username' ? value.trim() : value
  }

  let reviewIdentity = ''
  watch([() => props.open, () => props.projectId, () => props.draft?.id], () => {
    invalidate()
    opening.value = props.open
    const identity = `${props.projectId}:${props.draft?.id}`
    if (identity !== reviewIdentity) {
      reviewIdentity = identity
      preview.value = null
      credentials.value = []
      resolutions.value = {}
      selectedKeys.value = []
      hasSelection = false
    }
    error.value = ''
    notice.value = ''
    if (props.open) void refresh()
  }, { immediate: true, flush: 'sync' })
  watch(() => props.draft?.revision, (revision, previous) => {
    if (!props.open || revision === previous) return
    invalidate()
    if (!applying.value) void refresh()
  }, { flush: 'sync' })
  onScopeDispose(() => { disposed = true; invalidate() })

  return { preview, remainingChanges, selectedKeys, resolutions, credentials, loading, opening, applying, stale, error, notice, allowWarnings, warnings, errors, credentialErrors, canApply, refresh, selectChange, selectMany, resolveChange, updateCredential, apply }
}
