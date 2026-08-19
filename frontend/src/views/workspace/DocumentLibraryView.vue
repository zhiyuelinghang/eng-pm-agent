<template>
  <main class="document-library">
    <section class="dobby-workspace" :aria-busy="knowledgeWorkspaceBlocked">
      <nav class="knowledge-tabs" aria-label="工程资料功能切换">
        <button
          type="button"
          :class="{ active: activeWorkspaceTab === 'chat' }"
          :aria-selected="activeWorkspaceTab === 'chat'"
          role="tab"
          :disabled="knowledgeWorkspaceBlocked"
          @click="switchWorkspaceTab('chat')"
        >
          <n-icon :size="18"><MessageCircle /></n-icon>
          智能问答
        </button>
        <button
          type="button"
          :class="{ active: activeWorkspaceTab === 'files' }"
          :aria-selected="activeWorkspaceTab === 'files'"
          role="tab"
          :disabled="knowledgeWorkspaceBlocked"
          @click="switchWorkspaceTab('files')"
        >
          <n-icon :size="18"><FileText /></n-icon>
          知识库管理
          <span :class="{ 'is-loading': store.engineeringDocumentsLoading }" aria-live="polite">
            <template v-if="store.engineeringDocumentsLoading">
              <n-icon class="knowledge-loading-robot" :size="16"><Robot /></n-icon>
              加载中
            </template>
            <template v-else>{{ totalDocumentCount }}</template>
          </span>
        </button>
      </nav>

      <ProjectKnowledgeChat
        v-show="activeWorkspaceTab === 'chat'"
        :focus-document-id="chatFocusDocumentId"
        :disabled="knowledgeWorkspaceBlocked"
        @document-consumed="chatFocusDocumentId = ''"
        @busy-change="knowledgeChatBusy = $event"
        @ready-change="knowledgeChatReady = $event"
        @locate-reference="locateReferenceDocument"
      />

      <section v-show="activeWorkspaceTab === 'files'" class="file-workspace" aria-label="工程资料文件管理">
        <header class="file-toolbar">
          <form class="file-search" @submit.prevent="searchDocuments">
            <label class="file-search-field">
              <n-icon :size="18"><Search /></n-icon>
              <input
                v-model.trim="documentSearchKeyword"
                :disabled="!canManageDocuments || documentSearching"
                placeholder="搜索文件名或资料内容"
              >
            </label>
            <button type="submit" :disabled="!canManageDocuments || documentSearching">
              {{ documentSearching ? '正在搜索…' : '搜索' }}
            </button>
          </form>

          <div class="file-toolbar-actions">
            <button type="button" class="secondary-action" :disabled="!canManageDocuments || folderCreating || folderUpdating || folderDeleting || documentUploading || Boolean(documentMovingId) || Boolean(documentDeletingId)" @click="openFolderModal">
              <n-icon :size="16"><FolderPlus /></n-icon>
              新建目录
            </button>
            <button
              type="button"
              class="secondary-action"
              :disabled="!activeFolder || activeFolder.isKnowledgeBase || folderUpdating || folderDeleting || folderCreating || documentUploading || Boolean(documentMovingId) || Boolean(documentDeletingId)"
              :title="activeFolder && !activeFolder.isKnowledgeBase ? '移动或重命名选中目录' : '请先在左侧选择一个普通目录'"
              @click="openFolderUpdateModal"
            >
              <n-icon :size="16"><Pencil /></n-icon>
              移动/重命名
            </button>
            <button v-if="activeFolder && !activeFolder.isKnowledgeBase" type="button" class="secondary-action is-danger" :disabled="knowledgeChatBusy || folderDeleting || folderUpdating || folderCreating || documentUploading || Boolean(documentMovingId) || Boolean(documentDeletingId)" @click="confirmDeleteFolder">
              <n-icon :size="16"><Trash /></n-icon>
              {{ folderDeleting ? '正在删除…' : '删除目录' }}
            </button>
            <button type="button" class="primary-action" :disabled="!canManageDocuments || documentUploading || folderCreating || folderUpdating || folderDeleting || Boolean(documentMovingId) || Boolean(documentDeletingId)" @click="openUploadModal">
              <n-icon :size="16"><Paperclip /></n-icon>
              上传资料
            </button>
          </div>
        </header>

        <section class="dobby-workspace-grid">
          <aside class="folder-rail" aria-label="项目资料目录">
            <header class="folder-rail-head">
              <strong>资料库目录</strong>
              <div class="folder-rail-tools">
                <span class="folder-count-legend" aria-label="数量颜色说明">
                  <span><i class="legend-swatch is-total" aria-hidden="true"></i>全部级别</span>
                  <span><i class="legend-swatch is-direct" aria-hidden="true"></i>本级</span>
                </span>
                <button
                  type="button"
                  class="folder-refresh-button"
                  :disabled="documentRefreshing || documentWorkspaceLoading || folderCreating || folderUpdating || folderDeleting || Boolean(documentMovingId) || Boolean(documentDeletingId)"
                  title="刷新目录和文件"
                  aria-label="刷新目录和文件"
                  @click="refreshDocumentLibrary"
                >
                  <n-icon :class="{ 'is-spinning': documentRefreshing }" :size="16"><Refresh /></n-icon>
                </button>
              </div>
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

          <section class="document-queue" aria-label="工程资料文件">
            <div v-if="isSearchActive" class="search-state">
              <span>找到 {{ visibleFiles.length }} 条与“{{ documentSearchKeyword }}”相关的资料</span>
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
                    :class="{ active: activeDocument?.id === file.id, 'is-moving': documentMovingId === file.id, 'is-deleting': documentDeletingId === file.id }"
                    role="option"
                    :aria-selected="activeDocument?.id === file.id"
                    :aria-busy="documentDeletingId === file.id"
                    :data-document-id="file.id"
                    tabindex="0"
                    @click="selectDocument(file)"
                    @keydown.enter.prevent="selectDocument(file)"
                    @keydown.space.prevent="selectDocument(file)"
                  >
                    <span class="document-file-name">
                      <span class="document-file-icon" aria-hidden="true"><DocumentTypeIcon :kind="documentIconKind(file)" /></span>
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
                        class="is-move"
                        :disabled="!canManageDocuments || folderUpdating || folderDeleting || Boolean(documentMovingId) || Boolean(documentDeletingId)"
                        :title="documentMovingId === file.id ? '正在移动' : '移动文件'"
                        :aria-label="documentMovingId === file.id ? `正在移动 ${file.fileName}` : `移动 ${file.fileName}`"
                        @click.stop="openDocumentMoveModal(file)"
                        @keydown.stop
                      >
                        <n-icon :size="16"><ArrowsLeftRight /></n-icon>
                      </button>
                      <button
                        type="button"
                        class="is-chat"
                        :disabled="knowledgeChatBusy || Boolean(documentMovingId)"
                        title="围绕此文件提问"
                        :aria-label="`围绕 ${file.fileName} 提问`"
                        @click.stop="openDocumentConversation(file)"
                        @keydown.stop
                      >
                        <n-icon :size="16"><MessageCircle /></n-icon>
                      </button>
                      <button
                        type="button"
                        class="is-delete"
                        :disabled="knowledgeChatBusy || !canManageDocuments || folderUpdating || Boolean(documentMovingId) || Boolean(documentDeletingId)"
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
                  <p>{{ isSearchActive ? '可以换一种关键词，或返回当前目录。' : '上传后资料将由 WeKnora 解析并出现在当前目录。' }}</p>
                  <button v-if="!isSearchActive" type="button" @click="openUploadModal">上传资料</button>
                </section>
              </div>
            </div>
          </section>
        </section>
      </section>

      <div v-if="knowledgeWorkspaceBlocked" class="knowledge-workspace-overlay" role="status" aria-live="polite">
        <section v-if="knowledgeWorkspaceError" class="knowledge-workspace-error">
          <span class="knowledge-workspace-robot is-error"><n-icon :size="32"><Robot /></n-icon></span>
          <strong>工程知识库加载失败</strong>
          <p>{{ knowledgeWorkspaceError }}</p>
          <button type="button" :disabled="knowledgeWorkspaceLoading" @click="retryKnowledgeWorkspace">
            {{ knowledgeWorkspaceLoading ? '正在重试…' : '重新加载' }}
          </button>
        </section>
        <section v-else class="knowledge-workspace-loading">
          <span class="knowledge-workspace-robot"><n-icon :size="32"><Robot /></n-icon></span>
          <strong>正在准备工程知识库</strong>
          <p>{{ knowledgeWorkspaceLoading ? '正在读取知识库和目录数据…' : '正在恢复最近对话…' }}</p>
          <span class="knowledge-loading-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        </section>
      </div>
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

    <div v-if="folderUpdateModalOpen" class="library-modal-backdrop" @click.self="closeFolderUpdateModal">
      <section class="library-modal" role="dialog" aria-modal="true" aria-labelledby="folder-update-title">
        <div class="library-modal-head">
          <div><span>资料库目录</span><h2 id="folder-update-title">移动或重命名目录</h2></div>
          <button type="button" class="modal-close" :disabled="folderUpdating" @click="closeFolderUpdateModal">关闭</button>
        </div>
        <form class="folder-create-form" @submit.prevent="updateFolder">
          <div class="path-operation-source">
            <span>当前目录</span>
            <strong>{{ folderUpdateSource?.path || folderUpdateSource?.name }}</strong>
          </div>
          <div class="upload-target-field">
            <span>新的上级目录</span>
            <n-tree-select
              v-model:value="folderUpdateParentId"
              :options="folderUpdateTreeOptions"
              :default-expanded-keys="folderPickerExpandedKeys(folderUpdateParentId)"
              :render-prefix="renderFolderTreePrefix"
              :disabled="folderUpdating"
              :indent="20"
              filterable
              show-line
              show-path
              separator=" / "
              placeholder="搜索或选择新的上级目录"
              aria-label="选择目录移动后的上级目录"
            />
          </div>
          <label class="folder-name-field">
            <span>目录名称</span>
            <input v-model.trim="folderUpdateName" maxlength="255" required :disabled="folderUpdating" placeholder="请输入目录名称">
          </label>
          <div v-if="folderUpdateTargetPath" class="path-operation-target">
            <span>更新后路径</span>
            <strong>{{ folderUpdateTargetPath }}</strong>
          </div>
          <div class="upload-actions">
            <button type="button" class="modal-secondary" :disabled="folderUpdating" @click="closeFolderUpdateModal">取消</button>
            <button type="submit" class="modal-primary" :disabled="folderUpdating || !folderUpdateChanged">
              <n-icon :size="16"><Pencil /></n-icon>
              {{ folderUpdating ? '正在更新…' : '确认更新' }}
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="documentMoveModalOpen" class="library-modal-backdrop" @click.self="closeDocumentMoveModal">
      <section class="library-modal" role="dialog" aria-modal="true" aria-labelledby="document-move-title">
        <div class="library-modal-head">
          <div><span>工程资料</span><h2 id="document-move-title">移动文件</h2></div>
          <button type="button" class="modal-close" :disabled="Boolean(documentMovingId)" @click="closeDocumentMoveModal">关闭</button>
        </div>
        <form class="folder-create-form" @submit.prevent="moveDocument">
          <div class="path-operation-source">
            <span>文件</span>
            <strong>{{ documentMoveSource?.fileName }}</strong>
          </div>
          <div class="upload-target-field">
            <span>目标目录</span>
            <n-tree-select
              v-model:value="documentMoveTargetFolderId"
              :options="documentMoveTreeOptions"
              :default-expanded-keys="folderPickerExpandedKeys(documentMoveTargetFolderId)"
              :render-prefix="renderFolderTreePrefix"
              :disabled="Boolean(documentMovingId)"
              :indent="20"
              filterable
              show-line
              show-path
              separator=" / "
              placeholder="搜索或选择目标目录"
              aria-label="选择文件移动目标目录"
            />
          </div>
          <div class="upload-actions">
            <button type="button" class="modal-secondary" :disabled="Boolean(documentMovingId)" @click="closeDocumentMoveModal">取消</button>
            <button type="submit" class="modal-primary" :disabled="Boolean(documentMovingId) || !documentMoveChanged">
              <n-icon :size="16"><ArrowsLeftRight /></n-icon>
              {{ documentMovingId ? '正在移动…' : '移动文件' }}
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
  ArrowsLeftRight,
  ChevronDown,
  ChevronRight,
  Database,
  DatabaseImport,
  FileText,
  Folder,
  FolderPlus,
  MessageCircle,
  Paperclip,
  Pencil,
  Refresh,
  Robot,
  Search,
  Trash,
} from '@vicons/tabler'
import DocumentTypeIcon from '@/components/business/DocumentTypeIcon.vue'
import ProjectKnowledgeChat from '@/components/business/ProjectKnowledgeChat.vue'
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

