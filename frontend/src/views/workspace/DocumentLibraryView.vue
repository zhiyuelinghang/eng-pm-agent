<template>
  <main class="document-library">
    <section class="dobby-workspace">
      <header class="dobby-topbar">
        <div class="dobby-identity">
          <span class="dobby-avatar" aria-hidden="true"><n-icon :size="21"><Robot /></n-icon></span>
          <div>
            <span>Dobby 资料助手</span>
            <strong>检索、解析、问答</strong>
          </div>
          <em :class="{ 'is-error': store.engineeringDocumentsError, 'is-loading': store.engineeringDocumentsLoading }">
            <i></i>
            {{ store.engineeringDocumentsLoading ? '正在连接 WeKnora' : store.engineeringDocumentsError ? 'WeKnora 连接异常' : store.weknoraKnowledgeBases.length ? 'WeKnora 已连接' : '暂无 WeKnora 数据' }}
          </em>
        </div>

        <form class="dobby-search" @submit.prevent="searchDocuments">
          <n-icon :size="18"><Search /></n-icon>
          <input
            v-model.trim="documentSearchKeyword"
            :disabled="!canManageDocuments"
            placeholder="问 Dobby：找出深基坑监测资料和对应的预警依据"
          >
          <button v-if="documentSearching" type="button" class="is-stop" :disabled="documentSearchStopping" @click="stopDocumentSearch">
            <n-icon :size="15"><PlayerStop /></n-icon>
            {{ documentSearchStopping ? '正在停止…' : '终止' }}
          </button>
          <button v-else type="submit" :disabled="!canManageDocuments">问 Dobby</button>
        </form>

        <div class="topbar-actions">
          <button type="button" class="secondary-action" :disabled="!canManageDocuments || folderCreating || folderDeleting || documentUploading || Boolean(documentDeletingId)" @click="openFolderModal">
            <n-icon :size="16"><FolderPlus /></n-icon>
            新建目录
          </button>
          <button v-if="activeFolder && !activeFolder.isKnowledgeBase" type="button" class="secondary-action is-danger" :disabled="folderDeleting || folderCreating || documentUploading || Boolean(documentDeletingId) || documentAsking" @click="confirmDeleteFolder">
            <n-icon :size="16"><Trash /></n-icon>
            {{ folderDeleting ? '正在删除…' : '删除目录' }}
          </button>
          <button type="button" class="primary-action" :disabled="!canManageDocuments || documentUploading || folderCreating || folderDeleting || Boolean(documentDeletingId)" @click="openUploadModal">
            <n-icon :size="16"><Paperclip /></n-icon>
            上传资料
          </button>
        </div>
      </header>

      <section class="dobby-workspace-grid">
        <aside class="folder-rail" aria-label="项目资料目录">
          <header class="folder-rail-head">
            <div>
              <strong>资料库目录</strong>
            </div>
            <span class="folder-count-legend" aria-label="数量颜色说明">
              <span><i class="legend-swatch is-total" aria-hidden="true"></i>全部级别</span>
              <span><i class="legend-swatch is-direct" aria-hidden="true"></i>本级</span>
            </span>
          </header>

          <nav class="folder-tree-nav" :aria-busy="store.engineeringDocumentsLoading">
            <div v-if="store.engineeringDocumentsLoading" class="folder-tree-loading library-loading-state is-compact" role="status" aria-live="polite">
              <span class="library-loading-stack" aria-hidden="true"><i></i><i></i><i></i></span>
              <strong>正在加载资料目录</strong>
            </div>
            <template v-else>
              <div v-for="node in folderTreeNodes" :key="node.id" class="tree-row" :class="'tree-depth-' + Math.min(node.depth, 4)">
                <button v-if="node.hasChildren" type="button" class="tree-toggle" :aria-label="(isFolderExpanded(node.id) ? '收起 ' : '展开 ') + node.name" :aria-expanded="isFolderExpanded(node.id)" @click="toggleFolderExpanded(node.id)">
                  <n-icon :size="15"><ChevronDown v-if="isFolderExpanded(node.id)" /><ChevronRight v-else /></n-icon>
                </button>
                <span v-else class="tree-spacer" aria-hidden="true"></span>
                <button
                  type="button"
                  class="tree-item"
                  :class="{ 'is-active': activeTreeNodeId === node.id, 'is-library-root': node.depth === 0 }"
                  :title="node.name + '：全部级别 ' + node.totalCount + ' 个，本级 ' + node.directCount + ' 个'"
                  :aria-label="node.name + '，全部级别 ' + node.totalCount + ' 个文件，本级 ' + node.directCount + ' 个文件'"
                  @click="selectTreeNode(node)"
                >
                  <span class="tree-counts" aria-hidden="true">
                    <b class="tree-count-total" :title="'全部级别 ' + node.totalCount + ' 个文件'">{{ node.totalCount }}</b>
                    <b class="tree-count-direct" :title="'本级 ' + node.directCount + ' 个文件'">{{ node.directCount }}</b>
                  </span>
                  <n-icon :size="16"><Database v-if="node.depth === 0" /><Folder v-else /></n-icon>
                  <span>{{ node.name }}</span>
                </button>
              </div>
            </template>
          </nav>
        </aside>

        <section class="workspace-main">
          <section class="document-queue" aria-label="工程资料文件">
            <div v-if="isSearchActive" class="search-state">
              <span>Dobby 找到 {{ visibleFiles.length }} 条与“{{ documentSearchKeyword }}”相关的资料</span>
              <button type="button" @click="clearSearch">返回当前目录</button>
            </div>

            <div class="library-stream">
              <div class="document-file-scroll" :aria-busy="store.engineeringDocumentsLoading || store.engineeringDocumentFolderLoading">
                <section v-if="store.engineeringDocumentsLoading || store.engineeringDocumentFolderLoading" class="document-loading" role="status" aria-live="polite">
                  <div class="library-loading-state">
                    <span class="library-loading-stack" aria-hidden="true"><i></i><i></i><i></i></span>
                    <span class="library-loading-text">
                      <strong>正在加载工程资料</strong>
                      <span>正在从 WeKnora 获取当前目录内容</span>
                    </span>
                  </div>
                </section>

                <div v-else-if="visibleFiles.length" class="document-file-list" role="listbox" aria-label="工程资料文件列表">
                  <div class="document-file-list-head" aria-hidden="true">
                    <span>名称</span>
                    <span>上传时间</span>
                    <span>类型</span>
                    <span>大小</span>
                    <span>操作</span>
                  </div>
                  <div
                    v-for="file in visibleFiles"
                    :key="file.id"
                    class="document-file-row"
                    :class="{ active: activeDocument?.id === file.id, 'is-deleting': documentDeletingId === file.id }"
                    role="option"
                    :aria-selected="activeDocument?.id === file.id"
                    :aria-busy="documentDeletingId === file.id"
                    tabindex="0"
                    @click="selectDocument(file)"
                    @keydown.enter.prevent="selectDocument(file)"
                    @keydown.space.prevent="selectDocument(file)"
                  >
                    <span class="document-file-name">
                      <span class="document-file-icon" aria-hidden="true">
                        <DocumentTypeIcon :kind="documentIconKind(file)" />
                      </span>
                      <strong :title="file.fileName">{{ file.fileName }}</strong>
                    </span>
                    <time class="document-file-date">{{ formatDate(file.createdAt) }}</time>
                    <span class="document-file-type">
                      <b>{{ fileExtension(file.fileName) }}</b>
                      <em>{{ parseStatusLabel(file.parseStatus) }}</em>
                    </span>
                    <span class="document-file-size">{{ remoteFileSizeLabel(file.fileSize) }}</span>
                    <span class="document-file-actions">
                      <button
                        type="button"
                        :disabled="!canManageDocuments || Boolean(documentDeletingId) || (documentAsking && activeDocument?.id === file.id)"
                        :title="documentDeletingId === file.id ? '正在删除' : '删除文件'"
                        :aria-label="documentDeletingId === file.id ? `正在删除 ${file.fileName}` : `删除 ${file.fileName}`"
                        @click.stop="confirmDeleteDocument(file)"
                        @keydown.stop
                      >
                        <n-icon :size="16"><Trash /></n-icon>
                      </button>
                    </span>
                  </div>
                </div>

                <section v-else class="document-empty">
                  <n-icon :size="30"><FileText /></n-icon>
                  <strong>{{ isSearchActive ? '没有找到相关资料' : '当前目录还没有资料' }}</strong>
                  <p>{{ isSearchActive ? '可以换一种说法，或返回目录后上传新的资料。' : '上传后资料将由 WeKnora 解析并出现在当前目录。' }}</p>
                  <button v-if="!isSearchActive" type="button" @click="openUploadModal">上传资料</button>
                </section>
              </div>
            </div>
          </section>

          <section class="document-chat" aria-label="WeKnora 资料问答">
            <header class="chat-head">
              <span class="chat-avatar"><n-icon :size="19"><Robot /></n-icon></span>
              <strong :title="activeDocument?.fileName">{{ documentWorkspaceLoading ? '正在加载资料' : activeDocument?.fileName || '选择一份文件后开始问答' }}</strong>
              <button
                v-if="activeDocumentMessages.length"
                type="button"
                class="chat-clear"
                :disabled="documentAsking"
                aria-label="清空当前文件聊天记录"
                @click="clearActiveDocumentChat"
              >
                清空
              </button>
              <em :class="{ 'is-loading': documentAsking || documentWorkspaceLoading }"><i></i>{{ documentWorkspaceLoading ? '加载中' : documentStopping ? '正在停止' : documentAsking ? '正在回答' : activeDocument ? '当前文件' : '等待选择' }}</em>
            </header>

            <section v-if="documentWorkspaceLoading" class="chat-loading" role="status" aria-live="polite">
              <div class="library-loading-state">
                <span class="library-loading-stack" aria-hidden="true"><i></i><i></i><i></i></span>
                <span class="library-loading-text">
                  <strong>正在加载资料</strong>
                  <span>目录和文件准备完成后即可选择问答</span>
                </span>
              </div>
            </section>

            <div v-else-if="activeDocument" ref="chatScrollRef" class="chat-scroll" :aria-busy="documentAsking">
              <article v-if="!activeDocumentMessages.length && activeDocument.snippet" class="dobby-message">
                <span><n-icon :size="16"><Robot /></n-icon></span>
                <div>
                  <small>资料说明</small>
                  <p>{{ activeDocument.snippet }}</p>
                </div>
              </article>
              <section v-else-if="!activeDocumentMessages.length" class="remote-description-empty">
                <strong>暂无资料说明</strong>
                <p>WeKnora 未返回该资料的说明内容，可直接提问。</p>
              </section>

              <article
                v-for="chatMessage in activeDocumentMessages"
                :key="chatMessage.id"
                class="document-chat-message"
                :class="['is-' + chatMessage.role, { 'is-failed': chatMessage.failed }]"
              >
                <span v-if="chatMessage.role === 'assistant'"><n-icon :size="16"><Robot /></n-icon></span>
                <div>
                  <p>{{ chatMessage.content }}</p>
                </div>
              </article>

              <article v-if="documentAsking" class="document-chat-message is-assistant is-pending" role="status" aria-live="polite">
                <span><n-icon :size="16"><Robot /></n-icon></span>
                <div><p>{{ documentStopping ? '正在终止本次回答…' : '正在查询资料并组织回答…' }}</p></div>
              </article>

              <div class="assistant-suggestions">
                <button type="button" :disabled="documentAsking" @click="askAboutDocument('请概括这份资料的主要内容')">概括资料内容</button>
                <button type="button" :disabled="documentAsking" @click="askAboutDocument('请根据资料内容检查信息是否完整，并明确说明依据')">检查资料完整性</button>
                <button type="button" :disabled="documentAsking" @click="askAboutDocument('请提取这份资料中的关键数据和结论')">提取关键数据</button>
              </div>
            </div>

            <section v-else class="chat-empty">
              <n-icon :size="29"><MessageCircle /></n-icon>
              <strong>先选择一份文件</strong>
              <p>选中上方文件卡片后，可以在这里围绕资料内容继续问 Dobby。</p>
            </section>

            <form class="assistant-composer" @submit.prevent="sendDocumentQuestion">
              <textarea v-model.trim="documentQuestion" :disabled="documentWorkspaceLoading || !activeDocument" :placeholder="documentWorkspaceLoading ? '正在加载资料' : activeDocument ? '围绕当前资料继续问 Dobby' : '请先选择一份文件'"></textarea>
              <button v-if="documentAsking" type="button" class="is-stop" :disabled="documentStopping" aria-label="终止回答" @click="stopDocumentAnswer"><n-icon :size="17"><PlayerStop /></n-icon></button>
              <button v-else type="submit" :disabled="documentWorkspaceLoading || !activeDocument || !documentQuestion" aria-label="发送问题"><n-icon :size="17"><Send /></n-icon></button>
            </form>
          </section>
        </section>
      </section>
    </section>

    <div v-if="folderModalOpen" class="library-modal-backdrop" @click.self="closeFolderModal">
      <section class="library-modal" role="dialog" aria-modal="true" aria-labelledby="folder-create-title">
        <div class="library-modal-head">
          <div><span>资料库目录</span><h2 id="folder-create-title">新建目录</h2></div>
          <button type="button" class="modal-close" :disabled="folderCreating" @click="closeFolderModal">关闭</button>
        </div>
        <form class="folder-create-form" @submit.prevent="createFolder">
          <div class="upload-target-field">
            <span>上级目录</span>
            <n-tree-select
              v-model:value="newFolderParentId"
              :options="folderTreeOptions"
              :default-expanded-keys="folderPickerExpandedKeys(newFolderParentId)"
              :render-prefix="renderFolderTreePrefix"
              :disabled="folderCreating"
              :indent="20"
              filterable
              show-line
              show-path
              separator=" / "
              placeholder="搜索或选择知识库、上级目录"
              aria-label="选择新目录的上级目录"
            />
          </div>
          <label class="folder-name-field">
            <span>目录名称</span>
            <input v-model.trim="newFolderName" maxlength="255" required :disabled="folderCreating" placeholder="请输入目录名称">
          </label>
          <div class="upload-actions">
            <button type="button" class="modal-secondary" :disabled="folderCreating" @click="closeFolderModal">取消</button>
            <button type="submit" class="modal-primary" :disabled="folderCreating || !newFolderParentId || !newFolderName.trim()">
              <n-icon :size="16"><FolderPlus /></n-icon>
              {{ folderCreating ? '正在创建…' : '创建目录' }}
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="uploadModalOpen" class="library-modal-backdrop" @click.self="closeUploadModal">
      <section class="library-modal upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title">
        <div class="library-modal-head">
          <div><span>WeKnora 资料接收</span><h2 id="upload-title">上传工程资料</h2></div>
          <button type="button" class="modal-close" :disabled="documentUploading" @click="closeUploadModal">关闭</button>
        </div>
        <form class="upload-form" @submit.prevent="uploadDocuments">
          <div class="upload-weknora-note">
            <n-icon :size="19"><DatabaseImport /></n-icon>
            <div><strong>文件将直接提交 WeKnora</strong><span>上传完成后由 WeKnora 解析；页面只展示服务实际返回的状态和资料信息。</span></div>
          </div>
          <div class="upload-target-field">
            <span>目标目录</span>
            <n-tree-select
              v-model:value="uploadFolderId"
              :options="folderTreeOptions"
              :default-expanded-keys="folderPickerExpandedKeys(uploadFolderId)"
              :render-prefix="renderFolderTreePrefix"
              :disabled="documentUploading"
              :indent="20"
              filterable
              show-line
              show-path
              separator=" / "
              placeholder="搜索或选择 WeKnora 知识库、目标目录"
              aria-label="选择资料上传目标目录"
            >
              <template #action>
                <button type="button" class="folder-tree-create-action" :disabled="documentUploading" @click.stop="openFolderModalFromUpload">
                  <n-icon :size="16"><FolderPlus /></n-icon>
                  在当前选中目录下新建文件夹
                </button>
              </template>
            </n-tree-select>
          </div>
          <div class="upload-queue-head">
            <div><strong>待上传列表</strong><span>{{ pendingUploadFiles.length }} 个文件 · {{ formatFileSize(pendingUploadTotalSize) }}</span></div>
            <label class="upload-picker"><input type="file" multiple :disabled="documentUploading" @change="queueUploadFiles">选择文件</label>
          </div>
          <ul v-if="pendingUploadFiles.length" class="upload-queue">
            <li v-for="(file, index) in pendingUploadFiles" :key="file.name + '-' + file.size + '-' + file.lastModified">
              <span class="upload-file-type">{{ fileExtension(file.name) }}</span>
              <div><strong :title="file.name">{{ file.name }}</strong><span>{{ formatFileSize(file.size) }}</span></div>
              <button type="button" :disabled="documentUploading" :aria-label="'移除 ' + file.name" @click="removePendingUpload(index)">移除</button>
            </li>
          </ul>
          <div v-else class="upload-queue-empty"><n-icon :size="26"><FileText /></n-icon><strong>选择要上传的工程资料</strong><span>支持一次选择多个文件，提交后由 WeKnora 解析。</span></div>
          <div class="upload-actions">
            <button type="button" class="modal-secondary" :disabled="documentUploading" @click="closeUploadModal">取消</button>
            <button type="submit" class="modal-primary" :disabled="documentUploading || !pendingUploadFiles.length || !uploadTargetAvailable">
              <n-icon :size="16"><DatabaseImport /></n-icon>
              {{ documentUploading ? '正在上传…' : '上传到 WeKnora' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, h, nextTick, ref, watch } from 'vue'
import { useDialog, useMessage, NIcon, NTreeSelect, type TreeSelectOption } from 'naive-ui'
import {
  ChevronDown,
  ChevronRight,
  Database,
  DatabaseImport,
  FileText,
  Folder,
  FolderPlus,
  MessageCircle,
  Paperclip,
  PlayerStop,
  Robot,
  Search,
  Send,
  Trash,
} from '@vicons/tabler'
import DocumentTypeIcon from '@/components/business/DocumentTypeIcon.vue'
import { useAppStore, type AttachmentRecord, type DocumentFolderRecord } from '@/stores/app'

type FolderTreeDisplayNode = {
  id: string
  name: string
  depth: number
  hasChildren: boolean
  directCount: number
  totalCount: number
  folderId?: string
}

type DocumentChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  failed?: boolean
}

