import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { checkProjectChatTitle } from '@/api/projectChatManagement'

export function useChatTitleValidation(title: Ref<string>, projectId: () => string,
  excludeChannelId: () => number | undefined = () => undefined,
  enabled: () => boolean = () => true) {
  const checking = ref(false), error = ref('')
  let sequence = 0, controller: AbortController | null = null
  function reset() {
    sequence += 1
    controller?.abort()
    controller = null
    checking.value = false
    error.value = ''
  }
  watch([title, projectId, excludeChannelId, enabled], reset, { flush: 'sync' })
  onScopeDispose(reset)

  async function check() {
    reset()
    if (!enabled() || !projectId()) return
    if (!title.value.trim()) { error.value = '群名称不能为空'; return }
    const request = sequence
    controller = new AbortController()
    checking.value = true
    try {
      const result = await checkProjectChatTitle(projectId(), title.value.trim(), excludeChannelId(), controller.signal)
      if (request === sequence && !result.available) error.value = '当前项目已存在同名群聊，请更换群名称'
    } catch (cause: any) {
      if (request !== sequence) return
      const detail = cause?.response?.data?.detail
      error.value = typeof detail === 'string' ? detail
        : Array.isArray(detail) ? String(detail[0]?.msg || '群名称格式不正确').replace(/^Value error, /, '')
          : '群名检测失败，请重新聚焦后移开重试'
    } finally {
      if (request === sequence) checking.value = false
    }
  }
  return { checking, error, check, reset }
}