const store = useAppStore()
const message = useMessage()
const dialog = useDialog()

const activeWorkspaceTab = ref<'chat' | 'files'>('chat')
const chatFocusDocumentId = ref('')
const knowledgeChatBusy = ref(false)
const knowledgeChatReady = ref(false)
const knowledgeWorkspaceLoading = ref(false)
const knowledgeWorkspaceReady = ref(false)
const knowledgeWorkspaceError = ref('')
const fileWorkspaceInitialized = ref(false)
const activeFolderId = ref('')
const expandedFolderIds = ref<string[]>([])
const initialDirectoryExpansionApplied = ref(false)
const selectedFileId = ref('')
const documentUploading = ref(false)
const folderModalOpen = ref(false)
const folderCreating = ref(false)
const folderUpdateModalOpen = ref(false)
const folderUpdating = ref(false)
const folderUpdateSourceId = ref('')
const folderUpdateParentId = ref('')
const folderUpdateName = ref('')
const folderDeleting = ref(false)
const newFolderName = ref('')
const newFolderParentId = ref('')
const resumeUploadAfterFolderModal = ref(false)
const uploadModalOpen = ref(false)
const uploadFolderId = ref('')
const pendingUploadFiles = ref<File[]>([])
const documentMoveModalOpen = ref(false)
const documentMovingId = ref('')
const documentMoveSource = ref<AttachmentRecord>()
const documentMoveTargetFolderId = ref('')
const documentDeletingId = ref('')
const documentSearching = ref(false)
const documentSearchKeyword = ref('')
const documentSearchResults = ref<AttachmentRecord[]>([])
const isSearchActive = ref(false)
const documentRefreshing = ref(false)
const locatingReferenceId = ref('')

