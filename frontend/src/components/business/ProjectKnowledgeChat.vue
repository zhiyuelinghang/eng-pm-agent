<template>
  <section class="project-knowledge-chat" aria-label="项目知识库智能问答">
    <aside class="conversation-rail">
      <header class="conversation-rail-head">
        <button type="button" class="new-conversation-button" :disabled="disabled || loadingHistory || answering" @click="startNewConversation()">
          <n-icon :size="17"><Plus /></n-icon>
          新对话
        </button>
      </header>

      <label class="conversation-search">
        <n-icon :size="17"><Search /></n-icon>
        <input v-model.trim="conversationKeyword" placeholder="搜索对话" aria-label="搜索知识库对话">
      </label>

      <section class="conversation-list" aria-label="知识库对话历史">
        <span class="conversation-list-label">最近对话</span>
        <div
          v-for="conversation in filteredConversations"
          :key="conversation.id"
          class="conversation-item"
          :class="{ active: conversation.id === activeConversationId }"
        >
          <button type="button" class="conversation-select" @click="selectConversation(conversation.id)">
            <span>
              <strong :title="conversation.title">{{ conversation.title }}</strong>
              <small>{{ conversationScopeLabel(conversation.scope) }}</small>
            </span>
            <time>{{ formatConversationTime(conversation.updatedAt) }}</time>
          </button>
          <button
            type="button"
            class="conversation-delete"
            :disabled="deletingConversationId !== null"
            :aria-busy="deletingConversationId === conversation.id"
            :aria-label="deletingConversationId === conversation.id ? `正在删除对话：${conversation.title}` : `删除对话：${conversation.title}`"
            :title="deletingConversationId === conversation.id ? '正在删除' : '删除对话'"
            @click.stop="confirmDeleteConversation(conversation)"
          >
            <n-icon v-if="deletingConversationId === conversation.id" class="conversation-delete-spinner" :size="16"><Loader /></n-icon>
            <n-icon v-else :size="16"><Trash /></n-icon>
          </button>
        </div>
        <div v-if="loadingHistory" class="conversation-list-empty" role="status">
          <span class="conversation-loading-robot"><n-icon :size="24"><Robot /></n-icon></span>
          <strong>正在加载对话</strong>
        </div>
        <div v-else-if="!filteredConversations.length" class="conversation-list-empty">
          <n-icon :size="26"><MessageCircle /></n-icon>
          <strong>没有匹配的对话</strong>
          <span>{{ conversationKeyword ? '调整关键词后再试。' : '发送第一条消息后才会出现在这里。' }}</span>
        </div>
      </section>

      <footer class="conversation-rail-foot">
        <n-icon :size="17"><Messages /></n-icon>
        {{ conversations.length }} 个对话
      </footer>
    </aside>

    <section class="knowledge-chat-pane">
      <header class="knowledge-chat-head">
        <div class="knowledge-assistant-heading"><strong>项目资料助手</strong><small>资料依据与项目动态，在这里一起梳理</small></div>
        <div class="knowledge-scope-picker">
          <button
            type="button"
            class="knowledge-scope-trigger"
            :class="{ active: scopePickerOpen }"
            :disabled="disabled || loadingHistory || answering"
            aria-label="选择问答范围"
            :aria-expanded="scopePickerOpen"
            @click.stop="toggleScopePicker"
          >
            <span class="knowledge-scope-trigger-icon" aria-hidden="true"><n-icon :size="16"><Database /></n-icon></span>
            <span :title="scopeTriggerLabel">{{ scopeTriggerLabel }}</span>
            <n-icon class="knowledge-scope-trigger-chevron" :class="{ open: scopePickerOpen }" :size="16"><ChevronDown /></n-icon>
          </button>
          <div v-if="scopePickerOpen" class="knowledge-scope-backdrop" aria-hidden="true" @click="closeScopePicker"></div>
          <section v-if="scopePickerOpen" class="knowledge-scope-menu" aria-label="知识库问答范围列表" @click.stop>
            <header class="knowledge-scope-menu-head">
              <span><strong>选择问答范围</strong><small>可多选；勾选目录即包含其下全部资料</small></span>
              <em>{{ pendingScopeItems.length ? `已选 ${pendingScopeItems.length} 项` : '全部资料' }}</em>
            </header>
            <button type="button" class="knowledge-scope-all" :class="{ selected: !pendingScopeItems.length }" @click="selectProjectScope">
              <span class="knowledge-scope-checkbox" :class="{ checked: !pendingScopeItems.length }" role="checkbox" :aria-checked="!pendingScopeItems.length"></span>
              <span class="knowledge-scope-node-icon"><n-icon :size="17"><Database /></n-icon></span>
              <span><strong>全部项目资料</strong><small>当前项目的全部可用资料</small></span>
            </button>
            <div class="knowledge-scope-tree" role="tree">
              <div
                v-for="row in scopePickerRows"
                :key="`${row.kind}:${row.id}`"
                class="knowledge-scope-row"
                :class="[{ selected: scopeRowCheckState(row) === 'checked' }, `is-${row.kind}`]"
                role="treeitem"
                :aria-selected="scopeRowCheckState(row) === 'checked'"
              >
                <span v-for="level in row.depth" :key="level" class="knowledge-scope-indent" aria-hidden="true"></span>
                <button
                  v-if="row.kind === 'folder'"
                  type="button"
                  class="knowledge-scope-expand"
                  :class="{ hidden: !row.hasChildren }"
                  :disabled="!row.hasChildren || scopeFolderLoadingIds.includes(row.id)"
                  :aria-label="row.expanded ? `收起${row.folder.name}` : `展开${row.folder.name}`"
                  @click="toggleScopeFolder(row.folder)"
                >
                  <n-icon v-if="scopeFolderLoadingIds.includes(row.id)" class="knowledge-scope-spinner" :size="15"><Refresh /></n-icon>
                  <n-icon v-else :size="15"><component :is="row.expanded ? ChevronDown : ChevronRight" /></n-icon>
                </button>
                <span v-else class="knowledge-scope-expand hidden" aria-hidden="true"></span>
                <button v-if="row.kind === 'folder'" type="button" class="knowledge-scope-choice" @click="toggleScopeRow(row)">
                  <span
                    class="knowledge-scope-checkbox"
                    :class="scopeRowCheckState(row)"
                    role="checkbox"
                    :aria-checked="scopeRowCheckState(row) === 'mixed' ? 'mixed' : scopeRowCheckState(row) === 'checked'"
                  ></span>
                  <span class="knowledge-scope-node-icon"><n-icon :size="17"><component :is="row.folder.isKnowledgeBase ? Database : Folder" /></n-icon></span>
                  <span class="knowledge-scope-choice-copy"><strong :title="row.folder.name">{{ row.folder.name }}</strong><small>{{ row.folder.isKnowledgeBase ? '知识库' : '目录' }} · {{ row.folder.totalCount ?? row.folder.documentCount ?? 0 }} 份资料</small></span>
                </button>
                <button v-else type="button" class="knowledge-scope-choice" @click="toggleScopeRow(row)">
                  <span
                    class="knowledge-scope-checkbox"
                    :class="scopeRowCheckState(row)"
                    role="checkbox"
                    :aria-checked="scopeRowCheckState(row) === 'checked'"
                  ></span>
                  <span class="knowledge-scope-file-icon"><DocumentTypeIcon :kind="referenceIconKind(row.file.fileName)" /></span>
                  <span class="knowledge-scope-choice-copy"><strong :title="row.file.fileName">{{ row.file.fileName }}</strong><small>文件 · {{ formatScopeFileSize(row.file.fileSize) }}</small></span>
                </button>
              </div>
              <div v-if="!scopePickerRows.length" class="knowledge-scope-tree-empty">当前项目没有可选择的知识库目录。</div>
            </div>
            <footer class="knowledge-scope-menu-foot">
              <span>{{ pendingScopeSummary }}</span>
              <div>
                <button type="button" @click="closeScopePicker">取消</button>
                <button type="button" class="primary" @click="applyScopeSelection">应用范围</button>
              </div>
            </footer>
          </section>
        </div>
      </header>

      <div ref="chatScrollRef" class="knowledge-chat-scroll" :aria-busy="answering" @scroll="trackScroll">
        <section v-if="loadingMessages" class="knowledge-chat-empty" role="status">
          <span class="knowledge-chat-empty-icon conversation-loading-robot"><n-icon :size="26"><Robot /></n-icon></span>
          <strong>正在加载聊天记录</strong>
        </section>
        <section v-else-if="!activeMessages.length && !answering" class="knowledge-chat-empty">
          <span class="knowledge-chat-empty-icon"><n-icon :size="26"><Robot /></n-icon></span>
          <strong>项目资料问答</strong>
          <p>选择资料范围，或直接输入问题。</p>
        </section>

        <template v-else>
          <article
            v-for="chatMessage in activeMessages"
            :key="chatMessage.id"
            class="knowledge-chat-message"
            :class="['is-' + chatMessage.role, { 'is-failed': chatMessage.failed }]"
          >
            <span v-if="chatMessage.role === 'assistant'" class="knowledge-message-avatar"><n-icon :size="17"><Robot /></n-icon></span>
            <div class="knowledge-message-card">
              <AgentMessageContent v-if="chatMessage.role === 'assistant' && chatMessage.runtimeTrace"
                :content="chatMessage.content" :runtime-trace="chatMessage.runtimeTrace" assistant-name="资料助手"
                :confirmation-busy="answering" :markdown-renderer="text => renderMarkdown(text, displayedMessageReferences(chatMessage))" @confirm="confirmToolCall" />
              <div v-else-if="chatMessage.role === 'assistant'" class="knowledge-markdown" v-html="renderMarkdown(chatMessage.content, displayedMessageReferences(chatMessage))"></div>
              <p v-else>{{ chatMessage.content }}</p>
              <KnowledgeReferenceList
                v-if="displayedMessageReferences(chatMessage).length && store.currentProjectId"
              :project-id="store.currentProjectId"
              :references="displayedMessageReferences(chatMessage)"
              :locating-knowledge-id="locatingKnowledgeId"
              @locate="emit('locate-reference', $event)"
              />
              <time>{{ formatMessageTime(chatMessage.createdAt) }}</time>
            </div>
            <span v-if="chatMessage.role === 'user'" class="knowledge-user-avatar"><n-icon :size="18"><User /></n-icon></span>
          </article>
        </template>

        <article v-if="answering" class="knowledge-chat-message is-assistant is-pending" :class="{ 'has-content': streamingMessage?.content }" role="status" aria-live="polite">
          <span class="knowledge-message-avatar"><n-icon :size="17"><Robot /></n-icon></span>
          <div class="knowledge-message-card">
            <AgentMessageContent :runtime-trace="streamingTrace" streaming assistant-name="资料助手"
              :starting-label="stopping ? '正在停止并保留已生成内容…' : streamStatus" :confirmation-busy="answering"
              :markdown-renderer="text => renderMarkdown(text, streamingMessage ? displayedMessageReferences(streamingMessage) : [])" />
            <div class="knowledge-wait-detail"><span>{{ stopping ? '正在停止' : '处理中' }} · {{ elapsedSeconds }} 秒</span><span v-if="idleSeconds >= 20">暂未收到新的进度，可继续等待或停止本次回答。</span></div>
            <KnowledgeReferenceList
              v-if="streamingMessage && displayedMessageReferences(streamingMessage).length && store.currentProjectId"
              :project-id="store.currentProjectId"
              :references="displayedMessageReferences(streamingMessage)"
              :locating-knowledge-id="locatingKnowledgeId"
              @locate="emit('locate-reference', $event)"
            />
          </div>
        </article>
      </div>

      <footer class="knowledge-chat-footer">
        <div v-if="catalogError || requestError" class="knowledge-chat-alert" role="alert"><span>{{ requestError || catalogError }}</span><button v-if="catalogError" type="button" @click="loadKnowledgeAgents">重新加载</button><button v-else-if="!answering" type="button" @click="recoverMessages">恢复记录</button></div>
        <button v-if="!followingBottom && answering" type="button" class="knowledge-return-latest" @click="followLatest">查看最新进度 ↓</button>
        <div class="knowledge-scope-summary">
          <span>资料范围：</span>
          <strong>{{ conversationScopeLabel(currentScope) }}</strong>
        </div>
        <form class="knowledge-composer" @submit.prevent="sendQuestion">
          <ChatComposerSurface :busy="answering">
            <textarea
              v-model.trim="question"
              class="chat-composer-input"
              rows="1"
              :disabled="disabled || loadingHistory || loadingMessages || !store.currentProjectId"
              :placeholder="scopeQuestionPlaceholder"
              @keydown.enter.exact.prevent="sendQuestion"
            ></textarea>
            <template #action>
              <button v-if="answering || recoveringRun" type="button" class="chat-composer-action is-stop" :disabled="stopping" aria-label="终止回答" @click="stopAnswer">
                <n-icon v-if="stopping" :size="17" class="conversation-delete-spinner"><Loader /></n-icon>
                <n-icon v-else :size="17"><PlayerStop /></n-icon>
                <span>{{ stopping ? '正在停止…' : '停止' }}</span>
              </button>
              <button v-else type="submit" class="chat-composer-action" :disabled="disabled || loadingHistory || loadingMessages || !store.currentProjectId || !question" aria-label="发送问题">
                <n-icon :size="17"><Send /></n-icon>
                <span>发送</span>
              </button>
            </template>
          </ChatComposerSurface>
        </form>
      </footer>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ChevronDown, ChevronRight, Database, Folder, Loader, MessageCircle, Messages, PlayerStop, Plus, Refresh, Robot, Search, Send, Trash, User } from '@vicons/tabler'
