<template>
  <main class="document-library">
    <section class="library-browser">
      <form class="library-toolbar" @submit.prevent="searchDocuments">
        <label class="toolbar-search-field">
          <n-icon :size="18"><Search /></n-icon>
          <input v-model.trim="documentSearchKeyword" :disabled="!canManageDocuments" placeholder="搜索文件或文件夹，例如：基坑、监测、验收">
        </label>
        <button type="submit" class="toolbar-search" :disabled="!canManageDocuments || documentSearching">{{ documentSearching ? '检索中…' : '搜索资料' }}</button>
        <button v-if="isSearchActive" type="button" class="toolbar-clear" @click="clearSearch">清除</button>
        <div class="toolbar-actions">
          <button type="button" class="toolbar-folder" @click="openFolderCreate"><n-icon :size="15"><Plus /></n-icon>新建文件夹</button>
          <button type="button" class="toolbar-upload" :disabled="!canManageDocuments || documentUploading" @click="openUploadModal"><n-icon :size="15"><Paperclip /></n-icon>{{ documentUploading ? '正在上传…' : '上传文件' }}</button>
        </div>
      </form>

      <section class="library-shell">
        <aside class="folder-tree" aria-label="项目资料目录">
          <nav class="folder-tree-nav">
            <div class="tree-row tree-root-row">
              <button type="button" class="tree-toggle" :aria-label="allFoldersExpanded ? '收起全部资料' : '展开全部资料'" :aria-expanded="allFoldersExpanded" @click="allFoldersExpanded = !allFoldersExpanded"><n-icon :size="15"><ChevronDown v-if="allFoldersExpanded" /><ChevronRight v-else /></n-icon></button>
              <button type="button" class="tree-item" :class="{ 'is-active': !activeFolderId }" @click="selectFolder('')"><n-icon :size="16"><Folder /></n-icon><span>全部资料</span></button>
            </div>
            <div v-for="node in folderTreeNodes" v-show="allFoldersExpanded" :key="node.folder.id" class="tree-row" :class="`tree-depth-${Math.min(node.depth, 4)}`">
              <button v-if="node.hasChildren" type="button" class="tree-toggle" :aria-label="`${isFolderExpanded(node.folder.id) ? '收起' : '展开'} ${node.folder.name}`" :aria-expanded="isFolderExpanded(node.folder.id)" @click="toggleFolderExpanded(node.folder.id)"><n-icon :size="15"><ChevronDown v-if="isFolderExpanded(node.folder.id)" /><ChevronRight v-else /></n-icon></button>
              <span v-else class="tree-spacer" aria-hidden="true"></span>
              <button type="button" class="tree-item" :class="{ 'is-active': activeFolderId === node.folder.id }" :title="node.folder.name" @click="selectFolder(node.folder.id)"><n-icon :size="16"><Folder /></n-icon><span>{{ node.folder.name }}</span></button>
            </div>
          </nav>
        </aside>
        <section class="library-content">
        <nav class="library-path-row" aria-label="资料目录导航">
          <div class="library-breadcrumb"><button type="button" class="breadcrumb-root" :disabled="!activeFolderId" @click="selectFolder('')">项目资料</button><template v-for="folder in activeFolderPath" :key="folder.id"><n-icon class="breadcrumb-separator" :size="15"><ChevronRight /></n-icon><button type="button" :class="{ 'is-current': folder.id === activeFolderId }" :disabled="folder.id === activeFolderId" @click="selectFolder(folder.id)">{{ folder.name }}</button></template></div>
          <span class="library-count">{{ directoryItemCount }} 个项目</span>
        </nav>

        <div v-if="isSearchActive" class="search-state"><span>正在显示“{{ documentSearchKeyword }}”的搜索结果</span><button type="button" @click="clearSearch">返回文件夹</button></div>

        <section class="file-grid-panel" :class="{ 'is-empty': !visibleFolders.length && !visibleFiles.length }" aria-label="当前目录内容">
          <button v-for="folder in visibleFolders" :key="folder.id" type="button" class="file-tile folder-tile" :aria-label="`打开文件夹 ${folder.name}`" @click="selectFolder(folder.id)">
            <span class="tile-icon folder-icon" aria-hidden="true"><span></span></span>
            <strong :title="folder.name">{{ folder.name }}</strong>
            <span class="tile-meta">{{ folderDescendantCount(folder.id) }} 个子项</span>
          </button>
          <article v-for="file in visibleFiles" :key="file.id" class="file-tile document-tile">
            <span class="tile-icon document-icon" aria-hidden="true"><span>{{ fileExtension(file.fileName) }}</span></span>
            <strong :title="file.fileName">{{ file.fileName }}</strong>
            <span class="tile-meta">{{ formatFileSize(file.fileSize) }} · V{{ file.version }}</span>
            <button v-if="file.category === '日报'" type="button" class="tile-action" @click="store.parseDailyAttachment(file.id)">登记日报</button>
            <span v-else-if="file.snippet" class="tile-snippet" :title="file.snippet">{{ file.snippet }}</span>
            <span v-else class="tile-meta">{{ file.category }}</span>
          </article>
          <div v-if="!visibleFolders.length && !visibleFiles.length" class="file-empty"><n-icon :size="24"><FileText /></n-icon><strong>{{ isSearchActive ? '没有匹配的文件或文件夹' : canManageDocuments ? '当前目录还没有内容，可新建文件夹或上传文件到当前目录。' : '请先在工程配置中创建并选择一个项目。' }}</strong></div>
        </section>
      </section>

    </section>
    </section>

    <div v-if="folderCreateOpen" class="library-modal-backdrop" @click.self="closeFolderCreate">
      <section class="library-modal" role="dialog" aria-modal="true" aria-labelledby="folder-create-title">
        <div class="library-modal-head"><div><h2 id="folder-create-title">新建文件夹</h2></div><button type="button" class="modal-close" @click="closeFolderCreate">关闭</button></div>
        <form class="folder-create-form" @submit.prevent="createFolder"><div class="folder-parent-context"><span>父目录</span><strong>{{ currentDirectoryName }}</strong></div><label>文件夹名称<input v-model.trim="folderCreateName" required maxlength="200" placeholder="例如：监测报告"></label><div><button type="button" class="modal-secondary" @click="closeFolderCreate">取消</button><button type="submit" class="modal-primary" :disabled="folderCreating">{{ folderCreating ? '正在创建…' : '创建文件夹' }}</button></div></form>
      </section>
    </div>

    <div v-if="uploadModalOpen" class="library-modal-backdrop" @click.self="closeUploadModal">
      <section class="library-modal upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title">
        <div class="library-modal-head"><div><h2 id="upload-title">上传文件</h2></div><button type="button" class="modal-close" :disabled="documentUploading" @click="closeUploadModal">关闭</button></div>
        <form class="upload-form" @submit.prevent="confirmUploadDocuments">
          <div class="folder-parent-context"><span>当前目录</span><strong>{{ currentDirectoryName }}</strong></div>
          <div class="upload-queue-head"><div><strong>待上传列表</strong><span>{{ pendingUploadFiles.length }} 个文件 · {{ formatFileSize(pendingUploadTotalSize) }}</span></div><label class="upload-picker"><input type="file" multiple :disabled="documentUploading" @change="queueUploadFiles">选择文件</label></div>
          <ul v-if="pendingUploadFiles.length" class="upload-queue">
            <li v-for="(file, index) in pendingUploadFiles" :key="`${file.name}-${file.size}-${file.lastModified}`"><span class="upload-file-type">{{ fileExtension(file.name) }}</span><div><strong :title="file.name">{{ file.name }}</strong><span>{{ formatFileSize(file.size) }}</span></div><button type="button" :disabled="documentUploading" :aria-label="`移除 ${file.name}`" @click="removePendingUpload(index)">移除</button></li>
          </ul>
          <div v-else class="upload-queue-empty"><n-icon :size="24"><FileText /></n-icon><strong>还没有待上传文件</strong><span>点击“选择文件”可一次选择多个文件。</span></div>
          <div class="upload-actions"><button type="button" class="modal-secondary" :disabled="documentUploading" @click="closeUploadModal">取消</button><button type="submit" class="modal-primary" :disabled="documentUploading || !pendingUploadFiles.length">{{ documentUploading ? '正在上传…' : `上传 ${pendingUploadFiles.length} 个文件` }}</button></div>
        </form>
      </section>
    </div>

  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMessage, NIcon } from 'naive-ui'