const canManageDocuments = computed(() => Boolean(store.currentProjectId))
const knowledgeWorkspaceBlocked = computed(() => Boolean(store.currentProjectId) && (
  !knowledgeWorkspaceReady.value || !knowledgeChatReady.value
))
const totalDocumentCount = computed(() => {
  const knowledgeBaseFolders = store.documentFolders.filter(folder => folder.isKnowledgeBase)
  if (knowledgeBaseFolders.length) {
    return knowledgeBaseFolders.reduce((total, folder) => total + Math.max(folder.totalCount || 0, folder.documentCount || 0), 0)
  }
  return store.attachments.length
})
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
const folderUpdateSource = computed(() => store.documentFolders.find(folder => folder.id === folderUpdateSourceId.value))
const folderUpdateTreeOptions = computed<TreeSelectOption[]>(() => {
  const source = folderUpdateSource.value
  if (!source?.knowledgeBaseId) return []
  return folderOptionsForKnowledgeBase(
    source.knowledgeBaseId,
    new Set([source.id, ...descendantFolderIds(source)]),
  )
})
const folderUpdateTargetPath = computed(() => {
  const source = folderUpdateSource.value
  const parent = store.documentFolders.find(folder => folder.id === folderUpdateParentId.value)
  const name = folderUpdateName.value.trim()
  if (!source?.knowledgeBaseId || !parent || parent.knowledgeBaseId !== source.knowledgeBaseId || !name || /[\\/\0]/.test(name)) return ''
  const parentPath = normalizedFolderPath(parent.path)
  return normalizedFolderPath(parentPath ? `${parentPath}/${name}` : name)
})
const folderUpdateChanged = computed(() => Boolean(
  folderUpdateTargetPath.value
  && folderUpdateTargetPath.value !== normalizedFolderPath(folderUpdateSource.value?.path),
))
const documentMoveTreeOptions = computed<TreeSelectOption[]>(() => (
  documentMoveSource.value?.knowledgeBaseId
    ? folderOptionsForKnowledgeBase(documentMoveSource.value.knowledgeBaseId)
    : []
))
const documentMoveChanged = computed(() => Boolean(
  documentMoveSource.value
  && documentMoveTargetFolderId.value
  && documentMoveTargetFolderId.value !== documentMoveSource.value.folderId,
))
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
watch(() => store.documentFolders, folders => {
  if (initialDirectoryExpansionApplied.value || !folders.length) return
  const rootFolders = folders.filter(folder => !folder.parentId)
  expandedFolderIds.value = [...new Set([...expandedFolderIds.value, ...rootFolders.map(folder => folder.id)])]
  initialDirectoryExpansionApplied.value = true
}, { immediate: true })