import MarkdownIt from 'markdown-it'
import DocumentTypeIcon from '@/components/business/DocumentTypeIcon.vue'
import KnowledgeReferenceList from '@/components/business/KnowledgeReferenceList.vue'
import ChatComposerSurface from '@/components/chat/ChatComposerSurface.vue'
import { useAsyncConfirmDialog } from '@/composables/useAsyncConfirmDialog'
import { fetchWeKnoraKnowledgePreviewBlob, fetchWeKnoraResourceBlob } from '@/api/weknoraAssets'
import api, { type ApiEnvelope } from '@/api/client'
import { streamAgentConversationMessage, streamAgentConversationConfirmation, type AgentStreamHandlers } from '@/api/agentStream'
import AgentMessageContent from '@/components/agent/AgentMessageContent.vue'
import { applyAgentRuntimeEvents, createEmptyRuntimeTrace, runtimeTraceFromExtraData, type AgentRuntimeTrace, type AgentToolCallBlock, type ApiAgentMessage } from '@/types/agentRuntime'
import { knowledgeAgentReferences, knowledgeAgentText } from '@/utils/knowledgeAgentPresentation'
import {
  useAppStore,
  type AttachmentRecord,
  type DocumentFolderRecord,
  type EngineeringKnowledgeConversationRecord,
  type EngineeringKnowledgeMessageRecord,
  type EngineeringKnowledgeScopeItemRecord,
} from '@/stores/app'

type KnowledgeScope =
  | { type: 'project' }
  | { type: 'knowledge_base'; knowledgeBaseId: string; knowledgeBaseName: string }
  | { type: 'folder'; folderPath: string; folderName: string; knowledgeBaseId: string }
  | { type: 'document'; documentId: string; documentName: string; knowledgeBaseId?: string }
  | { type: 'selection'; items: KnowledgeScopeItem[] }

type KnowledgeScopeItem =
  | { type: 'knowledge_base'; knowledgeBaseId: string; knowledgeBaseName: string }
  | { type: 'folder'; folderPath: string; folderName: string; knowledgeBaseId: string }
  | { type: 'document'; documentId: string; documentName: string; knowledgeBaseId?: string }

type ScopePickerRow =
  | {
      kind: 'folder'
      id: string
      depth: number
      folder: DocumentFolderRecord
      expanded: boolean
      hasChildren: boolean
    }
  | {
      kind: 'document'
      id: string
      depth: number
      file: AttachmentRecord
    }

type KnowledgeReference = {
  id: string
  knowledgeId: string
  knowledgeBaseId?: string
  chunkId?: string
  fileName: string
  title?: string
  folderPath?: string
  contentSnippet?: string
  score?: number
  chunkIndex?: number
  startAt?: number
  endAt?: number
  matchType?: string
  chunkType?: string
  knowledgeChannel?: string
  fileType?: string
  fileSize?: number
  source?: string
  knowledgeType?: string
  parseStatus?: string
  resourceHandles?: string[]
}

type KnowledgeChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  references?: KnowledgeReference[]
  failed?: boolean
  runtimeTrace?: AgentRuntimeTrace | null
}

type KnowledgeConversation = {
  id: number
  agentConversationId?: number | null
  title: string
  sessionId: string
  scope: KnowledgeScope
  messages: KnowledgeChatMessage[]
  updatedAt: string
  loaded: boolean
}

