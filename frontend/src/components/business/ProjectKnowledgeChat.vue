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
            :disabled="deletingConversationId === conversation.id"
            :aria-label="`删除对话：${conversation.title}`"
            title="删除对话"
            @click.stop="confirmDeleteConversation(conversation)"
          >
            <n-icon :size="16"><Trash /></n-icon>
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
        <strong>项目资料综合问答</strong>
        <div class="knowledge-scope-picker">
          <button
            type="button"
            class="knowledge-scope-trigger"
            :class="{ active: scopePickerOpen }"
            :disabled="disabled || loadingHistory || answering"
            aria-label="选择问答范围"
            :aria-expanded="scopePickerOpen"
            @click.stop="scopePickerOpen = !scopePickerOpen"
          >
            <i aria-hidden="true"></i>
            <span :title="scopeTriggerLabel">{{ scopeTriggerLabel }}</span>
            <n-icon :size="16"><ChevronDown /></n-icon>
          </button>
          <div v-if="scopePickerOpen" class="knowledge-scope-backdrop" aria-hidden="true" @click="scopePickerOpen = false"></div>
          <section v-if="scopePickerOpen" class="knowledge-scope-menu" aria-label="知识库问答范围列表" @click.stop>
            <button type="button" class="knowledge-scope-all" :class="{ selected: currentScope.type === 'project' }" @click="selectProjectScope">
              <span class="knowledge-scope-node-icon"><n-icon :size="17"><Database /></n-icon></span>
              <span><strong>全部</strong><small>当前项目绑定机器人可读取的全部知识库</small></span>
            </button>
            <div class="knowledge-scope-tree" role="tree">
              <div
                v-for="row in scopePickerRows"
                :key="`${row.kind}:${row.id}`"
                class="knowledge-scope-row"
                :class="[{ selected: scopeRowSelected(row) }, `is-${row.kind}`]"
                role="treeitem"
                :aria-selected="scopeRowSelected(row)"
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
                <button v-if="row.kind === 'folder'" type="button" class="knowledge-scope-choice" @click="selectFolderScope(row.folder)">
                  <span class="knowledge-scope-node-icon"><n-icon :size="17"><component :is="row.folder.isKnowledgeBase ? Database : Folder" /></n-icon></span>
                  <span><strong :title="row.folder.name">{{ row.folder.name }}</strong><small>{{ row.folder.isKnowledgeBase ? '知识库' : '目录' }} · {{ row.folder.totalCount ?? row.folder.documentCount ?? 0 }} 份资料</small></span>
                </button>
                <button v-else type="button" class="knowledge-scope-choice" @click="selectDocumentScope(row.file)">
                  <span class="knowledge-scope-file-icon"><DocumentTypeIcon :kind="referenceIconKind(row.file.fileName)" /></span>
                  <span><strong :title="row.file.fileName">{{ row.file.fileName }}</strong><small>文件 · {{ formatScopeFileSize(row.file.fileSize) }}</small></span>
                </button>
              </div>
              <div v-if="!scopePickerRows.length" class="knowledge-scope-tree-empty">当前项目没有可选择的知识库目录。</div>
            </div>
          </section>
        </div>
      </header>

      <div ref="chatScrollRef" class="knowledge-chat-scroll" :aria-busy="answering">
        <section v-if="loadingMessages" class="knowledge-chat-empty" role="status">
          <span class="knowledge-chat-empty-icon conversation-loading-robot"><n-icon :size="26"><Robot /></n-icon></span>
          <strong>正在加载聊天记录</strong>
        </section>
        <section v-else-if="!activeMessages.length" class="knowledge-chat-empty">
          <span class="knowledge-chat-empty-icon"><n-icon :size="26"><Robot /></n-icon></span>
          <strong>从项目资料中查找答案</strong>
          <p>默认检索本项目绑定机器人可读取的全部 WeKnora 知识库，也可以从知识库管理进入单文件问答。</p>
          <div class="knowledge-starter-list">
            <button type="button" :disabled="disabled || loadingHistory" @click="askSuggestedQuestion('本项目有哪些深基坑监测要求？')">本项目有哪些深基坑监测要求？</button>
            <button type="button" :disabled="disabled || loadingHistory" @click="askSuggestedQuestion('查找最新的安全例会纪要并概括主要结论')">查找最新的安全例会纪要</button>
            <button type="button" :disabled="disabled || loadingHistory" @click="askSuggestedQuestion('汇总工程资料中的风险预警依据')">汇总风险预警依据</button>
          </div>
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
              <div v-if="chatMessage.role === 'assistant'" class="knowledge-markdown" v-html="renderMarkdown(chatMessage.content)"></div>
              <p v-else>{{ chatMessage.content }}</p>
              <div v-if="chatMessage.references?.length" class="knowledge-reference-list">
                <span class="reference-label">来源参考</span>
                <span v-for="reference in chatMessage.references" :key="reference.id + reference.fileName" class="knowledge-reference-chip" :title="reference.folderPath || reference.fileName">
                  <DocumentTypeIcon :kind="referenceIconKind(reference.fileName)" />
                  {{ reference.fileName }}
                </span>
              </div>
              <time>{{ formatMessageTime(chatMessage.createdAt) }}</time>
            </div>
            <span v-if="chatMessage.role === 'user'" class="knowledge-user-avatar"><n-icon :size="18"><User /></n-icon></span>
          </article>
        </template>

        <article v-if="answering" class="knowledge-chat-message is-assistant is-pending" role="status" aria-live="polite">
          <span class="knowledge-message-avatar"><n-icon :size="17"><Robot /></n-icon></span>
          <div class="knowledge-message-card">
            <p>{{ stopping ? '正在终止本次回答…' : '正在检索项目资料并组织回答…' }}</p>
          </div>
        </article>
      </div>

      <footer class="knowledge-chat-footer">
        <div class="knowledge-scope-summary">
          <span>问答范围：</span>
          <strong>{{ conversationScopeLabel(currentScope) }}</strong>
        </div>
        <form class="knowledge-composer" @submit.prevent="sendQuestion">
          <textarea
            v-model.trim="question"
            :disabled="disabled || loadingHistory || loadingMessages || !store.currentProjectId"
            :placeholder="scopeQuestionPlaceholder"
            @keydown.enter.exact.prevent="sendQuestion"
          ></textarea>
          <button v-if="answering" type="button" class="is-stop" :disabled="stopping" aria-label="终止回答" @click="stopAnswer">
            <n-icon :size="18"><PlayerStop /></n-icon>
          </button>
          <button v-else type="submit" :disabled="disabled || loadingHistory || loadingMessages || !store.currentProjectId || !question" aria-label="发送问题">
            <n-icon :size="18"><Send /></n-icon>
          </button>
        </form>
      </footer>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NIcon, useDialog, useMessage } from 'naive-ui'