watch(() => store.currentProjectId, async projectId => {
  activeWorkspaceTab.value = 'chat'
  chatFocusDocumentId.value = ''
  knowledgeChatBusy.value = false
  knowledgeChatReady.value = false
  knowledgeWorkspaceLoading.value = false
  knowledgeWorkspaceReady.value = false
  knowledgeWorkspaceError.value = ''
  fileWorkspaceInitialized.value = false
  initialDirectoryExpansionApplied.value = false
  expandedFolderIds.value = projectId ? restoreFolderExpansion(projectId) : []
  folderModalOpen.value = false
  folderUpdateModalOpen.value = false
  folderUpdating.value = false
  folderUpdateSourceId.value = ''
  folderUpdateParentId.value = ''
  folderUpdateName.value = ''
  newFolderName.value = ''
  newFolderParentId.value = ''
  resumeUploadAfterFolderModal.value = false
  uploadModalOpen.value = false
  uploadFolderId.value = ''
  pendingUploadFiles.value = []
  documentMoveModalOpen.value = false
  documentMovingId.value = ''
  documentMoveSource.value = undefined
  documentMoveTargetFolderId.value = ''
  documentDeletingId.value = ''
  activeFolderId.value = ''
  selectedFileId.value = ''
  documentSearching.value = false
  documentRefreshing.value = false
  if (!projectId) return
  await initializeKnowledgeWorkspace(projectId)
}, { immediate: true })

async function initializeKnowledgeWorkspace(projectId: string, force = false) {
  if (!projectId || projectId !== store.currentProjectId) return
  knowledgeWorkspaceLoading.value = true
  knowledgeWorkspaceReady.value = false
  knowledgeWorkspaceError.value = ''
  try {
    await store.loadEngineeringDocuments(projectId, force)
    if (projectId === store.currentProjectId) knowledgeWorkspaceReady.value = true
  } catch (error: any) {
    if (projectId === store.currentProjectId) {
      knowledgeWorkspaceError.value = error.response?.data?.detail || error.message || 'WeKnora 工程资料加载失败。'
    }
  } finally {
    if (projectId === store.currentProjectId) knowledgeWorkspaceLoading.value = false
  }
}

function retryKnowledgeWorkspace() {
  const projectId = store.currentProjectId
  if (!projectId || knowledgeWorkspaceLoading.value) return
  void initializeKnowledgeWorkspace(projectId, true)
}

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
function folderOptionsForKnowledgeBase(knowledgeBaseId: string, excludedIds = new Set<string>()) {
  const createOption = (folder: DocumentFolderRecord): TreeSelectOption | undefined => {
    if (folder.knowledgeBaseId !== knowledgeBaseId || excludedIds.has(folder.id)) return undefined
    const children = (folderChildren.value.get(folder.id) || [])
      .map(createOption)
      .filter((option): option is TreeSelectOption => Boolean(option))
    return {
      key: folder.id,
      label: folder.name,
      isKnowledgeBase: Boolean(folder.isKnowledgeBase),
      children: children.length ? children : undefined,
    }
  }
  return (folderChildren.value.get(undefined) || [])
    .map(createOption)
    .filter((option): option is TreeSelectOption => Boolean(option))
}
function selectTreeNode(node: FolderTreeDisplayNode) {
  void selectFolder(node.folderId || node.id)
}
async function selectFolder(folderId: string, force = false) {
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
    await store.loadEngineeringDocumentFolder(folderId, force)
    fileWorkspaceInitialized.value = true
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || 'WeKnora 目录资料加载失败。')
  }
}
async function refreshDocumentLibrary() {
  const projectId = store.currentProjectId
  if (!projectId || documentRefreshing.value || documentWorkspaceLoading.value) return
  const selectedFolder = activeFolder.value
  const selectedKnowledgeBaseId = selectedFolder?.knowledgeBaseId || ''
  const selectedFolderPath = normalizedFolderPath(selectedFolder?.path)
  const restoreSearch = isSearchActive.value && Boolean(documentSearchKeyword.value.trim())
  documentRefreshing.value = true
  try {
    await store.loadEngineeringDocuments(projectId, true)
    const restoredFolder = store.documentFolders.find(folder => folder.id === selectedFolder?.id)
      || store.documentFolders.find(folder => (
        folder.knowledgeBaseId === selectedKnowledgeBaseId
        && normalizedFolderPath(folder.path) === selectedFolderPath
      ))
      || store.documentFolders.find(folder => folder.isKnowledgeBase)
    if (restoredFolder) await selectFolder(restoredFolder.id)
    if (restoreSearch) await searchDocuments()
    message.success('知识库已刷新')
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '知识库刷新失败。')
  } finally {
    documentRefreshing.value = false
  }
}
function selectDocument(file: AttachmentRecord) {
  selectedFileId.value = file.id
}

type KnowledgeReferenceLocation = {
  knowledgeId: string
  knowledgeBaseId?: string
  fileName: string
  folderPath?: string
}