const props = defineProps<{ focusDocumentId?: string; locatingKnowledgeId?: string; disabled?: boolean }>()
const locatingKnowledgeId = computed(() => props.locatingKnowledgeId || '')
const emit = defineEmits<{
  'document-consumed': []
  'busy-change': [value: boolean]
  'ready-change': [value: boolean]
  'locate-reference': [reference: KnowledgeReference]
}>()
const store = useAppStore()
const message = useMessage()
const { confirmAsyncAction } = useAsyncConfirmDialog()
const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
const validateMarkdownLink = markdown.validateLink.bind(markdown)
markdown.validateLink = (url: string) => (
  url.startsWith('blob:') || validateMarkdownLink(url)
)

const conversations = ref<KnowledgeConversation[]>([])
const activeConversationId = ref<number | null>(null)
const draftScope = ref<KnowledgeScope>({ type: 'project' })
const conversationKeyword = ref('')
const question = ref('')
const answering = ref(false)
const recoveringRun = ref(false)
let recoveryTimer: ReturnType<typeof setTimeout> | null = null
const stopping = ref(false)
const stopRequested = ref(false)
const streamStatus = ref('正在连接资料助手…')
const streamingTrace = ref<AgentRuntimeTrace | null>(null)
const knowledgeAgentReady = ref(false)
const catalogLoading = ref(false)
const catalogError = ref('')
const requestError = ref('')
const followingBottom = ref(true)
const elapsedSeconds = ref(0)
const idleSeconds = ref(0)
let turnStartedAt = 0
let lastProgressAt = 0
let progressClock: ReturnType<typeof setInterval> | null = null
const streamingMessage = ref<KnowledgeChatMessage | null>(null)
const draftUserMessage = ref<KnowledgeChatMessage | null>(null)
let turnEpoch = 0
let lastScrollTop = 0
const streamingRawReferences = ref<Array<Record<string, unknown>>>([])
const loadingHistory = ref(false)
const loadingMessages = ref(false)
const deletingConversationId = ref<number | null>(null)
const chatScrollRef = ref<HTMLElement | null>(null)
const scopePickerOpen = ref(false)
const pendingScopeItems = ref<KnowledgeScopeItem[]>([])
const scopeExpandedFolderIds = ref<string[]>([])
const scopeFolderLoadingIds = ref<string[]>([])
let historyLoadVersion = 0
let messageLoadVersion = 0
let activeStreamController: AbortController | null = null
const resourceObjectUrls = ref<Record<string, string>>({})
const knowledgePreviewObjectUrls = ref<Record<string, string>>({})
const resourceRequests = new Map<string, Promise<void>>()
const knowledgePreviewRequests = new Map<string, Promise<void>>()
const failedResourceHandles = new Set<string>()
const failedKnowledgePreviewIds = new Set<string>()
let resourceFetchQueue: Promise<void> = Promise.resolve()

const activeConversation = computed(() => conversations.value.find(item => item.id === activeConversationId.value))
const activeMessages = computed(() => [...(activeConversation.value?.messages || []), ...(draftUserMessage.value ? [draftUserMessage.value] : [])])
const currentScope = computed<KnowledgeScope>(() => activeConversation.value?.scope || draftScope.value)
const filteredConversations = computed(() => {
  const keyword = conversationKeyword.value.toLocaleLowerCase('zh-CN')
  return [...conversations.value]
    .filter(item => !keyword || item.title.toLocaleLowerCase('zh-CN').includes(keyword))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
})
const scopeTriggerLabel = computed(() => {
  const scope = currentScope.value
  if (scope.type === 'project') return '全部'
  if (scope.type === 'knowledge_base') return `已选 ${scope.knowledgeBaseName} 知识库`
  if (scope.type === 'folder') return `已选 ${scope.folderName} 目录`
  if (scope.type === 'document') return `已选 ${scope.documentName} 文件`
  return `已选 ${scope.items.length} 项范围`
})
const pendingScopeSummary = computed(() => {
  if (!pendingScopeItems.value.length) return '将检索全部项目资料'
  if (pendingScopeItems.value.length === 1) return `将检索：${scopeItemName(pendingScopeItems.value[0])}`
  return `将同时检索 ${pendingScopeItems.value.length} 项范围`
})
const scopeQuestionPlaceholder = computed(() => {
  const scope = currentScope.value
  if (scope.type === 'document') return '围绕当前文件继续提问…'
  if (scope.type === 'folder') return '向当前目录中的资料提问…'
  if (scope.type === 'knowledge_base') return '向当前知识库提问…'
  if (scope.type === 'selection') return `向已选择的 ${scope.items.length} 项资料范围提问…`
  return '询问项目资料、任务进展，或继续刚才的话题…'
})
const scopePickerRows = computed<ScopePickerRow[]>(() => {
  const rows: ScopePickerRow[] = []
  const children = new Map<string | undefined, DocumentFolderRecord[]>()
  for (const folder of store.documentFolders) {
    const key = folder.isKnowledgeBase ? undefined : folder.parentId
    children.set(key, [...(children.get(key) || []), folder])
  }
  for (const folders of children.values()) {
    folders.sort((left, right) => left.name.localeCompare(right.name, 'zh-CN', { numeric: true }))
  }
  const filesByFolder = new Map<string, AttachmentRecord[]>()
  for (const file of store.attachments) {
    if (!file.folderId) continue
    filesByFolder.set(file.folderId, [...(filesByFolder.get(file.folderId) || []), file])
  }
  for (const files of filesByFolder.values()) {
    files.sort((left, right) => left.fileName.localeCompare(right.fileName, 'zh-CN', { numeric: true }))
  }

  const appendFolder = (folder: DocumentFolderRecord, depth: number) => {
    const childFolders = children.get(folder.id) || []
    const directFiles = filesByFolder.get(folder.id) || []
    const expanded = scopeExpandedFolderIds.value.includes(folder.id)
    rows.push({
      kind: 'folder',
      id: folder.id,
      depth,
      folder,
      expanded,
      hasChildren: childFolders.length > 0 || (folder.documentCount || 0) > 0 || directFiles.length > 0,
    })
    if (!expanded) return
    for (const child of childFolders) appendFolder(child, depth + 1)
    for (const file of directFiles) rows.push({ kind: 'document', id: file.id, depth: depth + 1, file })
  }
  for (const root of children.get(undefined) || []) appendFolder(root, 0)
  return rows
})

watch(() => store.currentProjectId, projectId => {
  turnEpoch += 1
  const previousId = activeConversation.value?.agentConversationId
  if ((answering.value || recoveringRun.value) && previousId) void api.post(`/agent-conversations/${previousId}/interrupt`).catch(() => undefined)
  activeStreamController?.abort()
  stopRecoveryPolling()
  finishTurn()
  requestError.value = ''
  void loadConversationHistory(projectId)
}, { immediate: true })

watch(() => props.focusDocumentId, documentId => {
  if (!documentId) return
  const file = store.attachments.find(item => item.id === documentId)
  if (file) startNewConversation(documentScope(file))
  emit('document-consumed')
}, { immediate: true })

watch(() => answering.value || recoveringRun.value, value => emit('busy-change', value), { immediate: true })

function conversationScope(record: EngineeringKnowledgeConversationRecord): KnowledgeScope {
  if (record.scope_type === 'selection') {
    const items = (record.scope_items || [])
      .map(scopeItemFromRecord)
      .filter((item): item is KnowledgeScopeItem => Boolean(item))
    if (items.length) return { type: 'selection', items }
  }
  if (record.scope_type === 'knowledge_base' && record.knowledge_base_id) {
    return {
      type: 'knowledge_base',
      knowledgeBaseId: record.knowledge_base_id,
      knowledgeBaseName: record.knowledge_name || '当前知识库',
    }
  }
  if (record.scope_type === 'folder' && record.knowledge_base_id && record.folder_path) {
    const folderSegments = record.folder_path.split('/').filter(Boolean)
    return {
      type: 'folder',
      knowledgeBaseId: record.knowledge_base_id,
      folderPath: record.folder_path,
      folderName: record.knowledge_name || folderSegments[folderSegments.length - 1] || '当前目录',
    }
  }
  if (record.scope_type === 'document' && record.knowledge_id) {
    return {
      type: 'document',
      documentId: record.knowledge_id,
      documentName: record.knowledge_name || '当前文件',
      knowledgeBaseId: record.knowledge_base_id || undefined,
    }
  }
  return { type: 'project' }
}

function mapConversation(record: EngineeringKnowledgeConversationRecord): KnowledgeConversation {
  return {
    id: record.id,
    agentConversationId: record.agent_conversation_id,
    title: record.title,
    sessionId: record.weknora_session_id || '',
    scope: conversationScope(record),
    messages: [],
    updatedAt: record.updated_at || record.created_at,
    loaded: false,
  }
}

