import { computed, nextTick, ref, shallowRef, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import api, { type ApiEnvelope } from '@/api/client'
import {
  streamAgentConversationConfirmation,
  streamAgentConversationMessage,
} from '@/api/agentStream'
import { useAppStore } from '@/stores/app'
import { useAsyncConfirmDialog } from '@/composables/useAsyncConfirmDialog'
import {
  applyAgentRuntimeEvents,
  createEmptyRuntimeTrace,
  runtimeTraceFromExtraData,
  type AgentRuntimeTrace,
  type AgentToolCallBlock,
  type ApiAgentMessage,
} from '@/types/agentRuntime'

export type HomeChatAttachment = {
  id: string
  name: string
  size: number
  type: string
}

export type HomeChatMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  generatedTaskIds?: string[]
  attachments?: HomeChatAttachment[]
  runtimeTrace?: AgentRuntimeTrace | null
}

export type HomeAgentConversation = {
  id: number
  project_id: number
  agent_id: string
  agent_name: string
  conversation_type: 'general' | 'business'
  title: string
  status: string
  created_at: string
  updated_at: string
}

function routeQueryValue(value: unknown) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function nowText() {
  const now = new Date()
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}

function firstUserSentenceTitle(content: string) {
  const userRequest = content.match(/(?:^|\n)用户请求[：:]\s*([\s\S]*)$/)?.[1]
  const source = userRequest ?? content
  const firstLine = source
    .split(/\r?\n/)
    .map(line => line.trim())
    .find(Boolean) || ''
  const normalized = firstLine.replace(/\s+/g, ' ').trim()
  if (!normalized) return '新对话'
  const firstSentence = normalized.match(/^.*?[。！？!?]|^.*?\.(?=\s|$)/)?.[0]
    || normalized
  return firstSentence.length > 300
    ? `${firstSentence.slice(0, 299).trimEnd()}…`
    : firstSentence
}

function mapAgentMessage(row: ApiAgentMessage): HomeChatMessage {
  return {
    id: String(row.id),
    role: row.role,
    content: row.content,
    runtimeTrace: runtimeTraceFromExtraData(row.extra_data),
  }
}

function createChatAttachments(files: File[]): HomeChatAttachment[] {
  return files.map(file => ({
    id: `${file.name}-${file.size}-${file.lastModified}`,
    name: file.name,
    size: file.size,
    type: file.type || 'application/octet-stream',
  }))
}