type DocumentChatSession = {
  sessionId: string
  messages: DocumentChatMessage[]
}

const store = useAppStore()
const message = useMessage()
const dialog = useDialog()
const domainSearchTerms = ['基坑', '监测', '日报', '风险', '验收', '计划', 'WBS', '方案', '照片', '隐患', '测量']

const activeFolderId = ref('')
const expandedFolderIds = ref<string[]>([])
const initialDirectoryExpansionApplied = ref(false)
const selectedFileId = ref('')
const documentUploading = ref(false)
const folderModalOpen = ref(false)
const folderCreating = ref(false)
const folderDeleting = ref(false)
const newFolderName = ref('')
const newFolderParentId = ref('')
const resumeUploadAfterFolderModal = ref(false)
const uploadModalOpen = ref(false)
const uploadFolderId = ref('')
const pendingUploadFiles = ref<File[]>([])
const documentDeletingId = ref('')
const documentSearching = ref(false)
const documentSearchStopping = ref(false)
const documentSearchStopRequested = ref(false)
const documentSearchSessionId = ref('')
const documentSearchKeyword = ref('')
const documentSearchResults = ref<AttachmentRecord[]>([])
const isSearchActive = ref(false)
const documentQuestion = ref('')
const documentAsking = ref(false)
const documentStopping = ref(false)
const documentStopRequested = ref(false)
const documentAnswerSessionId = ref('')
const documentChatSessions = ref<Record<string, DocumentChatSession>>({})
const chatScrollRef = ref<HTMLElement | null>(null)