function mapMessage(record: EngineeringKnowledgeMessageRecord): KnowledgeChatMessage {
  const references = mergeRawReferences(record.references || [])
  return {
    id: String(record.id),
    role: record.role,
    content: record.content,
    createdAt: record.created_at,
    references: normalizeReferences(references),
    failed: Boolean(record.failed),
  }
}

async function loadConversationHistory(projectId: string) {
  const requestVersion = ++historyLoadVersion
  emit('ready-change', false)
  releaseResourceUrls()
  messageLoadVersion += 1
  conversations.value = []
  activeConversationId.value = null
  draftScope.value = { type: 'project' }
  scopePickerOpen.value = false
  pendingScopeItems.value = []
  scopeExpandedFolderIds.value = []
  scopeFolderLoadingIds.value = []
  loadingMessages.value = false
  if (!projectId) {
    loadingHistory.value = false
    emit('ready-change', true)
    return
  }
  loadingHistory.value = true
  try {
    const records = await store.loadEngineeringKnowledgeConversations()
    if (requestVersion !== historyLoadVersion) return
    conversations.value = records.map(mapConversation)
    const first = conversations.value[0]
    activeConversationId.value = first?.id ?? null
    if (first) await loadConversationMessages(first)
  } catch (error: any) {
    if (requestVersion !== historyLoadVersion) return
    message.error(error.response?.data?.detail || error.message || '知识库对话加载失败。')
  } finally {
    if (requestVersion === historyLoadVersion) {
      loadingHistory.value = false
      emit('ready-change', true)
    }
  }
}

async function loadConversationMessages(conversation: KnowledgeConversation) {
  if (conversation.loaded) {
    void scrollToBottom()
    return
  }
  const requestVersion = ++messageLoadVersion
  if (!recoveringRun.value) loadingMessages.value = true
  try {
    const records = await store.loadEngineeringKnowledgeMessages(conversation.id)
    const agentRecords = conversation.agentConversationId
      ? (await api.get<ApiEnvelope<ApiAgentMessage[]>>(`/agent-conversations/${conversation.agentConversationId}/messages`)).data.data : []
    if (requestVersion !== messageLoadVersion) return
    const target = conversations.value.find(item => item.id === conversation.id)
    if (!target) return
    // A newly created legacy shell stores the first question. Native agent
    // history owns that question once accepted; old completed Q&A stays visible.
    target.messages = [...(agentRecords.length && !records.some(item => item.role === 'assistant') ? [] : records.map(mapMessage)), ...agentRecords.map(mapAgentMessage)]
    for (const chatMessage of target.messages) hydrateMessageResources(chatMessage)
    target.loaded = true
    const latest = [...target.messages].reverse().find(item => item.role === 'assistant')
    const recovering = ['creating', 'running', 'interrupting', 'awaiting_external_result'].includes(latest?.runtimeTrace?.status || '')
    stopRecoveryPolling()
    recoveringRun.value = recovering
    if (recovering) {
      recoveryTimer = setTimeout(() => {
        if (activeConversationId.value !== target.id || answering.value) return
        target.loaded = false
        void loadConversationMessages(target)
      }, 3000)
    } else stopping.value = false
    void scrollToBottom()
  } catch (error: any) {
    if (requestVersion !== messageLoadVersion) return
    requestError.value = error.response?.data?.detail || error.message || '聊天记录加载失败，请恢复记录后重试。'
  } finally {
    if (requestVersion === messageLoadVersion) loadingMessages.value = false
  }
}

function documentScope(file: AttachmentRecord): KnowledgeScopeItem {
  return {
    type: 'document',
    documentId: file.id,
    documentName: file.fileName,
    knowledgeBaseId: file.knowledgeBaseId,
  }
}

function knowledgeBaseScope(folder: DocumentFolderRecord): KnowledgeScopeItem {
  return {
    type: 'knowledge_base',
    knowledgeBaseId: folder.knowledgeBaseId || '',
    knowledgeBaseName: folder.name,
  }
}

function folderScope(folder: DocumentFolderRecord): KnowledgeScopeItem {
  return {
    type: 'folder',
    knowledgeBaseId: folder.knowledgeBaseId || '',
    folderPath: normalizeScopeFolderPath(folder.path),
    folderName: folder.name,
  }
}

function normalizeScopeFolderPath(value?: string) {
  return (value || '').replace(/\\/g, '/').split('/').map(item => item.trim()).filter(Boolean).join('/')
}

function scopeItemFromRecord(record: EngineeringKnowledgeScopeItemRecord): KnowledgeScopeItem | null {
  if (record.scope_type === 'knowledge_base' && record.knowledge_base_id) {
    return {
      type: 'knowledge_base',
      knowledgeBaseId: record.knowledge_base_id,
      knowledgeBaseName: record.knowledge_name || '当前知识库',
    }
  }
  if (record.scope_type === 'folder' && record.knowledge_base_id && record.folder_path) {
    const folderPath = normalizeScopeFolderPath(record.folder_path)
    const segments = folderPath.split('/').filter(Boolean)
    return {
      type: 'folder',
      knowledgeBaseId: record.knowledge_base_id,
      folderPath,
      folderName: record.knowledge_name || segments[segments.length - 1] || '当前目录',
    }
  }
  if (record.scope_type === 'document' && record.knowledge_id) {
    return {
      type: 'document',
      documentId: record.knowledge_id,
      documentName: record.knowledge_name || '当前文件',
      knowledgeBaseId: record.knowledge_base_id || undefined,
    }
  }
  return null
}

function scopeItemRecord(item: KnowledgeScopeItem): EngineeringKnowledgeScopeItemRecord {
  return {
    scope_type: item.type,
    knowledge_id: item.type === 'document' ? item.documentId : undefined,
    knowledge_name: scopeItemName(item),
    knowledge_base_id: item.knowledgeBaseId,
    folder_path: item.type === 'folder' ? item.folderPath : undefined,
  }
}

function scopeItems(scope: KnowledgeScope): KnowledgeScopeItem[] {
  if (scope.type === 'project') return []
  if (scope.type === 'selection') return scope.items.map(item => ({ ...item }))
  return [{ ...scope }]
}

function scopeItemName(item: KnowledgeScopeItem) {
  if (item.type === 'knowledge_base') return item.knowledgeBaseName
  if (item.type === 'folder') return item.folderName
  return item.documentName
}

function scopeItemKey(item: KnowledgeScopeItem) {
  if (item.type === 'knowledge_base') return `knowledge_base:${item.knowledgeBaseId}`
  if (item.type === 'folder') return `folder:${item.knowledgeBaseId}:${normalizeScopeFolderPath(item.folderPath)}`
  return `document:${item.documentId}`
}

function scopeItemForRow(row: ScopePickerRow): KnowledgeScopeItem {
  if (row.kind === 'document') return documentScope(row.file)
  return row.folder.isKnowledgeBase ? knowledgeBaseScope(row.folder) : folderScope(row.folder)
}

function scopeItemFolderPath(item: KnowledgeScopeItem) {
  if (item.type === 'folder') return normalizeScopeFolderPath(item.folderPath)
  if (item.type !== 'document') return ''
  return normalizeScopeFolderPath(store.attachments.find(file => file.id === item.documentId)?.folderPath)
}

function scopeItemContains(parent: KnowledgeScopeItem, child: KnowledgeScopeItem) {
  if (scopeItemKey(parent) === scopeItemKey(child)) return true
  if (!parent.knowledgeBaseId || parent.knowledgeBaseId !== child.knowledgeBaseId) return false
  if (parent.type === 'knowledge_base') return true
  if (parent.type !== 'folder') return false
  const parentPath = normalizeScopeFolderPath(parent.folderPath)
  const childPath = scopeItemFolderPath(child)
  return Boolean(childPath && (childPath === parentPath || childPath.startsWith(`${parentPath}/`)))
}

function scopeRowCheckState(row: ScopePickerRow): 'checked' | 'mixed' | 'unchecked' {
  const item = scopeItemForRow(row)
  if (pendingScopeItems.value.some(selected => scopeItemKey(selected) === scopeItemKey(item))) return 'checked'
  if (row.kind === 'folder' && pendingScopeItems.value.some(selected => scopeItemContains(item, selected))) return 'mixed'
  return 'unchecked'
}

