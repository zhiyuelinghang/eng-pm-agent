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
        :locating-knowledge-id="locatingReferenceId"
        :disabled="knowledgeWorkspaceBlocked"
        @document-consumed="chatFocusDocumentId = ''"
        @busy-change="knowledgeChatBusy = $event"
        @ready-change="knowledgeChatReady = $event"
        @locate-reference="locateReferenceDocument"
      />

      <section v-show="activeWorkspaceTab === 'files'" class="file-workspace" aria-label="工程资料文件管理">
        <header class="file-toolbar">
          <form class="file-search" @submit.prevent="searchDocuments()">
            <label class="file-search-field">
              <n-icon :size="18"><Search /></n-icon>
              <input
                v-model.trim="documentSearchKeyword"
                :disabled="!canReadDocuments || documentSearching"
                placeholder="搜索文件名或资料内容"
              >
            </label>
            <button type="submit" :disabled="!canReadDocuments || documentSearching">
              {{ documentSearching ? '正在搜索…' : '搜索' }}
            </button>
          </form>

          <div class="file-toolbar-actions">
            <button type="button" class="secondary-action" :disabled="!canCreateDocuments || folderCreating || folderUpdating || folderDeleting || documentUploading || Boolean(documentMovingId) || Boolean(documentDeletingId)" @click="openFolderModal">
              <n-icon :size="16"><FolderPlus /></n-icon>
              新建目录
            </button>
            <button
              type="button"
              class="secondary-action"
              :disabled="!canUpdateActiveFolder || !activeFolder || activeFolder.isKnowledgeBase || folderUpdating || folderDeleting || folderCreating || documentUploading || Boolean(documentMovingId) || Boolean(documentDeletingId)"
              :title="activeFolder && !activeFolder.isKnowledgeBase ? '移动或重命名选中目录' : '请先在左侧选择一个普通目录'"
              @click="openFolderUpdateModal"
            >
              <n-icon :size="16"><Pencil /></n-icon>
              移动/重命名
            </button>
            <button v-if="activeFolder && !activeFolder.isKnowledgeBase" type="button" class="secondary-action is-danger" :disabled="!canDeleteActiveFolder || knowledgeChatBusy || folderDeleting || folderUpdating || folderCreating || documentUploading || Boolean(documentMovingId) || Boolean(documentDeletingId)" :aria-busy="folderDeleting" @click="confirmDeleteFolder">
              <n-icon v-if="folderDeleting" class="is-spinning" :size="16"><Loader /></n-icon>
              <n-icon v-else :size="16"><Trash /></n-icon>
              {{ folderDeleting ? '正在删除…' : '删除目录' }}
            </button>
            <button type="button" class="primary-action" :disabled="!canCreateDocuments || documentUploading || folderCreating || folderUpdating || folderDeleting || Boolean(documentMovingId) || Boolean(documentDeletingId)" @click="openUploadModal">
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
              <button type="button" @click="clearSearch()">返回当前目录</button>
            </div>

            <div class="library-stream">
              <div class="document-file-scroll" :aria-busy="store.engineeringDocumentsLoading || store.engineeringDocumentFolderLoading">
                <section v-if="store.engineeringDocumentsLoading || store.engineeringDocumentFolderLoading" class="document-loading" role="status" aria-live="polite">
                  <div class="library-loading-state">
                    <span class="library-loading-stack" aria-hidden="true"><i></i><i></i><i></i></span>
                    <span class="library-loading-text">
                      <strong>正在加载工程资料</strong>
                      <span>正在读取当前目录文件</span>
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
                        class="is-info"
                        title="查看文件信息"
                        :aria-label="`查看 ${file.fileName} 的文件信息`"
                        @click.stop="openDocumentInfo(file)"
                        @keydown.stop
                      >
                        <n-icon :size="16"><InfoCircle /></n-icon>
                      </button>
                      <button
                        type="button"
                        class="is-move"
                        :disabled="!allowsCapability(file.capabilities, 'can_update') || folderUpdating || folderDeleting || Boolean(documentMovingId) || Boolean(documentDeletingId)"
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
                        :disabled="knowledgeChatBusy || !allowsCapability(file.capabilities, 'can_delete') || folderUpdating || Boolean(documentMovingId) || Boolean(documentDeletingId)"
                        :aria-busy="documentDeletingId === file.id"
                        :title="documentDeletingId === file.id ? '正在删除' : '删除文件'"
                        :aria-label="documentDeletingId === file.id ? `正在删除 ${file.fileName}` : `删除 ${file.fileName}`"
                        @click.stop="confirmDeleteDocument(file)"
                        @keydown.stop
                      >
                        <n-icon v-if="documentDeletingId === file.id" class="is-spinning" :size="16"><Loader /></n-icon>
                        <n-icon v-else :size="16"><Trash /></n-icon>
                      </button>
                    </span>
                  </div>
                </div>

                <section v-else class="document-empty">
                  <n-icon :size="30"><FileText /></n-icon>
                  <strong>{{ isSearchActive ? '没有找到相关资料' : '当前目录还没有资料' }}</strong>
                  <p v-if="isSearchActive">可以换一种关键词，或返回当前目录。</p>
                  <button v-if="!isSearchActive && canCreateDocuments" type="button" @click="openUploadModal">上传资料</button>
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
        <section v-else-if="catalogueUninitialized" class="knowledge-workspace-error">
          <span class="knowledge-workspace-robot is-idle"><n-icon :size="32"><Robot /></n-icon></span>
          <strong>工程资料尚未初始化</strong>
          <p>当前项目的工程资料尚未准备好，请联系管理员。</p>
        </section>
        <section v-else class="knowledge-workspace-loading">
          <span class="knowledge-workspace-robot"><n-icon :size="32"><Robot /></n-icon></span>
          <strong>正在准备工程知识库</strong>
          <p>{{ knowledgeWorkspaceStatusText }}</p>
          <span class="knowledge-loading-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        </section>
      </div>
    </section>

    <div v-if="documentInfoOpen && documentInfoSource" class="library-modal-backdrop" @click.self="closeDocumentInfo">
      <section class="library-modal document-info-modal" role="dialog" aria-modal="true" aria-labelledby="document-info-title">
        <div class="library-modal-head">
          <div><span>资料详情</span><h2 id="document-info-title">文件信息</h2></div>
          <button type="button" class="modal-close" @click="closeDocumentInfo">关闭</button>
        </div>

        <section class="document-info-overview">
          <span class="document-info-icon" aria-hidden="true"><DocumentTypeIcon :kind="documentIconKind(documentInfoSource)" /></span>
          <div>
            <strong>{{ documentInfoSource.fileName }}</strong>
            <span>{{ documentKnowledgeBaseLabel(documentInfoSource) }}<template v-if="documentInfoSource.folderPath"> / {{ documentInfoSource.folderPath }}</template></span>
          </div>
          <em>{{ parseStatusLabel(documentInfoSource.parseStatus) }}</em>
        </section>

        <dl class="document-info-grid">
          <div><dt>文件格式</dt><dd>{{ fileExtension(documentInfoSource.fileName) }}</dd></div>
          <div><dt>文件大小</dt><dd>{{ remoteFileSizeLabel(documentInfoSource.fileSize) }}</dd></div>
          <div><dt>上传时间</dt><dd>{{ formatDate(documentInfoSource.createdAt) }}</dd></div>
          <div><dt>解析完成时间</dt><dd>{{ formatDate(documentInfoSource.processedAt || '') }}</dd></div>
        </dl>

        <section class="document-info-summary">
          <strong>内容简介</strong>
          <p>{{ documentInfoSource.snippet || '暂无内容简介。' }}</p>
        </section>

        <div class="document-info-identity">
          <span>文件标识</span>
          <code>{{ documentInfoSource.id }}</code>
        </div>

        <div class="upload-actions">
          <button type="button" class="modal-secondary" @click="closeDocumentInfo">关闭</button>
          <button type="button" class="modal-primary" :disabled="knowledgeChatBusy" @click="openDocumentConversationFromInfo">
            <n-icon :size="16"><MessageCircle /></n-icon>
            围绕此文件提问
          </button>
        </div>
      </section>
    </div>

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
          <div><span>资料上传</span><h2 id="upload-title">上传工程资料</h2></div>
          <button type="button" class="modal-close" :disabled="documentUploading" @click="closeUploadModal">关闭</button>
        </div>
        <form class="upload-form" @submit.prevent="uploadDocuments">
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
              placeholder="搜索或选择知识库、目标目录"
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
          <div v-else class="upload-queue-empty"><n-icon :size="26"><FileText /></n-icon><strong>选择要上传的工程资料</strong><span>支持一次选择多个文件。</span></div>
          <div class="upload-actions">
            <button type="button" class="modal-secondary" :disabled="documentUploading" @click="closeUploadModal">取消</button>
            <button type="submit" class="modal-primary" :disabled="documentUploading || !pendingUploadFiles.length || !uploadTargetAvailable">
              <n-icon :size="16"><Paperclip /></n-icon>
              {{ documentUploading ? '正在上传…' : '开始上传' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, h, nextTick, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage, NIcon, NTreeSelect, type TreeSelectOption } from 'naive-ui'
import {
  ArrowsLeftRight,
  ChevronDown,
  ChevronRight,
  Database,
  FileText,
  Folder,
  FolderPlus,
  InfoCircle,
  Loader,
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
import { useAsyncConfirmDialog } from '@/composables/useAsyncConfirmDialog'
import {
  useAppStore,
  type AttachmentRecord,
  type DocumentFolderRecord,
  type EngineeringDocumentCapabilities,
} from '@/stores/app'

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
const { confirmAsyncAction } = useAsyncConfirmDialog()
const route = useRoute()
const router = useRouter()

function documentQueryValue(value: unknown) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function replaceDocumentQuery(patch: Record<string, string | undefined>) {
  const query = { ...route.query }
  Object.entries(patch).forEach(([key, value]) => {
    if (value) query[key] = value
    else delete query[key]
  })
  void router.replace({ path: '/docs', query })
}

const activeWorkspaceTab = ref<'chat' | 'files'>('chat')
const chatFocusDocumentId = ref('')
const knowledgeChatBusy = ref(false)
const knowledgeChatReady = ref(false)
const knowledgeWorkspaceLoading = ref(false)
const knowledgeWorkspaceReady = ref(false)
const knowledgeWorkspaceError = ref('')
let catalogueSyncPollTimer: number | undefined
const fileWorkspaceInitialized = ref(false)
const activeFolderId = ref('')
const expandedFolderIds = ref<string[]>([])
const initialDirectoryExpansionApplied = ref(false)
const selectedFileId = ref('')
const documentInfoOpen = ref(false)
const documentInfoSource = ref<AttachmentRecord>()
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

function allowsCapability(capabilities: EngineeringDocumentCapabilities | undefined, capability: keyof EngineeringDocumentCapabilities) {
  return capabilities ? capabilities[capability] || capabilities.can_manage : true
}
const canReadDocuments = computed(() => Boolean(store.currentProjectId) && (
  store.weknoraKnowledgeBases.some(base => allowsCapability(base.capabilities, 'can_read'))
  || store.documentFolders.length > 0
))
const canCreateDocuments = computed(() => Boolean(store.currentProjectId) && store.documentFolders.some(folder => allowsCapability(folder.capabilities, 'can_create')))
const knowledgeWorkspaceBlocked = computed(() => Boolean(store.currentProjectId) && (
  !knowledgeWorkspaceReady.value || !knowledgeChatReady.value
))
const catalogueUninitialized = computed(() => store.engineeringDocumentSync?.status === 'uninitialized')
const knowledgeWorkspaceStatusText = computed(() => {
  const status = store.engineeringDocumentSync?.status
  if (status === 'pending') return '工程资料正在准备，请稍候…'
  if (status === 'syncing') return '工程资料正在更新，请稍候…'
  if (knowledgeWorkspaceLoading.value) return '正在读取工程资料…'
  return '正在恢复最近对话…'
})
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
      disabled: !allowsCapability(folder.capabilities, 'can_create'),
      children: children.length ? children.map(createOption) : undefined,
    }
  }
  return (folderChildren.value.get(undefined) || []).map(createOption)
})
const activeFolder = computed(() => store.documentFolders.find(folder => folder.id === activeFolderId.value))
const canUpdateActiveFolder = computed(() => Boolean(activeFolder.value) && allowsCapability(activeFolder.value?.capabilities, 'can_update'))
const canDeleteActiveFolder = computed(() => Boolean(activeFolder.value) && allowsCapability(activeFolder.value?.capabilities, 'can_delete'))
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
  const rootFolderIds = new Set(rootFolders.map(folder => folder.id))
  const firstLevelFolders = folders.filter(folder => (
    Boolean(folder.parentId) && rootFolderIds.has(folder.parentId as string)
  ))
  expandedFolderIds.value = [...new Set([
    ...expandedFolderIds.value,
    ...rootFolders.map(folder => folder.id),
    ...firstLevelFolders.map(folder => folder.id),
  ])]
  initialDirectoryExpansionApplied.value = true
}, { immediate: true })