const canManageDocuments = computed(() => Boolean(store.currentProjectId))
const folderChildren = computed(() => {
  const result = new Map<string | undefined, DocumentFolderRecord[]>()
  for (const folder of store.documentFolders) {
    const siblings = result.get(folder.parentId) || []
    siblings.push(folder)
    result.set(folder.parentId, siblings)
  }
  for (const siblings of result.values()) siblings.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN', { numeric: true }))
  return result
})
const folderTreeNodes = computed(() => {
  const nodes: FolderTreeDisplayNode[] = []
  const appendFolder = (folder: DocumentFolderRecord, depth: number) => {
    const children = folderChildren.value.get(folder.id) || []
    const hasChildren = children.length > 0
    const directCount = Math.max(0, folder.documentCount || 0)
    nodes.push({
      id: folder.id,
      name: folder.name,
      depth,
      hasChildren,
      directCount,
      totalCount: Math.max(directCount, folder.totalCount || 0),
      folderId: folder.id,
    })
    if (hasChildren && expandedFolderIds.value.includes(folder.id)) {
      for (const child of children) appendFolder(child, depth + 1)
    }
  }
  for (const folder of folderChildren.value.get(undefined) || []) appendFolder(folder, 0)
  return nodes
})
const folderTreeOptions = computed<TreeSelectOption[]>(() => {
  const createOption = (folder: DocumentFolderRecord): TreeSelectOption => {
    const children = folderChildren.value.get(folder.id) || []
    return {
      key: folder.id,
      label: folder.name,
      isKnowledgeBase: Boolean(folder.isKnowledgeBase),
      children: children.length ? children.map(createOption) : undefined,
    }
  }
  return (folderChildren.value.get(undefined) || []).map(createOption)
})
const activeFolder = computed(() => store.documentFolders.find(folder => folder.id === activeFolderId.value))
const activeTreeNodeId = computed(() => activeFolderId.value)
const uploadTargetAvailable = computed(() => store.documentFolders.some(folder => folder.id === uploadFolderId.value))
const pendingUploadTotalSize = computed(() => pendingUploadFiles.value.reduce((total, file) => total + file.size, 0))
const documentWorkspaceLoading = computed(() => store.engineeringDocumentsLoading || store.engineeringDocumentFolderLoading)
const visibleFiles = computed(() => {
  if (isSearchActive.value) return documentSearchResults.value
  return activeFolderId.value ? store.attachments.filter(file => file.folderId === activeFolderId.value) : store.attachments
})
const activeDocument = computed(() => {
  if (documentWorkspaceLoading.value || !selectedFileId.value) return undefined
  return visibleFiles.value.find(item => item.id === selectedFileId.value)
    || store.attachments.find(item => item.id === selectedFileId.value)
})
const activeDocumentMessages = computed(() => {
  const file = activeDocument.value
  if (!file) return []
  return documentChatSessions.value[documentChatKey(file)]?.messages || []
})

watch(() => store.documentFolders, folders => {
  if (initialDirectoryExpansionApplied.value || !folders.length) return
  const rootFolders = folders.filter(folder => !folder.parentId)
  expandedFolderIds.value = [...new Set([...expandedFolderIds.value, ...rootFolders.map(folder => folder.id)])]
  initialDirectoryExpansionApplied.value = true
}, { immediate: true })

watch(() => store.currentProjectId, async projectId => {
  initialDirectoryExpansionApplied.value = false
  expandedFolderIds.value = projectId ? restoreFolderExpansion(projectId) : []
  folderModalOpen.value = false
  newFolderName.value = ''
  newFolderParentId.value = ''
  resumeUploadAfterFolderModal.value = false
  uploadModalOpen.value = false
  uploadFolderId.value = ''
  pendingUploadFiles.value = []
  documentDeletingId.value = ''
  activeFolderId.value = ''
  selectedFileId.value = ''
  documentQuestion.value = ''
  documentSearching.value = false
  documentSearchStopping.value = false
  documentSearchStopRequested.value = false
  documentSearchSessionId.value = ''
  documentAsking.value = false
  documentStopping.value = false
  documentStopRequested.value = false
  documentAnswerSessionId.value = ''
  documentChatSessions.value = projectId ? restoreDocumentChats(projectId) : {}
  if (!projectId) return
  try {
    await store.loadEngineeringDocuments(projectId)
    const firstKnowledgeBase = store.documentFolders.find(folder => folder.isKnowledgeBase)
    if (firstKnowledgeBase) await selectFolder(firstKnowledgeBase.id)
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || 'WeKnora 工程资料加载失败。')
  }
}, { immediate: true })

watch(documentChatSessions, sessions => {
  const projectId = store.currentProjectId
  if (!projectId) return
  const persistedSessions = Object.fromEntries(
    Object.entries(sessions).map(([key, session]) => [key, {
      sessionId: session.sessionId,
      messages: session.messages.slice(-80),
    }]),
  )
  try {
    sessionStorage.setItem(documentChatStorageKey(projectId), JSON.stringify(persistedSessions))
  } catch {
    // 浏览器会话缓存达到上限时仍保留当前页面中的完整问答，不影响继续提问。
  }
}, { deep: true })

watch(expandedFolderIds, folderIds => {
  const projectId = store.currentProjectId
  if (!projectId) return
  try {
    sessionStorage.setItem(folderExpansionStorageKey(projectId), JSON.stringify(folderIds))
  } catch {
    // 浏览器会话缓存不可用时只影响目录展开状态，不影响资料加载。
  }
}, { deep: true })

function isFolderExpanded(folderId: string) {
  return expandedFolderIds.value.includes(folderId)
}
function toggleFolderExpanded(folderId: string) {
  expandedFolderIds.value = isFolderExpanded(folderId)
    ? expandedFolderIds.value.filter(id => id !== folderId)
    : [...expandedFolderIds.value, folderId]
}
function folderPickerExpandedKeys(folderId: string) {
  const expanded = new Set(store.documentFolders.filter(folder => folder.isKnowledgeBase).map(folder => folder.id))
  let current = store.documentFolders.find(folder => folder.id === folderId)
  while (current?.parentId) {
    expanded.add(current.parentId)
    current = store.documentFolders.find(folder => folder.id === current?.parentId)
  }
  return [...expanded]
}
function renderFolderTreePrefix({ option }: { option: TreeSelectOption }) {
  return h(NIcon, { size: 16 }, { default: () => h(option.isKnowledgeBase ? Database : Folder) })
}
function selectTreeNode(node: FolderTreeDisplayNode) {
  void selectFolder(node.folderId || node.id)
}
async function selectFolder(folderId: string) {
  if (isSearchActive.value) clearSearch()
  activeFolderId.value = folderId
  selectedFileId.value = ''
  let current = store.documentFolders.find(folder => folder.id === folderId)
  const ancestorIds: string[] = []
  while (current?.parentId) {
    ancestorIds.push(current.parentId)
    current = store.documentFolders.find(folder => folder.id === current?.parentId)
  }
  if (ancestorIds.length) expandedFolderIds.value = [...new Set([...expandedFolderIds.value, ...ancestorIds])]
  try {
    await store.loadEngineeringDocumentFolder(folderId)
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || 'WeKnora 目录资料加载失败。')
  }
}
function selectDocument(file: AttachmentRecord) {
  selectedFileId.value = file.id
  void scrollChatToBottom()
}