function toggleScopeRow(row: ScopePickerRow) {
  const item = scopeItemForRow(row)
  const itemKey = scopeItemKey(item)
  if (pendingScopeItems.value.some(selected => scopeItemKey(selected) === itemKey)) {
    pendingScopeItems.value = pendingScopeItems.value.filter(selected => scopeItemKey(selected) !== itemKey)
    return
  }
  pendingScopeItems.value = pendingScopeItems.value.filter(selected => (
    !scopeItemContains(selected, item) && !scopeItemContains(item, selected)
  ))
  pendingScopeItems.value = [...pendingScopeItems.value, item]
}

function toggleScopePicker() {
  if (scopePickerOpen.value) {
    closeScopePicker()
    return
  }
  pendingScopeItems.value = scopeItems(currentScope.value)
  scopePickerOpen.value = true
}

function closeScopePicker() {
  scopePickerOpen.value = false
  pendingScopeItems.value = []
}

async function toggleScopeFolder(folder: DocumentFolderRecord) {
  const expanded = scopeExpandedFolderIds.value.includes(folder.id)
  if (expanded) {
    scopeExpandedFolderIds.value = scopeExpandedFolderIds.value.filter(item => item !== folder.id)
    return
  }
  scopeExpandedFolderIds.value = [...scopeExpandedFolderIds.value, folder.id]
  if (!(folder.documentCount || 0) || scopeFolderLoadingIds.value.includes(folder.id)) return
  scopeFolderLoadingIds.value = [...scopeFolderLoadingIds.value, folder.id]
  try {
    await store.loadEngineeringDocumentFolder(folder.id)
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '目录文件加载失败。')
  } finally {
    scopeFolderLoadingIds.value = scopeFolderLoadingIds.value.filter(item => item !== folder.id)
  }
}

function selectProjectScope() {
  pendingScopeItems.value = []
}

function applyScopeSelection() {
  const items = pendingScopeItems.value.map(item => ({ ...item }))
  const scope: KnowledgeScope = !items.length
    ? { type: 'project' }
    : items.length === 1
      ? items[0]
      : { type: 'selection', items }
  startNewConversation(scope)
  closeScopePicker()
}

function formatScopeFileSize(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '未知大小'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / 1024 / 1024).toFixed(value >= 10 * 1024 * 1024 ? 0 : 1)} MB`
}

function startNewConversation(scope: KnowledgeScope = { type: 'project' }) {
  if (answering.value || recoveringRun.value) {
    message.warning('请先终止当前回答，再新建对话。')
    return
  }
  messageLoadVersion += 1
  loadingMessages.value = false
  activeConversationId.value = null
  requestError.value = ''
  followingBottom.value = true
  draftScope.value = scope
  question.value = ''
  void scrollToBottom()
}

function selectConversation(conversationId: number) {
  if ((answering.value || recoveringRun.value) && conversationId !== activeConversationId.value) {
    message.warning('请先终止当前回答，再切换对话。')
    return
  }
  const conversation = conversations.value.find(item => item.id === conversationId)
  if (!conversation) return
  activeConversationId.value = conversationId
  draftScope.value = { type: 'project' }
  question.value = ''
  void loadConversationMessages(conversation)
}

function confirmDeleteConversation(conversation: KnowledgeConversation) {
  if ((answering.value || recoveringRun.value) && conversation.id === activeConversationId.value) {
    message.warning('请先终止当前回答，再删除该对话。')
    return
  }
  confirmAsyncAction({
    title: '删除对话',
    content: `确定删除“${conversation.title}”及其全部聊天记录吗？`,
    positiveText: '删除',
    negativeText: '取消',
    loadingText: '正在删除…',
    onConfirm: () => deleteConversation(conversation),
  })
}

async function deleteConversation(conversation: KnowledgeConversation): Promise<boolean> {
  if (deletingConversationId.value !== null) return false
  deletingConversationId.value = conversation.id
  try {
    await store.deleteEngineeringKnowledgeConversation(conversation.id)
    conversations.value = conversations.value.filter(item => item.id !== conversation.id)
    if (activeConversationId.value === conversation.id) {
      const next = conversations.value[0]
      activeConversationId.value = next?.id ?? null
      draftScope.value = { type: 'project' }
      if (next) await loadConversationMessages(next)
    }
    message.success('对话及聊天记录已删除。')
    return true
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '删除对话失败。')
    return false
  } finally {
    deletingConversationId.value = null
  }
}

function conversationScopeLabel(scope: KnowledgeScope) {
  if (scope.type === 'project') return '全部'
  if (scope.type === 'knowledge_base') return `知识库 · ${scope.knowledgeBaseName}`
  if (scope.type === 'folder') return `目录 · ${scope.folderName}`
  if (scope.type === 'document') return `文件 · ${scope.documentName}`
  return `已选 ${scope.items.length} 项范围`
}

function createId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`
}

function createChatMessage(role: KnowledgeChatMessage['role'], content: string, references?: KnowledgeReference[], failed = false): KnowledgeChatMessage {
  return {
    id: createId(),
    role,
    content,
    createdAt: new Date().toISOString(),
    references,
    failed,
  }
}

function normalizeReferences(items?: Array<Record<string, unknown>>): KnowledgeReference[] {
  const result = new Map<string, KnowledgeReference>()
  for (const item of mergeRawReferences(items || [])) {
    const nestedFile = item.file_info && typeof item.file_info === 'object'
      ? item.file_info as Record<string, unknown>
      : {}
    const knowledgeId = textValue(item.knowledge_id, item.knowledgeId)
    const knowledgeBaseId = textValue(item.knowledge_base_id, item.knowledgeBaseId)
    const chunkId = textValue(item.chunk_id, item.id)
    const title = textValue(item.knowledge_title, item.title)
    const fileName = textValue(
      item.knowledge_filename,
      item.file_name,
      item.filename,
      nestedFile.file_name,
      title,
    ) || '来源资料'
    const folderPath = textValue(item.folder_path, item.folderPath, item.path, nestedFile.folder_path)
    const contentSnippet = textValue(item.content, item.content_snippet, item.snippet)
    const resourceHandles = extractResourceHandles(contentSnippet)
    const key = knowledgeId
      ? `knowledge:${knowledgeId}`
      : `file:${knowledgeBaseId}:${fileName.toLocaleLowerCase('zh-CN')}:${folderPath}`
    result.set(key, {
      id: key,
      knowledgeId,
      knowledgeBaseId: knowledgeBaseId || undefined,
      chunkId: chunkId || undefined,
      fileName,
      title: title || undefined,
      folderPath: folderPath || undefined,
      contentSnippet: contentSnippet || undefined,
      score: numberValue(item.score),
      chunkIndex: numberValue(item.chunk_index),
      startAt: numberValue(item.start_at),
      endAt: numberValue(item.end_at),
      matchType: textValue(item.match_type) || undefined,
      chunkType: textValue(item.chunk_type) || undefined,
      knowledgeChannel: textValue(item.knowledge_channel, item.channel) || undefined,
      fileType: textValue(item.file_type, nestedFile.file_type) || undefined,
      fileSize: numberValue(item.file_size, nestedFile.file_size),
      source: textValue(item.knowledge_source, item.source, nestedFile.source) || undefined,
      knowledgeType: textValue(item.knowledge_type, item.type) || undefined,
      parseStatus: textValue(item.parse_status, nestedFile.parse_status) || undefined,
      resourceHandles: resourceHandles.length ? resourceHandles : undefined,
    })
  }
  return [...result.values()].sort((left, right) => (right.score || 0) - (left.score || 0))
}

function decodeCitationValue(value: string) {
  return value
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .trim()
}