function referenceFolder(knowledgeBaseId: string, folderPath?: string) {
  const normalizedPath = normalizedFolderPath(folderPath)
  return store.documentFolders.find(folder => (
    folder.knowledgeBaseId === knowledgeBaseId
    && normalizedFolderPath(folder.path) === normalizedPath
  ))
}

async function locateReferenceDocument(reference: KnowledgeReferenceLocation) {
  const projectId = store.currentProjectId
  const knowledgeId = reference.knowledgeId?.trim()
  if (!projectId || !knowledgeId || locatingReferenceId.value) return
  locatingReferenceId.value = knowledgeId
  try {
    const currentFile = await store.getEngineeringDocument(knowledgeId)
    if (projectId !== store.currentProjectId) return

    let folder = referenceFolder(
      currentFile.knowledgeBaseId || reference.knowledgeBaseId || '',
      currentFile.folderPath,
    )
    if (!folder) {
      await store.loadEngineeringDocuments(projectId, true)
      folder = referenceFolder(
        currentFile.knowledgeBaseId || reference.knowledgeBaseId || '',
        currentFile.folderPath,
      )
    }
    if (!folder) throw new Error('未找到引用文件当前所在的知识库目录。')

    activeWorkspaceTab.value = 'files'
    await selectFolder(folder.id, true)
    if (projectId !== store.currentProjectId) return
    const locatedFile = store.attachments.find(item => item.id === knowledgeId)
    if (!locatedFile) throw new Error('引用文件已不在该目录中，请刷新知识库后重试。')

    selectedFileId.value = knowledgeId
    fileWorkspaceInitialized.value = true
    await nextTick()
    const row = [...document.querySelectorAll<HTMLElement>('[data-document-id]')]
      .find(element => element.dataset.documentId === knowledgeId)
    row?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    row?.focus({ preventScroll: true })
  } catch (error: any) {
    const status = Number(error.response?.status || 0)
    message.error(
      status === 404
        ? `引用文件“${reference.fileName}”已被删除或不再可访问。`
        : error.response?.data?.detail || error.message || '引用文件定位失败。',
    )
  } finally {
    locatingReferenceId.value = ''
  }
}

async function switchWorkspaceTab(tab: 'chat' | 'files') {
  activeWorkspaceTab.value = tab
  if (tab !== 'files' || fileWorkspaceInitialized.value || !store.currentProjectId) return
  const preferredFolder = store.documentFolders.find(folder => folder.id === activeFolderId.value)
    || store.documentFolders.find(folder => folder.isKnowledgeBase)
    || store.documentFolders[0]
  if (preferredFolder) await selectFolder(preferredFolder.id)
}