import { ChevronDown, ChevronRight, Database, Folder, MessageCircle, Messages, PlayerStop, Plus, Refresh, Robot, Search, Send, Trash, User } from '@vicons/tabler'
import MarkdownIt from 'markdown-it'
import DocumentTypeIcon from '@/components/business/DocumentTypeIcon.vue'
import {
  useAppStore,
  type AttachmentRecord,
  type DocumentFolderRecord,
  type EngineeringKnowledgeConversationRecord,
  type EngineeringKnowledgeMessageRecord,
} from '@/stores/app'

type KnowledgeScope =
  | { type: 'project' }
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
  fileName: string
  folderPath?: string
}

type KnowledgeChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  references?: KnowledgeReference[]
  failed?: boolean
}

type KnowledgeConversation = {
  id: number
  title: string
  sessionId: string
  scope: KnowledgeScope
  messages: KnowledgeChatMessage[]
  updatedAt: string
  loaded: boolean
}

const props = defineProps<{ focusDocumentId?: string; disabled?: boolean }>()
const emit = defineEmits<{
  'document-consumed': []
  'busy-change': [value: boolean]
  'ready-change': [value: boolean]
}>()
const store = useAppStore()
const message = useMessage()
const dialog = useDialog()
const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })

const conversations = ref<KnowledgeConversation[]>([])
const activeConversationId = ref<number | null>(null)
const draftScope = ref<KnowledgeScope>({ type: 'project' })
const conversationKeyword = ref('')
const question = ref('')
const answering = ref(false)
const stopping = ref(false)
const stopRequested = ref(false)
const answerSessionId = ref('')
const loadingHistory = ref(false)
const loadingMessages = ref(false)
const deletingConversationId = ref<number | null>(null)
const chatScrollRef = ref<HTMLElement | null>(null)
const scopePickerOpen = ref(false)
const scopeExpandedFolderIds = ref<string[]>([])
const scopeFolderLoadingIds = ref<string[]>([])
let historyLoadVersion = 0
let messageLoadVersion = 0

const activeConversation = computed(() => conversations.value.find(item => item.id === activeConversationId.value))
const activeMessages = computed(() => activeConversation.value?.messages || [])
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
  return `已选 ${scope.documentName} 文件`
})
const scopeQuestionPlaceholder = computed(() => {
  const scope = currentScope.value
  if (scope.type === 'document') return '围绕当前文件继续提问…'
  if (scope.type === 'folder') return '向当前目录中的资料提问…'
  if (scope.type === 'knowledge_base') return '向当前知识库提问…'
  return '向当前项目知识库提问…'
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
  void loadConversationHistory(projectId)
}, { immediate: true })

