<template>
  <main class="document-library">
    <section class="dobby-workspace">
      <header class="dobby-topbar">
        <div class="dobby-identity">
          <span class="dobby-avatar" aria-hidden="true"><n-icon :size="21"><Robot /></n-icon></span>
          <div>
            <span>Dobby 资料助手</span>
            <strong>先诊断，再归档</strong>
          </div>
          <em><i></i>AI 在线</em>
        </div>

        <form class="dobby-search" @submit.prevent="searchDocuments">
          <n-icon :size="18"><Search /></n-icon>
          <input
            v-model.trim="documentSearchKeyword"
            :disabled="!canManageDocuments"
            placeholder="问 Dobby：找出深基坑监测资料和对应的预警依据"
          >
          <button type="submit" :disabled="!canManageDocuments || documentSearching">
            {{ documentSearching ? '正在分析…' : '问 Dobby' }}
          </button>
        </form>

        <div class="topbar-actions">
          <button type="button" class="secondary-action" @click="openFolderCreate">
            <n-icon :size="16"><Plus /></n-icon>
            新建目录
          </button>
          <button type="button" class="primary-action" :disabled="!canManageDocuments || documentUploading || diagnosisRunning" @click="openUploadModal">
            <n-icon :size="16"><Paperclip /></n-icon>
            上传并诊断
          </button>
        </div>
      </header>

      <section class="dobby-workspace-grid">
        <aside class="folder-rail" aria-label="项目资料目录">
          <header class="folder-rail-head">
            <div>
              <strong>资料库目录</strong>
            </div>
            <button type="button" aria-label="新建文件夹" @click="openFolderCreate"><n-icon :size="16"><Plus /></n-icon></button>
          </header>

          <nav class="folder-tree-nav">
            <div v-for="node in folderTreeNodes" :key="node.id" class="tree-row" :class="'tree-depth-' + Math.min(node.depth, 4)">
              <button v-if="node.hasChildren" type="button" class="tree-toggle" :aria-label="(isFolderExpanded(node.id) ? '收起 ' : '展开 ') + node.name" :aria-expanded="isFolderExpanded(node.id)" @click="toggleFolderExpanded(node.id)">
                <n-icon :size="15"><ChevronDown v-if="isFolderExpanded(node.id)" /><ChevronRight v-else /></n-icon>
              </button>
              <span v-else class="tree-spacer" aria-hidden="true"></span>
              <button type="button" class="tree-item" :class="{ 'is-active': activeTreeNodeId === node.id, 'is-library-root': node.depth === 0 }" :title="node.name" @click="selectTreeNode(node)">
                <em>{{ node.count }}</em>
                <n-icon :size="16"><Database v-if="node.depth === 0" /><Folder v-else /></n-icon>
                <span>{{ node.name }}</span>
              </button>
            </div>
          </nav>

          <section class="folder-rail-summary">
            <div><span>AI 已识别</span><strong>{{ store.attachments.length }}</strong></div>
            <div><span>待你确认</span><strong>{{ intakeDiagnoses.length }}</strong></div>
            <p><n-icon :size="15"><ShieldCheck /></n-icon>所有 AI 建议均需确认后才会正式归档。</p>
          </section>
        </aside>

        <section class="document-queue">
          <header class="queue-head">
            <div>
              <span>Dobby 资料流</span>
              <h1>{{ queueMode === 'diagnosis' ? '待确认的 AI 诊断' : currentDirectoryName }}</h1>
              <p>{{ queueMode === 'diagnosis' ? 'Dobby 已完成初步识别，请确认类别、路径和版本。' : '按资料上下文浏览，选中后可在右侧继续追问。' }}</p>
            </div>
            <nav class="queue-tabs" aria-label="资料流状态">
              <button type="button" :class="{ active: queueMode === 'diagnosis' }" @click="queueMode = 'diagnosis'">
                待确认
                <b>{{ intakeDiagnoses.length }}</b>
              </button>
              <button type="button" :class="{ active: queueMode === 'library' }" @click="queueMode = 'library'">
                已入库
                <b>{{ store.attachments.length }}</b>
              </button>
            </nav>
          </header>

          <div v-if="isSearchActive" class="search-state">
            <span>Dobby 找到 {{ visibleFiles.length + visibleFolders.length }} 条与“{{ documentSearchKeyword }}”相关的资料</span>
            <button type="button" @click="clearSearch">返回当前目录</button>
          </div>

          <div v-if="queueMode === 'diagnosis'" class="diagnosis-worklist">
            <section v-if="!intakeDiagnoses.length" class="intake-launcher">
              <span class="launcher-icon"><n-icon :size="30"><DatabaseImport /></n-icon></span>
              <div>
                <span>AI 资料接收入口</span>
                <h2>把资料交给 Dobby，先识别再决定放在哪里</h2>
                <p>上传后将自动判断资料类别、推荐归档路径、识别相似版本，并检查可能缺少的签章或关键字段。</p>
              </div>
              <button type="button" :disabled="!canManageDocuments" @click="openUploadModal">
                <n-icon :size="17"><Paperclip /></n-icon>
                选择资料开始诊断
              </button>
            </section>

            <div v-else class="diagnosis-list">
              <div class="diagnosis-list-head">
                <span>{{ intakeDiagnoses.length }} 份资料等待确认</span>
                <button v-if="intakeDiagnoses.length > 1" type="button" :disabled="documentUploading" @click="confirmAllDiagnoses">全部按建议入库</button>
              </div>
              <button
                v-for="item in intakeDiagnoses"
                :key="item.id"
                type="button"
                class="diagnosis-row"
                :class="{ active: selectedDiagnosisId === item.id }"
                @click="selectDiagnosis(item.id)"
              >
                <span class="diagnosis-file-icon"><n-icon :size="20"><FileText /></n-icon></span>
                <span class="diagnosis-copy">
                  <span><b>{{ item.category }}</b><em>{{ item.confidence }}% 置信度</em></span>
                  <strong>{{ item.file.name }}</strong>
                  <small>{{ folderPathById(item.targetFolderId) }}</small>
                </span>
                <span class="diagnosis-version">{{ item.version > 1 ? '建议作为 V' + item.version : '建议新建 V1' }}</span>
                <n-icon class="diagnosis-arrow" :size="17"><ArrowRight /></n-icon>
              </button>
            </div>
          </div>

          <div v-else class="library-stream">
            <nav class="library-path-row" aria-label="资料目录导航">
              <div class="library-breadcrumb">
                <button type="button" class="breadcrumb-root" :disabled="!activeFolderId && !activeVirtualFolderId" @click="selectFolder('')">资料库</button>
                <template v-for="folder in activeFolderPath" :key="folder.id">
                  <n-icon class="breadcrumb-separator" :size="14"><ChevronRight /></n-icon>
                  <button type="button" :class="{ 'is-current': folder.id === activeFolderId }" :disabled="folder.id === activeFolderId" @click="selectFolder(folder.id)">{{ folder.name }}</button>
                </template>
                <template v-for="segment in activeVirtualFolderPath" :key="segment">
                  <n-icon class="breadcrumb-separator" :size="14"><ChevronRight /></n-icon>
                  <button type="button" class="is-current" disabled>{{ segment }}</button>
                </template>
              </div>
              <span>{{ visibleFolders.length + visibleFiles.length }} 项</span>
            </nav>

            <div class="document-stream-list">
              <button v-for="folder in visibleFolders" :key="folder.id" type="button" class="folder-stream-row" @click="selectFolder(folder.id)">
                <span class="stream-icon folder"><n-icon :size="20"><Folder /></n-icon></span>
                <span class="stream-copy"><strong>{{ folder.name }}</strong><small>{{ folderDescendantCount(folder.id) }} 个子项 · 点击进入目录</small></span>
                <span class="stream-state">目录</span>
                <n-icon :size="17"><ChevronRight /></n-icon>
              </button>

              <button
                v-for="file in visibleFiles"
                :key="file.id"
                type="button"
                class="document-stream-row"
                :class="{ active: activeDocument?.id === file.id }"
                @click="selectDocument(file)"
              >
                <span class="stream-icon document"><n-icon :size="20"><FileText /></n-icon></span>
                <span class="stream-copy">
                  <span><b>{{ file.category }}</b><em><n-icon :size="13"><Robot /></n-icon>AI 已识别</em></span>
                  <strong>{{ file.fileName }}</strong>
                  <small>{{ inferDocumentSummary(file.fileName, file.category) }}</small>
                </span>
                <span class="stream-version">V{{ file.version }}<small>{{ formatFileSize(file.fileSize) }}</small></span>
                <n-icon :size="17"><ArrowRight /></n-icon>
              </button>

              <section v-if="!visibleFolders.length && !visibleFiles.length" class="document-empty">
                <n-icon :size="30"><FileText /></n-icon>
                <strong>{{ isSearchActive ? '没有找到相关资料' : '当前目录还没有资料' }}</strong>
                <p>{{ isSearchActive ? '可以换一种说法，或返回目录后上传新的资料。' : '上传后 Dobby 会先完成诊断，再请你确认归档。' }}</p>
                <button v-if="!isSearchActive" type="button" @click="openUploadModal">上传并诊断</button>
              </section>
            </div>
          </div>
        </section>

        <aside class="dobby-inspector" aria-label="Dobby 资料诊断">
          <header class="inspector-head">
            <span class="inspector-avatar"><n-icon :size="19"><Robot /></n-icon></span>
            <div>
              <span>Dobby 诊断</span>
              <strong>{{ selectedDiagnosis ? '等待你确认' : activeDocument ? '已读取当前资料' : '等待选择资料' }}</strong>
            </div>
            <em><i></i>实时</em>
          </header>

          <template v-if="selectedDiagnosis">
            <div class="inspector-scroll">
              <section class="diagnosed-file">
                <span>{{ fileExtension(selectedDiagnosis.file.name) }}</span>
                <div><strong>{{ selectedDiagnosis.file.name }}</strong><small>{{ formatFileSize(selectedDiagnosis.file.size) }} · 刚刚完成诊断</small></div>
              </section>

              <ol class="analysis-steps">
                <li><n-icon :size="15"><Check /></n-icon><span>内容提取</span><em>完成</em></li>
                <li><n-icon :size="15"><Check /></n-icon><span>语义分类</span><em>完成</em></li>
                <li><n-icon :size="15"><Check /></n-icon><span>目录与版本匹配</span><em>完成</em></li>
              </ol>

              <section class="insight-block">
                <header><span>AI 内容摘要</span><b>{{ selectedDiagnosis.confidence }}% 置信度</b></header>
                <p>{{ selectedDiagnosis.summary }}</p>
              </section>

              <section class="insight-block diagnosis-form-block">
                <header><span>归档建议</span><b>可调整</b></header>
                <label>
                  资料类别
                  <select v-model="selectedDiagnosis.category">
                    <option v-for="category in documentCategories" :key="category" :value="category">{{ category }}</option>
                  </select>
                </label>
                <label>
                  推荐路径
                  <select v-model="selectedDiagnosis.targetFolderId">
                    <option value="">项目资料根目录</option>
                    <option v-for="folder in folderOptions" :key="folder.id" :value="folder.id">{{ folder.label }}</option>
                  </select>
                </label>
                <p class="recommendation-reason"><n-icon :size="15"><Route /></n-icon>{{ selectedDiagnosis.reason }}</p>
              </section>

              <section class="insight-block version-block">
                <header><span>版本判断</span><b>{{ selectedDiagnosis.version > 1 ? '发现相似资料' : '未发现重复' }}</b></header>
                <div>
                  <n-icon :size="19"><LayersLinked /></n-icon>
                  <p v-if="selectedDiagnosis.version > 1">建议作为 <strong>V{{ selectedDiagnosis.version }}</strong> 新版本入库，原版本继续保留。</p>
                  <p v-else>建议建立 <strong>V1</strong> 初始版本，后续同名资料自动形成版本链。</p>
                </div>
              </section>

              <section class="insight-block">
                <header><span>关联上下文</span><b>自动匹配</b></header>
                <div class="context-tags"><span v-for="context in selectedDiagnosis.contexts" :key="context">{{ context }}</span></div>
              </section>

              <section class="insight-block check-block">
                <header><span>完整性检查</span><b>{{ selectedDiagnosis.warning ? '需要留意' : '未发现明显问题' }}</b></header>
                <p :class="{ warning: selectedDiagnosis.warning }">
                  <n-icon :size="16"><AlertCircle v-if="selectedDiagnosis.warning" /><CircleCheck v-else /></n-icon>
                  {{ selectedDiagnosis.warning || '文件可读取，日期与主要字段结构完整，可进入资料库。' }}
                </p>
              </section>
            </div>

            <footer class="inspector-actions">
              <button type="button" class="discard-action" :disabled="documentUploading" @click="discardDiagnosis(selectedDiagnosis.id)">暂不归档</button>
              <button type="button" class="confirm-action" :disabled="documentUploading" @click="confirmDiagnosis(selectedDiagnosis)">
                <n-icon :size="16"><DatabaseImport /></n-icon>
                {{ documentUploading ? '正在入库…' : '采用建议并入库' }}
              </button>
            </footer>
          </template>

          <template v-else-if="activeDocument">
            <div class="inspector-scroll existing-document-insight">
              <section class="selected-document">
                <span>{{ fileExtension(activeDocument.fileName) }}</span>
                <div><strong>{{ activeDocument.fileName }}</strong><small>V{{ activeDocument.version }} · {{ formatDate(activeDocument.createdAt) }}</small></div>
              </section>

              <article class="dobby-message">
                <span><n-icon :size="16"><Robot /></n-icon></span>
                <div>
                  <small>Dobby</small>
                  <p>{{ documentAssistantMessage || inferDocumentSummary(activeDocument.fileName, activeDocument.category) }}</p>
                </div>
              </article>

              <section class="document-facts">
                <div><span>资料类别</span><strong>{{ activeDocument.category }}</strong></div>
                <div><span>识别置信度</span><strong>{{ activeDocumentConfidence }}%</strong></div>
                <div class="wide"><span>实际归档路径</span><strong>{{ folderPathById(activeDocument.folderId || '') }}</strong></div>
              </section>

              <section class="insight-block">
                <header><span>为什么放在这里</span><b>AI 归档依据</b></header>
                <p>{{ inferRecommendationReason(activeDocument.fileName, activeDocument.category) }}</p>
              </section>

              <section class="insight-block">
                <header><span>关联上下文</span><b>可继续追问</b></header>
                <div class="context-tags"><span v-for="context in inferRelatedContexts(activeDocument.fileName, activeDocument.category)" :key="context">{{ context }}</span></div>
              </section>

              <div class="assistant-suggestions">
                <button type="button" @click="askAboutDocument('这份资料为什么归档在这里？')">解释归档依据</button>
                <button type="button" @click="askAboutDocument('检查这份资料还缺什么')">检查资料完整性</button>
                <button type="button" @click="askAboutDocument('这份资料关联哪些任务？')">查看关联任务</button>
              </div>
            </div>

            <form class="assistant-composer" @submit.prevent="sendDocumentQuestion">
              <textarea v-model.trim="documentQuestion" placeholder="围绕当前资料继续问 Dobby"></textarea>
              <button type="submit" :disabled="!documentQuestion"><n-icon :size="17"><Send /></n-icon></button>
            </form>
          </template>

          <section v-else class="inspector-empty">
            <n-icon :size="31"><MessageCircle /></n-icon>
            <strong>选择一份资料查看 AI 诊断</strong>
            <p>Dobby 会说明资料内容、归档依据、关联工序以及可能的资料缺项。</p>
          </section>
        </aside>
      </section>
    </section>

    <div v-if="folderCreateOpen" class="library-modal-backdrop" @click.self="closeFolderCreate">
      <section class="library-modal" role="dialog" aria-modal="true" aria-labelledby="folder-create-title">
        <div class="library-modal-head"><div><span>目录管理</span><h2 id="folder-create-title">新建文件夹</h2></div><button type="button" class="modal-close" @click="closeFolderCreate">关闭</button></div>
        <form class="folder-create-form" @submit.prevent="createFolder">
          <div class="folder-parent-context"><span>父目录</span><strong>{{ currentDirectoryName }}</strong></div>
          <label>文件夹名称<input v-model.trim="folderCreateName" required maxlength="200" placeholder="例如：监测报告"></label>
          <div><button type="button" class="modal-secondary" @click="closeFolderCreate">取消</button><button type="submit" class="modal-primary" :disabled="folderCreating">{{ folderCreating ? '正在创建…' : '创建文件夹' }}</button></div>
        </form>
      </section>
    </div>

    <div v-if="uploadModalOpen" class="library-modal-backdrop" @click.self="closeUploadModal">
      <section class="library-modal upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title">
        <div class="library-modal-head">
          <div><span>Dobby 资料接收</span><h2 id="upload-title">上传并开始诊断</h2></div>
          <button type="button" class="modal-close" :disabled="diagnosisRunning" @click="closeUploadModal">关闭</button>
        </div>
        <form class="upload-form" @submit.prevent="beginDocumentDiagnosis">
          <div class="upload-ai-note">
            <n-icon :size="19"><Robot /></n-icon>
            <div><strong>文件不会直接入库</strong><span>Dobby 会先识别类别、推荐路径并判断版本，确认后才正式归档。</span></div>
          </div>
          <div class="folder-parent-context"><span>当前上传入口</span><strong>{{ currentDirectoryName }}</strong></div>
          <div class="upload-queue-head">
            <div><strong>待诊断列表</strong><span>{{ pendingUploadFiles.length }} 个文件 · {{ formatFileSize(pendingUploadTotalSize) }}</span></div>
            <label class="upload-picker"><input type="file" multiple :disabled="diagnosisRunning" @change="queueUploadFiles">选择文件</label>
          </div>
          <ul v-if="pendingUploadFiles.length" class="upload-queue">
            <li v-for="(file, index) in pendingUploadFiles" :key="file.name + '-' + file.size + '-' + file.lastModified">
              <span class="upload-file-type">{{ fileExtension(file.name) }}</span>
              <div><strong :title="file.name">{{ file.name }}</strong><span>{{ formatFileSize(file.size) }}</span></div>
              <button type="button" :disabled="diagnosisRunning" :aria-label="'移除 ' + file.name" @click="removePendingUpload(index)">移除</button>
            </li>
          </ul>
          <div v-else class="upload-queue-empty"><n-icon :size="26"><FileText /></n-icon><strong>选择要交给 Dobby 的资料</strong><span>支持一次选择多个文件，诊断完成后逐份确认。</span></div>
          <div class="upload-actions">
            <button type="button" class="modal-secondary" :disabled="diagnosisRunning" @click="closeUploadModal">取消</button>
            <button type="submit" class="modal-primary" :disabled="diagnosisRunning || !pendingUploadFiles.length">
              <n-icon :size="16"><Robot /></n-icon>
              {{ diagnosisRunning ? 'Dobby 正在诊断…' : '开始 AI 诊断' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMessage, NIcon } from 'naive-ui'
import {
  AlertCircle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Database,
  DatabaseImport,
  FileText,
  Folder,
  LayersLinked,
  MessageCircle,
  Paperclip,
  Plus,
  Robot,
  Route,
  Search,
  Send,
  ShieldCheck,
} from '@vicons/tabler'
import { useAppStore, type AttachmentRecord, type DocumentFolderRecord } from '@/stores/app'

type QueueMode = 'diagnosis' | 'library'
type IntakeDiagnosis = {
  id: string
  file: File
  category: string
  targetFolderId: string
  confidence: number
  version: number
  reason: string
  summary: string
  contexts: string[]
  warning: string
}
type FolderTreeDisplayNode = {
  id: string
  name: string
  depth: number
  hasChildren: boolean
  count: number
  folderId?: string
}

const virtualProjectLibraryId = 'virtual:project-library'
const virtualKnowledgeLibraryId = 'virtual:knowledge-library'
const prototypeProjectFolderNames = [
  '00_项目总览',
  '01_合同图纸与方案',
  '02_进度计划',
  '03_质量安全管理',
  '04_监测检测与试验',
  '05_会议沟通与过程记录',
  '06_问题整改与任务闭环',
  '07_变更签证',
  '08_验收移交',
  '09_影像与原始数据',
  '10_AI整理成果',
  '99_归档与历史版本',
]
const prototypeKnowledgeFolderNames = [
  '01_法规规范与标准',
  '02_企业制度与管理要求',
  '03_专业技术知识',
  '04_检查规则与控制阈值',
  '05_流程模板与表单模板',
  '06_风险隐患与案例库',
  '07_AI知识包',
  '99_废止与历史版本',
]

const store = useAppStore()
const message = useMessage()
const documentCategories = ['日报', '监测资料', '施工方案', '质量验收', '进度计划', '风险资料', '工程资料']
const domainSearchTerms = ['基坑', '监测', '日报', '风险', '验收', '计划', 'WBS', '方案', '照片', '隐患', '测量']

const activeFolderId = ref('')
const activeVirtualFolderId = ref('')
const expandedFolderIds = ref<string[]>([virtualProjectLibraryId, virtualKnowledgeLibraryId])
const initialDirectoryExpansionApplied = ref(false)
const queueMode = ref<QueueMode>('library')
const selectedFileId = ref('')
const selectedDiagnosisId = ref('')
const intakeDiagnoses = ref<IntakeDiagnosis[]>([])
const documentUploading = ref(false)
const diagnosisRunning = ref(false)
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
const documentQuestion = ref('')
const documentAssistantMessage = ref('')

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
const projectLibraryRoot = computed(() => store.documentFolders.find(folder => !folder.parentId && folder.name === 'A_项目工程资料库'))
const projectStorageFolder = computed(() => {
  const projectRoot = projectLibraryRoot.value
  if (!projectRoot) return undefined
  const candidates = folderChildren.value.get(projectRoot.id) || []
  return candidates.find(folder => (folderChildren.value.get(folder.id) || []).some(child => prototypeProjectFolderNames.includes(child.name))) || candidates[0]
})
const hasPersistedPrototypeTree = computed(() => {
  const knowledgeRoot = store.documentFolders.find(folder => !folder.parentId && folder.name === 'B_工程知识库')
  return Boolean(projectLibraryRoot.value && knowledgeRoot && projectStorageFolder.value)
})
const folderTreeNodes = computed(() => {
  const nodes: FolderTreeDisplayNode[] = []

  if (hasPersistedPrototypeTree.value) {
    const appendFolder = (folder: DocumentFolderRecord, depth: number) => {
      const hasChildren = Boolean(folderChildren.value.get(folder.id)?.length)
      nodes.push({ id: folder.id, name: folder.name, depth, hasChildren, count: folderDescendantCount(folder.id), folderId: folder.id })
      if (hasChildren && expandedFolderIds.value.includes(folder.id)) {
        for (const child of folderChildren.value.get(folder.id) || []) appendFolder(child, depth + 1)
      }
    }

    const projectRoot = projectLibraryRoot.value
    const knowledgeRoot = store.documentFolders.find(folder => !folder.parentId && folder.name === 'B_工程知识库')
    if (projectRoot) {
      nodes.push({ id: projectRoot.id, name: projectRoot.name, depth: 0, hasChildren: true, count: folderDescendantCount(projectRoot.id), folderId: projectRoot.id })
      if (expandedFolderIds.value.includes(projectRoot.id)) {
        const projectStorage = projectStorageFolder.value
        const projectFolders = projectStorage ? folderChildren.value.get(projectStorage.id) || [] : folderChildren.value.get(projectRoot.id) || []
        for (const folder of projectFolders) appendFolder(folder, 1)
      }
    }
    if (knowledgeRoot) appendFolder(knowledgeRoot, 0)
    for (const folder of folderChildren.value.get(undefined) || []) {
      if (folder.id !== projectRoot?.id && folder.id !== knowledgeRoot?.id) appendFolder(folder, 0)
    }
    return nodes
  }

  const legacyRootFolders = store.documentFolders.filter(folder => !folder.parentId && !['A_项目工程资料库', 'B_工程知识库'].includes(folder.name))
  const legacyFolderByName = new Map(legacyRootFolders.map(folder => [folder.name, folder]))
  const orderedProjectFolders = prototypeProjectFolderNames.map(name => ({ name, folder: legacyFolderByName.get(name) }))
  const extraProjectFolders = legacyRootFolders
    .filter(folder => !prototypeProjectFolderNames.includes(folder.name))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN', { numeric: true }))
    .map(folder => ({ name: folder.name, folder }))

  nodes.push({
    id: virtualProjectLibraryId,
    name: 'A_项目工程资料库',
    depth: 0,
    hasChildren: true,
    count: store.attachments.length,
  })
  if (expandedFolderIds.value.includes(virtualProjectLibraryId)) {
    for (const [index, item] of [...orderedProjectFolders, ...extraProjectFolders].entries()) {
      nodes.push({
        id: item.folder?.id || `virtual:project-folder:${index}`,
        name: item.name,
        depth: 1,
        hasChildren: false,
        count: item.folder ? folderDescendantCount(item.folder.id) : 0,
        folderId: item.folder?.id,
      })
    }
  }

  nodes.push({
    id: virtualKnowledgeLibraryId,
    name: 'B_工程知识库',
    depth: 0,
    hasChildren: true,
    count: 0,
  })
  if (expandedFolderIds.value.includes(virtualKnowledgeLibraryId)) {
    for (const [index, name] of prototypeKnowledgeFolderNames.entries()) {
      nodes.push({ id: `virtual:knowledge-folder:${index}`, name, depth: 1, hasChildren: false, count: 0 })
    }
  }
  return nodes
})
const folderOptions = computed(() => {
  const options: Array<{ id: string; label: string }> = []
  const appendFolder = (folder: DocumentFolderRecord, depth: number) => {
    options.push({ id: folder.id, label: (depth ? '　'.repeat(depth) : '') + folder.name })
    for (const child of folderChildren.value.get(folder.id) || []) appendFolder(child, depth + 1)
  }
  for (const folder of folderChildren.value.get(undefined) || []) {
    if (folder.id === projectLibraryRoot.value?.id && projectStorageFolder.value) {
      options.push({ id: projectStorageFolder.value.id, label: folder.name })
      for (const child of folderChildren.value.get(projectStorageFolder.value.id) || []) appendFolder(child, 1)
    } else {
      appendFolder(folder, 0)
    }
  }
  return options
})
const activeFolderPath = computed(() => {
  const path: DocumentFolderRecord[] = []
  let current = activeFolder.value
  while (current) {
    path.unshift(current)
    current = current.parentId ? store.documentFolders.find(folder => folder.id === current?.parentId) : undefined
  }
  return path.filter(folder => folder.id !== projectStorageFolder.value?.id)
})
const activeVirtualFolderName = computed(() => {
  if (activeVirtualFolderId.value.startsWith('virtual:project-folder:')) {
    const segments = activeVirtualFolderId.value.split(':')
    const index = Number(segments[segments.length - 1])
    return prototypeProjectFolderNames[index] || ''
  }
  if (activeVirtualFolderId.value.startsWith('virtual:knowledge-folder:')) {
    const segments = activeVirtualFolderId.value.split(':')
    const index = Number(segments[segments.length - 1])
    return prototypeKnowledgeFolderNames[index] || ''
  }
  return ''
})
const activeVirtualFolderPath = computed(() => {
  if (!activeVirtualFolderName.value) return []
  return activeVirtualFolderId.value.startsWith('virtual:knowledge-folder:')
    ? ['B_工程知识库', activeVirtualFolderName.value]
    : ['A_项目工程资料库', activeVirtualFolderName.value]
})
const activeTreeNodeId = computed(() => activeVirtualFolderId.value || activeFolderId.value)
const currentDirectoryName = computed(() => activeVirtualFolderName.value || activeFolder.value?.name || '全部资料库')
const pendingUploadTotalSize = computed(() => pendingUploadFiles.value.reduce((total, file) => total + file.size, 0))
const childFolders = computed(() => {
  if (activeVirtualFolderId.value) return []
  const parentId = activeFolderId.value === projectLibraryRoot.value?.id && projectStorageFolder.value
    ? projectStorageFolder.value.id
    : activeFolderId.value || undefined
  return store.documentFolders.filter(folder => folder.parentId === parentId)
})
const visibleFolders = computed(() => isSearchActive.value ? documentSearchFolderResults.value : childFolders.value)
const visibleFiles = computed(() => {
  if (isSearchActive.value) return documentSearchResults.value
  if (activeVirtualFolderId.value) return []
  return activeFolderId.value ? store.attachments.filter(file => file.folderId === activeFolderId.value) : store.attachments
})
const selectedDiagnosis = computed(() => intakeDiagnoses.value.find(item => item.id === selectedDiagnosisId.value))
const activeDocument = computed(() => {
  return store.attachments.find(item => item.id === selectedFileId.value) || visibleFiles.value[0]
})
const activeDocumentConfidence = computed(() => {
  if (!activeDocument.value) return 0
  return inferCategory(activeDocument.value.fileName) === activeDocument.value.category ? 96 : 88
})

watch(() => store.documentFolders, folders => {
  if (initialDirectoryExpansionApplied.value || !folders.length) return
  const prototypeRoots = folders.filter(folder => ['A_项目工程资料库', 'B_工程知识库'].includes(folder.name))
  if (!prototypeRoots.length) return
  const projectRootIds = prototypeRoots.filter(folder => folder.name === 'A_项目工程资料库').map(folder => folder.id)
  const projectStorageIds = folders.filter(folder => folder.parentId && projectRootIds.includes(folder.parentId)).map(folder => folder.id)
  expandedFolderIds.value = [...new Set([...expandedFolderIds.value, ...prototypeRoots.map(folder => folder.id), ...projectStorageIds])]
  initialDirectoryExpansionApplied.value = true
}, { immediate: true })

function isFolderExpanded(folderId: string) {
  return expandedFolderIds.value.includes(folderId)
}
function toggleFolderExpanded(folderId: string) {
  expandedFolderIds.value = isFolderExpanded(folderId)
    ? expandedFolderIds.value.filter(id => id !== folderId)
    : [...expandedFolderIds.value, folderId]
}
function selectTreeNode(node: FolderTreeDisplayNode) {
  if (node.folderId) {
    selectFolder(node.folderId)
    return
  }
  if (node.hasChildren) {
    toggleFolderExpanded(node.id)
    return
  }
  if (isSearchActive.value) clearSearch()
  activeFolderId.value = ''
  activeVirtualFolderId.value = node.id
  queueMode.value = 'library'
  selectedFileId.value = ''
  documentAssistantMessage.value = ''
}
function selectFolder(folderId: string) {
  if (isSearchActive.value) clearSearch()
  activeFolderId.value = folderId
  activeVirtualFolderId.value = ''
  queueMode.value = 'library'
  selectedFileId.value = ''
  documentAssistantMessage.value = ''
  let current = store.documentFolders.find(folder => folder.id === folderId)
  const ancestorIds: string[] = []
  while (current?.parentId) {
    ancestorIds.push(current.parentId)
    current = store.documentFolders.find(folder => folder.id === current?.parentId)
  }
  if (ancestorIds.length) expandedFolderIds.value = [...new Set([...expandedFolderIds.value, ...ancestorIds])]
}
function selectDocument(file: AttachmentRecord) {
  selectedFileId.value = file.id
  selectedDiagnosisId.value = ''
  documentAssistantMessage.value = ''
}
function selectDiagnosis(id: string) {
  selectedDiagnosisId.value = id
  selectedFileId.value = ''
}
function openFolderCreate() {
  if (!canManageDocuments.value) {
    message.warning('请先在工程配置中创建并选择一个项目。')
    return
  }
  folderCreateOpen.value = true
}
function openUploadModal() {
  if (!canManageDocuments.value) {
    message.warning('请先在工程配置中创建并选择一个项目。')
    return
  }
  pendingUploadFiles.value = []
  uploadModalOpen.value = true
}
function folderDescendantCount(folderId: string): number {
  const children = store.documentFolders.filter(folder => folder.parentId === folderId)
  const directFiles = store.attachments.filter(file => file.folderId === folderId).length
  return directFiles + children.reduce((total, child) => total + 1 + folderDescendantCount(child.id), 0)
}
function folderPathById(folderId: string) {
  if (!folderId) return '资料库 / 根目录'
  const names: string[] = []
  let current = store.documentFolders.find(folder => folder.id === folderId)
  while (current) {
    if (current.id !== projectStorageFolder.value?.id) names.unshift(current.name)
    current = current.parentId ? store.documentFolders.find(folder => folder.id === current?.parentId) : undefined
  }
  return ['资料库', ...names].join(' / ')
}
function fileExtension(fileName: string) {
  return fileName.includes('.') ? (fileName.split('.').pop() || 'FILE').slice(0, 5).toUpperCase() : 'FILE'
}
function formatFileSize(bytes: number) {
  if (bytes <= 0) return '0 KB'
  return bytes < 1024 * 1024 ? Math.max(1, Math.round(bytes / 1024)) + ' KB' : (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
function formatDate(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '刚刚'
}
function inferCategory(fileName: string) {
  const name = fileName.toLowerCase()
  if (name.includes('日报')) return '日报'
  if (['监测', '测量', '沉降', '位移'].some(keyword => name.includes(keyword))) return '监测资料'
  if (['方案', '专项', '施工组织'].some(keyword => name.includes(keyword))) return '施工方案'
  if (['验收', '质检', '检测'].some(keyword => name.includes(keyword))) return '质量验收'
  if (['wbs', '计划', '进度', '里程碑'].some(keyword => name.includes(keyword))) return '进度计划'
  if (['风险', '隐患', '整改', '预警'].some(keyword => name.includes(keyword))) return '风险资料'
  return '工程资料'
}
function inferDocumentSummary(fileName: string, category: string) {
  const name = fileName.replace(/\.[^.]+$/, '')
  const summaries: Record<string, string> = {
    日报: '记录当日施工内容、现场进展与问题，可用于更新项目状态和形成日报确认任务。',
    监测资料: '包含监测或测量数据，Dobby 可用于比对预警阈值并关联风险处置。',
    施工方案: '描述施工方法、组织安排与控制措施，可关联对应工序和风险源。',
    质量验收: '包含检查、检测或验收结果，可作为质量闭环与工序放行依据。',
    进度计划: '包含工序、计划节点或里程碑信息，可用于更新 WBS 与进度判断。',
    风险资料: '记录风险、隐患或整改信息，可用于生成处置任务与风险草稿。',
    工程资料: 'Dobby 已提取文件基础信息，可继续补充用途或关联工程上下文。',
  }
  return name + '：' + (summaries[category] || summaries.工程资料)
}
function inferRelatedContexts(fileName: string, category: string) {
  const name = fileName.toLowerCase()
  if (['监测', '基坑', '沉降', '位移'].some(keyword => name.includes(keyword))) return ['WBS · 基坑开挖', '风险源 · 深基坑支护', '责任人 · 王芳']
  if (category === '日报') return ['任务 · 日报解析确认', '项目状态 · 当日进展', '责任人 · 王芳']
  if (category === '进度计划') return ['WBS · 总进度计划', '里程碑 · 主体施工', '责任人 · 张伟']
  if (category === '质量验收') return ['质量指标 · 工序验收', '任务 · 质量复核', '责任人 · 李明']
  if (category === '施工方案') return ['WBS · 专项施工', '风险源 · 方案控制', '责任人 · 张伟']
  return ['项目 · 当前工程', '资料库 · 工程资料', 'Dobby · 可继续关联']
}
function inferRecommendationReason(fileName: string, category: string) {
  const cues = category === '监测资料'
    ? '文件名及内容出现监测、测量或位移相关信息'
    : category === '日报'
      ? '识别到施工日期、当日进展与现场记录结构'
      : category === '进度计划'
        ? '识别到计划节点、WBS 或里程碑字段'
        : '根据文件名称、内容摘要和当前工程目录进行匹配'
  return cues + '，因此 Dobby 将“' + fileName + '”归入当前类别并关联对应工程上下文。'
}
function normalizeFileName(fileName: string) {
  return fileName.toLowerCase().replace(/\.[^.]+$/, '').replace(/[\s_-]+/g, '')
}
function recommendFolder(fileName: string, category: string) {
  const keywordMap: Record<string, string[]> = {
    日报: ['日报', '施工记录'],
    监测资料: ['监测', '测量', '风险'],
    施工方案: ['方案', '技术'],
    质量验收: ['验收', '质量', '检测'],
    进度计划: ['计划', '进度', 'wbs'],
    风险资料: ['风险', '隐患', '整改'],
    工程资料: ['综合', '其他', '工程'],
  }
  const keywords = keywordMap[category] || keywordMap.工程资料
  const candidate = store.documentFolders.find(folder => keywords.some(keyword => folder.name.toLowerCase().includes(keyword.toLowerCase())))
  const fallback = store.documentFolders.find(folder => folder.id === activeFolderId.value) || store.documentFolders[0]
  return {
    folderId: candidate?.id || fallback?.id || '',
    reason: inferRecommendationReason(fileName, category),
  }
}
function buildDiagnosis(file: File, index: number): IntakeDiagnosis {
  const category = inferCategory(file.name)
  const recommendation = recommendFolder(file.name, category)
  const similar = store.attachments.find(item => normalizeFileName(item.fileName) === normalizeFileName(file.name))
  const confidence = category === '工程资料' ? 82 : 94 - (index % 3)
  const name = file.name.toLowerCase()
  const warning = ['照片', '扫描'].some(keyword => name.includes(keyword)) ? '图片类资料可能缺少可检索文字，建议确认拍摄日期和现场位置。' : ''
  return {
    id: String(Date.now()) + '-' + index + '-' + file.lastModified,
    file,
    category,
    targetFolderId: recommendation.folderId,
    confidence,
    version: similar ? similar.version + 1 : 1,
    reason: recommendation.reason,
    summary: inferDocumentSummary(file.name, category),
    contexts: inferRelatedContexts(file.name, category),
    warning,
  }
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
  if (diagnosisRunning.value) return
  uploadModalOpen.value = false
  pendingUploadFiles.value = []
}
async function beginDocumentDiagnosis() {
  if (!pendingUploadFiles.value.length || diagnosisRunning.value) return
  const files = [...pendingUploadFiles.value]
  diagnosisRunning.value = true
  try {
    await new Promise(resolve => window.setTimeout(resolve, 650))
    const diagnoses = files.map(buildDiagnosis)
    intakeDiagnoses.value = [...intakeDiagnoses.value, ...diagnoses]
    selectedDiagnosisId.value = diagnoses[0]?.id || selectedDiagnosisId.value
    selectedFileId.value = ''
    queueMode.value = 'diagnosis'
    pendingUploadFiles.value = []
    uploadModalOpen.value = false
    message.success('Dobby 已完成 ' + diagnoses.length + ' 份资料的初步诊断')
  } finally {
    diagnosisRunning.value = false
  }
}
async function confirmDiagnosis(diagnosis: IntakeDiagnosis) {
  if (documentUploading.value) return
  documentUploading.value = true
  try {
    await store.uploadAttachment(diagnosis.file, diagnosis.category, diagnosis.targetFolderId || undefined)
    intakeDiagnoses.value = intakeDiagnoses.value.filter(item => item.id !== diagnosis.id)
    const newest = store.attachments.find(item => item.fileName === diagnosis.file.name)
    activeFolderId.value = diagnosis.targetFolderId
    selectedFileId.value = newest?.id || ''
    selectedDiagnosisId.value = intakeDiagnoses.value[0]?.id || ''
    queueMode.value = intakeDiagnoses.value.length ? 'diagnosis' : 'library'
    message.success('已按 Dobby 建议归档：' + diagnosis.file.name)
  } catch (error: any) {
    message.error(error.response?.data?.detail || '资料入库失败，请检查服务连接。')
  } finally {
    documentUploading.value = false
  }
}
async function confirmAllDiagnoses() {
  if (!intakeDiagnoses.value.length || documentUploading.value) return
  documentUploading.value = true
  const items = [...intakeDiagnoses.value]
  let completed = 0
  try {
    for (const item of items) {
      await store.uploadAttachment(item.file, item.category, item.targetFolderId || undefined)
      completed += 1
    }
    intakeDiagnoses.value = []
    selectedDiagnosisId.value = ''
    queueMode.value = 'library'
    message.success('已按 Dobby 建议归档 ' + completed + ' 份资料')
  } catch (error: any) {
    intakeDiagnoses.value = items.slice(completed)
    selectedDiagnosisId.value = intakeDiagnoses.value[0]?.id || ''
    message.error('已完成 ' + completed + ' 份，其余资料入库失败。')
  } finally {
    documentUploading.value = false
  }
}
function discardDiagnosis(id: string) {
  intakeDiagnoses.value = intakeDiagnoses.value.filter(item => item.id !== id)
  selectedDiagnosisId.value = intakeDiagnoses.value[0]?.id || ''
  if (!intakeDiagnoses.value.length) queueMode.value = 'library'
}
async function searchDocuments() {
  if (!documentSearchKeyword.value) {
    clearSearch()
    return
  }
  documentSearching.value = true
  try {
    const rawKeyword = documentSearchKeyword.value.trim()
    const terms = domainSearchTerms.filter(term => rawKeyword.toLowerCase().includes(term.toLowerCase()))
    const searchTerm = terms[0] || rawKeyword
    const remoteResults = await store.searchDocuments(searchTerm)
    const localResults = store.attachments.filter(file => {
      const content = (file.fileName + ' ' + file.category + ' ' + (file.snippet || '')).toLowerCase()
      return (terms.length ? terms : [rawKeyword]).some(term => content.includes(term.toLowerCase()))
    })
    const resultMap = new Map<string, AttachmentRecord>()
    for (const file of [...remoteResults, ...localResults]) resultMap.set(file.id, file)
    documentSearchResults.value = [...resultMap.values()]
    documentSearchFolderResults.value = store.documentFolders.filter(folder => (terms.length ? terms : [rawKeyword]).some(term => folder.name.toLowerCase().includes(term.toLowerCase())))
    isSearchActive.value = true
    queueMode.value = 'library'
    selectedFileId.value = documentSearchResults.value[0]?.id || ''
    documentAssistantMessage.value = documentSearchResults.value.length
      ? '我找到 ' + documentSearchResults.value.length + ' 份相关资料，已按与问题的关联度集中展示。'
      : '暂时没有找到直接匹配的资料，可以尝试使用“监测”“风险”或“验收”等关键词。'
  } catch (error: any) {
    message.error(error.response?.data?.detail || '资料检索失败，请稍后重试。')
  } finally {
    documentSearching.value = false
  }
}
function clearSearch() {
  documentSearchKeyword.value = ''
  documentSearchResults.value = []
  documentSearchFolderResults.value = []
  isSearchActive.value = false
  selectedFileId.value = ''
  documentAssistantMessage.value = ''
}
function askAboutDocument(question: string) {
  if (!activeDocument.value) return
  if (question.includes('为什么')) {
    documentAssistantMessage.value = inferRecommendationReason(activeDocument.value.fileName, activeDocument.value.category)
  } else if (question.includes('缺什么')) {
    documentAssistantMessage.value = activeDocument.value.category === '监测资料'
      ? '建议重点确认监测日期、测点编号、预警阈值和复核签字。目前未发现明显缺页，但仍需人工核对签章。'
      : '文件内容可以读取。建议人工确认日期、责任人和签章是否完整，再用于后续任务或填报。'
  } else {
    documentAssistantMessage.value = '这份资料可关联：' + inferRelatedContexts(activeDocument.value.fileName, activeDocument.value.category).join('、') + '。'
  }
}
function sendDocumentQuestion() {
  if (!documentQuestion.value) return
  askAboutDocument(documentQuestion.value)
  documentQuestion.value = ''
}
function closeFolderCreate() {
  if (!folderCreating.value) folderCreateOpen.value = false
}
async function createFolder() {
  if (!canManageDocuments.value) {
    message.warning('请先在工程配置中创建并选择一个项目。')
    return
  }
  if (!folderCreateName.value) return
  folderCreating.value = true
  try {
    const parentId = activeFolderId.value === projectLibraryRoot.value?.id && projectStorageFolder.value
      ? projectStorageFolder.value.id
      : activeFolderId.value || undefined
    await store.createDocumentFolder({ name: folderCreateName.value, parentId })
    message.success('文件夹已创建')
    folderCreateName.value = ''
    folderCreateOpen.value = false
  } catch (error: any) {
    message.error(error.response?.data?.detail || '文件夹创建失败，请检查权限和服务连接。')
  } finally {
    folderCreating.value = false
  }
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
.inspector-avatar {
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
.dobby-identity > div,
.inspector-head > div { display: grid; min-width: 0; gap: 2px; }
.dobby-identity span,
.inspector-head span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .04em; }
.dobby-identity strong,
.inspector-head strong { overflow: hidden; color: #173235; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.dobby-identity em,
.inspector-head em {
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
.inspector-head em i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10a079;
  box-shadow: 0 0 0 3px rgba(16, 160, 121, .1);
}
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
.topbar-actions { display: flex; align-items: center; gap: 7px; }
.secondary-action { border: 1px solid #cddbd7; color: #496763; background: #fff; }
.primary-action { border: 1px solid #d45f1f; color: #fff; background: #d45f1f; box-shadow: 0 5px 12px rgba(212, 95, 31, .16); }
button:disabled { opacity: .5; cursor: not-allowed; box-shadow: none; }
.dobby-search button:not(:disabled):hover,
.primary-action:not(:disabled):hover { filter: brightness(.96); transform: translateY(-1px); }
.secondary-action:hover { border-color: #8fb1aa; color: #174f49; background: #f5f9f7; }

.dobby-workspace-grid {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-columns: 280px minmax(390px, 1fr) minmax(330px, .72fr);
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
.folder-rail-head button { display: grid; flex: 0 0 auto; width: 28px; height: 28px; place-items: center; border: 1px solid #d2dfdb; border-radius: 6px; color: #55706c; background: #fff; cursor: pointer; }
.folder-tree-nav { display: grid; flex: 1 1 auto; min-height: 0; align-content: start; overflow: auto; padding: 2px 8px 12px; scrollbar-gutter: stable; }
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
.tree-item em { flex: 0 0 auto; min-width: 18px; border-radius: 4px; padding: 1px 4px; color: #718682; background: #e7efec; font-size: 12px; font-style: normal; font-variant-numeric: tabular-nums; text-align: center; }
.tree-item:hover { color: #173b37; background: #eaf2ef; }
.tree-item.is-active { color: #173b37; background: #dcece7; font-weight: 800; box-shadow: inset 3px 0 #0f766e; }
.tree-item.is-library-root { height: 36px; color: #173f3e; background: rgba(225, 239, 234, .72); font-weight: 850; }
.tree-item.is-library-root > svg { color: #0f766e; }
.tree-item.is-library-root:hover { background: #deeee9; }
.folder-rail-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; padding: 11px; border-top: 1px solid #dde7e4; background: rgba(255, 255, 255, .72); }
.folder-rail-summary > div { display: grid; gap: 3px; padding: 8px; border-radius: 6px; background: #edf5f2; }
.folder-rail-summary span { color: #708681; font-size: 12px; }.folder-rail-summary strong { color: #174f49; font-size: 16px; font-variant-numeric: tabular-nums; }
.folder-rail-summary p { display: flex; grid-column: 1 / -1; gap: 6px; margin: 2px 0 0; color: #738782; font-size: 12px; line-height: 1.45; }.folder-rail-summary p svg { flex: 0 0 auto; color: #0f766e; }

.document-queue { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; border-right: 1px solid #e0e8e5; background: #fff; }
.queue-head { display: flex; flex: 0 0 auto; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 17px 18px 13px; border-bottom: 1px solid #e4ebe9; }
.queue-head > div { min-width: 0; }
.queue-head > div > span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .06em; }
.queue-head h1 { overflow: hidden; margin: 4px 0 3px; color: #173235; font-size: 18px; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.queue-head p { overflow: hidden; margin: 0; color: #748783; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.queue-tabs { display: flex; flex: 0 0 auto; gap: 5px; padding: 3px; border-radius: 7px; background: #edf2f0; }
.queue-tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; border-radius: 5px; padding: 7px 9px; color: #647a75; background: transparent; font: inherit; font-size: 12px; font-weight: 780; cursor: pointer; }
.queue-tabs button b { min-width: 18px; border-radius: 4px; padding: 2px 4px; background: rgba(77, 108, 102, .1); font-size: 12px; font-variant-numeric: tabular-nums; }
.queue-tabs button.active { color: #fff; background: #173f3e; box-shadow: 0 3px 8px rgba(23, 63, 62, .16); }.queue-tabs button.active b { background: rgba(255, 255, 255, .14); }
.search-state { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 18px; border-bottom: 1px solid #d9e8e3; color: #285d57; background: #f0f8f5; font-size: 12px; }
.search-state button { border: 0; padding: 0; color: #0f766e; background: transparent; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; }

.diagnosis-worklist,
.library-stream { display: flex; flex: 1 1 auto; min-height: 0; flex-direction: column; overflow: hidden; }
.intake-launcher { display: grid; flex: 1 1 auto; min-height: 0; place-content: center; justify-items: center; gap: 15px; padding: 38px; text-align: center; }
.launcher-icon { display: grid; width: 58px; height: 58px; place-items: center; border: 1px solid #bad6cf; border-radius: 16px; color: #0f766e; background: #e9f5f1; box-shadow: 0 10px 25px rgba(15, 118, 110, .09); }
.intake-launcher > div { display: grid; justify-items: center; gap: 7px; }
.intake-launcher > div > span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .05em; }
.intake-launcher h2 { max-width: 520px; margin: 0; color: #173235; font-size: 19px; line-height: 1.35; text-wrap: balance; }
.intake-launcher p { max-width: 58ch; margin: 0; color: #70837f; font-size: 12px; line-height: 1.65; }
.intake-launcher > button,
.document-empty button { display: inline-flex; align-items: center; gap: 7px; border: 0; border-radius: 7px; padding: 10px 14px; color: #fff; background: #d45f1f; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; box-shadow: 0 7px 15px rgba(212, 95, 31, .17); }
.diagnosis-list { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 12px; scrollbar-gutter: stable; }
.diagnosis-list-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 2px 3px 10px; color: #71847f; font-size: 12px; }
.diagnosis-list-head button { border: 1px solid #b9d2cc; border-radius: 5px; padding: 6px 8px; color: #0f6a62; background: #f4faf8; font: inherit; font-size: 12px; font-weight: 780; cursor: pointer; }
.diagnosis-row {
  display: grid;
  width: 100%;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 11px;
  margin-bottom: 7px;
  border: 1px solid #e0e8e5;
  border-radius: 8px;
  padding: 12px;
  color: inherit;
  background: #fff;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color .18s ease, background .18s ease, transform .18s ease, box-shadow .18s ease;
}
.diagnosis-row:hover { border-color: #a9c9c1; transform: translateY(-1px); box-shadow: 0 7px 15px rgba(33, 67, 62, .06); }
.diagnosis-row.active { border-color: #0f766e; background: #f1f9f6; box-shadow: inset 3px 0 #0f766e; }
.diagnosis-file-icon,
.stream-icon { display: grid; flex: 0 0 auto; width: 38px; height: 38px; place-items: center; border-radius: 8px; color: #0f766e; background: #e4f2ee; }
.diagnosis-copy { display: grid; min-width: 0; gap: 4px; }
.diagnosis-copy > span,
.stream-copy > span { display: flex; align-items: center; gap: 7px; }
.diagnosis-copy b,
.stream-copy b { color: #0f766e; font-size: 12px; }.diagnosis-copy em { color: #7d908c; font-size: 12px; font-style: normal; }
.diagnosis-copy strong { overflow: hidden; color: #173235; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.diagnosis-copy small { overflow: hidden; color: #71837f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.diagnosis-version { padding: 5px 7px; border-radius: 5px; color: #8a511d; background: #fff3e7; font-size: 12px; font-weight: 800; white-space: nowrap; }.diagnosis-arrow { color: #8ca09b; }

.library-path-row { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; min-height: 35px; margin: 12px 14px 6px; padding: 3px 8px; border: 1px solid #e1e8e6; border-radius: 6px; background: #f8faf9; }
.library-breadcrumb { display: flex; flex: 1 1 auto; min-width: 0; align-items: center; gap: 3px; overflow: auto; }
.library-breadcrumb button { flex: 0 0 auto; border: 0; border-radius: 4px; padding: 5px 6px; color: #38615c; background: transparent; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; white-space: nowrap; }
.library-breadcrumb button:not(:disabled):hover { background: #e7f1ee; }.library-breadcrumb button:disabled { color: #173235; cursor: default; }.breadcrumb-separator { color: #8ea09c; }
.library-path-row > span { flex: 0 0 auto; color: #778b86; font-size: 12px; font-variant-numeric: tabular-nums; }
.document-stream-list { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 6px 14px 14px; scrollbar-gutter: stable; }
.folder-stream-row,
.document-stream-row {
  display: grid;
  width: 100%;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 11px;
  min-height: 66px;
  border: 0;
  border-bottom: 1px solid #e8eeec;
  padding: 8px 7px;
  color: inherit;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background .18s ease, transform .18s ease;
}
.folder-stream-row:hover,
.document-stream-row:hover { background: #f6f9f8; transform: translateX(2px); }
.document-stream-row.active { background: #edf7f4; box-shadow: inset 3px 0 #0f766e; }
.stream-icon.folder { color: #c77e15; background: #fff3dc; }.stream-icon.document { color: #3d6f69; background: #e8f1ef; }
.stream-copy { display: grid; min-width: 0; gap: 4px; }
.stream-copy strong { overflow: hidden; color: #173235; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.stream-copy small { overflow: hidden; color: #748783; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.stream-copy em { display: inline-flex; align-items: center; gap: 3px; color: #67807b; font-size: 12px; font-style: normal; }
.stream-state { color: #8b6a35; font-size: 12px; font-weight: 750; }.stream-version { display: grid; justify-items: end; gap: 2px; color: #315c56; font-size: 12px; font-weight: 800; }.stream-version small { color: #849590; font-size: 12px; font-weight: 500; }
.document-empty { display: grid; min-height: 300px; place-content: center; justify-items: center; gap: 8px; color: #7a8e89; text-align: center; }
.document-empty strong { color: #385b56; font-size: 14px; }.document-empty p { max-width: 40ch; margin: 0 0 6px; font-size: 12px; line-height: 1.6; }

.dobby-inspector { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; background: #f8faf9; }
.inspector-head { display: flex; flex: 0 0 auto; align-items: center; gap: 9px; padding: 14px 15px; border-bottom: 1px solid #dfe8e5; background: #fff; }.inspector-avatar { width: 34px; height: 34px; border-radius: 9px; }.inspector-head > div { flex: 1 1 auto; }.inspector-head em { margin-left: auto; }
.inspector-scroll { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 14px; scrollbar-gutter: stable; }
.diagnosed-file,
.selected-document { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 10px; padding: 11px; border: 1px solid #dce7e4; border-radius: 8px; background: #fff; }
.diagnosed-file > span,
.selected-document > span { display: grid; width: 44px; height: 36px; place-items: center; border-radius: 6px; color: #2f625b; background: #e3f0ed; font-size: 12px; font-weight: 850; }
.diagnosed-file > div,
.selected-document > div { display: grid; min-width: 0; gap: 4px; }.diagnosed-file strong,.selected-document strong { overflow: hidden; color: #173235; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.diagnosed-file small,.selected-document small { color: #71847f; font-size: 12px; }
.analysis-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; margin: 10px 0; padding: 0; list-style: none; }
.analysis-steps li { display: grid; justify-items: center; gap: 3px; padding: 8px 4px; border-radius: 6px; color: #0f766e; background: #eaf5f1; text-align: center; }
.analysis-steps li span { color: #345e58; font-size: 12px; font-weight: 750; }.analysis-steps li em { color: #7a8e89; font-size: 12px; font-style: normal; }
.insight-block { margin-top: 9px; padding: 11px; border: 1px solid #dfe8e5; border-radius: 8px; background: #fff; }
.insight-block header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.insight-block header span { color: #173f3e; font-size: 12px; font-weight: 850; }.insight-block header b { color: #0f766e; font-size: 12px; font-weight: 750; }
.insight-block > p { margin: 0; color: #5f7671; font-size: 12px; line-height: 1.6; }
.diagnosis-form-block { display: grid; gap: 8px; }.diagnosis-form-block header { margin-bottom: 0; }
.diagnosis-form-block label { display: grid; gap: 5px; color: #657c77; font-size: 12px; font-weight: 750; }.diagnosis-form-block select { width: 100%; min-width: 0; padding: 8px; border: 1px solid #cddbd7; border-radius: 6px; color: #264c47; background: #f9fbfa; font: inherit; font-size: 12px; }
.recommendation-reason { display: flex; gap: 6px; padding: 8px; border-radius: 6px; background: #eef6f3; }.recommendation-reason svg { flex: 0 0 auto; margin-top: 1px; color: #0f766e; }
.version-block > div { display: flex; align-items: flex-start; gap: 8px; }.version-block > div > svg { flex: 0 0 auto; color: #ae6b1d; }.version-block p { margin: 0; color: #5f7671; font-size: 12px; line-height: 1.55; }.version-block p strong { color: #8a511d; }
.context-tags { display: flex; flex-wrap: wrap; gap: 5px; }.context-tags span { border-radius: 4px; padding: 5px 7px; color: #315e58; background: #eaf3f0; font-size: 12px; font-weight: 700; }
.check-block > p { display: flex; align-items: flex-start; gap: 6px; }.check-block > p svg { flex: 0 0 auto; margin-top: 1px; color: #0f8b6d; }.check-block > p.warning svg { color: #c46b21; }
.inspector-actions { display: grid; flex: 0 0 auto; grid-template-columns: auto minmax(0, 1fr); gap: 7px; padding: 11px 14px 14px; border-top: 1px solid #dfe8e5; background: #fff; }
.inspector-actions button { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; gap: 6px; border-radius: 6px; padding: 8px 10px; font: inherit; font-size: 12px; font-weight: 800; cursor: pointer; }.discard-action { border: 1px solid #d1ddd9; color: #607672; background: #fff; }.confirm-action { border: 0; color: #fff; background: #d45f1f; box-shadow: 0 5px 13px rgba(212, 95, 31, .16); }
.existing-document-insight { display: flex; flex-direction: column; }
.dobby-message { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; margin-top: 10px; }.dobby-message > span { display: grid; width: 27px; height: 27px; place-items: center; border-radius: 7px; color: #fff; background: #173f3e; }.dobby-message > div { padding: 10px; border: 1px solid #dbe6e3; border-radius: 3px 9px 9px 9px; background: #fff; }.dobby-message small { color: #0f766e; font-size: 12px; font-weight: 850; }.dobby-message p { margin: 4px 0 0; color: #506963; font-size: 12px; line-height: 1.65; }
.document-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 10px; }.document-facts > div { display: grid; gap: 4px; padding: 9px; border-radius: 6px; background: #eaf3f0; }.document-facts .wide { grid-column: 1 / -1; }.document-facts span { color: #718681; font-size: 12px; }.document-facts strong { overflow-wrap: anywhere; color: #244d47; font-size: 12px; line-height: 1.45; }
.assistant-suggestions { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }.assistant-suggestions button { border: 1px solid #c9dad5; border-radius: 5px; padding: 6px 7px; color: #315e58; background: #fff; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; }.assistant-suggestions button:hover { border-color: #73a399; color: #0f6d64; background: #f2f8f6; }
.assistant-composer { display: grid; flex: 0 0 auto; grid-template-columns: minmax(0, 1fr) 38px; gap: 7px; padding: 11px 14px 14px; border-top: 1px solid #dfe8e5; background: #fff; }.assistant-composer textarea { min-height: 38px; max-height: 80px; resize: none; box-sizing: border-box; padding: 9px; border: 1px solid #cddbd7; border-radius: 6px; color: #254942; background: #f9fbfa; font: inherit; font-size: 12px; line-height: 1.5; }.assistant-composer button { display: grid; place-items: center; border: 0; border-radius: 6px; color: #fff; background: #173f3e; cursor: pointer; }
.inspector-empty { display: grid; flex: 1 1 auto; place-content: center; justify-items: center; gap: 8px; padding: 26px; color: #77908a; text-align: center; }.inspector-empty strong { color: #315651; font-size: 13px; }.inspector-empty p { max-width: 34ch; margin: 0; font-size: 12px; line-height: 1.6; }

.library-modal-backdrop { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center; padding: 24px; background: rgba(15, 32, 35, .44); backdrop-filter: blur(3px); }
.library-modal { width: min(100%, 470px); max-height: calc(100dvh - 48px); overflow: auto; padding: 20px; border: 1px solid rgba(28, 56, 57, .18); border-radius: 12px; background: #fff; box-shadow: 0 22px 56px rgba(15, 39, 42, .26); }
.library-modal-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 13px; }.library-modal-head > div { display: flex; min-width: 0; align-items: baseline; gap: 9px; }.library-modal-head span { color: #0f766e; font-size: 12px; font-weight: 850; letter-spacing: .04em; }.library-modal-head h2 { margin: 0; color: #173235; font-size: 17px; }.modal-close,.modal-secondary,.modal-primary { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border-radius: 6px; padding: 8px 12px; font: inherit; font-size: 12px; font-weight: 780; cursor: pointer; }.modal-close,.modal-secondary { border: 1px solid #cad8d4; color: #536e69; background: #fff; }.modal-primary { border: 0; color: #fff; background: #d45f1f; }
.folder-create-form { display: grid; gap: 14px; }.folder-parent-context { display: grid; gap: 4px; padding: 9px 10px; border: 1px solid #dde8e5; border-radius: 6px; background: #f5f9f7; }.folder-parent-context span { color: #748782; font-size: 12px; }.folder-parent-context strong { color: #294d47; font-size: 12px; overflow-wrap: anywhere; }.folder-create-form label { display: grid; gap: 6px; color: #566f6a; font-size: 12px; font-weight: 750; }.folder-create-form input { box-sizing: border-box; width: 100%; padding: 9px 10px; border: 1px solid #cad8d4; border-radius: 6px; color: #173235; font: inherit; font-size: 12px; }.folder-create-form > div:last-child { display: flex; justify-content: flex-end; gap: 7px; }
.upload-modal { display: flex; width: min(100%, 650px); height: min(610px, calc(100dvh - 48px)); flex-direction: column; overflow: hidden; }.upload-modal > .library-modal-head { flex: 0 0 auto; }.upload-form { display: grid; flex: 1 1 auto; min-height: 0; grid-template-rows: auto auto auto minmax(0, 1fr) auto; gap: 12px; }
.upload-ai-note { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 9px; padding: 10px; border: 1px solid #bdd8d1; border-radius: 7px; color: #0f766e; background: #eaf5f1; }.upload-ai-note > div { display: grid; gap: 3px; }.upload-ai-note strong { color: #174b45; font-size: 12px; }.upload-ai-note span { color: #5e7772; font-size: 12px; line-height: 1.45; }
.upload-queue-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; }.upload-queue-head > div { display: grid; gap: 3px; }.upload-queue-head strong { color: #294d47; font-size: 12px; }.upload-queue-head span { color: #7a8d88; font-size: 12px; }
.upload-picker { display: inline-flex; align-items: center; justify-content: center; border: 1px solid #7eaaa1; border-radius: 6px; padding: 7px 10px; color: #17665d; background: #f2f8f6; font-size: 12px; font-weight: 780; cursor: pointer; }.upload-picker input { display: none; }
.upload-queue { display: grid; min-height: 0; align-content: start; gap: 6px; margin: 0; padding: 0; overflow: auto; list-style: none; scrollbar-gutter: stable; }.upload-queue li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 9px; padding: 8px 10px; border: 1px solid #e0e8e5; border-radius: 7px; background: #fbfcfc; }.upload-file-type { display: grid; min-width: 42px; min-height: 32px; place-items: center; border-radius: 5px; color: #3d6862; background: #e7f1ee; font-size: 12px; font-weight: 850; }.upload-queue li > div { display: grid; min-width: 0; gap: 3px; }.upload-queue li strong { overflow: hidden; color: #294842; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.upload-queue li div span { color: #7c8f8a; font-size: 12px; }.upload-queue li button { border: 0; padding: 5px; color: #b9532b; background: transparent; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; }
.upload-queue-empty { display: grid; min-height: 0; place-content: center; justify-items: center; gap: 7px; padding: 20px; border: 1px dashed #c8d8d4; border-radius: 8px; color: #7c8e8a; text-align: center; }.upload-queue-empty strong { color: #3b5d57; font-size: 12px; }.upload-queue-empty span { font-size: 12px; }.upload-actions { display: flex; justify-content: flex-end; gap: 7px; padding-top: 2px; }

button:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible { outline: 2px solid rgba(15, 118, 110, .45); outline-offset: 2px; }

@media (max-width: 1180px) {
  .dobby-workspace-grid { grid-template-columns: 200px minmax(350px, 1fr) minmax(300px, .7fr); }
  .dobby-topbar { gap: 10px; }
  .dobby-identity { min-width: 205px; }
  .secondary-action { display: none; }
}
@media (max-width: 960px) {
  .dobby-topbar { grid-template-columns: auto minmax(220px, 1fr); }
  .topbar-actions { grid-column: 1 / -1; justify-content: flex-end; }
  .secondary-action { display: inline-flex; }
  .dobby-workspace-grid { grid-template-columns: minmax(340px, 1fr) minmax(300px, .82fr); }
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
  .document-queue { min-height: 620px; border-right: 0; border-bottom: 1px solid #e0e8e5; }
  .dobby-inspector { min-height: 620px; }
  .queue-head { align-items: flex-start; flex-direction: column; }
  .queue-tabs { width: 100%; }
  .queue-tabs button { flex: 1 1 0; justify-content: center; }
  .diagnosis-row { grid-template-columns: auto minmax(0, 1fr) auto; }.diagnosis-version { display: none; }
  .library-modal-backdrop { padding: 10px; }
  .library-modal { max-height: calc(100dvh - 20px); padding: 15px; }
  .upload-modal { height: calc(100dvh - 20px); }
  .analysis-steps { grid-template-columns: 1fr; }
}
</style>