watch(() => store.currentProjectId, async projectId => {
  stopCatalogueSyncPolling()
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
  documentInfoOpen.value = false
  documentInfoSource.value = undefined
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
  await applyDocumentRouteContext()
}, { immediate: true })

watch(
  () => [route.query.tab, route.query.folderId, route.query.documentId, route.query.search] as const,
  () => void applyDocumentRouteContext(),
)

async function initializeKnowledgeWorkspace(projectId: string, force = false) {
  if (!projectId || projectId !== store.currentProjectId) return
  knowledgeWorkspaceLoading.value = true
  knowledgeWorkspaceReady.value = false
  knowledgeWorkspaceError.value = ''
  try {
    await store.loadEngineeringDocuments(projectId, force)
    if (projectId !== store.currentProjectId) return
    const syncStatus = store.engineeringDocumentSync?.status
    if (syncStatus === 'uninitialized') return
    if (syncStatus === 'pending' || syncStatus === 'syncing') {
      scheduleCatalogueSyncPolling(projectId)
      return
    }
    if (syncStatus === 'error' && !store.weknoraKnowledgeBases.length) {
      knowledgeWorkspaceError.value = store.engineeringDocumentSync?.last_error || '工程资料准备失败，请联系管理员。'
      return
    }
    knowledgeWorkspaceReady.value = true
  } catch (error: any) {
    if (projectId === store.currentProjectId) {
      knowledgeWorkspaceError.value = error.response?.data?.detail || error.message || '平台工程资料加载失败。'
    }
  } finally {
    if (projectId === store.currentProjectId) knowledgeWorkspaceLoading.value = false
  }
}