import { ChevronDown, ChevronRight, FileText, Folder, Paperclip, Plus, Search } from '@vicons/tabler'
import { useAppStore, type AttachmentRecord, type DocumentFolderRecord } from '@/stores/app'

const store = useAppStore()
const message = useMessage()
const activeFolderId = ref('')
const allFoldersExpanded = ref(true)
const expandedFolderIds = ref<string[]>([])
const documentUploading = ref(false)
const uploadModalOpen = ref(false)
const pendingUploadFiles = ref<File[]>([])
const documentSearching = ref(false)
const documentSearchKeyword = ref('')
const documentSearchResults = ref<AttachmentRecord[]>([])
const documentSearchFolderResults = ref<DocumentFolderRecord[]>([])
const isSearchActive = ref(false)
const folderCreateOpen = ref(false)
const folderCreating = ref(false)
const folderCreateName = ref('')

const canManageDocuments = computed(() => Boolean(store.currentProjectId))
const activeFolder = computed(() => store.documentFolders.find(folder => folder.id === activeFolderId.value))
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
  const nodes: Array<{ folder: DocumentFolderRecord; depth: number; hasChildren: boolean }> = []
  const visit = (parentId: string | undefined, depth: number) => {
    for (const folder of folderChildren.value.get(parentId) || []) {
      const hasChildren = Boolean(folderChildren.value.get(folder.id)?.length)
      nodes.push({ folder, depth, hasChildren })
      if (hasChildren && expandedFolderIds.value.includes(folder.id)) visit(folder.id, depth + 1)
    }
  }
  visit(undefined, 1)
  return nodes
})
const activeFolderPath = computed(() => {
  const path: DocumentFolderRecord[] = []
  let current = activeFolder.value
  while (current) {
    path.unshift(current)
    current = current.parentId ? store.documentFolders.find(folder => folder.id === current?.parentId) : undefined
  }
  return path
})
const currentDirectoryName = computed(() => activeFolder.value?.name || '全部资料')
const pendingUploadTotalSize = computed(() => pendingUploadFiles.value.reduce((total, file) => total + file.size, 0))
const childFolders = computed(() => store.documentFolders.filter(folder => folder.parentId === (activeFolderId.value || undefined)))
const visibleFolders = computed(() => isSearchActive.value ? documentSearchFolderResults.value : childFolders.value)
const visibleFiles = computed(() => {
  if (isSearchActive.value) return documentSearchResults.value
  const source = store.attachments
  return activeFolderId.value ? source.filter(file => file.folderId === activeFolderId.value) : source
})
const directoryItemCount = computed(() => visibleFolders.value.length + visibleFiles.value.length)

