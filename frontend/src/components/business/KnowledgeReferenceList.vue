<template>
  <details v-if="references.length" class="knowledge-references" open>
    <summary>
      <span>参考资料</span>
      <strong>{{ references.length }}</strong>
    </summary>
    <div class="reference-grid">
      <article v-for="reference in references" :key="reference.id" class="reference-card">
        <span class="reference-file-icon">
          <DocumentTypeIcon :kind="iconKind(reference.fileName)" />
        </span>
        <div class="reference-main">
          <header>
            <button
              v-if="reference.knowledgeId"
              type="button"
              class="reference-name-button"
              :title="`在知识库中定位 ${reference.fileName}`"
              @click="locate(reference)"
            >
              {{ reference.fileName }}
            </button>
            <strong v-else :title="reference.fileName">{{ reference.fileName }}</strong>
            <span v-if="reference.score && reference.score > 0" class="reference-score">相关度 {{ scoreLabel(reference.score) }}</span>
          </header>
          <p v-if="reference.contentSnippet">{{ reference.contentSnippet }}</p>
          <div class="reference-meta">
            <span v-if="reference.fileType">{{ reference.fileType.toUpperCase() }}</span>
            <span v-if="reference.fileSize">{{ fileSizeLabel(reference.fileSize) }}</span>
            <span v-if="reference.matchType">{{ matchTypeLabel(reference.matchType) }}</span>
            <span v-if="reference.chunkIndex !== undefined">第 {{ reference.chunkIndex + 1 }} 个片段</span>
            <span v-if="reference.knowledgeChannel">{{ channelLabel(reference.knowledgeChannel) }}</span>
            <span v-if="reference.folderPath" :title="reference.folderPath">{{ reference.folderPath }}</span>
          </div>
        </div>
        <footer class="reference-actions">
          <button v-if="reference.knowledgeId" type="button" @click="locate(reference)">
            <n-icon :size="16"><FileSearch /></n-icon>
            定位
          </button>
          <button v-if="reference.knowledgeId" type="button" @click="download(reference)">
            <n-icon :size="16"><Download /></n-icon>
            下载
          </button>
          <a v-if="externalSource(reference.source)" :href="reference.source" target="_blank" rel="noopener noreferrer">
            <n-icon :size="16"><ExternalLink /></n-icon>
            来源
          </a>
        </footer>
      </article>
    </div>
  </details>
</template>

<script setup lang="ts">
import { NIcon, useMessage } from 'naive-ui'
import { Download, ExternalLink, FileSearch } from '@vicons/tabler'
import DocumentTypeIcon from '@/components/business/DocumentTypeIcon.vue'
import { downloadWeKnoraKnowledge } from '@/api/weknoraAssets'

type KnowledgeReferenceView = {
  id: string
  knowledgeId: string
  knowledgeBaseId?: string
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
}

const props = defineProps<{
  projectId: string
  references: KnowledgeReferenceView[]
}>()
const emit = defineEmits<{
  locate: [reference: KnowledgeReferenceView]
}>()
const message = useMessage()

function scoreLabel(value: number) {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

function fileSizeLabel(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / 1024 / 1024).toFixed(value >= 10 * 1024 * 1024 ? 0 : 1)} MB`
}

function externalSource(value?: string) {
  return /^https?:\/\//i.test(value || '')
}

function matchTypeLabel(value: string) {
  const labels: Record<string, string> = {
    vector: '向量匹配',
    keyword: '关键词匹配',
    hybrid: '混合匹配',
  }
  return labels[value.toLowerCase()] || value
}

function channelLabel(value: string) {
  const labels: Record<string, string> = {
    web: '网页入库',
    api: '接口入库',
    feishu: '飞书入库',
    notion: 'Notion 入库',
  }
  return labels[value.toLowerCase()] || value
}

function locate(reference: KnowledgeReferenceView) {
  emit('locate', reference)
}

async function download(reference: KnowledgeReferenceView) {
  try {
    await downloadWeKnoraKnowledge(props.projectId, reference.knowledgeId, reference.fileName)
  } catch (error: any) {
    message.error(error.message || '资料下载失败。')
  }
}

function iconKind(fileName: string) {
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
.knowledge-references { margin-top: 15px; border-top: 1px solid #e4ebe9; padding-top: 11px; }
.knowledge-references summary { display: flex; width: fit-content; align-items: center; gap: 7px; color: #506a65; font-size: 12px; font-weight: 760; cursor: pointer; }
.knowledge-references summary strong { display: grid; min-width: 22px; height: 20px; place-items: center; border-radius: 10px; color: #0e685f; background: #e6f2ee; font-size: 12px; }
.reference-grid { display: grid; gap: 8px; margin-top: 10px; }
.reference-card { display: grid; min-width: 0; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 10px; border: 1px solid #dce6e3; border-radius: 8px; padding: 11px; background: #fbfcfc; }
.reference-file-icon { display: grid; width: 32px; height: 38px; place-items: center; }
.reference-file-icon :deep(img) { width: 30px; height: 34px; object-fit: contain; }
.reference-main { min-width: 0; }
.reference-main header { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 10px; }
.reference-main header > strong,.reference-name-button { min-width: 0; overflow: hidden; color: #294943; font-size: 13px; font-weight: 780; text-overflow: ellipsis; white-space: nowrap; }
.reference-name-button { border: 0; padding: 0; background: transparent; text-align: left; cursor: pointer; }
.reference-name-button:hover { color: #0e6e64; text-decoration: underline; text-underline-offset: 3px; }
.reference-score { flex: 0 0 auto; border-radius: 10px; padding: 3px 7px; color: #0f7369; background: #e6f4ef; font-size: 12px; font-weight: 700; }
.reference-main p { display: -webkit-box; margin: 7px 0 0; overflow: hidden; color: #5c716d; font-size: 12px; line-height: 1.6; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.reference-meta { display: flex; min-width: 0; flex-wrap: wrap; gap: 5px 10px; margin-top: 7px; color: #7c8e8a; font-size: 12px; }
.reference-meta span:last-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.reference-actions { display: flex; align-self: center; justify-self: end; gap: 7px; white-space: nowrap; }
.reference-actions button,.reference-actions a { display: inline-flex; min-height: 30px; flex: 0 0 auto; align-items: center; gap: 5px; border: 1px solid #d2dfdc; border-radius: 6px; padding: 0 9px; color: #315c55; background: #fff; font: inherit; font-size: 12px; line-height: 1; text-decoration: none; white-space: nowrap; cursor: pointer; }
.reference-actions button:hover,.reference-actions a:hover { border-color: #86aba3; color: #0e6e64; background: #f1f8f5; }
</style>