function stopCatalogueSyncPolling() {
  if (catalogueSyncPollTimer !== undefined) window.clearTimeout(catalogueSyncPollTimer)
  catalogueSyncPollTimer = undefined
}

function scheduleCatalogueSyncPolling(projectId: string) {
  stopCatalogueSyncPolling()
  catalogueSyncPollTimer = window.setTimeout(async () => {
    catalogueSyncPollTimer = undefined
    if (projectId !== store.currentProjectId) return
    try {
      await store.loadEngineeringDocuments(projectId, true)
      if (projectId !== store.currentProjectId) return
      const status = store.engineeringDocumentSync?.status
      if (status === 'pending' || status === 'syncing') {
        scheduleCatalogueSyncPolling(projectId)
        return
      }
      if (status === 'error' && !store.weknoraKnowledgeBases.length) {
        knowledgeWorkspaceError.value = store.engineeringDocumentSync?.last_error || '工程资料准备失败，请联系管理员。'
        return
      }
      knowledgeWorkspaceError.value = ''
      knowledgeWorkspaceReady.value = true
    } catch (error: any) {
      if (projectId === store.currentProjectId) {
        knowledgeWorkspaceError.value = error.response?.data?.detail || error.message || '工程资料状态读取失败。'
      }
    }
  }, 1500)
}