function citationAttribute(attributes: string, name: 'doc' | 'chunk_id' | 'kb_id') {
  const match = attributes.match(new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`, 'i'))
  return decodeCitationValue(match?.[1] || match?.[2] || '')
}

type KnowledgeCitation = {
  fileKey: string
  chunkId: string
  knowledgeBaseId: string
}

function referenceFileKey(value: string) {
  return value
    .replace(/\\/g, '/')
    .split('/')
    .filter(Boolean)
    .pop()
    ?.trim()
    .toLocaleLowerCase('zh-CN') || ''
}

function extractKnowledgeCitations(content: string): KnowledgeCitation[] {
  const citations: KnowledgeCitation[] = []
  for (const match of content.matchAll(/<kb\b([^>]*)\/?>/gi)) {
    const attributes = match[1] || ''
    const fileKey = referenceFileKey(citationAttribute(attributes, 'doc'))
    if (!fileKey) continue
    const citation = {
      fileKey,
      chunkId: citationAttribute(attributes, 'chunk_id'),
      knowledgeBaseId: citationAttribute(attributes, 'kb_id'),
    }
    if (!citations.some(item => (
      item.fileKey === citation.fileKey
      && item.chunkId === citation.chunkId
      && item.knowledgeBaseId === citation.knowledgeBaseId
    ))) citations.push(citation)
  }
  return citations
}

function referenceMatchesCitation(
  fileName: string,
  chunkId: string,
  knowledgeBaseId: string,
  citation: KnowledgeCitation,
) {
  if (citation.chunkId && chunkId && citation.chunkId === chunkId) return true
  if (referenceFileKey(fileName) !== citation.fileKey) return false
  return !citation.knowledgeBaseId
    || !knowledgeBaseId
    || citation.knowledgeBaseId === knowledgeBaseId
}

function contentMentionsReference(content: string, fileName: string) {
  const fileKey = referenceFileKey(fileName)
  return Boolean(fileKey && content.toLocaleLowerCase('zh-CN').includes(fileKey))
}

function extractResourceHandles(content: string) {
  return [...new Set(
    [...content.matchAll(/resource:\/\/([A-Za-z0-9_-]+)/g)]
      .map(match => match[1])
      .filter(Boolean),
  )]
}

function isImageFileName(fileName: string) {
  return /\.(?:avif|bmp|gif|jpe?g|png|svg|webp)$/i.test(referenceFileKey(fileName))
}

function isImageReference(reference: KnowledgeReference) {
  return isImageFileName(reference.fileName)
    || /^image(?:\/|$)/i.test(reference.fileType || '')
}

function citedReferences(
  content: string,
  references: KnowledgeReference[] = [],
) {
  const citations = extractKnowledgeCitations(content)
  if (!citations.length) {
    return references.filter(reference => contentMentionsReference(content, reference.fileName))
  }
  const matched: KnowledgeReference[] = []
  for (const citation of citations) {
    for (const reference of references) {
      if (matched.some(item => item.id === reference.id)) continue
      if (referenceMatchesCitation(
        reference.fileName,
        reference.chunkId || '',
        reference.knowledgeBaseId || '',
        citation,
      )) matched.push(reference)
    }
  }
  return matched
}

function displayedMessageReferences(chatMessage: KnowledgeChatMessage) {
  if (chatMessage.runtimeTrace) return chatMessage.references || []
  return citedReferences(chatMessage.content, chatMessage.references || [])
}

function referenceImageUrl(reference: KnowledgeReference) {
  const previewUrl = knowledgePreviewObjectUrls.value[reference.knowledgeId]
  if (previewUrl) return previewUrl
  for (const handle of reference.resourceHandles || []) {
    const resourceUrl = resourceObjectUrls.value[handle]
    if (resourceUrl) return resourceUrl
  }
  return ''
}

function referenceImageLoadFailed(reference: KnowledgeReference) {
  const projectId = store.currentProjectId
  if (!projectId) return false
  const previewUnavailable = !reference.knowledgeId
    || failedKnowledgePreviewIds.has(`${projectId}:${reference.knowledgeId}`)
  const resourceUnavailable = !reference.resourceHandles?.length
    || reference.resourceHandles.every(handle => failedResourceHandles.has(`${projectId}:${handle}`))
  return previewUnavailable && resourceUnavailable
}

function citedRawReferences(
  content: string,
  references: Array<Record<string, unknown>> = [],
) {
  const citations = extractKnowledgeCitations(content)
  if (!citations.length) {
    return mergeRawReferences(references).filter(reference => (
      contentMentionsReference(content, rawReferenceFilename(reference))
    ))
  }
  return mergeRawReferences(references).filter(reference => citations.some(citation => referenceMatchesCitation(
    rawReferenceFilename(reference),
    textValue(reference.chunk_id, reference.id),
    textValue(reference.knowledge_base_id, reference.knowledgeBaseId),
    citation,
  )))
}

function rawReferenceFilename(item: Record<string, unknown>) {
  const nestedFile = item.file_info && typeof item.file_info === 'object'
    ? item.file_info as Record<string, unknown>
    : {}
  return textValue(
    item.knowledge_filename,
    item.filename,
    item.file_name,
    nestedFile.file_name,
    item.knowledge_title,
    item.title,
  )
}

function mergeRawReferences(...groups: Array<Array<Record<string, unknown>>>): Array<Record<string, unknown>> {
  const merged: Array<Record<string, unknown>> = []
  for (const group of groups) {
    for (const rawItem of group) {
      const item = { ...rawItem }
      const chunkId = textValue(item.chunk_id, item.id)
      const knowledgeId = textValue(item.knowledge_id, item.knowledgeId)
      const knowledgeBaseId = textValue(item.knowledge_base_id, item.knowledgeBaseId)
      const filename = rawReferenceFilename(item).toLocaleLowerCase('zh-CN')
      const duplicate = merged.find(existing => {
        const existingChunkId = textValue(existing.chunk_id, existing.id)
        const existingKnowledgeId = textValue(existing.knowledge_id, existing.knowledgeId)
        const existingKnowledgeBaseId = textValue(existing.knowledge_base_id, existing.knowledgeBaseId)
        const existingFilename = rawReferenceFilename(existing).toLocaleLowerCase('zh-CN')
        return Boolean(chunkId && existingChunkId && chunkId === existingChunkId)
          || Boolean(knowledgeId && existingKnowledgeId && knowledgeId === existingKnowledgeId)
          || Boolean(
            filename
            && existingFilename
            && filename === existingFilename
            && (!knowledgeBaseId || !existingKnowledgeBaseId || knowledgeBaseId === existingKnowledgeBaseId),
          )
      })
      if (!duplicate) {
        merged.push(item)
        continue
      }
      for (const [key, value] of Object.entries(item)) {
        if (value !== null && value !== undefined && value !== '') duplicate[key] = value
      }
    }
  }
  return merged
}

function textValue(...values: unknown[]) {
  for (const value of values) if (typeof value === 'string' && value.trim()) return value.trim()
  return ''
}

function numberValue(...values: unknown[]) {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue
    const parsed = typeof value === 'number' ? value : Number(value)
    if (Number.isFinite(parsed) && parsed >= 0) return parsed
  }
  return undefined
}


function mapAgentMessage(record: ApiAgentMessage): KnowledgeChatMessage {
  const trace = runtimeTraceFromExtraData(record.extra_data)
  return { id: 'agent-' + record.id, role: record.role, content: record.content,
    createdAt: record.created_at, runtimeTrace: trace,
    references: normalizeReferences(knowledgeAgentReferences(trace)) }
}

async function loadKnowledgeAgents() {
  catalogLoading.value = true
  catalogError.value = ''
  knowledgeAgentReady.value = false
  try {
    const response = await api.get<ApiEnvelope<{ knowledge_assistant: { enabled: boolean; model_ready: boolean; project_knowledge_enabled: boolean } | null }>>('/agents/catalog')
    const agent = response.data.data.knowledge_assistant
    knowledgeAgentReady.value = Boolean(agent?.enabled && agent.model_ready && agent.project_knowledge_enabled)
    if (!agent?.enabled) catalogError.value = '资料助手尚未分配或已停用，请在智能体管理端「平台设置 → 资料助手」中配置。'
    else if (!knowledgeAgentReady.value) catalogError.value = '资料助手配置不完整，请检查固定模型和「启用项目资料查询」。'
  } catch (error: any) {
    catalogError.value = error.response?.data?.detail || '资料助手目录加载失败，请重试。'
  } finally { catalogLoading.value = false }
}
void loadKnowledgeAgents()

function scopeDisplayName(scope: KnowledgeScope) {
  if (scope.type === 'knowledge_base') return scope.knowledgeBaseName
  if (scope.type === 'folder') return scope.folderName
  if (scope.type === 'document') return scope.documentName
  if (scope.type === 'selection') return `${scope.items.length} 项范围`
  return ''
}

function beginTurn() {
  answering.value = true
  stopping.value = false
  stopRequested.value = false
  requestError.value = ''
  followingBottom.value = true
  elapsedSeconds.value = idleSeconds.value = 0
  turnStartedAt = lastProgressAt = Date.now()
  streamStatus.value = '正在连接资料助手…'
  streamingTrace.value = createEmptyRuntimeTrace()
  streamingMessage.value = createChatMessage('assistant', '', [])
  streamingRawReferences.value = []
  activeStreamController = new AbortController()
  progressClock = setInterval(() => {
    elapsedSeconds.value = Math.floor((Date.now() - turnStartedAt) / 1000)
    idleSeconds.value = Math.floor((Date.now() - lastProgressAt) / 1000)
  }, 1000)
}
function finishTurn() {
  if (progressClock) clearInterval(progressClock)
  progressClock = null
  answering.value = stopping.value = false
  activeStreamController = null
  streamingTrace.value = null
  streamingMessage.value = null
  streamingRawReferences.value = []
  draftUserMessage.value = null
  void scrollToBottom()
}
function upsertMessage(conversation: KnowledgeConversation, incoming: KnowledgeChatMessage) {
  const index = conversation.messages.findIndex(item => item.id === incoming.id)
  if (index >= 0) conversation.messages.splice(index, 1, incoming)
  else conversation.messages.push(incoming)
  hydrateMessageResources(incoming)
}
function agentHandlers(conversation: KnowledgeConversation, completed: { done: boolean; accepted: boolean }, optimisticId?: string): AgentStreamHandlers {
  const epoch = turnEpoch
  return {
    onAccepted: payload => {
      if (epoch !== turnEpoch) return
      completed.accepted = true
      lastProgressAt = Date.now()
      streamStatus.value = '资料助手已接收，正在理解问题…'
      if (payload.user_message) {
        if (!conversation.messages.some(item => item.role === 'assistant' || item.id.startsWith('agent-'))) conversation.messages = []
        if (optimisticId) conversation.messages = conversation.messages.filter(item => item.id !== optimisticId)
        upsertMessage(conversation, mapAgentMessage(payload.user_message))
      }
    },
    onEvents: events => {
      if (epoch !== turnEpoch) return
      lastProgressAt = Date.now()
      streamingTrace.value = applyAgentRuntimeEvents(streamingTrace.value, events)
      if (streamingMessage.value) {
        streamingMessage.value.runtimeTrace = streamingTrace.value
        streamingMessage.value.content = knowledgeAgentText(streamingTrace.value)
        streamingMessage.value.references = normalizeReferences(knowledgeAgentReferences(streamingTrace.value))
        hydrateMessageResources(streamingMessage.value)
      }
      void scrollToBottom()
    },
    onDone: payload => {
      if (epoch !== turnEpoch) return
      completed.done = true
      if (payload.message) upsertMessage(conversation, mapAgentMessage(payload.message))
      else if (streamingTrace.value?.messages.length) {
        upsertMessage(conversation, { ...streamingMessage.value!, runtimeTrace: { ...streamingTrace.value, status: payload.runtime_status } })
      }
      conversation.updatedAt = new Date().toISOString()
    },
  }
}
function keepPartial(conversation: KnowledgeConversation, detail: string) {
  requestError.value = detail
  if (streamingTrace.value?.messages.length && streamingMessage.value) {
    upsertMessage(conversation, { ...streamingMessage.value,
      runtimeTrace: { ...streamingTrace.value, status: stopRequested.value ? 'interrupted' : 'error' } })
  }
}
async function recoverMessages() {
  const conversation = activeConversation.value
  if (!conversation || answering.value) return
  conversation.loaded = false
  requestError.value = ''
  await loadConversationMessages(conversation)
}
function stopRecoveryPolling() {
  if (recoveryTimer) clearTimeout(recoveryTimer)
  recoveryTimer = null
  recoveringRun.value = false
}
async function sendQuestion() {
  const content = question.value.trim()
  if (props.disabled || loadingHistory.value || loadingMessages.value || !content || answering.value || recoveringRun.value || !store.currentProjectId) return
  if (!knowledgeAgentReady.value && !activeConversation.value?.agentConversationId) {
    requestError.value = catalogError.value || '正在检查资料助手配置，请稍候。'
    return
  }
  const projectId = store.currentProjectId
  const epoch = ++turnEpoch
  let conversation = activeConversation.value
  const completed = { done: false, accepted: false }
  let optimisticId = ''
  question.value = ''
  beginTurn()
  draftUserMessage.value = createChatMessage('user', content)
  void scrollToBottom()
  try {
    if (!conversation) {
      streamStatus.value = '正在建立项目对话…'
      const scope = draftScope.value
      const created = await store.createEngineeringKnowledgeConversation({
        title: scope.type === 'project' ? content.slice(0, 60) : `${scopeDisplayName(scope)} · ${content.slice(0, 24)}`,
        scopeType: scope.type,
        knowledgeId: scope.type === 'document' ? scope.documentId : undefined,
        knowledgeName: ['knowledge_base', 'folder', 'document'].includes(scope.type) ? scopeDisplayName(scope) : undefined,
        knowledgeBaseId: scope.type === 'project' || scope.type === 'selection' ? undefined : scope.knowledgeBaseId,
        folderPath: scope.type === 'folder' ? scope.folderPath : undefined,
        scopeItems: scope.type === 'selection' ? scope.items.map(scopeItemRecord) : undefined, firstMessage: content,
      })
      if (epoch !== turnEpoch) return
      conversations.value.unshift(mapConversation(created.conversation))
      conversation = conversations.value[0]!
      conversation.messages = created.messages.map(mapMessage)
      optimisticId = conversation.messages[0]?.id || ''
      conversation.loaded = true
      activeConversationId.value = conversation.id
    } else {
      const optimistic = createChatMessage('user', content)
      optimisticId = optimistic.id
      conversation.messages.push(optimistic)
    }
    draftUserMessage.value = null
    void scrollToBottom()
    if (stopRequested.value) return
    if (!conversation.agentConversationId) {
      const linked = await api.post<ApiEnvelope<{ id: number }>>(
        `/projects/${projectId}/engineering-knowledge-conversations/${conversation.id}/agent`,
        {},
      )
      if (epoch !== turnEpoch) return
      conversation.agentConversationId = linked.data.data.id
    }
    if (stopRequested.value) return
    streamStatus.value = '正在连接资料助手…'
    await streamAgentConversationMessage(conversation.agentConversationId!, content,
      agentHandlers(conversation, completed, optimisticId), activeStreamController!.signal)
    if (!completed.done) throw new Error('连接已中断，尚未确认处理结果。请先恢复记录，避免重复提交。')
  } catch (error: any) {
    if (epoch !== turnEpoch) return
    const detail = error.response?.data?.detail || error.message || '资料助手暂时无法回答，请稍后重试。'
    if (!completed.accepted && !question.value) question.value = content
    if (conversation) keepPartial(conversation, detail)
    else requestError.value = detail
  } finally {
    if (epoch === turnEpoch) finishTurn()
  }
}

async function confirmToolCall(replyId: string, toolCall: AgentToolCallBlock, confirmed: boolean) {
  const conversation = activeConversation.value
  if (!conversation?.agentConversationId || answering.value) return
  const completed = { done: false, accepted: false }
  const epoch = ++turnEpoch
  beginTurn()
  streamStatus.value = confirmed ? '正在继续处理…' : '正在取消这项操作…'
  try {
    await streamAgentConversationConfirmation(conversation.agentConversationId,
      { reply_id: replyId, tool_call: toolCall, confirmed },
      agentHandlers(conversation, completed), activeStreamController!.signal)
    if (!completed.done) throw new Error('连接已中断，请恢复记录确认操作结果。')
    if (epoch !== turnEpoch) return
    conversation.loaded = false
    await loadConversationMessages(conversation)
  } catch (error: any) {
    if (epoch !== turnEpoch) return
    keepPartial(conversation, error.response?.data?.detail || error.message || '操作未完成，请恢复记录。')
  } finally { if (epoch === turnEpoch) finishTurn() }
}
async function stopAnswer() {
  if ((!answering.value && !recoveringRun.value) || stopping.value) return
  stopRequested.value = stopping.value = true
  const id = activeConversation.value?.agentConversationId
  if (!id) return
  try {
    await api.post(`/agent-conversations/${id}/interrupt`)
    // Keep listening so the server can persist and return the interrupted turn.
    streamStatus.value = '正在停止并保留已生成内容…'
  } catch (error: any) {
    stopRequested.value = stopping.value = false
    requestError.value = error.response?.data?.detail || '停止请求未成功，请重试。'
  }
}
function trackScroll() {
  const el = chatScrollRef.value
  if (!el) return
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 100) followingBottom.value = true
  else if (el.scrollTop < lastScrollTop - 2) followingBottom.value = false
  lastScrollTop = el.scrollTop
}
function followLatest() {
  followingBottom.value = true
  void scrollToBottom()
}
async function scrollToBottom() {
  await nextTick()
  if (followingBottom.value && chatScrollRef.value) chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
}

function formatConversationTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  if (date.toDateString() === now.toDateString()) return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function formatMessageTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function normalizeMarkdownImageAlt(value: string) {
  return value
    .replace(/[\r\n]+/g, ' ')
    .replace(/[*_`~#[\]<>]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120) || '知识库原图'
}

function renderInlineKnowledgeImage(reference: KnowledgeReference, index: number) {
  const fileName = normalizeMarkdownImageAlt(reference.fileName)
  const escapedFileName = markdown.utils.escapeHtml(fileName)
  const imageUrl = referenceImageUrl(reference)
  const imageContent = imageUrl
    ? `<img src="${markdown.utils.escapeHtml(imageUrl)}" alt="${escapedFileName}" loading="lazy">`
    : `<span class="knowledge-inline-image-state${referenceImageLoadFailed(reference) ? ' is-failed' : ''}">${referenceImageLoadFailed(reference) ? '图片加载失败' : '图片加载中…'}</span>`
  return `<figure class="knowledge-inline-image"><div class="knowledge-inline-image-frame">${imageContent}</div><figcaption><span>图片 ${index + 1}</span><strong title="${escapedFileName}">${escapedFileName}</strong></figcaption></figure>`
}

function renderMarkdown(content: string, references: KnowledgeReference[] = []) {
  const projectId = store.currentProjectId
  const inlineCitations: string[] = []
  const imageReferences = references.filter(isImageReference)
  const inlineImages: KnowledgeReference[] = []
  let resolved = content
    .replace(/<kb\b[^>]*$/i, '')
    .replace(/<kb\b([^>]*)\/?>/gi, (_original, attributes: string) => {
      const citation = {
        fileKey: referenceFileKey(citationAttribute(attributes, 'doc')),
        chunkId: citationAttribute(attributes, 'chunk_id'),
        knowledgeBaseId: citationAttribute(attributes, 'kb_id'),
      }
      const reference = references.find(item => referenceMatchesCitation(
        item.fileName,
        item.chunkId || '',
        item.knowledgeBaseId || '',
        citation,
      ))
      if (!reference) return ''
      if (isImageReference(reference)) {
        if (inlineImages.some(item => item.id === reference.id)) return ''
        const token = `DOBBYKBIMAGE${inlineImages.length}TOKEN`
        inlineImages.push(reference)
        return `\n\n${token}\n\n`
      }
      const token = `DOBBYKBREFERENCE${inlineCitations.length}TOKEN`
      inlineCitations.push(reference.fileName)
      return token
    })
  resolved = resolved.replace(
    /!\[([^\]]*)\]\(resource:\/\/([A-Za-z0-9_-]+)\)/g,
    (_original, alt: string, handle: string) => {
      const imageReference = imageReferences.find(reference => (
        reference.resourceHandles?.includes(handle)
        || referenceFileKey(reference.fileName) === referenceFileKey(alt)
      ))
      if (imageReference && inlineImages.some(reference => reference.id === imageReference.id)) return ''
      const url = resourceObjectUrls.value[handle]
      if (url) return `![${normalizeMarkdownImageAlt(alt)}](${url})`
      const failed = projectId && failedResourceHandles.has(`${projectId}:${handle}`)
      return `*${normalizeMarkdownImageAlt(alt)}${failed ? '暂时无法加载' : '正在加载…'}*`
    },
  )
  resolved = resolved.replace(
    /(\]\()resource:\/\/([A-Za-z0-9_-]+)(\))/g,
    (original, prefix: string, handle: string, suffix: string) => {
      const url = resourceObjectUrls.value[handle]
      return url ? `${prefix}${url}${suffix}` : original
    },
  )
  let rendered = markdown.render(resolved)
  inlineCitations.forEach((filename, index) => {
    const escapedFilename = markdown.utils.escapeHtml(filename)
    rendered = rendered
      .split(`DOBBYKBREFERENCE${index}TOKEN`)
      .join(`<span class="knowledge-inline-citation" title="引用资料：${escapedFilename}">${escapedFilename}</span>`)
  })
  inlineImages.forEach((reference, index) => {
    const token = `DOBBYKBIMAGE${index}TOKEN`
    const imageHtml = renderInlineKnowledgeImage(reference, index)
    rendered = rendered
      .split(`<p>${token}</p>`)
      .join(imageHtml)
      .split(token)
      .join(imageHtml)
  })
  return rendered
}