watch(() => props.focusDocumentId, documentId => {
  if (!documentId) return
  const file = store.attachments.find(item => item.id === documentId)
  if (file) startNewConversation(documentScope(file))
  emit('document-consumed')
}, { immediate: true })

watch(answering, value => emit('busy-change', value), { immediate: true })

function conversationScope(record: EngineeringKnowledgeConversationRecord): KnowledgeScope {
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
    title: record.title,
    sessionId: record.weknora_session_id || '',
    scope: conversationScope(record),
    messages: [],
    updatedAt: record.updated_at || record.created_at,
    loaded: false,
  }
}

function mapMessage(record: EngineeringKnowledgeMessageRecord): KnowledgeChatMessage {
  return {
    id: String(record.id),
    role: record.role,
    content: record.content,
    createdAt: record.created_at,
    references: normalizeReferences(record.references),
    failed: Boolean(record.failed),
  }
}

async function loadConversationHistory(projectId: string) {
  const requestVersion = ++historyLoadVersion
  emit('ready-change', false)
  messageLoadVersion += 1
  conversations.value = []
  activeConversationId.value = null
  draftScope.value = { type: 'project' }
  scopePickerOpen.value = false
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
  loadingMessages.value = true
  try {
    const records = await store.loadEngineeringKnowledgeMessages(conversation.id)
    if (requestVersion !== messageLoadVersion) return
    const target = conversations.value.find(item => item.id === conversation.id)
    if (!target) return
    target.messages = records.map(mapMessage)
    target.loaded = true
    void scrollToBottom()
  } catch (error: any) {
    if (requestVersion !== messageLoadVersion) return
    message.error(error.response?.data?.detail || error.message || '聊天记录加载失败。')
  } finally {
    if (requestVersion === messageLoadVersion) loadingMessages.value = false
  }
}

function documentScope(file: AttachmentRecord): KnowledgeScope {
  return {
    type: 'document',
    documentId: file.id,
    documentName: file.fileName,
    knowledgeBaseId: file.knowledgeBaseId,
  }
}

function knowledgeBaseScope(folder: DocumentFolderRecord): KnowledgeScope {
  return {
    type: 'knowledge_base',
    knowledgeBaseId: folder.knowledgeBaseId || '',
    knowledgeBaseName: folder.name,
  }
}

function folderScope(folder: DocumentFolderRecord): KnowledgeScope {
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
  startNewConversation({ type: 'project' })
  scopePickerOpen.value = false
}

function selectFolderScope(folder: DocumentFolderRecord) {
  if (!folder.knowledgeBaseId) return
  startNewConversation(folder.isKnowledgeBase ? knowledgeBaseScope(folder) : folderScope(folder))
  scopePickerOpen.value = false
}

function selectDocumentScope(file: AttachmentRecord) {
  startNewConversation(documentScope(file))
  scopePickerOpen.value = false
}

function scopeRowSelected(row: ScopePickerRow) {
  const scope = currentScope.value
  if (row.kind === 'document') return scope.type === 'document' && scope.documentId === row.file.id
  if (row.folder.isKnowledgeBase) {
    return scope.type === 'knowledge_base' && scope.knowledgeBaseId === row.folder.knowledgeBaseId
  }
  return scope.type === 'folder'
    && scope.knowledgeBaseId === row.folder.knowledgeBaseId
    && normalizeScopeFolderPath(scope.folderPath) === normalizeScopeFolderPath(row.folder.path)
}

function formatScopeFileSize(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '未知大小'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / 1024 / 1024).toFixed(value >= 10 * 1024 * 1024 ? 0 : 1)} MB`
}

function startNewConversation(scope: KnowledgeScope = { type: 'project' }) {
  if (answering.value) {
    message.warning('请先终止当前回答，再新建对话。')
    return
  }
  messageLoadVersion += 1
  loadingMessages.value = false
  activeConversationId.value = null
  draftScope.value = scope
  question.value = ''
  void scrollToBottom()
}

function selectConversation(conversationId: number) {
  if (answering.value && conversationId !== activeConversationId.value) {
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
  if (answering.value && conversation.id === activeConversationId.value) {
    message.warning('请先终止当前回答，再删除该对话。')
    return
  }
  dialog.warning({
    title: '删除对话',
    content: `确定删除“${conversation.title}”及其全部聊天记录吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => deleteConversation(conversation),
  })
}

async function deleteConversation(conversation: KnowledgeConversation) {
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
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '删除对话失败。')
    throw error
  } finally {
    deletingConversationId.value = null
  }
}