onUnmounted(stopCatalogueSyncPolling)

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
      disabled: !allowsCapability(folder.capabilities, 'can_create'),
      children: children.length ? children : undefined,
    }
  }
  return (folderChildren.value.get(undefined) || [])
    .map(createOption)
    .filter((option): option is TreeSelectOption => Boolean(option))
}
function selectTreeNode(node: FolderTreeDisplayNode) {
  replaceDocumentQuery({ tab: 'files', folderId: node.folderId || node.id, documentId: undefined, search: undefined })
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
    message.error(error.response?.data?.detail || error.message || '工程资料加载失败。')
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
    message.success('工程资料已刷新')
  } catch (error: any) {
    message.error(error.response?.data?.detail || error.message || '知识库刷新失败。')
  } finally {
    documentRefreshing.value = false
  }
}
function selectDocument(file: AttachmentRecord) {
  selectedFileId.value = file.id
  replaceDocumentQuery({ tab: 'files', documentId: file.id, search: undefined })
}

function openDocumentInfo(file: AttachmentRecord) {
  selectedFileId.value = file.id
  documentInfoSource.value = file
  documentInfoOpen.value = true
}

function closeDocumentInfo() {
  documentInfoOpen.value = false
  documentInfoSource.value = undefined
}

function openDocumentConversationFromInfo() {
  const file = documentInfoSource.value
  if (!file) return
  closeDocumentInfo()
  openDocumentConversation(file)
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

async function locateReferenceDocument(reference: KnowledgeReferenceLocation, syncRoute = true) {
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
    if (syncRoute) replaceDocumentQuery({ tab: 'files', folderId: folder.id, documentId: knowledgeId, search: undefined })
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

async function switchWorkspaceTab(tab: 'chat' | 'files', syncRoute = true) {
  activeWorkspaceTab.value = tab
  if (syncRoute) {
    replaceDocumentQuery({
      tab,
      folderId: tab === 'files' ? activeFolderId.value || undefined : undefined,
      documentId: tab === 'files' ? selectedFileId.value || undefined : chatFocusDocumentId.value || undefined,
      search: tab === 'files' && isSearchActive.value ? documentSearchKeyword.value || undefined : undefined,
    })
  }
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
  replaceDocumentQuery({ tab: 'chat', documentId: file.id, folderId: undefined, search: undefined })
}

let documentRouteSequence = 0
async function applyDocumentRouteContext() {
  const projectId = store.currentProjectId
  if (!projectId) return
  const sequence = ++documentRouteSequence
  const tab = documentQueryValue(route.query.tab)
  const folderId = documentQueryValue(route.query.folderId)
  const documentId = documentQueryValue(route.query.documentId)
  const search = documentQueryValue(route.query.search).trim()
  if (tab === 'chat' && !folderId && !search) {
    activeWorkspaceTab.value = 'chat'
    chatFocusDocumentId.value = documentId
    return
  }
  if (tab !== 'files' && !folderId && !documentId && !search) return
  await switchWorkspaceTab('files', false)
  if (sequence !== documentRouteSequence || projectId !== store.currentProjectId) return
  if (folderId && store.documentFolders.some(folder => folder.id === folderId)) {
    await selectFolder(folderId)
  }
  if (sequence !== documentRouteSequence || projectId !== store.currentProjectId) return
  if (documentId) {
    const known = store.attachments.find(file => file.id === documentId)
    await locateReferenceDocument({
      knowledgeId: documentId,
      knowledgeBaseId: known?.knowledgeBaseId,
      fileName: known?.fileName || '目标资料',
      folderPath: known?.folderPath,
    }, false)
    return
  }
  if (search) {
    documentSearchKeyword.value = search
    await searchDocuments(false)
  }
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
  if (!canCreateDocuments.value) {
    message.warning('当前账号没有可新建目录的位置。')
    return
  }
  const preferredFolder = store.documentFolders.find(folder => folder.id === activeFolderId.value && allowsCapability(folder.capabilities, 'can_create'))
    || store.documentFolders.find(folder => folder.isKnowledgeBase && allowsCapability(folder.capabilities, 'can_create'))
    || store.documentFolders.find(folder => allowsCapability(folder.capabilities, 'can_create'))
  resumeUploadAfterFolderModal.value = false
  newFolderParentId.value = preferredFolder?.id || ''
  newFolderName.value = ''
  folderModalOpen.value = true
}
function openFolderModalFromUpload() {
  if (documentUploading.value) return
  const preferredFolder = store.documentFolders.find(folder => folder.id === uploadFolderId.value && allowsCapability(folder.capabilities, 'can_create'))
    || store.documentFolders.find(folder => folder.id === activeFolderId.value && allowsCapability(folder.capabilities, 'can_create'))
    || store.documentFolders.find(folder => folder.isKnowledgeBase && allowsCapability(folder.capabilities, 'can_create'))
    || store.documentFolders.find(folder => allowsCapability(folder.capabilities, 'can_create'))
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
  confirmAsyncAction({
    title: '删除文件',
    content: `确认永久删除“${file.fileName}”吗？删除后无法恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    loadingText: '正在删除…',
    onConfirm: () => deleteDocument(file),
  })
}
async function deleteDocument(file: AttachmentRecord): Promise<boolean> {
  if (documentDeletingId.value || documentMovingId.value || folderDeleting.value || folderUpdating.value) return false
  const projectId = store.currentProjectId
  if (!projectId) return false
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
    return false
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
  return true
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
  confirmAsyncAction({
    title: '删除目录',
    content,
    positiveText: documentCount || nestedFolderCount ? '删除全部' : '删除',
    negativeText: '取消',
    loadingText: '正在删除…',
    onConfirm: () => deleteFolder(folder),
  })
}
async function deleteFolder(folder: DocumentFolderRecord): Promise<boolean> {
  if (folderDeleting.value || folderUpdating.value || documentMovingId.value || documentDeletingId.value) return false
  const projectId = store.currentProjectId
  if (!projectId) return false
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
    return true
  } catch (error: any) {
    try {
      await store.loadEngineeringDocuments(projectId, true)
    } catch {
      // 递归删除可能已完成一部分，保留原始错误并让用户稍后刷新。
    }
    message.error(error.response?.data?.detail || error.message || '目录删除失败。')
    return false
  } finally {
    folderDeleting.value = false
  }
}
function openUploadModal() {
  if (!canCreateDocuments.value) {
    message.warning('当前账号没有可上传资料的位置。')
    return
  }
  const preferredFolder = store.documentFolders.find(folder => folder.id === activeFolderId.value && allowsCapability(folder.capabilities, 'can_create'))
    || store.documentFolders.find(folder => folder.isKnowledgeBase && allowsCapability(folder.capabilities, 'can_create'))
    || store.documentFolders.find(folder => allowsCapability(folder.capabilities, 'can_create'))
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
function documentKnowledgeBaseLabel(file: AttachmentRecord) {
  return store.weknoraKnowledgeBases.find(item => item.id === file.knowledgeBaseId)?.name
    || file.knowledgeBaseId
    || '未知知识库'
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
      const detail = uploadError.response?.data?.detail || uploadError.message || '资料上传失败，请检查服务连接。'
      const refreshSuffix = refreshError ? '；同时列表刷新失败：' + refreshError : ''
      message.error(completed ? '已提交 ' + completed + ' 份，其余资料上传失败：' + detail + refreshSuffix : detail)
    } else {
      activeFolderId.value = targetFolderId
      selectedFileId.value = store.attachments.find(item => item.fileName === files[0]?.name)?.id || ''
      pendingUploadFiles.value = []
      uploadModalOpen.value = false
      uploadFolderId.value = ''
      if (refreshError) {
        message.warning('已上传 ' + completed + ' 份资料，但列表刷新失败：' + refreshError)
      } else {
        message.success('已上传 ' + completed + ' 份资料')
      }
    }
  } finally {
    documentUploading.value = false
  }
}
async function searchDocuments(syncRoute = true) {
  if (documentSearching.value) return
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
    if (syncRoute) replaceDocumentQuery({ tab: 'files', search: rawKeyword, documentId: undefined })
  } catch (error: any) {
    message.error(error.response?.data?.detail || '资料检索失败，请稍后重试。')
  } finally {
    documentSearching.value = false
  }
}
function clearSearch(syncRoute = true) {
  documentSearchKeyword.value = ''
  documentSearchResults.value = []
  isSearchActive.value = false
  selectedFileId.value = ''
  if (syncRoute) replaceDocumentQuery({ search: undefined, documentId: undefined })
}
</script>

<style scoped src="./styles/DocumentLibraryView.css"></style>