function documentChatKey(file: AttachmentRecord) {
  return [store.currentProjectId || 'project', file.knowledgeBaseId || 'knowledge-base', file.id].join(':')
}
function forgetDocumentChat(file: AttachmentRecord) {
  const key = documentChatKey(file)
  if (!documentChatSessions.value[key]) return
  const next = { ...documentChatSessions.value }
  delete next[key]
  documentChatSessions.value = next
}
function normalizedFolderPath(value?: string) {
  return (value || '').replace(/\\/g, '/').split('/').map(segment => segment.trim()).filter(Boolean).join('/')
}
function fileIsInsideFolder(file: AttachmentRecord, folder: DocumentFolderRecord) {
  if (file.knowledgeBaseId !== folder.knowledgeBaseId) return false
  const folderPath = normalizedFolderPath(folder.path)
  const filePath = normalizedFolderPath(file.folderPath)
  return filePath === folderPath || filePath.startsWith(`${folderPath}/`)
}
function descendantFolderIds(folder: DocumentFolderRecord) {
  const folderPath = normalizedFolderPath(folder.path)
  const prefix = `${folderPath}/`
  return store.documentFolders
    .filter(item => (
      item.knowledgeBaseId === folder.knowledgeBaseId
      && normalizedFolderPath(item.path).startsWith(prefix)
    ))
    .map(item => item.id)
}
function documentChatStorageKey(projectId: string) {
  const userId = sessionStorage.getItem('current_user_id') || 'current'
  return `dobby-weknora-chats:${userId}:${projectId}`
}
function folderExpansionStorageKey(projectId: string) {
  const userId = sessionStorage.getItem('current_user_id') || 'current'
  return `dobby-weknora-folders:${userId}:${projectId}`
}
function restoreFolderExpansion(projectId: string) {
  try {
    const value = JSON.parse(sessionStorage.getItem(folderExpansionStorageKey(projectId)) || '[]')
    return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []
  } catch {
    return []
  }
}
function restoreDocumentChats(projectId: string): Record<string, DocumentChatSession> {
  try {
    const saved = JSON.parse(sessionStorage.getItem(documentChatStorageKey(projectId)) || '{}') as Record<string, Partial<DocumentChatSession>>
    const restored: Record<string, DocumentChatSession> = {}
    for (const [key, session] of Object.entries(saved)) {
      const messages = Array.isArray(session.messages)
        ? session.messages.filter(item => item && (item.role === 'user' || item.role === 'assistant') && typeof item.content === 'string')
        : []
      restored[key] = {
        sessionId: typeof session.sessionId === 'string' ? session.sessionId : '',
        messages,
      }
    }
    return restored
  } catch {
    return {}
  }
}
function ensureDocumentChat(file: AttachmentRecord) {
  const key = documentChatKey(file)
  if (!documentChatSessions.value[key]) {
    documentChatSessions.value[key] = { sessionId: '', messages: [] }
  }
  return documentChatSessions.value[key]!
}
function clearActiveDocumentChat() {
  const file = activeDocument.value
  if (!file || documentAsking.value) return
  documentChatSessions.value[documentChatKey(file)] = { sessionId: '', messages: [] }
  documentQuestion.value = ''
  message.success('当前资料的问答记录已清空，下一次提问将创建全新会话。')
  void scrollChatToBottom()
}
function createChatMessage(role: DocumentChatMessage['role'], content: string, failed = false): DocumentChatMessage {
  return {
    id: Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 9),
    role,
    content,
    failed,
  }
}
async function scrollChatToBottom() {
  await nextTick()
  if (chatScrollRef.value) chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
}
function openFolderModal() {
  if (!canManageDocuments.value) {
    message.warning('请先在工程配置中创建并选择一个项目。')
    return
  }
  const preferredFolder = store.documentFolders.find(folder => folder.id === activeFolderId.value)
    || store.documentFolders.find(folder => folder.isKnowledgeBase)
    || store.documentFolders[0]
  resumeUploadAfterFolderModal.value = false
  newFolderParentId.value = preferredFolder?.id || ''
  newFolderName.value = ''
  folderModalOpen.value = true
}
function openFolderModalFromUpload() {
  if (documentUploading.value) return
  const preferredFolder = store.documentFolders.find(folder => folder.id === uploadFolderId.value)
    || store.documentFolders.find(folder => folder.id === activeFolderId.value)
    || store.documentFolders.find(folder => folder.isKnowledgeBase)
    || store.documentFolders[0]
  resumeUploadAfterFolderModal.value = true
  newFolderParentId.value = preferredFolder?.id || ''
  newFolderName.value = ''
  uploadModalOpen.value = false
  folderModalOpen.value = true
}
function closeFolderModal() {
  if (folderCreating.value) return
  const shouldResumeUpload = resumeUploadAfterFolderModal.value
  folderModalOpen.value = false
  newFolderName.value = ''
  newFolderParentId.value = ''
  resumeUploadAfterFolderModal.value = false
  if (shouldResumeUpload) uploadModalOpen.value = true
}
async function createFolder() {
  if (folderCreating.value || !newFolderParentId.value || !newFolderName.value.trim()) return
  const parentId = newFolderParentId.value
  folderCreating.value = true
  try {
    const created = await store.createDocumentFolder({
      name: newFolderName.value,
      parentId,
    })
    const shouldResumeUpload = resumeUploadAfterFolderModal.value
    expandedFolderIds.value = [...new Set([...expandedFolderIds.value, parentId])]
    folderModalOpen.value = false
    newFolderName.value = ''
    newFolderParentId.value = ''
    resumeUploadAfterFolderModal.value = false
    if (shouldResumeUpload) {
      uploadFolderId.value = created.id
      uploadModalOpen.value = true
    } else {
      await selectFolder(created.id)
    }
    message.success('目录已创建')
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '目录创建失败。')
  } finally {
    folderCreating.value = false
  }
}
function confirmDeleteDocument(file: AttachmentRecord) {
  if (documentDeletingId.value || folderDeleting.value) return
  if (documentAsking.value && activeDocument.value?.id === file.id) {
    message.warning('请先终止当前资料的问答，再删除该文件。')
    return
  }
  dialog.warning({
    title: '删除文件',
    content: `确认永久删除“${file.fileName}”吗？文件将从 WeKnora 中移除，删除后无法恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    maskClosable: false,
    onPositiveClick: () => deleteDocument(file),
  })
}
async function deleteDocument(file: AttachmentRecord) {
  if (documentDeletingId.value || folderDeleting.value) return
  const projectId = store.currentProjectId
  if (!projectId) return
  const preferredFolderId = activeFolderId.value || file.folderId || ''
  const preferredFolder = store.documentFolders.find(item => item.id === preferredFolderId)
  const fileFolder = store.documentFolders.find(item => item.id === file.folderId)
  const fallbackParentId = preferredFolder?.parentId || fileFolder?.parentId || ''
  documentDeletingId.value = file.id
  try {
    await store.deleteEngineeringDocument(file.id)
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '文件删除失败。')
    documentDeletingId.value = ''
    return
  }

  documentSearchResults.value = documentSearchResults.value.filter(item => item.id !== file.id)
  if (selectedFileId.value === file.id) {
    selectedFileId.value = ''
    documentQuestion.value = ''
  }
  forgetDocumentChat(file)

  try {
    await store.loadEngineeringDocuments(projectId, true)
    const target = store.documentFolders.find(item => item.id === preferredFolderId)
      || store.documentFolders.find(item => item.id === fallbackParentId)
      || store.documentFolders.find(item => item.isKnowledgeBase && item.knowledgeBaseId === file.knowledgeBaseId)
    if (target) {
      activeFolderId.value = target.id
      await store.loadEngineeringDocumentFolder(target.id, true)
    } else {
      activeFolderId.value = ''
    }
    message.success(`文件“${file.fileName}”已删除`)
  } catch (error: any) {
    message.warning(`文件已删除，但目录刷新失败：${error.response?.data?.detail || error.message || '请稍后刷新页面。'}`)
  } finally {
    documentDeletingId.value = ''
  }
}
function confirmDeleteFolder() {
  const folder = activeFolder.value
  if (!folder || folder.isKnowledgeBase) {
    message.warning('知识库根节点不能删除。')
    return
  }
  if (documentAsking.value) {
    message.warning('请先终止当前资料的问答，再删除目录。')
    return
  }
  const nestedFolderCount = descendantFolderIds(folder).length
  const documentCount = Math.max(folder.totalCount || 0, folder.documentCount || 0)
  const content = documentCount || nestedFolderCount
    ? `“${folder.name}”包含 ${documentCount} 份资料、${nestedFolderCount} 个子目录。确认永久删除该目录及全部内容吗？此操作无法恢复。`
    : `确认永久删除空目录“${folder.name}”吗？此操作无法恢复。`
  dialog.warning({
    title: '删除目录',
    content,
    positiveText: documentCount || nestedFolderCount ? '删除全部' : '删除',
    negativeText: '取消',
    positiveButtonProps: { type: 'error' },
    maskClosable: false,
    onPositiveClick: () => deleteFolder(folder),
  })
}
async function deleteFolder(folder: DocumentFolderRecord) {
  if (folderDeleting.value || documentDeletingId.value) return
  const projectId = store.currentProjectId
  if (!projectId) return
  folderDeleting.value = true
  const nestedIds = new Set([folder.id, ...descendantFolderIds(folder)])
  const affectedFiles = [...new Map(
    [...store.attachments, ...documentSearchResults.value]
      .filter(file => fileIsInsideFolder(file, folder))
      .map(file => [file.id, file]),
  ).values()]
  try {
    const parentId = folder.parentId || ''
    await store.deleteDocumentFolder(folder.id)
    expandedFolderIds.value = expandedFolderIds.value.filter(id => !nestedIds.has(id))
    activeFolderId.value = ''
    selectedFileId.value = ''
    documentQuestion.value = ''
    documentSearchResults.value = documentSearchResults.value.filter(file => !fileIsInsideFolder(file, folder))
    for (const file of affectedFiles) forgetDocumentChat(file)
    const target = store.documentFolders.find(item => item.id === parentId)
      || store.documentFolders.find(item => item.isKnowledgeBase && item.knowledgeBaseId === folder.knowledgeBaseId)
    if (target) await selectFolder(target.id)
    message.success(`目录“${folder.name}”及其中内容已删除`)
  } catch (error: any) {
    try {
      await store.loadEngineeringDocuments(projectId, true)
    } catch {
      // 递归删除可能已完成一部分，保留原始错误并让用户稍后刷新。
    }
    message.error(error.response?.data?.detail || error.message || '目录删除失败。')
  } finally {
    folderDeleting.value = false
  }
}
function openUploadModal() {
  if (!canManageDocuments.value) {
    message.warning('请先在工程配置中创建并选择一个项目。')
    return
  }
  const preferredFolder = store.documentFolders.find(folder => folder.id === activeFolderId.value)
    || store.documentFolders.find(folder => folder.isKnowledgeBase)
    || store.documentFolders[0]
  uploadFolderId.value = preferredFolder?.id || ''
  pendingUploadFiles.value = []
  uploadModalOpen.value = true
}
function fileExtension(fileName: string) {
  return fileName.includes('.') ? (fileName.split('.').pop() || 'FILE').slice(0, 5).toUpperCase() : 'FILE'
}
function formatFileSize(bytes: number) {
  if (bytes <= 0) return '0 KB'
  return bytes < 1024 * 1024 ? Math.max(1, Math.round(bytes / 1024)) + ' KB' : (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
function formatDate(value: string) {
  if (!value) return '未提供'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
function remoteFileSizeLabel(bytes: number) {
  return bytes > 0 ? formatFileSize(bytes) : '未提供'
}
function documentIconKind(file: AttachmentRecord) {
  const extension = fileExtension(file.fileName).toLowerCase()
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
function parseStatusLabel(status?: string) {
  if (!status) return '未提供'
  const labels: Record<string, string> = {
    pending: '等待解析',
    processing: '解析中',
    parsing: '解析中',
    ready: '已解析',
    parsed: '已解析',
    completed: '已解析',
    success: '已解析',
    failed: '解析失败',
    error: '解析失败',
  }
  return labels[status.toLowerCase()] || status
}
function queueUploadFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const selectedFiles = Array.from(input.files || [])
  if (!selectedFiles.length) return
  const existingKeys = new Set(pendingUploadFiles.value.map(file => file.name + '-' + file.size + '-' + file.lastModified))
  pendingUploadFiles.value = [...pendingUploadFiles.value, ...selectedFiles.filter(file => !existingKeys.has(file.name + '-' + file.size + '-' + file.lastModified))]
  input.value = ''
}
function removePendingUpload(index: number) {
  pendingUploadFiles.value = pendingUploadFiles.value.filter((_, fileIndex) => fileIndex !== index)
}
function closeUploadModal() {
  if (documentUploading.value) return
  uploadModalOpen.value = false
  uploadFolderId.value = ''
  pendingUploadFiles.value = []
}
async function uploadDocuments() {
  if (!pendingUploadFiles.value.length || !uploadTargetAvailable.value || documentUploading.value) return
  const files = [...pendingUploadFiles.value]
  const targetFolderId = uploadFolderId.value
  let completed = 0
  let uploadError: any = null
  let refreshError = ''
  documentUploading.value = true
  try {
    for (const file of files) {
      try {
        await store.uploadAttachment(file, 'WeKnora', targetFolderId)
        completed += 1
      } catch (error: any) {
        uploadError = error
        break
      }
    }

    if (completed) {
      try {
        await store.loadEngineeringDocuments(store.currentProjectId, true)
        await store.loadEngineeringDocumentFolder(targetFolderId, true)
      } catch (error: any) {
        refreshError = error.response?.data?.detail || error.message || '资料已上传，但列表刷新失败。'
      }
    }

    if (uploadError) {
      pendingUploadFiles.value = files.slice(completed)
      const detail = uploadError.response?.data?.detail || uploadError.message || '资料上传失败，请检查 WeKnora 服务连接。'
      const refreshSuffix = refreshError ? '；同时列表刷新失败：' + refreshError : ''
      message.error(completed ? '已提交 ' + completed + ' 份，其余资料上传失败：' + detail + refreshSuffix : detail)
    } else {
      activeFolderId.value = targetFolderId
      selectedFileId.value = store.attachments.find(item => item.fileName === files[0]?.name)?.id || ''
      pendingUploadFiles.value = []
      uploadModalOpen.value = false
      uploadFolderId.value = ''
      if (refreshError) {
        message.warning('已提交 ' + completed + ' 份资料至 WeKnora，但列表刷新失败：' + refreshError)
      } else {
        message.success('已提交 ' + completed + ' 份资料至 WeKnora')
      }
    }
  } finally {
    documentUploading.value = false
  }
}
async function searchDocuments() {
  if (!documentSearchKeyword.value) {
    clearSearch()
    return
  }
  documentSearching.value = true
  documentSearchStopping.value = false
  documentSearchStopRequested.value = false
  documentSearchSessionId.value = ''
  try {
    const rawKeyword = documentSearchKeyword.value.trim()
    const terms = domainSearchTerms.filter(term => rawKeyword.toLowerCase().includes(term.toLowerCase()))
    const searchTerm = terms[0] || rawKeyword
    const session = await store.createEngineeringDocumentSession()
    documentSearchSessionId.value = session.session_id
    if (documentSearchStopRequested.value) return
    const [remoteResults, answer] = await Promise.all([
      store.searchDocuments(searchTerm),
      store.askEngineeringDocuments(rawKeyword, [], [], session.session_id),
    ])
    const resultMap = new Map<string, AttachmentRecord>()
    for (const file of remoteResults) resultMap.set(file.id, file)
    documentSearchResults.value = [...resultMap.values()]
    isSearchActive.value = true
    const firstResult = documentSearchResults.value[0]
    selectedFileId.value = firstResult?.id || ''
    if (firstResult && answer.answer?.trim()) {
      const chat = ensureDocumentChat(firstResult)
      chat.sessionId = answer.session_id || chat.sessionId
      chat.messages.push(createChatMessage('user', rawKeyword))
      chat.messages.push(createChatMessage(
        'assistant',
        answer.answer.trim() + (documentSearchStopRequested.value ? '\n\n（回答已终止）' : ''),
      ))
      void scrollChatToBottom()
    }
  } catch (error: any) {
    if (!documentSearchStopRequested.value) {
      message.error(error.response?.data?.detail || '资料检索失败，请稍后重试。')
    }
  } finally {
    documentSearching.value = false
    documentSearchStopping.value = false
    documentSearchStopRequested.value = false
    documentSearchSessionId.value = ''
  }
}
async function stopDocumentSearch() {
  if (!documentSearching.value || documentSearchStopping.value) return
  documentSearchStopRequested.value = true
  documentSearchStopping.value = true
  const sessionId = documentSearchSessionId.value
  if (!sessionId) return
  try {
    const result = await store.stopEngineeringDocumentAnswer(sessionId)
    if (!result.stopped) {
      documentSearchStopRequested.value = false
      documentSearchStopping.value = false
      message.info(result.message || '当前没有正在生成的回答。')
      return
    }
    message.info('已发送终止请求，正在保留已经生成的内容。')
  } catch (error: any) {
    documentSearchStopRequested.value = false
    documentSearchStopping.value = false
    message.error(error.response?.data?.detail || error.message || '终止回答失败。')
  }
}
function clearSearch() {
  documentSearchKeyword.value = ''
  documentSearchResults.value = []
  isSearchActive.value = false
  selectedFileId.value = ''
}
async function askAboutDocument(question: string) {
  const file = activeDocument.value
  const normalizedQuestion = question.trim()
  if (!file || !normalizedQuestion || documentAsking.value) return
  const chat = ensureDocumentChat(file)
  chat.messages.push(createChatMessage('user', normalizedQuestion))
  documentAsking.value = true
  documentStopping.value = false
  documentStopRequested.value = false
  documentAnswerSessionId.value = chat.sessionId
  void scrollChatToBottom()
  try {
    if (!chat.sessionId) {
      const session = await store.createEngineeringDocumentSession()
      chat.sessionId = session.session_id
      documentAnswerSessionId.value = chat.sessionId
    }
    if (documentStopRequested.value) {
      chat.messages.push(createChatMessage('assistant', '回答已终止。'))
      return
    }
    const answer = await store.askEngineeringDocuments(
      normalizedQuestion,
      [file.id],
      file.knowledgeBaseId ? [file.knowledgeBaseId] : [],
      chat.sessionId,
    )
    chat.sessionId = answer.session_id || chat.sessionId
    const content = answer.answer?.trim()
    chat.messages.push(createChatMessage(
      'assistant',
      content
        ? content + (documentStopRequested.value ? '\n\n（回答已终止）' : '')
        : documentStopRequested.value
          ? '回答已终止。'
          : 'WeKnora 未返回可展示的回答。',
    ))
  } catch (error: any) {
    if (documentStopRequested.value) {
      chat.messages.push(createChatMessage('assistant', '回答已终止。'))
    } else {
      const detail = error.response?.data?.detail || error.message || '资料问答失败，请稍后重试。'
      chat.messages.push(createChatMessage('assistant', detail, true))
      message.error(detail)
    }
  } finally {
    documentAsking.value = false
    documentStopping.value = false
    documentStopRequested.value = false
    documentAnswerSessionId.value = ''
    void scrollChatToBottom()
  }
}
async function stopDocumentAnswer() {
  if (!documentAsking.value || documentStopping.value) return
  documentStopRequested.value = true
  documentStopping.value = true
  const sessionId = documentAnswerSessionId.value
  if (!sessionId) return
  try {
    const result = await store.stopEngineeringDocumentAnswer(sessionId)
    if (!result.stopped) {
      documentStopRequested.value = false
      documentStopping.value = false
      message.info(result.message || '当前没有正在生成的回答。')
      return
    }
    message.info('已发送终止请求，正在保留已经生成的内容。')
  } catch (error: any) {
    documentStopRequested.value = false
    documentStopping.value = false
    message.error(error.response?.data?.detail || error.message || '终止回答失败。')
  }
}
async function sendDocumentQuestion() {
  if (!documentQuestion.value) return
  const question = documentQuestion.value
  documentQuestion.value = ''
  await askAboutDocument(question)
}
</script>

<style scoped>
.document-library {
  height: calc(100dvh - var(--header-height, 56px));
  min-height: 0;
  box-sizing: border-box;
  overflow: hidden;
  padding: 14px;
  color: var(--text-primary);
  background:
    radial-gradient(circle at 84% 4%, rgba(15, 118, 110, .08), transparent 28rem),
    linear-gradient(180deg, #f5f7f4, #edf1ee);
}

.dobby-workspace {
  display: grid;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #dce5e2;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 16px 36px rgba(24, 58, 52, .07);
}

.dobby-topbar {
  display: grid;
  grid-template-columns: auto minmax(260px, 1fr) auto;
  align-items: center;
  gap: 18px;
  padding: 13px 16px;
  border-bottom: 1px solid #e0e8e5;
  background: rgba(255, 255, 255, .96);
}
.dobby-identity { display: flex; align-items: center; min-width: 238px; gap: 10px; }
.dobby-avatar,
.chat-avatar {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  color: #fff;
  background: #123f3d;
  box-shadow: 0 6px 15px rgba(18, 63, 61, .18);
}
.dobby-identity > div { display: grid; min-width: 0; gap: 2px; }
.dobby-identity span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .04em; }
.dobby-identity strong,
.chat-head > strong { overflow: hidden; color: #173235; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.dobby-identity em,
.chat-head em {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: 4px;
  color: #5b7772;
  font-size: 12px;
  font-style: normal;
  white-space: nowrap;
}
.dobby-identity em i,
.chat-head em i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10a079;
  box-shadow: 0 0 0 3px rgba(16, 160, 121, .1);
}
.dobby-identity em.is-loading i { background: #c98118; box-shadow: 0 0 0 3px rgba(201, 129, 24, .12); }
.dobby-identity em.is-error i { background: #c45445; box-shadow: 0 0 0 3px rgba(196, 84, 69, .12); }
.dobby-search {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  min-width: 0;
  gap: 8px;
  padding: 4px 4px 4px 11px;
  border: 1px solid #bfd2cd;
  border-radius: 8px;
  background: #f8fbfa;
  transition: border-color .18s ease, box-shadow .18s ease, background .18s ease;
}
.dobby-search:focus-within { border-color: #3d8177; background: #fff; box-shadow: 0 0 0 3px rgba(15, 118, 110, .1); }
.dobby-search > svg { color: #66817d; }
.dobby-search input { min-width: 0; height: 34px; border: 0; outline: 0; color: #173235; background: transparent; font: inherit; font-size: 13px; }
.dobby-search button,
.primary-action,
.secondary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 6px;
  padding: 8px 11px;
  font: inherit;
  font-size: 12px;
  font-weight: 780;
  cursor: pointer;
  white-space: nowrap;
}
.dobby-search button { border: 0; color: #fff; background: #173f3e; }
.dobby-search button.is-stop { background: #b34f36; }
.topbar-actions { display: flex; align-items: center; gap: 7px; }
.primary-action { border: 1px solid #d45f1f; color: #fff; background: #d45f1f; box-shadow: 0 5px 12px rgba(212, 95, 31, .16); }
.secondary-action { border: 1px solid #b9cdc8; color: #315e58; background: #fff; }
.secondary-action.is-danger { border-color: #e3b9b4; color: #b44735; background: #fff9f8; }
button:disabled { opacity: .5; cursor: not-allowed; box-shadow: none; }
.dobby-search button:not(:disabled):hover,
.primary-action:not(:disabled):hover,
.secondary-action:not(:disabled):hover { filter: brightness(.96); transform: translateY(-1px); }

.dobby-workspace-grid {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-columns: 250px minmax(0, 1fr);
}

.workspace-main {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-columns: minmax(480px, 1.15fr) minmax(340px, .85fr);
  grid-template-rows: minmax(0, 1fr);
  overflow: hidden;
  background: #fff;
}

.folder-rail {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #e0e8e5;
  background: linear-gradient(180deg, #f8faf9, #f3f7f5);
}
.folder-rail-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 15px 13px 12px; }
.folder-rail-head > div { display: grid; min-width: 0; gap: 4px; }
.folder-rail-head span { color: #6f8580; font-size: 12px; font-weight: 800; letter-spacing: .05em; }
.folder-rail-head strong { overflow: hidden; color: #1c3936; font-size: 14px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.folder-count-legend { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 8px; color: #788a86; font-size: 12px; font-weight: 600; letter-spacing: 0; line-height: 1; }
.folder-count-legend > span { display: inline-flex; align-items: center; gap: 4px; color: inherit; font-size: 12px; font-weight: inherit; letter-spacing: 0; white-space: nowrap; }
.legend-swatch { display: inline-block; width: 7px; height: 7px; flex: 0 0 7px; border-radius: 2px; }
.legend-swatch.is-total { background: #0f766e; }
.legend-swatch.is-direct { background: #b7791f; }
.folder-tree-nav { display: grid; flex: 1 1 auto; min-height: 0; align-content: start; overflow: auto; padding: 2px 8px 12px; scrollbar-gutter: stable; }
.folder-tree-loading { width: 100%; height: 100%; min-height: 100%; box-sizing: border-box; padding: 24px 8px; }
.library-loading-state { display: grid; width: 100%; min-height: 220px; place-content: center; justify-items: center; gap: 14px; color: #607a75; text-align: center; }
.library-loading-state.is-compact { min-height: 100%; gap: 10px; }
.library-loading-state.is-compact > strong { font-size: 12px; font-weight: 750; }
.library-loading-stack { position: relative; display: block; width: 54px; height: 48px; }
.library-loading-state.is-compact .library-loading-stack { transform: scale(.82); }
.library-loading-stack > i { position: absolute; display: block; width: 38px; height: 42px; box-sizing: border-box; border: 1px solid rgba(77, 126, 118, .24); border-radius: 7px; background: #eef5f3; box-shadow: 0 8px 18px rgba(35, 84, 76, .07); animation: library-loading-float 1.55s ease-in-out infinite; }
.library-loading-stack > i::before,
.library-loading-stack > i::after { content: ''; position: absolute; left: 9px; display: block; height: 3px; border-radius: 2px; background: #bfd6d0; }
.library-loading-stack > i::before { top: 12px; width: 18px; }
.library-loading-stack > i::after { top: 20px; width: 13px; box-shadow: 0 8px 0 #d2e2de; }
.library-loading-stack > i:nth-child(1) { left: 0; top: 5px; opacity: .42; animation-delay: -.52s; }
.library-loading-stack > i:nth-child(2) { left: 8px; top: 2px; opacity: .68; animation-delay: -.26s; }
.library-loading-stack > i:nth-child(3) { left: 16px; top: 0; border-color: rgba(28, 114, 101, .28); background: #f8fbfa; }
.library-loading-text { display: grid; justify-items: center; gap: 4px; }
.library-loading-text strong { color: #315a54; font-size: 13px; font-weight: 800; }
.library-loading-text > span { color: #81928e; font-size: 12px; line-height: 1.5; }
.tree-row { display: flex; width: max-content; min-width: 100%; align-items: center; }
.tree-depth-1 { padding-left: 12px; }.tree-depth-2 { padding-left: 24px; }.tree-depth-3 { padding-left: 36px; }.tree-depth-4 { padding-left: 48px; }
.tree-toggle,
.tree-spacer { flex: 0 0 21px; width: 21px; height: 31px; }
.tree-toggle { display: grid; place-items: center; border: 0; border-radius: 4px; padding: 0; color: #758b87; background: transparent; cursor: pointer; }
.tree-toggle:hover { color: #174f49; background: #e6f0ed; }
.tree-item {
  display: flex;
  flex: 1 0 auto;
  min-width: max-content;
  align-items: center;
  gap: 7px;
  height: 32px;
  border: 0;
  border-radius: 6px;
  padding: 0 8px 0 5px;
  color: #49635f;
  background: transparent;
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.tree-item > svg { color: #cf861b; }.tree-root-row .tree-item > svg { color: #1b746a; }
.tree-item span { flex: 0 0 auto; white-space: nowrap; }
.tree-counts { display: inline-grid; min-width: 48px; grid-template-columns: repeat(2, minmax(18px, auto)); align-items: center; justify-content: end; gap: 4px; font-size: 12px; font-variant-numeric: tabular-nums; line-height: 1; text-align: right; }
.tree-counts b { font-size: 12px; font-weight: 850; }
.tree-count-total { color: #0f766e; }
.tree-count-direct { color: #b7791f; }
.tree-item:hover { color: #173b37; background: #eaf2ef; }
.tree-item.is-active { color: #173b37; background: #dcece7; font-weight: 800; box-shadow: inset 3px 0 #0f766e; }
.tree-item.is-library-root { height: 36px; color: #173f3e; background: rgba(225, 239, 234, .72); font-weight: 850; }
.tree-item.is-library-root > svg { color: #0f766e; }
.tree-item.is-library-root:hover { background: #deeee9; }

.document-queue { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; border-right: 1px solid #dce6e3; background: #fff; }
.search-state { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 18px; border-bottom: 1px solid #d9e8e3; color: #285d57; background: #f0f8f5; font-size: 12px; }
.search-state button { border: 0; padding: 0; color: #0f766e; background: transparent; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; }

.library-stream { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; overflow: hidden; }
.document-file-scroll { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; overflow: auto; scrollbar-gutter: stable; }
.document-file-list { display: flex; min-width: 0; flex: 0 0 auto; flex-direction: column; }
.document-file-list-head,
.document-file-row {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(160px, 1fr) 94px 68px 64px 38px;
  align-items: center;
  column-gap: 10px;
  box-sizing: border-box;
}
.document-file-list-head {
  position: sticky;
  top: 0;
  z-index: 2;
  min-height: 34px;
  padding: 0 12px;
  border-bottom: 1px solid #dbe5e2;
  color: #667b76;
  background: rgba(248, 250, 249, .97);
  box-shadow: 0 1px 0 rgba(31, 69, 63, .03);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
  backdrop-filter: blur(8px);
}
.document-file-list-head > span:not(:first-child) { border-left: 1px solid #e2e9e7; padding-left: 10px; }
.document-file-list-head > span:last-child { padding-left: 0; text-align: center; }
.document-file-row {
  width: 100%;
  min-height: 52px;
  border: 0;
  border-bottom: 1px solid #e7ecea;
  padding: 7px 12px;
  color: inherit;
  background: #fff;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background .15s ease, box-shadow .15s ease;
}
.document-file-row:hover { background: #f1f7f5; }
.document-file-row.active { background: #deeeea; box-shadow: inset 3px 0 #0f766e; }
.document-file-row.is-deleting { opacity: .58; cursor: wait; }
.document-file-row:focus-visible { outline: 2px solid rgba(15, 118, 110, .45); outline-offset: -2px; }
.document-file-row > * { min-width: 0; }
.document-file-name { display: grid; min-width: 0; grid-template-columns: 34px minmax(0, 1fr); align-items: center; gap: 8px; }
.document-file-icon { display: grid; width: 30px; height: 34px; place-items: center; }
.document-file-icon > img { width: 30px; height: 30px; }
.document-file-name strong {
  min-width: 0;
  color: #193a36;
  font-size: 12px;
  font-weight: 760;
  line-height: 1.4;
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: normal;
}
.document-file-date,
.document-file-size { overflow: hidden; color: #748782; font-size: 12px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.document-file-type { display: grid; min-width: 0; gap: 2px; }
.document-file-type b { overflow: hidden; color: #496963; font-size: 12px; font-weight: 780; text-overflow: ellipsis; white-space: nowrap; }
.document-file-type em { overflow: hidden; color: #16806a; font-size: 12px; font-style: normal; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.document-file-size { color: #45645e; font-weight: 720; }
.document-file-actions { display: grid; place-items: center; }
.document-file-actions button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 5px;
  padding: 0;
  color: #a65346;
  background: transparent;
  cursor: pointer;
  transition: border-color .15s ease, color .15s ease, background .15s ease;
}
.document-file-actions button:not(:disabled):hover { border-color: #e1bbb5; color: #a43f31; background: #fff5f3; }
.document-loading { display: grid; flex: 1 1 auto; min-height: 220px; box-sizing: border-box; place-items: center; }
.document-empty { display: grid; flex: 1 1 auto; min-height: 220px; box-sizing: border-box; place-content: center; justify-items: center; gap: 8px; color: #7a8e89; text-align: center; }
.document-empty strong { color: #385b56; font-size: 14px; }
.document-empty p { max-width: 40ch; margin: 0 0 6px; font-size: 12px; line-height: 1.6; }
.document-empty button { display: inline-flex; align-items: center; gap: 7px; border: 0; border-radius: 7px; padding: 10px 14px; color: #fff; background: #d45f1f; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; box-shadow: 0 7px 15px rgba(212, 95, 31, .17); }

.document-chat { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; background: #f6f9f8; }
.chat-head { display: flex; flex: 0 0 auto; align-items: center; gap: 9px; padding: 11px 15px; border-bottom: 1px solid #dfe8e5; background: #fff; }
.chat-avatar { width: 34px; height: 34px; border-radius: 9px; }
.chat-head > strong { flex: 1 1 auto; min-width: 0; }
.chat-loading { display: grid; flex: 1 1 auto; min-height: 220px; box-sizing: border-box; place-items: center; }
.chat-clear {
  flex: 0 0 auto;
  border: 1px solid #d3dfdc;
  border-radius: 5px;
  padding: 5px 7px;
  color: #627872;
  background: #fff;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}
.chat-clear:not(:disabled):hover { border-color: #b9ccc7; color: #315e58; background: #f3f8f6; }
.chat-head em { margin-left: auto; }
.chat-head em.is-loading i { background: #c98118; box-shadow: 0 0 0 3px rgba(201, 129, 24, .12); }
.chat-scroll { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 11px 15px; scrollbar-gutter: stable; }
.dobby-message { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; margin-top: 9px; }
.dobby-message > span { display: grid; width: 27px; height: 27px; place-items: center; border-radius: 7px; color: #fff; background: #173f3e; }
.dobby-message > div { padding: 9px 11px; border: 1px solid #dbe6e3; border-radius: 3px 9px 9px 9px; background: #fff; }
.dobby-message small { color: #0f766e; font-size: 12px; font-weight: 850; }
.dobby-message p { margin: 4px 0 0; color: #506963; font-size: 12px; line-height: 1.65; white-space: pre-wrap; }
.document-chat-message { margin-top: 9px; }
.document-chat-message.is-assistant { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; }
.document-chat-message.is-assistant > span { display: grid; width: 27px; height: 27px; place-items: center; border-radius: 7px; color: #fff; background: #173f3e; }
.document-chat-message > div { min-width: 0; max-width: 92%; padding: 9px 11px; border: 1px solid #dbe6e3; background: #fff; }
.document-chat-message.is-assistant > div { border-radius: 3px 9px 9px 9px; }
.document-chat-message.is-user { display: flex; justify-content: flex-end; }
.document-chat-message.is-user > div { border-color: #bcd8d1; border-radius: 9px 3px 9px 9px; background: #e8f3f0; }
.document-chat-message p { margin: 0; color: #405e58; font-size: 12px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.document-chat-message.is-failed > div { border-color: #e6c8c2; background: #fff7f5; }
.document-chat-message.is-failed p { color: #a34f43; }
.document-chat-message.is-pending p { color: #728681; animation: chat-answer-pulse 1.25s ease-in-out infinite; }
.remote-description-empty { display: grid; gap: 5px; margin-top: 9px; padding: 10px; border: 1px dashed #cddbd7; border-radius: 7px; color: #6f837e; background: #f5f8f7; }
.remote-description-empty strong { color: #355a54; font-size: 12px; }
.remote-description-empty p { margin: 0; font-size: 12px; line-height: 1.55; }
.assistant-suggestions { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
.assistant-suggestions button { border: 1px solid #c9dad5; border-radius: 5px; padding: 6px 8px; color: #315e58; background: #fff; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; transition: border-color .18s ease, background .18s ease, transform .18s ease; }
.assistant-suggestions button:not(:disabled):hover { border-color: #73a399; color: #0f6d64; background: #f2f8f6; transform: translateY(-1px); }
.assistant-suggestions button:not(:disabled):active { transform: translateY(0); }
.assistant-composer { display: grid; flex: 0 0 auto; grid-template-columns: minmax(0, 1fr) 38px; gap: 7px; padding: 9px 14px 11px; border-top: 1px solid #dfe8e5; background: #fff; }
.assistant-composer textarea { min-height: 38px; max-height: 72px; resize: none; box-sizing: border-box; padding: 9px; border: 1px solid #cddbd7; border-radius: 6px; color: #254942; background: #f9fbfa; font: inherit; font-size: 12px; line-height: 1.5; }
.assistant-composer button { display: grid; place-items: center; border: 0; border-radius: 6px; color: #fff; background: #173f3e; cursor: pointer; transition: background .18s ease, transform .18s ease; }
.assistant-composer button:not(:disabled):hover { background: #0f5551; transform: translateY(-1px); }
.assistant-composer button:not(:disabled):active { transform: translateY(0); }
.assistant-composer button.is-stop { background: #b34f36; }
.assistant-composer button.is-stop:not(:disabled):hover { background: #943d29; }
.assistant-composer button:disabled { opacity: .58; cursor: not-allowed; }
.chat-empty { display: grid; flex: 1 1 auto; place-content: center; justify-items: center; gap: 7px; padding: 20px; color: #77908a; text-align: center; }
.chat-empty strong { color: #315651; font-size: 13px; }
.chat-empty p { max-width: 40ch; margin: 0; font-size: 12px; line-height: 1.6; }

.library-modal-backdrop { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center; padding: 24px; background: rgba(15, 32, 35, .44); backdrop-filter: blur(3px); }
.library-modal { width: min(100%, 470px); max-height: calc(100dvh - 48px); overflow: auto; padding: 20px; border: 1px solid rgba(28, 56, 57, .18); border-radius: 12px; background: #fff; box-shadow: 0 22px 56px rgba(15, 39, 42, .26); }
.library-modal-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 13px; }.library-modal-head > div { display: flex; min-width: 0; align-items: baseline; gap: 9px; }.library-modal-head span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .04em; }.library-modal-head h2 { margin: 0; color: #173235; font-size: 17px; }.modal-close,.modal-secondary,.modal-primary { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border-radius: 6px; padding: 8px 12px; font: inherit; font-size: 12px; font-weight: 780; cursor: pointer; }.modal-close,.modal-secondary { border: 1px solid #cad8d4; color: #536e69; background: #fff; }.modal-primary { border: 0; color: #fff; background: #d45f1f; }
.upload-modal { display: flex; width: min(100%, 650px); height: min(610px, calc(100dvh - 48px)); flex-direction: column; overflow: hidden; }.upload-modal > .library-modal-head { flex: 0 0 auto; }.upload-form { display: grid; flex: 1 1 auto; min-height: 0; grid-template-rows: auto auto auto minmax(0, 1fr) auto; gap: 12px; }
.upload-weknora-note { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 9px; padding: 10px; border: 1px solid #bdd8d1; border-radius: 7px; color: #0f766e; background: #eaf5f1; }.upload-weknora-note > div { display: grid; gap: 3px; }.upload-weknora-note strong { color: #174b45; font-size: 12px; }.upload-weknora-note span { color: #5e7772; font-size: 12px; line-height: 1.45; }
.upload-target-field { display: grid; gap: 6px; color: #566f6a; font-size: 12px; font-weight: 750; }
.upload-target-field :deep(.n-base-selection) { --n-border: 1px solid #cad8d4 !important; --n-border-active: 1px solid #4d8d84 !important; --n-border-focus: 1px solid #4d8d84 !important; --n-border-hover: 1px solid #7eaaa1 !important; --n-box-shadow-active: 0 0 0 2px rgba(15, 118, 110, .12) !important; --n-box-shadow-focus: 0 0 0 2px rgba(15, 118, 110, .12) !important; --n-color: #f9fbfa !important; --n-height: 40px !important; --n-border-radius: 6px !important; }
.upload-target-field :deep(.n-base-selection-label) { font-size: 12px; font-weight: 700; }
.upload-target-field :deep(.n-base-selection-placeholder) { color: #81928e; font-size: 12px; font-weight: 500; }
.folder-tree-create-action { display: flex; width: 100%; min-height: 36px; align-items: center; gap: 7px; border: 0; padding: 7px 10px; color: #17665d; background: transparent; font: inherit; font-size: 12px; font-weight: 780; text-align: left; cursor: pointer; transition: color .16s ease, background .16s ease; }
.folder-tree-create-action:not(:disabled):hover { color: #0f554e; background: #edf6f3; }
.folder-tree-create-action:disabled { opacity: .55; cursor: not-allowed; }
.folder-create-form { display: grid; gap: 13px; }.folder-name-field { display: grid; gap: 6px; color: #566f6a; font-size: 12px; font-weight: 750; }.folder-name-field input { width: 100%; min-width: 0; box-sizing: border-box; padding: 9px 10px; border: 1px solid #cad8d4; border-radius: 6px; color: #173235; background: #f9fbfa; font: inherit; font-size: 12px; }
.upload-queue-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; }.upload-queue-head > div { display: grid; gap: 3px; }.upload-queue-head strong { color: #294d47; font-size: 12px; }.upload-queue-head span { color: #7a8d88; font-size: 12px; }
.upload-picker { display: inline-flex; align-items: center; justify-content: center; border: 1px solid #7eaaa1; border-radius: 6px; padding: 7px 10px; color: #17665d; background: #f2f8f6; font-size: 12px; font-weight: 780; cursor: pointer; }.upload-picker input { display: none; }
.upload-queue { display: grid; min-height: 0; align-content: start; gap: 6px; margin: 0; padding: 0; overflow: auto; list-style: none; scrollbar-gutter: stable; }.upload-queue li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 9px; padding: 8px 10px; border: 1px solid #e0e8e5; border-radius: 7px; background: #fbfcfc; }.upload-file-type { display: grid; min-width: 42px; min-height: 32px; place-items: center; border-radius: 5px; color: #3d6862; background: #e7f1ee; font-size: 12px; font-weight: 850; }.upload-queue li > div { display: grid; min-width: 0; gap: 3px; }.upload-queue li strong { overflow: hidden; color: #294842; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.upload-queue li div span { color: #7c8f8a; font-size: 12px; }.upload-queue li button { border: 0; padding: 5px; color: #b9532b; background: transparent; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; }
.upload-queue-empty { display: grid; min-height: 0; place-content: center; justify-items: center; gap: 7px; padding: 20px; border: 1px dashed #c8d8d4; border-radius: 8px; color: #7c8e8a; text-align: center; }.upload-queue-empty strong { color: #3b5d57; font-size: 12px; }.upload-queue-empty span { font-size: 12px; }.upload-actions { display: flex; justify-content: flex-end; gap: 7px; padding-top: 2px; }

button:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible { outline: 2px solid rgba(15, 118, 110, .45); outline-offset: 2px; }

@keyframes library-loading-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}
@keyframes chat-answer-pulse {
  0%, 100% { opacity: .58; }
  50% { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .library-loading-stack > i,
  .document-chat-message.is-pending p { animation: none; }
}

@media (max-width: 1180px) {
  .dobby-workspace-grid { grid-template-columns: 220px minmax(0, 1fr); }
  .workspace-main { grid-template-columns: minmax(400px, 1fr) minmax(300px, .76fr); }
  .dobby-topbar { gap: 10px; }
  .dobby-identity { min-width: 205px; }
  .document-file-list-head,
  .document-file-row { grid-template-columns: minmax(140px, 1fr) 86px 58px 56px 34px; column-gap: 8px; }
}
@media (max-width: 960px) {
  .dobby-topbar { grid-template-columns: auto minmax(220px, 1fr); }
  .topbar-actions { grid-column: 1 / -1; justify-content: flex-end; }
  .dobby-workspace-grid { grid-template-columns: minmax(0, 1fr); }
  .folder-rail { display: none; }
}
@media (max-width: 760px) {
  .document-library { height: auto; min-height: calc(100dvh - var(--header-height, 56px)); overflow: visible; padding: 10px; }
  .dobby-workspace { height: auto; overflow: visible; }
  .dobby-topbar { grid-template-columns: 1fr; }
  .dobby-identity { min-width: 0; }
  .dobby-search { grid-row: 2; }
  .topbar-actions { grid-column: auto; }
  .topbar-actions button { flex: 1 1 0; }
  .dobby-workspace-grid { display: block; }
  .workspace-main { display: block; overflow: visible; }
  .document-queue { min-height: 560px; border-right: 0; border-bottom: 1px solid #e0e8e5; }
  .document-chat { min-height: 420px; }
  .library-modal-backdrop { padding: 10px; }
  .library-modal { max-height: calc(100dvh - 20px); padding: 15px; }
  .upload-modal { height: calc(100dvh - 20px); }
}
</style>