function isFolderExpanded(folderId: string) { return expandedFolderIds.value.includes(folderId) }
function toggleFolderExpanded(folderId: string) { expandedFolderIds.value = isFolderExpanded(folderId) ? expandedFolderIds.value.filter(id => id !== folderId) : [...expandedFolderIds.value, folderId] }
function selectFolder(folderId: string) {
  if (isSearchActive.value) clearSearch()
  activeFolderId.value = folderId
  let current = store.documentFolders.find(folder => folder.id === folderId)
  const ancestorIds: string[] = []
  while (current?.parentId) {
    ancestorIds.push(current.parentId)
    current = store.documentFolders.find(folder => folder.id === current?.parentId)
  }
  if (ancestorIds.length) expandedFolderIds.value = [...new Set([...expandedFolderIds.value, ...ancestorIds])]
}
function openFolderCreate() { if (!canManageDocuments.value) { message.warning('请先在工程配置中创建并选择一个项目。'); return }; folderCreateOpen.value = true }
function openUploadModal() {
  if (!canManageDocuments.value) { message.warning('请先在工程配置中创建并选择一个项目。'); return }
  pendingUploadFiles.value = []
  uploadModalOpen.value = true
}
function folderDescendantCount(folderId: string): number {
  const children = store.documentFolders.filter(folder => folder.parentId === folderId)
  const directFiles = store.attachments.filter(file => file.folderId === folderId).length
  return directFiles + children.reduce((total, child) => total + 1 + folderDescendantCount(child.id), 0)
}
function fileExtension(fileName: string) { return fileName.includes('.') ? (fileName.split('.').pop() || 'FILE').slice(0, 5).toUpperCase() : 'FILE' }
function formatFileSize(bytes: number) { if (bytes <= 0) return '0 KB'; return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }
function formatDate(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '刚刚' }

function queueUploadFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const selectedFiles = Array.from(input.files || [])
  if (!selectedFiles.length) return
  const existingKeys = new Set(pendingUploadFiles.value.map(file => `${file.name}-${file.size}-${file.lastModified}`))
  pendingUploadFiles.value = [...pendingUploadFiles.value, ...selectedFiles.filter(file => !existingKeys.has(`${file.name}-${file.size}-${file.lastModified}`))]
  input.value = ''
}
function removePendingUpload(index: number) { pendingUploadFiles.value = pendingUploadFiles.value.filter((_, fileIndex) => fileIndex !== index) }
function closeUploadModal() {
  if (documentUploading.value) return
  uploadModalOpen.value = false
  pendingUploadFiles.value = []
}
async function confirmUploadDocuments() {
  if (!pendingUploadFiles.value.length || documentUploading.value) return
  const files = [...pendingUploadFiles.value]
  let uploadedCount = 0
  documentUploading.value = true
  try {
    for (const file of files) {
      await store.uploadAttachment(file, '自动归类', activeFolderId.value || undefined)
      uploadedCount += 1
    }
    pendingUploadFiles.value = []
    uploadModalOpen.value = false
    message.success(`已上传 ${uploadedCount} 个文件`)
  } catch (error: any) {
    pendingUploadFiles.value = files.slice(uploadedCount)
    const uploadedNote = uploadedCount ? `已完成 ${uploadedCount} 个，` : ''
    message.error(`${uploadedNote}${error.response?.data?.detail || '其余文件上传失败，请检查服务连接。'}`)
  } finally { documentUploading.value = false }
}
async function searchDocuments() {
  if (!documentSearchKeyword.value) { clearSearch(); return }
  documentSearching.value = true
  try {
    const keyword = documentSearchKeyword.value.trim().toLocaleLowerCase('zh-CN')
    documentSearchResults.value = await store.searchDocuments(documentSearchKeyword.value)
    documentSearchFolderResults.value = store.documentFolders.filter(folder => folder.name.toLocaleLowerCase('zh-CN').includes(keyword))
    isSearchActive.value = true
  } catch (error: any) { message.error(error.response?.data?.detail || '资料检索失败，请稍后重试。') } finally { documentSearching.value = false }
}
function clearSearch() { documentSearchKeyword.value = ''; documentSearchResults.value = []; documentSearchFolderResults.value = []; isSearchActive.value = false }
function closeFolderCreate() { if (!folderCreating.value) folderCreateOpen.value = false }
async function createFolder() {
  if (!canManageDocuments.value) { message.warning('请先在工程配置中创建并选择一个项目。'); return }
  if (!folderCreateName.value) return
  folderCreating.value = true
  try { await store.createDocumentFolder({ name: folderCreateName.value, parentId: activeFolderId.value || undefined }); message.success('文件夹已创建'); folderCreateName.value = ''; folderCreateOpen.value = false } catch (error: any) { message.error(error.response?.data?.detail || '文件夹创建失败，请检查权限和服务连接。') } finally { folderCreating.value = false }
}
</script>