async function hydrateResourceHandles(content: string) {
  const projectId = store.currentProjectId
  if (!projectId) return
  const handles = [...content.matchAll(/\]\(resource:\/\/([A-Za-z0-9_-]+)\)/g)].map(match => match[1])
  for (const handle of new Set(handles)) {
    const requestKey = `${projectId}:${handle}`
    if (!handle || resourceObjectUrls.value[handle] || failedResourceHandles.has(requestKey)) continue
    const pending = resourceRequests.get(requestKey)
    if (pending) continue
    const request = resourceFetchQueue.then(async () => {
      try {
        if (projectId !== store.currentProjectId) return
        const blob = await fetchWeKnoraResourceBlob(projectId, handle)
        if (projectId !== store.currentProjectId) return
        const url = URL.createObjectURL(blob)
        resourceObjectUrls.value = { ...resourceObjectUrls.value, [handle]: url }
      } catch {
        failedResourceHandles.add(requestKey)
        resourceObjectUrls.value = { ...resourceObjectUrls.value }
      } finally {
        resourceRequests.delete(requestKey)
      }
    })
    resourceFetchQueue = request
    resourceRequests.set(requestKey, request)
  }
}

function hydrateMessageResources(chatMessage: KnowledgeChatMessage) {
  const referenceResourceMarkdown = (chatMessage.references || [])
    .flatMap(reference => reference.resourceHandles || [])
    .map(handle => `[](resource://${handle})`)
    .join('\n')
  void hydrateResourceHandles(`${chatMessage.content}\n${referenceResourceMarkdown}`)
  void hydrateKnowledgePreviewImages(chatMessage)
}