function conversationScopeLabel(scope: KnowledgeScope) {
  if (scope.type === 'project') return '全部'
  if (scope.type === 'knowledge_base') return `知识库 · ${scope.knowledgeBaseName}`
  if (scope.type === 'folder') return `目录 · ${scope.folderName}`
  return `文件 · ${scope.documentName}`
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
  for (const item of items || []) {
    const id = textValue(item.knowledge_id, item.knowledgeId, item.id)
    const fileName = textValue(item.knowledge_filename, item.file_name, item.filename, item.knowledge_title, item.title) || '来源资料'
    const folderPath = textValue(item.folder_path, item.folderPath, item.path)
    const key = id || `${fileName}:${folderPath}`
    result.set(key, { id: id || key, fileName, folderPath: folderPath || undefined })
  }
  return [...result.values()].slice(0, 8)
}

function textValue(...values: unknown[]) {
  for (const value of values) if (typeof value === 'string' && value.trim()) return value.trim()
  return ''
}

function isMissingSessionError(error: any) {
  const status = Number(error?.response?.status || 0)
  const detail = String(error?.response?.data?.detail || error?.message || '')
  return status === 404 && /(session|会话).*(not found|不存在|失效)/i.test(detail)
}

function sessionRecoveryQuestion(messages: KnowledgeChatMessage[], currentQuestion: string) {
  const context = messages
    .filter(item => !item.failed)
    .slice(0, -1)
    .slice(-10)
    .map(item => `${item.role === 'user' ? '用户' : '助手'}：${item.content}`)
    .join('\n')
    .slice(-5000)
  if (!context) return currentQuestion
  return `请结合以下此前对话继续回答最后的问题。\n\n${context}\n\n用户当前问题：${currentQuestion}`
}

function scopeDisplayName(scope: KnowledgeScope) {
  if (scope.type === 'knowledge_base') return scope.knowledgeBaseName
  if (scope.type === 'folder') return scope.folderName
  if (scope.type === 'document') return scope.documentName
  return ''
}

async function resolveScopeAskFilters(scope: KnowledgeScope) {
  if (scope.type === 'project') return { knowledgeIds: [] as string[], knowledgeBaseIds: [] as string[] }
  if (scope.type === 'knowledge_base') {
    return { knowledgeIds: [] as string[], knowledgeBaseIds: [scope.knowledgeBaseId] }
  }
  if (scope.type === 'document') {
    return {
      knowledgeIds: [scope.documentId],
      knowledgeBaseIds: scope.knowledgeBaseId ? [scope.knowledgeBaseId] : [],
    }
  }

  let folder = store.documentFolders.find(item => (
    item.knowledgeBaseId === scope.knowledgeBaseId
    && normalizeScopeFolderPath(item.path) === normalizeScopeFolderPath(scope.folderPath)
  ))
  if (!folder && store.currentProjectId) {
    await store.loadEngineeringDocuments(store.currentProjectId, true)
    folder = store.documentFolders.find(item => (
      item.knowledgeBaseId === scope.knowledgeBaseId
      && normalizeScopeFolderPath(item.path) === normalizeScopeFolderPath(scope.folderPath)
    ))
  }
  if (!folder) throw new Error('所选目录已不存在，请重新选择问答范围。')
  const files = await store.loadEngineeringDocumentFolder(folder.id, false, true)
  const knowledgeIds = [...new Set(files.map(item => item.id).filter(Boolean))]
  if (!knowledgeIds.length) throw new Error('所选目录中没有可用于问答的资料。')
  if (knowledgeIds.length > 200) {
    throw new Error(`所选目录包含 ${knowledgeIds.length} 份资料，当前单次问答最多限定 200 份，请选择更小的目录。`)
  }
  return { knowledgeIds, knowledgeBaseIds: [scope.knowledgeBaseId] }
}

