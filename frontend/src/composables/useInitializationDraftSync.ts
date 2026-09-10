import { onScopeDispose, shallowRef, watch, type Ref } from 'vue'
import { getConversationInitializationDraft, initializationChangeError } from '@/api/initializationChanges'

type DraftIdentity = { id: number; revision: number; project_id: number; conversation_id: number }
type DraftSyncOptions<TDraft extends DraftIdentity> = {
  projectId: Ref<string>
  conversationId: Ref<number | null>
  running: Ref<boolean>
  onChange?: (draft: TDraft | null, previous: TDraft | null) => void
  onError?: (message: string) => void
}
type DraftSyncDependencies<TDraft> = {
  load: (projectId: string, conversationId: number, signal?: AbortSignal) => Promise<TDraft | null>
  pollMs: number
}

export function useInitializationDraftSync<TDraft extends DraftIdentity>(options: DraftSyncOptions<TDraft>, dependencies: Partial<DraftSyncDependencies<TDraft>> = {}) {
  const load = dependencies.load || getConversationInitializationDraft<TDraft>
  const pollMs = dependencies.pollMs ?? 3000
  const draft = shallowRef<TDraft | null>(null)
  let controller: AbortController | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let sequence = 0
  let disposed = false

  function cancel() {
    sequence += 1
    controller?.abort()
    controller = null
    if (timer) clearTimeout(timer)
    timer = undefined
  }
  function schedule() {
    if (timer) clearTimeout(timer)
    timer = undefined
    if (!disposed && !controller && options.running.value && options.projectId.value && options.conversationId.value) {
      timer = setTimeout(() => { void refresh(true) }, pollMs)
    }
  }
  function replace(next: TDraft | null) {
    const previous = draft.value
    draft.value = next
    options.onChange?.(next, previous)
  }
  async function refresh(quiet = false) {
    cancel()
    const projectId = options.projectId.value
    const conversationId = options.conversationId.value
    if (!projectId || !conversationId || disposed) { replace(null); return }
    const requestSequence = sequence
    const requestController = new AbortController()
    controller = requestController
    try {
      const next = await load(projectId, conversationId, requestController.signal)
      if (disposed || requestSequence !== sequence || projectId !== options.projectId.value || conversationId !== options.conversationId.value) return
      // Keep the displayed draft bound to this conversation even if an old server
      // ignores the optional latest-draft filter during a rolling upgrade.
      if (next && (String(next.project_id) !== projectId || next.conversation_id !== conversationId)) { replace(null); return }
      replace(next)
    } catch (failure: unknown) {
      if (requestSequence !== sequence || disposed) return
      const result = initializationChangeError(failure)
      if (!quiet && !result.cancelled) options.onError?.(result.message)
    } finally {
      if (requestSequence === sequence && !disposed) { controller = null; schedule() }
    }
  }

  watch(() => [options.projectId.value, options.conversationId.value] as const, () => {
    cancel()
    replace(null)
    if (options.projectId.value && options.conversationId.value) void refresh()
  }, { immediate: true, flush: 'sync' })
  watch(options.running, running => {
    if (running) schedule()
    else { if (timer) clearTimeout(timer); timer = undefined }
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { disposed = true; cancel() })
  return { draft, refresh }
}