async function hydrateKnowledgePreviewImages(chatMessage: KnowledgeChatMessage) {
  const projectId = store.currentProjectId
  if (!projectId) return
  const imageReferences = displayedMessageReferences(chatMessage).filter(isImageReference)
  for (const reference of imageReferences) {
    const knowledgeId = reference.knowledgeId
    const requestKey = `${projectId}:${knowledgeId}`
    if (
      !knowledgeId
      || knowledgePreviewObjectUrls.value[knowledgeId]
      || failedKnowledgePreviewIds.has(requestKey)
      || knowledgePreviewRequests.has(requestKey)
    ) continue
    const request = resourceFetchQueue.then(async () => {
      try {
        if (projectId !== store.currentProjectId) return
        const blob = await fetchWeKnoraKnowledgePreviewBlob(projectId, knowledgeId)
        if (projectId !== store.currentProjectId) return
        const url = URL.createObjectURL(blob)
        knowledgePreviewObjectUrls.value = {
          ...knowledgePreviewObjectUrls.value,
          [knowledgeId]: url,
        }
      } catch {
        failedKnowledgePreviewIds.add(requestKey)
        knowledgePreviewObjectUrls.value = { ...knowledgePreviewObjectUrls.value }
      } finally {
        knowledgePreviewRequests.delete(requestKey)
      }
    })
    resourceFetchQueue = request
    knowledgePreviewRequests.set(requestKey, request)
  }
}

function releaseResourceUrls() {
  for (const url of Object.values(resourceObjectUrls.value)) URL.revokeObjectURL(url)
  for (const url of Object.values(knowledgePreviewObjectUrls.value)) URL.revokeObjectURL(url)
  resourceObjectUrls.value = {}
  knowledgePreviewObjectUrls.value = {}
  failedResourceHandles.clear()
  failedKnowledgePreviewIds.clear()
}

function referenceIconKind(fileName: string) {
  const extension = (fileName.split('.').pop() || '').toLowerCase()
  if (extension === 'pdf') return 'pdf'
  if (['doc', 'docx'].includes(extension)) return 'document'
  if (['xls', 'xlsx', 'csv'].includes(extension)) return 'spreadsheet'
  if (['ppt', 'pptx'].includes(extension)) return 'presentation'
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'].includes(extension)) return 'image'
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(extension)) return 'archive'
  if (['mp3', 'wav', 'aac', 'flac', 'm4a'].includes(extension)) return 'audio'
  if (['mp4', 'avi', 'mov', 'mkv', 'webm'].includes(extension)) return 'video'
  if (['html', 'css', 'js', 'ts', 'tsx', 'jsx', 'json', 'xml', 'yaml', 'yml'].includes(extension)) return 'code'
  return 'generic'
}

onBeforeUnmount(() => {
  turnEpoch += 1
  const wasWorking = answering.value || recoveringRun.value
  stopRecoveryPolling()
  if (progressClock) clearInterval(progressClock)
  const id = activeConversation.value?.agentConversationId
  if (wasWorking && id) void api.post(`/agent-conversations/${id}/interrupt`).catch(() => undefined)
  activeStreamController?.abort()
  releaseResourceUrls()
})
</script>

<style scoped src="./ProjectKnowledgeChat.css"></style>