export function useHomeAgentConversations() {
  const route = useRoute()
  const router = useRouter()
  const store = useAppStore()
  const message = useMessage()
  const { confirmAsyncAction } = useAsyncConfirmDialog()

  const homeAgentConversations = ref<HomeAgentConversation[]>([])
  const homeAgentConversation = ref<HomeAgentConversation | null>(null)
  const homeConversationKeyword = ref('')
  const homeConversationListLoading = ref(false)
  const homeConversationMessagesLoading = ref(false)
  const homeConversationDeletingId = ref<number | null>(null)
  const homeQuickChatMessages = ref<HomeChatMessage[]>([])
  const homeQuickStreamingTrace = shallowRef<AgentRuntimeTrace | null>(null)
  const homeQuickViewport = ref<HTMLElement | null>(null)
  const quickCommand = ref('')
  const quickFiles = ref<File[]>([])
  const quickUploading = ref(false)
  const quickStopping = ref(false)

  let listSequence = 0
  let messageSequence = 0
  let stateRevision = 0
  let loadedProjectId = 0
  let loadedConversationId = 0
  let streamAbortController: AbortController | null = null

  const filteredHomeAgentConversations = computed(() => {
    const keyword = homeConversationKeyword.value.trim().toLowerCase()
    if (!keyword) return homeAgentConversations.value
    return homeAgentConversations.value.filter(conversation => (
      `${conversation.title} ${conversation.agent_name}`.toLowerCase().includes(keyword)
    ))
  })
  const homeQuickSession = computed(() => homeAgentConversation.value)
  const homeQuickSessionTitle = computed(
    () => homeQuickSession.value?.title || '新对话',
  )
  const homeQuickSessionTime = computed(() => {
    const session = homeQuickSession.value
    return session
      ? formatHomeConversationTime(session.updated_at || session.created_at)
      : '发送第一条消息后保存到聊天记录'
  })
  const homeQuickAgentName = computed(
    () => 'Dobby',
  )

  function formatHomeConversationTime(value: string) {
    if (!value) return '刚刚'
    const timestamp = Date.parse(value)
    if (!Number.isFinite(timestamp)) return value.replace('T', ' ').slice(0, 16)
    const date = new Date(timestamp)
    const now = new Date()
    const pad = (part: number) => String(part).padStart(2, '0')
    const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`
    const sameDay = date.toDateString() === now.toDateString()
    if (sameDay) return `今天 ${time}`
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    if (date.toDateString() === yesterday.toDateString()) return `昨天 ${time}`
    if (date.getFullYear() === now.getFullYear()) {
      return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${time}`
    }
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  }

  function syncConversationQuery(conversationId?: number) {
    if (route.path !== '/workbench') return
    const query: LocationQueryRaw = { ...route.query, mode: 'quick' }
    if (conversationId) query.conversationId = String(conversationId)
    else delete query.conversationId
    void router.replace({ path: route.path, query })
  }

  function scrollHomeQuick(smooth = false) {
    const viewport = homeQuickViewport.value
    if (!viewport) return
    viewport.scrollTo({
      top: viewport.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    })
  }

  function touchConversation(
    conversation: HomeAgentConversation,
    patch: Partial<HomeAgentConversation>,
  ) {
    const updated = { ...conversation, ...patch }
    homeAgentConversation.value = updated
    homeAgentConversations.value = [
      updated,
      ...homeAgentConversations.value.filter(item => item.id !== updated.id),
    ]
    return updated
  }

  function alignConversationTitleWithFirstMessage(
    conversation: HomeAgentConversation,
    rows: ApiAgentMessage[],
  ) {
    if (conversation.conversation_type !== 'general') return conversation
    const firstUserMessage = rows.find(row => row.role === 'user')
    if (!firstUserMessage) return conversation
    const title = firstUserSentenceTitle(firstUserMessage.content)
    if (title === conversation.title) return conversation
    const updated = { ...conversation, title }
    if (homeAgentConversation.value?.id === conversation.id) {
      homeAgentConversation.value = updated
    }
    homeAgentConversations.value = homeAgentConversations.value.map(item => (
      item.id === conversation.id ? updated : item
    ))
    return updated
  }

  async function selectHomeConversation(
    conversationId: number,
    syncRoute = true,
    clearDraft = true,
  ) {
    if (quickUploading.value) {
      message.warning('Dobby 正在处理当前消息，完成或停止后再切换会话。')
      return false
    }
    const conversation = homeAgentConversations.value.find(
      item => item.id === conversationId,
    )
    if (!conversation) {
      message.warning('该聊天记录不存在或已被删除。')
      return false
    }
    if (
      homeAgentConversation.value?.id === conversationId
      && loadedConversationId === conversationId
    ) {
      if (syncRoute) syncConversationQuery(conversationId)
      return true
    }
    if (
      clearDraft
      && homeAgentConversation.value?.id !== conversationId
      && (quickCommand.value.trim() || quickFiles.value.length)
    ) {
      quickCommand.value = ''
      quickFiles.value = []
      message.info('已切换会话，上一会话中未发送的内容已清空。')
    }

    const sequence = ++messageSequence
    homeAgentConversation.value = conversation
    homeQuickChatMessages.value = []
    homeQuickStreamingTrace.value = null
    loadedConversationId = 0
    homeConversationMessagesLoading.value = true
    if (syncRoute) syncConversationQuery(conversationId)
    try {
      const response = await api.get<ApiEnvelope<ApiAgentMessage[]>>(
        `/agent-conversations/${conversationId}/messages`,
      )
      if (sequence !== messageSequence) return false
      const rows = response.data.data
      alignConversationTitleWithFirstMessage(conversation, rows)
      homeQuickChatMessages.value = rows.map(mapAgentMessage)
      loadedConversationId = conversationId
      await nextTick()
      scrollHomeQuick()
      return true
    } catch (error: any) {
      if (sequence === messageSequence) {
        message.error(error?.response?.data?.detail || '聊天记录加载失败。')
      }
      return false
    } finally {
      if (sequence === messageSequence) homeConversationMessagesLoading.value = false
    }
  }

  function startNewHomeConversation(preserveDraft = true, syncRoute = true) {
    if (quickUploading.value) {
      message.warning('Dobby 正在处理当前消息，完成或停止后再新建会话。')
      return false
    }
    ++messageSequence
    homeAgentConversation.value = null
    homeQuickChatMessages.value = []
    homeQuickStreamingTrace.value = null
    loadedConversationId = 0
    homeConversationMessagesLoading.value = false
    if (!preserveDraft) {
      quickCommand.value = ''
      quickFiles.value = []
    }
    if (syncRoute) syncConversationQuery()
    return true
  }

  async function loadHomeAgentConversations() {
    const projectId = Number(store.currentProjectId || 0)
    const sequence = ++listSequence
    homeConversationListLoading.value = true
    if (!projectId) {
      loadedProjectId = 0
      homeConversationListLoading.value = false
      return
    }
    try {
      const response = await api.get<ApiEnvelope<HomeAgentConversation[]>>(
        `/projects/${projectId}/agent-conversations`,
        { params: { conversation_type: 'general' } },
      )
      if (sequence !== listSequence || projectId !== Number(store.currentProjectId)) return
      homeAgentConversations.value = response.data.data
      loadedProjectId = projectId
      const isQuickWorkspace = route.path === '/workbench'
        && routeQueryValue(route.query.mode) === 'quick'
      const requestedId = isQuickWorkspace
        ? Number(routeQueryValue(route.query.conversationId))
        : 0
      const requested = requestedId
        ? homeAgentConversations.value.find(item => item.id === requestedId)
        : undefined
      if (requestedId && !requested) {
        message.warning('链接中的聊天记录不存在，已为你打开新对话。')
      }
      if (requested) {
        await selectHomeConversation(
          requested.id,
          true,
          false,
        )
      } else if (isQuickWorkspace) {
        startNewHomeConversation(true, true)
      }
    } catch (error: any) {
      if (sequence === listSequence) {
        message.error(error?.response?.data?.detail || '加载主智能体会话失败。')
      }
    } finally {
      if (sequence === listSequence) homeConversationListLoading.value = false
    }
  }

  async function ensureHomeAgentConversation(content: string, projectId: number) {
    const current = homeAgentConversation.value
    if (current?.project_id === projectId) return current
    const response = await api.post<ApiEnvelope<HomeAgentConversation>>(
      `/projects/${projectId}/agent-conversations`,
      {
        conversation_type: 'general',
        title: firstUserSentenceTitle(content),
      },
    )
    const created = response.data.data
    if (projectId !== Number(store.currentProjectId)) {
      throw new Error('项目已切换，本次会话已停止显示。')
    }
    homeAgentConversation.value = created
    homeAgentConversations.value = [
      created,
      ...homeAgentConversations.value.filter(item => item.id !== created.id),
    ]
    syncConversationQuery(created.id)
    return created
  }

  async function uploadComposerFiles(files: File[]) {
    for (const file of files) await store.uploadAttachment(file, 'Dobby问答附件')
  }

  async function dispatchQuickCommand() {
    const files = [...quickFiles.value]
    const content = quickCommand.value.trim()
      || (files.length ? '请识别并分析我上传的资料' : '')
    if (
      !content
      || quickUploading.value
      || homeConversationMessagesLoading.value
    ) return false
    const projectId = Number(store.currentProjectId || 0)
    if (!projectId) {
      message.warning('请先选择项目。')
      return false
    }
    const revision = stateRevision
    quickStopping.value = false
    quickUploading.value = true
    try {
      if (files.length) await uploadComposerFiles(files)
      const conversation = await ensureHomeAgentConversation(content, projectId)
      if (revision !== stateRevision) return false
      const optimisticUser: HomeChatMessage = {
        id: `hq-u-${Date.now()}`,
        role: 'user',
        content,
        attachments: files.length ? createChatAttachments(files) : undefined,
      }
      homeQuickChatMessages.value = [...homeQuickChatMessages.value, optimisticUser]
      homeQuickStreamingTrace.value = createEmptyRuntimeTrace()
      quickCommand.value = ''
      quickFiles.value = []
      touchConversation(conversation, { status: 'running', updated_at: nowText() })
      const completion: {
        message: ApiAgentMessage | null
        runtimeStatus: string
      } = { message: null, runtimeStatus: 'running' }
      streamAbortController = new AbortController()
      await streamAgentConversationMessage(
        conversation.id,
        content,
        {
          onEvents: async runtimeEvents => {
            if (revision !== stateRevision) return
            homeQuickStreamingTrace.value = applyAgentRuntimeEvents(
              homeQuickStreamingTrace.value,
              runtimeEvents,
            )
            await nextTick()
            scrollHomeQuick()
          },
          onDone: payload => {
            completion.message = payload.message
            completion.runtimeStatus = payload.runtime_status
          },
        },
        streamAbortController.signal,
      )
      if (revision !== stateRevision) return false
      if (!completion.message) {
        throw new Error('AgentScope 已结束事件流，但没有返回最终消息。')
      }
      homeQuickChatMessages.value = [
        ...homeQuickChatMessages.value,
        mapAgentMessage(completion.message),
      ]
      loadedConversationId = conversation.id
      homeQuickStreamingTrace.value = null
      touchConversation(conversation, {
        status: completion.runtimeStatus,
        updated_at: nowText(),
      })
      store.addLog({
        id: `log${Date.now()}`,
        time: nowText(),
        operator: sessionStorage.getItem('current_user_name') || '当前用户',
        action: files.length ? '资料问答' : 'Dobby问答',
        detail: files.length
          ? `${content}；附件：${files.map(file => file.name).join('、')}`
          : content,
        level: 'info',
      })
      await nextTick()
      scrollHomeQuick(true)
      return true
    } catch (error: any) {
      if (revision !== stateRevision) return false
      homeQuickStreamingTrace.value = null
      if (homeAgentConversation.value) {
        touchConversation(homeAgentConversation.value, {
          status: 'error',
          updated_at: nowText(),
        })
      }
      message.error(
        error?.response?.data?.detail
        || error?.message
        || '主智能体处理失败，请检查 AgentScope 配置后重试。',
      )
      return false
    } finally {
      streamAbortController = null
      if (revision === stateRevision) {
        quickUploading.value = false
        quickStopping.value = false
      }
    }
  }

  async function sendHomeAgentMessage(content: string, files: File[] = []) {
    if (quickUploading.value) return false
    quickCommand.value = content
    quickFiles.value = [...files]
    return dispatchQuickCommand()
  }

  async function stopHomeAgent() {
    if (
      !homeAgentConversation.value
      || !quickUploading.value
      || quickStopping.value
    ) return
    quickStopping.value = true
    try {
      await api.post(`/agent-conversations/${homeAgentConversation.value.id}/interrupt`)
      message.info('已请求停止，正在等待智能体安全结束当前步骤。')
    } catch (error: any) {
      quickStopping.value = false
      message.error(error?.response?.data?.detail || '停止主智能体失败。')
    }
  }

  async function confirmHomeToolCall(
    replyId: string,
    toolCall: AgentToolCallBlock,
    confirmed: boolean,
  ) {
    const conversation = homeAgentConversation.value
    if (!conversation || quickUploading.value) return
    const revision = stateRevision
    quickStopping.value = false
    quickUploading.value = true
    homeQuickStreamingTrace.value = createEmptyRuntimeTrace()
    let runtimeStatus = conversation.status
    try {
      streamAbortController = new AbortController()
      await streamAgentConversationConfirmation(
        conversation.id,
        { reply_id: replyId, tool_call: toolCall, confirmed },
        {
          onAccepted: payload => {
            message.success(
              payload.message
              || (confirmed
                ? `已允许「${toolCall.name}」，智能体正在继续执行。`
                : `已拒绝「${toolCall.name}」，智能体正在处理确认结果。`),
            )
          },
          onEvents: async runtimeEvents => {
            if (revision !== stateRevision) return
            homeQuickStreamingTrace.value = applyAgentRuntimeEvents(
              homeQuickStreamingTrace.value,
              runtimeEvents,
            )
            await nextTick()
            scrollHomeQuick()
          },
          onDone: payload => {
            runtimeStatus = payload.runtime_status
          },
        },
        streamAbortController.signal,
      )
      if (revision === stateRevision) {
        const sequence = ++messageSequence
        const response = await api.get<ApiEnvelope<ApiAgentMessage[]>>(
          `/agent-conversations/${conversation.id}/messages`,
        )
        if (sequence === messageSequence) {
          const rows = response.data.data
          const titledConversation = alignConversationTitleWithFirstMessage(
            conversation,
            rows,
          )
          homeQuickChatMessages.value = rows.map(mapAgentMessage)
          loadedConversationId = conversation.id
          touchConversation(titledConversation, {
            status: runtimeStatus,
            updated_at: nowText(),
          })
          await nextTick()
          scrollHomeQuick(true)
        }
      }
    } catch (error: any) {
      if (revision === stateRevision) {
        message.error(
          error?.response?.data?.detail
          || error?.message
          || '提交人工确认失败。',
        )
      }
    } finally {
      streamAbortController = null
      if (revision === stateRevision) {
        homeQuickStreamingTrace.value = null
        quickUploading.value = false
        quickStopping.value = false
      }
    }
  }

  function deleteHomeConversation(conversationId: number) {
    if (homeConversationDeletingId.value !== null) return
    if (quickUploading.value) {
      message.warning('Dobby 正在处理当前消息，完成或停止后再删除会话。')
      return
    }
    const conversation = homeAgentConversations.value.find(
      item => item.id === conversationId,
    )
    if (!conversation) return

    confirmAsyncAction({
      title: '删除对话',
      content: `确定删除“${conversation.title}”及其全部聊天记录吗？`,
      positiveText: '删除',
      negativeText: '取消',
      loadingText: '正在删除…',
      onConfirm: () => performDeleteHomeConversation(conversation),
    })
  }

  async function performDeleteHomeConversation(conversation: HomeAgentConversation): Promise<boolean> {
    if (homeConversationDeletingId.value !== null) return false
    const conversationId = conversation.id
    homeConversationDeletingId.value = conversationId
    try {
      await api.delete<ApiEnvelope<{ id: number }>>(
        `/agent-conversations/${conversationId}`,
      )
      homeAgentConversations.value = homeAgentConversations.value.filter(
        item => item.id !== conversationId,
      )
      if (homeAgentConversation.value?.id === conversationId) {
        const nextConversation = homeAgentConversations.value[0]
        if (nextConversation) {
          homeAgentConversation.value = null
          await selectHomeConversation(nextConversation.id, true, false)
        } else {
          startNewHomeConversation(false, true)
        }
      }
      message.success('聊天记录已删除。')
      return true
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '聊天记录删除失败。')
      return false
    } finally {
      homeConversationDeletingId.value = null
    }
  }

  watch(
    () => store.currentProjectId,
    () => {
      stateRevision += 1
      listSequence += 1
      messageSequence += 1
      streamAbortController?.abort()
      streamAbortController = null
      loadedProjectId = 0
      loadedConversationId = 0
      quickUploading.value = false
      quickStopping.value = false
      homeAgentConversations.value = []
      homeAgentConversation.value = null
      homeQuickChatMessages.value = []
      homeQuickStreamingTrace.value = null
      homeConversationMessagesLoading.value = false
      homeConversationDeletingId.value = null
      homeConversationKeyword.value = ''
      void loadHomeAgentConversations()
    },
    { immediate: true },
  )

  watch(
    () => [route.path, route.query.mode, route.query.conversationId] as const,
    () => {
      if (
        route.path !== '/workbench'
        || routeQueryValue(route.query.mode) !== 'quick'
        || loadedProjectId !== Number(store.currentProjectId)
      ) return
      const requestedId = Number(routeQueryValue(route.query.conversationId))
      if (requestedId) {
        if (!homeAgentConversations.value.some(item => item.id === requestedId)) {
          message.warning('该聊天记录不存在或已被删除，已为你打开新对话。')
          startNewHomeConversation(true, true)
          return
        }
        if (homeAgentConversation.value?.id !== requestedId) {
          void selectHomeConversation(requestedId, false, true)
        }
      } else if (homeAgentConversation.value) {
        startNewHomeConversation(true, false)
      }
    },
  )

  return {
    homeAgentConversations,
    filteredHomeAgentConversations,
    homeAgentConversation,
    homeConversationKeyword,
    homeConversationListLoading,
    homeConversationMessagesLoading,
    homeConversationDeletingId,
    homeQuickChatMessages,
    homeQuickStreamingTrace,
    homeQuickViewport,
    quickCommand,
    quickFiles,
    quickUploading,
    quickStopping,
    homeQuickSession,
    homeQuickSessionTitle,
    homeQuickSessionTime,
    homeQuickAgentName,
    formatHomeConversationTime,
    loadHomeAgentConversations,
    selectHomeConversation,
    startNewHomeConversation,
    deleteHomeConversation,
    dispatchQuickCommand,
    sendHomeAgentMessage,
    stopHomeAgent,
    confirmHomeToolCall,
  }
}