async function sendQuestion() {
  const content = question.value.trim()
  if (props.disabled || loadingHistory.value || loadingMessages.value || !content || answering.value || !store.currentProjectId) return
  let conversation = activeConversation.value
  let userMessageStored = false
  question.value = ''
  answering.value = true
  stopping.value = false
  stopRequested.value = false
  answerSessionId.value = conversation?.sessionId || ''
  try {
    const requestedScope = conversation?.scope || draftScope.value
    const scopeFilters = await resolveScopeAskFilters(requestedScope)
    if (!conversation) {
      const scope = draftScope.value
      const created = await store.createEngineeringKnowledgeConversation({
        title: scope.type === 'project'
          ? content.slice(0, 60)
          : `${scopeDisplayName(scope)} · ${content.slice(0, 24)}`,
        scopeType: scope.type,
        knowledgeId: scope.type === 'document' ? scope.documentId : undefined,
        knowledgeName: scope.type === 'project' ? undefined : scopeDisplayName(scope),
        knowledgeBaseId: scope.type === 'project' ? undefined : scope.knowledgeBaseId,
        folderPath: scope.type === 'folder' ? scope.folderPath : undefined,
        firstMessage: content,
      })
      conversation = mapConversation(created.conversation)
      conversation.messages = created.messages.map(mapMessage)
      conversation.loaded = true
      conversations.value = [conversation, ...conversations.value]
      activeConversationId.value = conversation.id
      userMessageStored = true
    } else {
      const savedUserMessage = await store.appendEngineeringKnowledgeMessage(
        conversation.id,
        { role: 'user', content },
      )
      conversation.messages.push(mapMessage(savedUserMessage))
      conversation.updatedAt = savedUserMessage.created_at
      userMessageStored = true
    }
    void scrollToBottom()

    if (!conversation.sessionId) {
      const session = await store.createEngineeringDocumentSession()
      await updateConversationSession(conversation, session.session_id)
    }
    answerSessionId.value = conversation.sessionId
    if (stopRequested.value) {
      await saveAssistantMessage(conversation, '回答已终止。')
      return
    }
    const scopedConversation = conversation
    const ask = (query: string) => store.askEngineeringDocuments(
      query,
      scopeFilters.knowledgeIds,
      scopeFilters.knowledgeBaseIds,
      scopedConversation.sessionId,
    )
    let answer
    try {
      answer = await ask(content)
    } catch (error: any) {
      if (!isMissingSessionError(error) || stopRequested.value) throw error
      const session = await store.createEngineeringDocumentSession()
      await updateConversationSession(conversation, session.session_id)
      answerSessionId.value = conversation.sessionId
      answer = await ask(sessionRecoveryQuestion(conversation.messages, content))
    }
    if (answer.session_id && answer.session_id !== conversation.sessionId) {
      await updateConversationSession(conversation, answer.session_id)
    }
    const answerContent = answer.answer?.trim()
    await saveAssistantMessage(
      conversation,
      answerContent
        ? answerContent + (stopRequested.value ? '\n\n（回答已终止）' : '')
        : stopRequested.value
          ? '回答已终止。'
          : 'WeKnora 未返回可展示的回答。',
      answer.references,
    )
  } catch (error: any) {
    const detail = error.response?.data?.detail || error.message || '知识库问答失败，请稍后重试。'
    if (!conversation || !userMessageStored) {
      question.value = content
      message.error(detail)
    } else if (stopRequested.value) {
      await saveAssistantMessage(conversation, '回答已终止。')
    } else {
      await saveAssistantMessage(conversation, detail, undefined, true)
      message.error(detail)
    }
  } finally {
    if (conversation) conversation.updatedAt = new Date().toISOString()
    answering.value = false
    stopping.value = false
    stopRequested.value = false
    answerSessionId.value = ''
    void scrollToBottom()
  }
}

async function updateConversationSession(conversation: KnowledgeConversation, sessionId: string) {
  conversation.sessionId = sessionId
  answerSessionId.value = sessionId
  try {
    const updated = await store.updateEngineeringKnowledgeConversation(
      conversation.id,
      { sessionId },
    )
    conversation.updatedAt = updated.updated_at
  } catch (error: any) {
    message.warning(error.response?.data?.detail || '会话已建立，但会话标识暂未写入数据库。')
  }
}

async function saveAssistantMessage(
  conversation: KnowledgeConversation,
  content: string,
  references?: Array<Record<string, unknown>>,
  failed = false,
) {
  try {
    const saved = await store.appendEngineeringKnowledgeMessage(
      conversation.id,
      { role: 'assistant', content, references, failed },
    )
    conversation.messages.push(mapMessage(saved))
    conversation.updatedAt = saved.created_at
  } catch {
    conversation.messages.push(createChatMessage(
      'assistant',
      content,
      normalizeReferences(references),
      failed,
    ))
    message.error('回答已显示，但这条聊天记录未能写入数据库。')
  }
  void scrollToBottom()
}

function askSuggestedQuestion(value: string) {
  if (props.disabled || loadingHistory.value || loadingMessages.value) return
  question.value = value
  void sendQuestion()
}

async function stopAnswer() {
  if (!answering.value || stopping.value) return
  stopRequested.value = true
  stopping.value = true
  if (!answerSessionId.value) return
  try {
    const result = await store.stopEngineeringDocumentAnswer(answerSessionId.value)
    if (!result.stopped) {
      stopRequested.value = false
      stopping.value = false
      message.info(result.message || '当前没有正在生成的回答。')
      return
    }
    message.info('已发送终止请求，正在保留已经生成的内容。')
  } catch (error: any) {
    stopRequested.value = false
    stopping.value = false
    message.error(error.response?.data?.detail || error.message || '终止回答失败。')
  }
}