function openDocumentConversation(file: AttachmentRecord) {
  if (knowledgeChatBusy.value) {
    message.warning('请先终止当前回答，再切换到其他资料。')
    return
  }
  selectedFileId.value = file.id
  chatFocusDocumentId.value = file.id
  activeWorkspaceTab.value = 'chat'
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
function openFolderUpdateModal() {
  const folder = activeFolder.value
  if (!folder || folder.isKnowledgeBase || !folder.knowledgeBaseId) {
    message.warning('请选择需要移动或重命名的目录。')
    return
  }
  folderUpdateSourceId.value = folder.id
  folderUpdateParentId.value = folder.parentId
    || store.documentFolders.find(item => item.isKnowledgeBase && item.knowledgeBaseId === folder.knowledgeBaseId)?.id
    || ''
  folderUpdateName.value = folder.name
  folderUpdateModalOpen.value = true
}
function closeFolderUpdateModal() {
  if (folderUpdating.value) return
  folderUpdateModalOpen.value = false
  folderUpdateSourceId.value = ''
  folderUpdateParentId.value = ''
  folderUpdateName.value = ''
}
async function updateFolder() {
  const source = folderUpdateSource.value
  if (folderUpdating.value || !source || !folderUpdateChanged.value || !folderUpdateParentId.value) return
  const staleFolderIds = new Set([source.id, ...descendantFolderIds(source)])
  folderUpdating.value = true
  try {
    const updated = await store.updateDocumentFolder(source.id, {
      name: folderUpdateName.value,
      parentId: folderUpdateParentId.value,
    })
    folderUpdateModalOpen.value = false
    folderUpdateSourceId.value = ''
    folderUpdateParentId.value = ''
    folderUpdateName.value = ''
    expandedFolderIds.value = expandedFolderIds.value.filter(folderId => (
      !staleFolderIds.has(folderId)
      && store.documentFolders.some(folder => folder.id === folderId)
    ))
    if (updated.parentId) expandedFolderIds.value = [...new Set([...expandedFolderIds.value, updated.parentId])]
    await selectFolder(updated.id)
    message.success(`目录已更新为“${updated.name}”`)
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '目录更新失败。')
  } finally {
    folderUpdating.value = false
  }
}
function openDocumentMoveModal(file: AttachmentRecord) {
  if (!file.knowledgeBaseId) {
    message.warning('该资料缺少知识库信息，无法移动。')
    return
  }
  const currentFolder = store.documentFolders.find(folder => folder.id === file.folderId)
    || store.documentFolders.find(folder => folder.isKnowledgeBase && folder.knowledgeBaseId === file.knowledgeBaseId)
  documentMoveSource.value = file
  documentMoveTargetFolderId.value = currentFolder?.id || ''
  documentMoveModalOpen.value = true
}
function closeDocumentMoveModal() {
  if (documentMovingId.value) return
  documentMoveModalOpen.value = false
  documentMoveSource.value = undefined
  documentMoveTargetFolderId.value = ''
}
async function moveDocument() {
  const file = documentMoveSource.value
  const targetFolderId = documentMoveTargetFolderId.value
  if (!file || !targetFolderId || !documentMoveChanged.value || documentMovingId.value) return
  const originFolder = store.documentFolders.find(folder => folder.id === activeFolderId.value)
  const originKnowledgeBaseId = originFolder?.knowledgeBaseId || file.knowledgeBaseId || ''
  const originFolderPath = normalizedFolderPath(originFolder?.path)
  const keepSearchResults = isSearchActive.value
  documentMovingId.value = file.id
  try {
    const target = await store.moveEngineeringDocuments([file.id], targetFolderId)
    documentMoveModalOpen.value = false
    documentMoveSource.value = undefined
    documentMoveTargetFolderId.value = ''
    if (keepSearchResults) {
      documentSearchResults.value = documentSearchResults.value.map(item => (
        item.id === file.id
          ? { ...item, folderId: target.id, folderPath: target.path || '' }
          : item
      ))
      selectedFileId.value = file.id
    } else {
      const refreshedOrigin = store.documentFolders.find(folder => folder.id === originFolder?.id)
        || store.documentFolders.find(folder => (
          folder.knowledgeBaseId === originKnowledgeBaseId
          && normalizedFolderPath(folder.path) === originFolderPath
        ))
      if (refreshedOrigin) await selectFolder(refreshedOrigin.id)
      else selectedFileId.value = ''
    }
    message.success(`文件“${file.fileName}”已移动到“${target.name}”`)
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '文件移动失败。')
  } finally {
    documentMovingId.value = ''
  }
}
function confirmDeleteDocument(file: AttachmentRecord) {
  if (documentDeletingId.value || documentMovingId.value || folderDeleting.value || folderUpdating.value) return
  if (knowledgeChatBusy.value) {
    message.warning('请先终止当前回答，再删除文件。')
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
  if (documentDeletingId.value || documentMovingId.value || folderDeleting.value || folderUpdating.value) return
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
  }

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
  if (folderUpdating.value || documentMovingId.value) return
  const folder = activeFolder.value
  if (!folder || folder.isKnowledgeBase) {
    message.warning('知识库根节点不能删除。')
    return
  }
  if (knowledgeChatBusy.value) {
    message.warning('请先终止当前回答，再删除目录。')
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
  if (folderDeleting.value || folderUpdating.value || documentMovingId.value || documentDeletingId.value) return
  const projectId = store.currentProjectId
  if (!projectId) return
  folderDeleting.value = true
  const nestedIds = new Set([folder.id, ...descendantFolderIds(folder)])
  try {
    const parentId = folder.parentId || ''
    await store.deleteDocumentFolder(folder.id)
    expandedFolderIds.value = expandedFolderIds.value.filter(id => !nestedIds.has(id))
    activeFolderId.value = ''
    selectedFileId.value = ''
    documentSearchResults.value = documentSearchResults.value.filter(file => !fileIsInsideFolder(file, folder))
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
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
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
  try {
    const rawKeyword = documentSearchKeyword.value.trim()
    const remoteResults = await store.searchDocuments(rawKeyword)
    const resultMap = new Map<string, AttachmentRecord>()
    for (const file of remoteResults) resultMap.set(file.id, file)
    documentSearchResults.value = [...resultMap.values()]
    isSearchActive.value = true
    const firstResult = documentSearchResults.value[0]
    selectedFileId.value = firstResult?.id || ''
  } catch (error: any) {
    message.error(error.response?.data?.detail || '资料检索失败，请稍后重试。')
  } finally {
    documentSearching.value = false
  }
}
function clearSearch() {
  documentSearchKeyword.value = ''
  documentSearchResults.value = []
  isSearchActive.value = false
  selectedFileId.value = ''
}
</script>

<style scoped>
.document-library {
  height: calc(100dvh - var(--header-height, 56px));
  min-height: 0;
  box-sizing: border-box;
  overflow: hidden;
  color: var(--text-primary);
  background: #fff;
}

.dobby-workspace {
  position: relative;
  --folder-rail-width: 272px;
  display: grid;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  background: #fff;
}

.knowledge-workspace-overlay {
  position: absolute;
  z-index: 25;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at 50% 42%, rgba(221, 239, 234, .72), transparent 32%),
    rgba(250, 252, 251, .98);
}
.knowledge-workspace-loading,
.knowledge-workspace-error {
  display: grid;
  width: min(100%, 430px);
  justify-items: center;
  gap: 11px;
  color: #6d827d;
  text-align: center;
}
.knowledge-workspace-robot {
  display: grid;
  width: 68px;
  height: 68px;
  place-items: center;
  border: 1px solid #bcd6d0;
  border-radius: 20px;
  color: #fff;
  background: linear-gradient(145deg, #176b62, #123f3d);
  box-shadow: 0 15px 32px rgba(19, 77, 71, .19);
  transform-origin: 50% 100%;
  animation: knowledge-workspace-duang 1.08s cubic-bezier(.34, 1.56, .64, 1) infinite;
}
.knowledge-workspace-robot.is-error {
  color: #a24a38;
  border-color: #e2beb6;
  background: #fff4f1;
  box-shadow: none;
  animation: none;
}
.knowledge-workspace-loading strong,
.knowledge-workspace-error strong { color: #234844; font-size: 17px; font-weight: 850; }
.knowledge-workspace-loading p,
.knowledge-workspace-error p { max-width: 48ch; margin: 0; font-size: 13px; line-height: 1.65; }
.knowledge-workspace-error button {
  margin-top: 4px;
  border: 1px solid #9bbeb7;
  border-radius: 7px;
  padding: 9px 16px;
  color: #155f57;
  background: #fff;
  font: inherit;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}
.knowledge-loading-dots { display: inline-flex; align-items: center; gap: 5px; min-height: 16px; }
.knowledge-loading-dots i { display: block; width: 6px; height: 6px; border-radius: 50%; background: #4d8b82; animation: knowledge-loading-dot 1.1s ease-in-out infinite; }
.knowledge-loading-dots i:nth-child(2) { animation-delay: .14s; }
.knowledge-loading-dots i:nth-child(3) { animation-delay: .28s; }

.knowledge-tabs {
  display: flex;
  min-height: 54px;
  align-items: center;
  gap: 26px;
  padding: 0 28px;
  border-bottom: 1px solid #e0e8e5;
  background: #fff;
}
.knowledge-tabs button {
  position: relative;
  display: inline-flex;
  min-height: 54px;
  align-items: center;
  gap: 8px;
  border: 0;
  padding: 0 2px;
  color: #60756f;
  background: transparent;
  font: inherit;
  font-size: 13px;
  font-weight: 760;
  cursor: pointer;
}
.knowledge-tabs button::after {
  content: '';
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
}
.knowledge-tabs button.active { color: #0f6f67; }
.knowledge-tabs button.active::after { background: #0f766e; }
.knowledge-tabs button > span {
  display: inline-flex;
  min-width: 24px;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border-radius: 10px;
  padding: 2px 7px;
  color: #70827e;
  background: #edf2f0;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}
.knowledge-tabs button.active > span { color: #0f6f67; background: #e4f0ed; }
.knowledge-tabs button > span.is-loading { min-width: 74px; color: #8a6a2c; background: #f7f0df; }
.knowledge-loading-robot {
  flex: 0 0 auto;
  transform-origin: 50% 100%;
  animation: knowledge-robot-duang .92s cubic-bezier(.36, .07, .19, .97) infinite;
}

.file-workspace {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  background: #fff;
}
.file-toolbar {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) auto;
  align-items: center;
  gap: 18px;
  min-height: 64px;
  padding: 10px 18px;
  border-bottom: 1px solid #e3e9e7;
  background: #fbfcfc;
}
.file-search {
  display: grid;
  width: max-content;
  grid-template-columns: calc(var(--folder-rail-width) - 18px) auto;
  align-items: center;
  gap: 8px;
}
.file-search-field {
  display: grid;
  min-width: 0;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 42px;
  box-sizing: border-box;
  padding: 4px 10px;
  border: 1px solid #c6d5d1;
  border-radius: 7px;
  background: #fff;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.file-search-field:focus-within { border-color: #4b8a80; box-shadow: 0 0 0 3px rgba(15, 118, 110, .09); }
.file-search-field > svg { color: #6c827d; }
.file-search input { min-width: 0; height: 34px; border: 0; outline: 0; color: #173235; background: transparent; font: inherit; font-size: 13px; }
.file-search button,
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
.file-search button { border: 0; color: #fff; background: #173f3e; }
.file-toolbar-actions { display: flex; align-items: center; gap: 7px; }
.primary-action { border: 1px solid #d45f1f; color: #fff; background: #d45f1f; box-shadow: 0 5px 12px rgba(212, 95, 31, .16); }
.secondary-action { border: 1px solid #b9cdc8; color: #315e58; background: #fff; }
.secondary-action.is-danger { border-color: #e3b9b4; color: #b44735; background: #fff9f8; }
button:disabled { opacity: .5; cursor: not-allowed; box-shadow: none; }
.file-search button:not(:disabled):hover,
.primary-action:not(:disabled):hover,
.secondary-action:not(:disabled):hover { filter: brightness(.96); transform: translateY(-1px); }

.dobby-workspace-grid {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-columns: var(--folder-rail-width) minmax(0, 1fr);
  overflow: hidden;
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
.folder-rail-head > div:not(.folder-rail-tools) { display: grid; min-width: 0; gap: 4px; }
.folder-rail-head span { color: #6f8580; font-size: 12px; font-weight: 800; letter-spacing: .05em; }
.folder-rail-head strong { overflow: hidden; color: #1c3936; font-size: 14px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.folder-count-legend { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 8px; color: #788a86; font-size: 12px; font-weight: 600; letter-spacing: 0; line-height: 1; }
.folder-count-legend > span { display: inline-flex; align-items: center; gap: 4px; color: inherit; font-size: 12px; font-weight: inherit; letter-spacing: 0; white-space: nowrap; }
.folder-rail-tools { display: flex; min-width: 0; align-items: center; justify-content: flex-end; gap: 7px; }
.folder-refresh-button { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; border: 1px solid #c7d6d2; border-radius: 6px; padding: 0; color: #456f69; background: #fff; cursor: pointer; }
.folder-refresh-button:not(:disabled):hover { border-color: #84aaa3; color: #0f6f67; background: #eef6f4; }
.folder-refresh-button .is-spinning { animation: folder-refresh-spin .78s linear infinite; }
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
.tree-item.is-active { color: #173b37; background: transparent; font-weight: 800; box-shadow: inset 0 0 0 1.5px #0f766e; }
.tree-item.is-library-root { height: 36px; color: #173f3e; background: transparent; font-weight: 850; }
.tree-item.is-library-root > svg { color: #0f766e; }
.tree-item.is-library-root:hover { background: #eaf2ef; }
.tree-item.is-library-root.is-active { background: transparent; }

.document-queue { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; background: #fff; }
.search-state { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 18px; border-bottom: 1px solid #d9e8e3; color: #285d57; background: #f0f8f5; font-size: 12px; }
.search-state button { border: 0; padding: 0; color: #0f766e; background: transparent; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; }

.library-stream { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; overflow: hidden; }
.document-file-scroll { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; overflow: auto; scrollbar-gutter: stable; }
.document-file-list { display: flex; min-width: 0; flex: 0 0 auto; flex-direction: column; }
.document-file-list-head,
.document-file-row {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(220px, 1fr) 148px 82px 76px 100px;
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
.document-file-row.is-moving,
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
.document-file-actions { display: flex; align-items: center; justify-content: center; gap: 3px; }
.document-file-actions button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 5px;
  padding: 0;
  color: #607772;
  background: transparent;
  cursor: pointer;
  transition: border-color .15s ease, color .15s ease, background .15s ease;
}
.document-file-actions button.is-chat:not(:disabled):hover { border-color: #a9cbc4; color: #0f7067; background: #eff7f5; }
.document-file-actions button.is-move:not(:disabled):hover { border-color: #c4b587; color: #8a6417; background: #fff9e9; }
.document-file-actions button.is-delete { color: #a65346; }
.document-file-actions button.is-delete:not(:disabled):hover { border-color: #e1bbb5; color: #a43f31; background: #fff5f3; }
.document-loading { display: grid; flex: 1 1 auto; min-height: 220px; box-sizing: border-box; place-items: center; }
.document-empty { display: grid; flex: 1 1 auto; min-height: 220px; box-sizing: border-box; place-content: center; justify-items: center; gap: 8px; color: #7a8e89; text-align: center; }
.document-empty strong { color: #385b56; font-size: 14px; }
.document-empty p { max-width: 40ch; margin: 0 0 6px; font-size: 12px; line-height: 1.6; }
.document-empty button { display: inline-flex; align-items: center; gap: 7px; border: 0; border-radius: 7px; padding: 10px 14px; color: #fff; background: #d45f1f; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; box-shadow: 0 7px 15px rgba(212, 95, 31, .17); }

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
.path-operation-source,
.path-operation-target { display: grid; min-width: 0; gap: 5px; padding: 10px 11px; border: 1px solid #dce6e3; border-radius: 7px; background: #f8faf9; }
.path-operation-target { border-color: #bdd8d1; background: #eef7f4; }
.path-operation-source span,
.path-operation-target span { color: #71847f; font-size: 12px; font-weight: 700; }
.path-operation-source strong,
.path-operation-target strong { overflow-wrap: anywhere; color: #294b46; font-size: 12px; line-height: 1.55; }
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
@keyframes folder-refresh-spin {
  to { transform: rotate(360deg); }
}
@keyframes knowledge-robot-duang {
  0%, 100% { transform: translateY(0) scale(1); }
  28% { transform: translateY(-4px) scale(.94, 1.08); }
  52% { transform: translateY(1px) scale(1.08, .9); }
  70% { transform: translateY(-1px) scale(.98, 1.03); }
}
@keyframes knowledge-workspace-duang {
  0%, 100% { transform: translateY(0) scale(1); }
  36% { transform: translateY(-10px) scale(.94, 1.06); }
  58% { transform: translateY(2px) scale(1.08, .9); }
  72% { transform: translateY(-2px) scale(.99, 1.02); }
}
@keyframes knowledge-loading-dot {
  0%, 100% { opacity: .28; transform: translateY(0); }
  48% { opacity: 1; transform: translateY(-4px); }
}
@media (prefers-reduced-motion: reduce) {
  .library-loading-stack > i,
  .knowledge-loading-robot,
  .knowledge-workspace-robot,
  .knowledge-loading-dots i { animation: none; }
}

@media (max-width: 1180px) {
  .dobby-workspace { --folder-rail-width: 220px; }
  .document-file-list-head,
  .document-file-row { grid-template-columns: minmax(180px, 1fr) 142px 70px 66px 96px; column-gap: 8px; }
}
@media (max-width: 960px) {
  .dobby-workspace { --folder-rail-width: 210px; }
  .file-toolbar { grid-template-columns: minmax(0, 1fr); gap: 9px; }
  .file-search { width: max-content; }
  .file-toolbar-actions { justify-content: flex-end; }
  .document-file-list-head,
  .document-file-row { grid-template-columns: minmax(170px, 1fr) 142px 64px 96px; }
  .document-file-list-head > span:nth-child(3),
  .document-file-row > .document-file-type { display: none; }
}
@media (max-width: 760px) {
  .document-library { height: auto; min-height: calc(100dvh - var(--header-height, 56px)); overflow: visible; }
  .dobby-workspace { height: auto; overflow: visible; }
  .knowledge-tabs { padding: 0 18px; }
  .file-search { width: 100%; grid-template-columns: minmax(0, 1fr) auto; }
  .file-toolbar-actions { flex-wrap: wrap; justify-content: stretch; }
  .file-toolbar-actions button { flex: 1 1 120px; }
  .dobby-workspace-grid { display: block; }
  .folder-rail { min-height: 280px; max-height: 360px; border-right: 0; border-bottom: 1px solid #e0e8e5; }
  .document-queue { min-height: 560px; }
  .document-file-list-head,
  .document-file-row { grid-template-columns: minmax(150px, 1fr) 80px 96px; }
  .document-file-list-head > span:nth-child(2),
  .document-file-row > .document-file-date { display: none; }
  .library-modal-backdrop { padding: 10px; }
  .library-modal { max-height: calc(100dvh - 20px); padding: 15px; }
  .upload-modal { height: calc(100dvh - 20px); }
}
</style>