<style scoped>
.document-library { box-sizing:border-box; display:flex; min-height:calc(100dvh - var(--header-height, 56px)); padding:18px; color:var(--text-primary); background:radial-gradient(circle at 80% 0%, rgba(219,120,48,.06), transparent 26rem), linear-gradient(180deg,#f6f7f3,#edf1ee); }
.library-browser { display:flex; flex:1 1 auto; width:100%; min-width:0; flex-direction:column; min-height:0; border:1px solid var(--border-default); border-radius:11px; background:#fff; box-shadow:0 12px 28px rgba(29,58,53,.06); overflow:hidden; }.library-toolbar { display:flex; align-items:center; gap:9px; padding:10px 12px; border-bottom:1px solid var(--border-default); background:#fff; }.toolbar-search-field { display:flex; flex:1 1 auto; align-items:center; gap:8px; min-width:120px; border:1px solid var(--border-emphasis); border-radius:6px; padding:0 10px; background:#fff; transition:border-color .16s ease,box-shadow .16s ease; }.toolbar-search-field:focus-within { border-color:#3c716b; box-shadow:0 0 0 3px rgba(15,118,110,.1); }.toolbar-search-field>svg { flex:0 0 auto; color:var(--text-muted); }.toolbar-search-field input { flex:1; min-width:0; height:32px; border:0; outline:0; background:transparent; color:var(--text-primary); font:inherit; font-size:13px; }.toolbar-search,.toolbar-clear,.toolbar-folder,.toolbar-draft,.toolbar-upload { display:inline-flex; align-items:center; justify-content:center; gap:6px; border:1px solid var(--border-emphasis); border-radius:6px; padding:7px 10px; font:inherit; font-size:12px; font-weight:750; cursor:pointer; white-space:nowrap; }.toolbar-search { border-color:#173235; color:#fff; background:#173235; }.toolbar-clear,.toolbar-folder,.toolbar-draft { color:var(--text-secondary); background:#fff; }.toolbar-upload { color:#fff; border-color:transparent; background:var(--color-primary); }.toolbar-upload input { display:none; }.toolbar-search:disabled,.toolbar-folder:disabled,.toolbar-draft:disabled,.toolbar-upload.disabled { opacity:.55; cursor:not-allowed; }.toolbar-actions { display:flex; align-items:center; gap:7px; margin-left:auto; }
.library-shell { display:flex; flex:1 1 auto; min-height:0; }
.library-content { display:flex; flex:1 1 auto; flex-direction:column; min-width:0; min-height:0; overflow:auto; padding:16px; }.library-path-row { display:flex; align-items:center; gap:8px; min-height:38px; margin-bottom:12px; padding:4px 9px; border:1px solid var(--border-default); border-radius:7px; background:#f7faf8; }.library-breadcrumb { display:flex; flex:1 1 auto; align-items:center; gap:4px; min-width:0; overflow:auto; color:var(--text-muted); font-size:12px; scrollbar-width:thin; }.library-breadcrumb button { flex:0 0 auto; border:0; border-radius:4px; padding:5px 6px; color:#315854; background:transparent; font:inherit; font-size:12px; font-weight:750; cursor:pointer; white-space:nowrap; }.library-breadcrumb button:not(:disabled):hover { color:#173235; background:#e7f1ee; }.library-breadcrumb .breadcrumb-root:disabled,.library-breadcrumb .is-current:disabled { color:#173235; cursor:default; }.breadcrumb-separator { flex:0 0 auto; color:#8aa09d; }.library-count { flex:0 0 auto; padding:0 5px; color:var(--text-muted); font-size:12px; font-variant-numeric:tabular-nums; white-space:nowrap; }.search-state { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:12px; padding:8px 10px; border:1px solid rgba(15,118,110,.15); border-radius:6px; color:#285d57; background:#f0f8f5; font-size:12px; }.search-state button { border:0; padding:0; color:#0f766e; background:transparent; font:inherit; font-size:12px; font-weight:750; cursor:pointer; }.file-list-panel { display:flex; flex:1 1 auto; flex-direction:column; min-height:250px; border:1px solid var(--border-default); border-radius:8px; overflow:hidden; }.file-list-head,.file-list-row { display:grid; grid-template-columns:minmax(180px,1.7fr) .65fr .45fr .72fr .35fr .6fr; align-items:center; gap:10px; }.file-list-head { padding:9px 12px; color:var(--text-muted); background:#f7faf8; font-size:11px; font-weight:800; }.file-list-row { min-height:57px; padding:8px 12px; border-top:1px solid var(--border-default); color:var(--text-secondary); font-size:12px; }.directory-row { width:100%; border:0; border-top:1px solid var(--border-default); background:#fff; text-align:left; font:inherit; cursor:pointer; transition:background .16s ease; }.directory-row:hover { background:#f7faf8; }.directory-row:focus-visible,.library-breadcrumb button:focus-visible { outline:2px solid rgba(15,118,110,.45); outline-offset:-2px; }.folder-entry-icon { flex:0 0 auto; color:var(--color-primary); }.file-name { display:flex; align-items:center; min-width:0; gap:9px; }.file-type { flex:0 0 auto; min-width:35px; padding:5px 4px; border-radius:4px; color:#496967; background:#e7f1ee; text-align:center; font-size:9px; font-weight:850; letter-spacing:.02em; }.file-name strong,.file-name p { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.file-name strong { color:#173235; font-size:12px; }.file-name p { max-width:35ch; margin:3px 0 0; color:var(--text-muted); font-size:11px; }.file-category { color:#466b66; }.file-list-row time { color:var(--text-muted); font-variant-numeric:tabular-nums; }.file-action { justify-self:start; border:0; border-radius:5px; padding:6px 8px; color:#fff; background:var(--color-primary); font:inherit; font-size:11px; font-weight:750; cursor:pointer; }.file-ready,.file-open { color:#4b6d68; font-size:11px; font-weight:700; }.file-empty { display:grid; flex:1 1 auto; align-content:center; justify-items:center; gap:7px; padding:50px 18px; color:var(--text-muted); text-align:center; }.file-empty strong { color:var(--text-secondary); font-size:13px; }.file-empty p { max-width:35ch; margin:0; font-size:12px; line-height:1.6; }
.library-modal-backdrop { position:fixed; inset:0; z-index:30; display:grid; place-items:center; padding:24px; background:rgba(15,32,35,.42); backdrop-filter:blur(2px); }.library-modal { width:min(100%,470px); max-height:calc(100dvh - 48px); overflow:auto; padding:20px; border:1px solid rgba(28,56,57,.18); border-radius:12px; background:#fff; box-shadow:0 22px 56px rgba(15,39,42,.26); }.draft-modal { width:min(100%,720px); }.library-modal-head { display:flex; justify-content:space-between; align-items:center; gap:14px; min-width:0; margin-bottom:12px; }.library-modal-head>div { display:flex; flex:1 1 auto; align-items:baseline; gap:10px; min-width:0; }.library-modal-head span { flex:0 0 auto; color:var(--color-primary); font-size:12px; font-weight:800; letter-spacing:.04em; white-space:nowrap; }.library-modal-head h2 { flex:0 1 auto; overflow:hidden; min-width:0; margin:0; color:#173235; font-size:17px; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }.library-modal-head p { flex:1 1 12rem; overflow:hidden; min-width:4rem; margin:0; color:var(--text-muted); font-size:12px; line-height:1.4; text-overflow:ellipsis; white-space:nowrap; }.library-modal-head .modal-close { flex:0 0 auto; }.modal-close,.modal-secondary,.modal-primary,.modal-assist { border:0; border-radius:6px; padding:8px 12px; font:inherit; font-size:12px; font-weight:750; cursor:pointer; }.modal-close,.modal-secondary { border:1px solid var(--border-emphasis); color:var(--text-secondary); background:#fff; }.modal-primary { color:#fff; background:var(--color-primary); }.modal-assist { color:#0c5d58; background:#e7f4f0; }.modal-assist:disabled { opacity:.5; cursor:not-allowed; }.folder-create-form { display:grid; gap:14px; }.folder-parent-context span { color:var(--text-muted); font-size:12px; font-weight:700; }.folder-parent-context strong { color:#294d47; font-size:13px; font-weight:750; line-height:1.5; overflow-wrap:anywhere; }.folder-create-form label,.draft-create-form label { display:grid; gap:6px; color:var(--text-secondary); font-size:12px; font-weight:750; }.folder-create-form input,.draft-create-form input,.draft-create-form select,.draft-create-form textarea { width:100%; min-width:0; box-sizing:border-box; padding:9px 10px; border:1px solid var(--border-emphasis); border-radius:6px; background:#fff; color:var(--text-primary); font:inherit; font-size:13px; }.folder-create-form>div,.draft-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }.folder-create-form>.folder-parent-context { display:grid; justify-content:stretch; gap:5px; padding:10px 11px; border:1px solid #dfe9e6; border-radius:6px; background:#f5f9f7; }.draft-create-form { display:grid; grid-template-columns:1fr 1fr; gap:13px 12px; }.draft-content-field,.draft-actions { grid-column:1 / -1; }.draft-create-form textarea { min-height:110px; resize:vertical; }

.toolbar-upload:disabled { opacity:.55; cursor:not-allowed; }
.upload-modal { display:flex; width:min(100%,620px); height:min(560px,calc(100dvh - 48px)); flex-direction:column; overflow:hidden; }
.upload-modal>.library-modal-head { flex:0 0 auto; }
.upload-form { display:grid; flex:1 1 auto; min-height:0; grid-template-rows:auto auto minmax(0,1fr) auto; gap:14px; }
.upload-form>.folder-parent-context { display:grid; gap:5px; padding:10px 11px; border:1px solid #dfe9e6; border-radius:6px; background:#f5f9f7; }
.upload-queue-head { display:flex; align-items:center; justify-content:space-between; gap:14px; }
.upload-queue-head>div { display:grid; gap:3px; min-width:0; }
.upload-queue-head strong { color:#294d47; font-size:13px; }
.upload-queue-head span { color:var(--text-muted); font-size:12px; }
.upload-picker { display:inline-flex; flex:0 0 auto; align-items:center; justify-content:center; border:1px solid #83afa7; border-radius:6px; padding:8px 12px; color:#17665d; background:#f2f8f6; font-size:12px; font-weight:750; cursor:pointer; }
.upload-picker:hover { border-color:#4d8c82; background:#eaf5f2; }
.upload-picker input { display:none; }
.upload-queue { display:grid; min-height:0; align-content:start; gap:6px; margin:0; padding:0; overflow:auto; list-style:none; scrollbar-gutter:stable; }
.upload-queue li { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:10px; min-height:52px; padding:8px 10px; border:1px solid #e1e9e7; border-radius:7px; background:#fbfcfc; }
.upload-file-type { display:grid; place-items:center; min-width:42px; min-height:32px; border-radius:5px; color:#3d6862; background:#e7f1ee; font-size:12px; font-weight:800; }
.upload-queue li>div { display:grid; min-width:0; gap:3px; }
.upload-queue li strong { overflow:hidden; color:#294842; font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
.upload-queue li div span { color:var(--text-muted); font-size:12px; }
.upload-queue li button { border:0; padding:6px; color:#b9532b; background:transparent; font:inherit; font-size:12px; font-weight:700; cursor:pointer; }
.upload-queue li button:disabled { opacity:.5; cursor:not-allowed; }
.upload-queue-empty { display:grid; min-height:0; place-content:center; justify-items:center; gap:7px; padding:20px; border:1px dashed #cad9d5; border-radius:8px; color:var(--text-muted); text-align:center; }
.upload-queue-empty strong { color:#3b5d57; font-size:13px; }
.upload-queue-empty span { font-size:12px; }
.upload-actions { display:flex; justify-content:flex-end; gap:8px; padding-top:2px; }

/* 图标网格独立滚动，页面框架、工具栏与路径导航保持固定。 */
.document-library { height:calc(100dvh - var(--header-height, 56px)); min-height:0; overflow:hidden; }
.library-content { overflow:hidden; }
.folder-tree { flex:0 0 240px; min-width:240px; overflow-x:auto; overflow-y:auto; padding:12px 8px; border-right:1px solid var(--border-default); background:linear-gradient(180deg,#fbfcfb,#f6f8f7); scrollbar-gutter:stable; }
.folder-tree-head { display:flex; align-items:center; justify-content:space-between; padding:0 8px 9px; color:var(--text-muted); font-size:11px; font-weight:800; letter-spacing:.04em; }.folder-tree-head span:last-child { min-width:19px; border-radius:4px; padding:2px 5px; color:#56736f; background:#e8efed; text-align:center; font-size:10px; font-variant-numeric:tabular-nums; }
.folder-tree-nav { display:grid; width:max-content; min-width:100%; align-content:start; gap:1px; }.tree-row { display:flex; width:max-content; min-width:100%; align-items:center; }.tree-depth-1 { padding-left:14px; }.tree-depth-2 { padding-left:28px; }.tree-depth-3 { padding-left:42px; }.tree-depth-4 { padding-left:56px; }
.tree-toggle,.tree-spacer { flex:0 0 22px; width:22px; height:28px; }.tree-toggle { display:grid; place-items:center; border:0; border-radius:4px; padding:0; color:#6f8985; background:transparent; cursor:pointer; }.tree-toggle:hover { color:#174f49; background:#e6f0ed; }.tree-item { display:flex; flex:1 0 auto; align-items:center; min-width:max-content; gap:7px; height:28px; border:0; border-radius:5px; padding:0 7px 0 4px; color:#405f5b; background:transparent; font:inherit; font-size:12px; font-weight:650; text-align:left; cursor:pointer; transition:background .16s ease, color .16s ease; }.tree-item>svg { flex:0 0 auto; color:#d58a17; }.tree-item>span { white-space:nowrap; }.tree-item:hover { color:#173b37; background:#edf5f2; }.tree-item.is-active { color:#173b37; background:#dcece7; font-weight:800; }.tree-item:focus-visible,.tree-toggle:focus-visible { outline:2px solid rgba(15,118,110,.48); outline-offset:-2px; }
.file-grid-panel { display:grid; grid-template-columns:repeat(auto-fill, minmax(116px, 1fr)); grid-auto-rows:minmax(154px, auto); align-content:start; flex:1 1 auto; min-height:0; overflow:auto; gap:6px 4px; padding:15px; border:1px solid var(--border-default); border-radius:8px; background:linear-gradient(180deg,#fff,#fbfcfb); scrollbar-gutter:stable; }
.file-grid-panel.is-empty { display:flex; }
.file-tile { display:flex; flex-direction:column; align-items:center; min-width:0; min-height:148px; padding:8px 7px 9px; border:1px solid transparent; border-radius:7px; color:var(--text-primary); background:transparent; font:inherit; text-align:center; transition:border-color .16s ease, background .16s ease, transform .16s ease; }
.folder-tile { cursor:pointer; }.file-tile:hover { border-color:#d5e5e1; background:#f3f8f6; transform:translateY(-1px); }.file-tile:active { transform:translateY(0) scale(.985); }.file-tile:focus-visible { outline:2px solid rgba(15,118,110,.48); outline-offset:-2px; }
.tile-icon { position:relative; flex:0 0 auto; display:block; width:76px; height:60px; margin:3px 0 9px; }.folder-icon::before { content:''; position:absolute; z-index:0; top:2px; left:8px; width:32px; height:15px; border-radius:7px 7px 1px 1px; background:#dc9b20; }.folder-icon::after { content:''; position:absolute; inset:12px 2px 2px; z-index:1; border:1px solid #d4951e; border-radius:4px 6px 6px; background:linear-gradient(135deg,#ffd875,#efaa2c); box-shadow:inset 0 1px rgba(255,255,255,.4), 0 2px 3px rgba(124,82,16,.12); }.folder-icon span { position:absolute; z-index:2; top:14px; left:4px; width:68px; height:9px; border-radius:4px 5px 0 0; background:linear-gradient(90deg,#ffe697,#f7c354); }
.document-icon { width:52px; margin-bottom:9px; border:1px solid #cbd5d2; border-radius:3px; background:#fff; box-shadow:0 2px 4px rgba(34,65,60,.1); }.document-icon::before { content:''; position:absolute; top:-1px; right:-1px; width:15px; height:15px; border-left:1px solid #cbd5d2; border-bottom:1px solid #cbd5d2; border-radius:0 3px 0 3px; background:linear-gradient(135deg,#eaf0ed 49%,#fff 50%); }.document-icon span { position:absolute; right:5px; bottom:6px; left:5px; overflow:hidden; color:#376761; font-size:8px; font-weight:850; letter-spacing:.03em; white-space:nowrap; }
.file-tile>strong { display:-webkit-box; width:100%; overflow:hidden; color:#24413e; font-size:12px; font-weight:750; line-height:1.35; text-align:center; text-wrap:pretty; -webkit-box-orient:vertical; -webkit-line-clamp:2; }.tile-meta,.tile-snippet { display:block; width:100%; overflow:hidden; margin-top:4px; color:var(--text-muted); font-size:10px; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }.tile-snippet { color:#66817d; }.tile-action { margin-top:5px; border:0; border-radius:4px; padding:4px 6px; color:#fff; background:var(--color-primary); font:inherit; font-size:10px; font-weight:750; cursor:pointer; }
.file-grid-panel>.file-empty { display:flex; grid-column:1 / -1; align-self:stretch; align-items:center; justify-content:center; gap:9px; min-height:0; padding:24px; color:var(--text-muted); text-align:center; }.file-grid-panel.is-empty>.file-empty { flex:1 1 auto; }.file-grid-panel>.file-empty strong { color:var(--text-secondary); font-size:13px; font-weight:700; white-space:nowrap; }
@media (max-width:960px) { .folder-tree { display:none; } }
@media (max-width:900px) { .file-list-head { display:none; }.file-list-row { grid-template-columns:minmax(0,1fr) auto; gap:7px 10px; }.file-list-row>.file-category,.file-list-row>span:not(.file-ready),.file-list-row>time { display:none; }.file-name { grid-column:1 / -1; }.file-action,.file-ready { grid-column:2; } }
@media (max-width:760px) { .document-library { padding:12px; }.library-toolbar { flex-wrap:wrap; padding:9px; }.library-toolbar input { flex:1 1 150px; }.toolbar-actions { width:100%; margin-left:0; }.toolbar-folder,.toolbar-draft,.toolbar-upload { flex:1 1 0; }.library-content { padding:13px; }.file-grid-panel { grid-template-columns:repeat(auto-fill, minmax(98px, 1fr)); gap:4px; padding:9px; }.file-tile { min-height:132px; padding:6px 4px; }.tile-icon { transform:scale(.88); margin-bottom:3px; }.library-modal-backdrop { padding:12px; }.library-modal { max-height:calc(100dvh - 24px); padding:16px; }.draft-create-form { grid-template-columns:1fr; }.draft-content-field,.draft-actions { grid-column:auto; }.draft-actions button,.folder-create-form>div button { flex:1 1 auto; } }
@media (max-width:760px) { .upload-modal { height:calc(100dvh - 24px); }.upload-queue-head { align-items:flex-start; }.upload-actions button { flex:1 1 0; } }
@media (max-width:760px) { .library-modal-head span,.library-modal-head p { display:none; } }
</style>