async function scrollToBottom() {
  await nextTick()
  if (chatScrollRef.value) chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
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

function renderMarkdown(content: string) {
  return markdown.render(content)
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
</script>

<style scoped>
.project-knowledge-chat {
  display: grid;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  grid-template-columns: minmax(230px, 270px) minmax(0, 1fr);
  overflow: hidden;
  background: #fff;
}

.conversation-rail {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #e1e8e6;
  background: #fbfcfc;
}
.conversation-rail-head { padding: 18px 18px 10px; }
.new-conversation-button {
  display: flex;
  width: 100%;
  min-height: 38px;
  box-sizing: border-box;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid #cad9d5;
  border-radius: 7px;
  padding: 0 13px;
  color: #0f6f67;
  background: #fff;
  font: inherit;
  font-size: 13px;
  font-weight: 780;
  cursor: pointer;
  transition: border-color .18s ease, background .18s ease, transform .18s ease;
}
.new-conversation-button:not(:disabled):hover { transform: translateY(-1px); border-color: #82aaa2; background: #f3f8f6; }
.new-conversation-button:not(:disabled):active { transform: translateY(0); }
.conversation-search {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  margin: 0 18px 16px;
  padding: 0 10px;
  border: 1px solid #d6e0dd;
  border-radius: 7px;
  color: #718681;
  background: #fff;
}
.conversation-search:focus-within { border-color: #72a197; box-shadow: 0 0 0 3px rgba(15, 118, 110, .09); }
.conversation-search input { min-width: 0; height: 38px; border: 0; outline: 0; color: #294844; background: transparent; font: inherit; font-size: 12px; }
.conversation-list { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; overflow: auto; padding: 0 10px 14px; scrollbar-gutter: stable; }
.conversation-list-label { padding: 4px 8px 8px; color: #7d8f8b; font-size: 12px; font-weight: 700; }
.conversation-item {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) 32px;
  align-items: center;
  gap: 2px;
  border-radius: 7px;
  padding: 2px;
  color: #284a45;
  background: transparent;
  transition: color .16s ease, background .16s ease;
}
.conversation-item:hover { background: #f0f5f3; }
.conversation-item.active { color: #0d6860; background: #e5f0ed; }
.conversation-select {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 8px;
  border: 0;
  border-radius: 6px;
  padding: 9px 7px;
  color: inherit;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.conversation-select > span { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.conversation-select strong { overflow: hidden; font-size: 12px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.conversation-select time { color: #7b8d89; font-size: 12px; font-variant-numeric: tabular-nums; }
.conversation-select small { overflow: hidden; color: #82938f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.conversation-delete {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 6px;
  color: #879793;
  background: transparent;
  cursor: pointer;
  opacity: .58;
  transition: color .16s ease, background .16s ease, opacity .16s ease;
}
.conversation-item:hover .conversation-delete,
.conversation-delete:focus-visible { opacity: 1; }
.conversation-delete:not(:disabled):hover { color: #b64737; background: #fff1ee; }
.conversation-list-empty { display: grid; flex: 1 1 auto; min-height: 180px; place-content: center; justify-items: center; gap: 6px; color: #81938f; text-align: center; }
.conversation-list-empty strong { color: #48635e; font-size: 13px; }
.conversation-list-empty span { font-size: 12px; }
.conversation-loading-robot { animation: conversation-robot-duang 1.05s cubic-bezier(.34, 1.56, .64, 1) infinite; transform-origin: 50% 100%; }
.conversation-rail-foot { display: flex; align-items: center; gap: 7px; padding: 13px 18px; border-top: 1px solid #e5ebe9; color: #748783; font-size: 12px; }

.knowledge-chat-pane { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; background: #fff; }
.knowledge-chat-head { display: flex; flex: 0 0 auto; align-items: center; gap: 24px; min-height: 62px; padding: 0 38px; border-bottom: 1px solid #edf1ef; }
.knowledge-chat-head > strong { color: #1d3835; font-size: 16px; font-weight: 820; }
.knowledge-scope-picker { position: relative; min-width: 188px; }
.knowledge-scope-trigger { position: relative; z-index: 13; display: grid; width: min(360px, 32vw); min-width: 188px; min-height: 36px; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 9px; border: 1px solid #d5e0dd; border-radius: 7px; padding: 0 10px; color: #49645f; background: #f9fbfa; font: inherit; font-size: 12px; text-align: left; cursor: pointer; transition: border-color .16s ease, background .16s ease, box-shadow .16s ease; }
.knowledge-scope-trigger:hover,.knowledge-scope-trigger.active { border-color: #8aafa7; background: #fff; }
.knowledge-scope-trigger.active { box-shadow: 0 0 0 3px rgba(15, 118, 110, .09); }
.knowledge-scope-trigger > i { width: 7px; height: 7px; border-radius: 50%; background: #0f9a79; }
.knowledge-scope-trigger > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.knowledge-scope-backdrop { position: fixed; z-index: 11; inset: 0; }
.knowledge-scope-menu { position: absolute; z-index: 12; top: calc(100% + 7px); left: 0; display: grid; width: min(430px, calc(100vw - 32px)); max-height: min(520px, calc(100dvh - 170px)); grid-template-rows: auto minmax(0, 1fr); overflow: hidden; border: 1px solid #cbdad6; border-radius: 9px; background: #fff; box-shadow: 0 18px 42px rgba(25, 58, 52, .17); }
.knowledge-scope-all { display: grid; min-width: 0; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 10px; border: 0; border-bottom: 1px solid #e3ebe9; padding: 12px 14px; color: #48645e; background: #f8fbfa; font: inherit; text-align: left; cursor: pointer; }
.knowledge-scope-all:hover,.knowledge-scope-all.selected { color: #164f47; background: #eaf5f1; }
.knowledge-scope-all > span:last-child,.knowledge-scope-choice > span:last-child { display: grid; min-width: 0; gap: 2px; }
.knowledge-scope-all strong,.knowledge-scope-choice strong { overflow: hidden; color: #294b45; font-size: 12px; font-weight: 760; text-overflow: ellipsis; white-space: nowrap; }
.knowledge-scope-all small,.knowledge-scope-choice small { overflow: hidden; color: #7a8c88; font-size: 12px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.knowledge-scope-tree { min-height: 0; overflow: auto; padding: 7px; }
.knowledge-scope-row { display: flex; min-width: 0; align-items: center; border-radius: 6px; color: #526c67; }
.knowledge-scope-row:hover { background: #f1f7f5; }
.knowledge-scope-row.selected { background: #e5f2ee; box-shadow: inset 3px 0 #168273; }
.knowledge-scope-indent { flex: 0 0 15px; width: 15px; }
.knowledge-scope-expand { display: grid; flex: 0 0 26px; width: 26px; height: 34px; place-items: center; border: 0; padding: 0; color: #6f8580; background: transparent; cursor: pointer; }
.knowledge-scope-expand.hidden { visibility: hidden; cursor: default; }
.knowledge-scope-choice { display: grid; flex: 1 1 auto; min-width: 0; min-height: 44px; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 9px; border: 0; padding: 5px 9px 5px 2px; color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer; }
.knowledge-scope-node-icon { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 7px; color: #176f64; background: #e4f1ed; }
.knowledge-scope-file-icon { display: grid; width: 28px; height: 28px; place-items: center; }
.knowledge-scope-file-icon :deep(img) { width: 24px; height: 24px; object-fit: contain; }
.knowledge-scope-tree-empty { padding: 28px 16px; color: #7a8d88; font-size: 12px; text-align: center; }
.knowledge-scope-spinner { animation: conversation-scope-spin .8s linear infinite; }
.knowledge-chat-scroll { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 30px clamp(28px, 7vw, 108px); scrollbar-gutter: stable; scroll-behavior: smooth; }
.knowledge-chat-empty { display: grid; min-height: 100%; place-content: center; justify-items: center; gap: 9px; color: #768b86; text-align: center; }
.knowledge-chat-empty-icon { display: grid; width: 48px; height: 48px; place-items: center; border-radius: 13px; color: #fff; background: #164a46; box-shadow: 0 10px 24px rgba(22, 74, 70, .16); }
.knowledge-chat-empty strong { color: #274844; font-size: 17px; }
.knowledge-chat-empty p { max-width: 56ch; margin: 0; font-size: 13px; line-height: 1.65; }
.knowledge-starter-list { display: flex; flex-wrap: wrap; justify-content: center; gap: 7px; margin-top: 7px; }
.knowledge-starter-list button { border: 1px solid #d2dfdb; border-radius: 6px; padding: 8px 10px; color: #42615b; background: #fff; font: inherit; font-size: 12px; cursor: pointer; transition: border-color .16s ease, background .16s ease, transform .16s ease; }
.knowledge-starter-list button:hover { transform: translateY(-1px); border-color: #86aaa2; background: #f4f8f7; }
.knowledge-chat-message { display: flex; align-items: flex-start; gap: 12px; margin: 0 auto 18px; }
.knowledge-chat-message.is-user { justify-content: flex-end; }
.knowledge-message-avatar,
.knowledge-user-avatar { display: grid; flex: 0 0 auto; width: 38px; height: 38px; place-items: center; border-radius: 50%; }
.knowledge-message-avatar { color: #fff; background: #164a46; }
.knowledge-user-avatar { color: #fff; background: #0f6e67; }
.knowledge-message-card { min-width: 0; max-width: min(860px, 84%); padding: 17px 18px; border: 1px solid #dce5e2; border-radius: 9px; color: #344f4a; background: #fff; box-shadow: 0 5px 18px rgba(29, 66, 60, .04); }
.knowledge-chat-message.is-user .knowledge-message-card { max-width: min(620px, 72%); border-color: #c8ddd7; background: #edf6f3; }
.knowledge-chat-message.is-failed .knowledge-message-card { border-color: #e5c5bf; background: #fff7f5; }
.knowledge-chat-message.is-failed p { color: #a04b3f; }
.knowledge-chat-message.is-pending .knowledge-message-card { color: #71847f; animation: knowledge-answer-pulse 1.3s ease-in-out infinite; }
.knowledge-message-card > p { margin: 0; font-size: 13px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.knowledge-message-card > time { display: block; margin-top: 10px; color: #84938f; font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; }
.knowledge-markdown { font-size: 13px; line-height: 1.72; overflow-wrap: anywhere; }
.knowledge-markdown :deep(p) { margin: 0 0 10px; }
.knowledge-markdown :deep(p:last-child) { margin-bottom: 0; }
.knowledge-markdown :deep(ol),
.knowledge-markdown :deep(ul) { margin: 8px 0; padding-left: 24px; }
.knowledge-markdown :deep(li) { margin: 5px 0; }
.knowledge-markdown :deep(code) { border-radius: 4px; padding: 2px 5px; color: #315b55; background: #eef4f2; font-size: 12px; }
.knowledge-reference-list { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
.reference-label { flex: 0 0 100%; color: #71847f; font-size: 12px; }
.knowledge-reference-chip { display: inline-flex; max-width: 280px; align-items: center; gap: 7px; border: 1px solid #d8e2df; border-radius: 6px; padding: 6px 9px; overflow: hidden; color: #42605b; background: #fbfcfc; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.knowledge-reference-chip :deep(img) { width: 18px; height: 18px; }

.knowledge-chat-footer { flex: 0 0 auto; border-top: 1px solid #e3eae8; background: #fff; }
.knowledge-scope-summary { display: flex; align-items: center; gap: 6px; min-height: 42px; padding: 0 24px; color: #71847f; background: #f3f8f6; font-size: 12px; }
.knowledge-scope-summary strong { color: #0f7168; font-size: 12px; }
.knowledge-composer { display: grid; grid-template-columns: minmax(0, 1fr) 48px; gap: 10px; padding: 12px 20px 16px; }
.knowledge-composer textarea { width: 100%; min-height: 56px; max-height: 128px; box-sizing: border-box; resize: none; border: 1px solid #d1ddda; border-radius: 8px; padding: 16px; outline: 0; color: #294943; background: #fbfcfc; font: inherit; font-size: 13px; line-height: 1.55; }
.knowledge-composer textarea:focus { border-color: #6c9f95; box-shadow: 0 0 0 3px rgba(15, 118, 110, .09); }
.knowledge-composer button { display: grid; width: 48px; height: 48px; align-self: end; place-items: center; border: 0; border-radius: 8px; color: #fff; background: #164a46; cursor: pointer; transition: background .18s ease, transform .18s ease; }
.knowledge-composer button:not(:disabled):hover { transform: translateY(-1px); background: #0f5f59; }
.knowledge-composer button:not(:disabled):active { transform: translateY(0); }
.knowledge-composer button.is-stop { background: #ad4935; }
button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible,
input:focus-visible,
select:focus-visible,
textarea:focus-visible { outline: 2px solid rgba(15, 118, 110, .48); outline-offset: 2px; }

@keyframes knowledge-answer-pulse {
  0%, 100% { opacity: .62; }
  50% { opacity: 1; }
}
@keyframes conversation-robot-duang {
  0%, 100% { transform: translateY(0) scale(1); }
  38% { transform: translateY(-7px) scale(.96, 1.04); }
  62% { transform: translateY(1px) scale(1.05, .94); }
}
@keyframes conversation-scope-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .knowledge-chat-message.is-pending .knowledge-message-card,
  .conversation-loading-robot,
  .knowledge-scope-spinner { animation: none; }
}
@media (max-width: 900px) {
  .project-knowledge-chat { grid-template-columns: 220px minmax(0, 1fr); }
  .knowledge-chat-scroll { padding-right: 24px; padding-left: 24px; }
  .knowledge-chat-head { padding: 0 24px; }
}
@media (max-width: 720px) {
  .project-knowledge-chat { display: block; overflow: visible; }
  .conversation-rail { min-height: 240px; border-right: 0; border-bottom: 1px solid #e1e8e6; }
  .knowledge-chat-pane { min-height: 620px; }
  .knowledge-chat-head { align-items: flex-start; flex-direction: column; gap: 8px; padding-top: 12px; padding-bottom: 12px; }
  .knowledge-scope-picker,.knowledge-scope-trigger { width: 100%; }
}
</style>
