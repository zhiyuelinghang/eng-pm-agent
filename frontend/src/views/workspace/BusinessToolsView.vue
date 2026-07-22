<template>
  <main class="business-tools-page">
    <section class="business-tools-shell">
      <aside class="tool-rail" aria-label="业务工具列表">
        <header class="tool-rail-head">
          <div>
            <span>专业智能体</span>
            <strong>业务工具</strong>
          </div>
          <em>{{ businessTools.length }}</em>
          <p>选择一个专业智能体，围绕当前项目继续分析和处理。</p>
        </header>

        <nav class="tool-list">
          <button
            v-for="tool in businessTools"
            :key="tool.key"
            type="button"
            :class="{ active: selectedToolKey === tool.key }"
            @click="selectTool(tool.key)"
          >
            <span class="tool-list-icon"><n-icon :size="20"><component :is="tool.icon" /></n-icon></span>
            <span class="tool-list-copy">
              <strong>{{ tool.name }}</strong>
              <small>{{ tool.shortDescription }}</small>
            </span>
            <i aria-hidden="true"></i>
          </button>
        </nav>

      </aside>

      <section class="tool-workspace" aria-label="业务工具对话区">
        <header class="tool-workspace-head">
          <div class="active-tool-icon"><n-icon :size="24"><component :is="selectedTool.icon" /></n-icon></div>
          <div class="active-tool-copy">
            <span><n-icon :size="15"><Robot /></n-icon>专业智能体</span>
            <h1>{{ selectedTool.name }}</h1>
            <p>{{ selectedTool.description }}</p>
          </div>
          <div class="tool-online-state"><i></i><span>可用</span></div>
        </header>

        <div ref="threadViewport" class="tool-thread">
          <article v-for="item in activeToolMessages" :key="item.id" :class="['tool-message', item.role]">
            <div class="tool-message-avatar" aria-hidden="true">{{ item.role === 'assistant' ? '管' : '我' }}</div>
            <div class="tool-message-stack">
              <span v-if="item.role === 'assistant'">{{ selectedTool.name }}</span>
              <div class="tool-message-bubble">
                <p>{{ item.content }}</p>
                <div v-if="item.attachments?.length" class="tool-message-files">
                  <span v-for="attachment in item.attachments" :key="attachment.id">
                    <n-icon :size="16"><FileText /></n-icon>
                    <b :title="attachment.name">{{ attachment.name }}</b>
                    <small>{{ formatFileSize(attachment.size) }}</small>
                  </span>
                </div>
              </div>
            </div>
          </article>

          <section v-if="!activeToolMessages.length" class="tool-empty-state">
            <div class="tool-empty-icon"><n-icon :size="27"><component :is="selectedTool.icon" /></n-icon></div>
            <span>{{ selectedTool.name }}智能体</span>
            <h2>{{ selectedTool.emptyTitle }}</h2>
            <p>{{ selectedTool.emptyDescription }}</p>
            <div class="tool-starters" aria-label="示例任务">
              <button v-for="starter in selectedTool.starters" :key="starter" type="button" @click="useStarter(starter)">{{ starter }}</button>
            </div>
          </section>
        </div>

        <form class="tool-composer" @submit.prevent="submitToolMessage">
          <div class="tool-composer-entry">
            <div v-if="selectedFiles.length" class="tool-file-queue" aria-label="待发送附件">
              <span v-for="(file, index) in selectedFiles" :key="`${file.name}-${file.lastModified}`">
                <n-icon :size="15"><FileText /></n-icon>
                <b :title="file.name">{{ file.name }}</b>
                <small>{{ formatFileSize(file.size) }}</small>
                <button type="button" :aria-label="`移除附件 ${file.name}`" @click="removeFile(index)">×</button>
              </span>
            </div>
            <div class="tool-composer-row">
              <label class="tool-attach-button" title="添加工程资料或图片">
                <input type="file" multiple @change="selectFiles">
                <n-icon :size="19"><Paperclip /></n-icon>
                <span>添加附件</span>
              </label>
              <textarea
                v-model="command"
                :placeholder="selectedTool.placeholder"
                @keydown.enter.exact.prevent="submitToolMessage"
              ></textarea>
            </div>
          </div>
          <button class="tool-send-button" type="submit" :disabled="submitting || (!command.trim() && !selectedFiles.length)">
            <n-icon :size="18"><Send /></n-icon>
            {{ submitting ? '处理中…' : '发送' }}
          </button>
        </form>
      </section>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ChartBar, CircleCheck, Database, FileText, Paperclip, Robot, Route, Send, ShieldCheck } from '@vicons/tabler'
import { useAppStore } from '@/stores/app'

type ToolKey = 'analysis' | 'safety' | 'trend' | 'risk' | 'writing' | 'review'
type ToolMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  attachments?: Array<{ id: string; name: string; size: number }>
}

const businessTools = [
  {
    key: 'analysis' as const,
    name: '数据分析',
    shortDescription: '查询数据并生成分析结论',
    description: '按自然语言查询当前项目数据，整理统计口径、表格和结论摘要。',
    emptyTitle: '描述你要分析的数据问题',
    emptyDescription: '说明指标、范围和时间条件，智能体会整理查询口径并输出数据结论。',
    placeholder: '例如：统计当前项目风险、隐患、质量问题和逾期任务',
    starters: ['统计当前项目重点风险和逾期任务', '汇总各工序当前进度', '分析任务闭环情况'],
    icon: Database,
  },
  {
    key: 'safety' as const,
    name: '安全隐患',
    shortDescription: '识别隐患并给出整改建议',
    description: '结合巡检照片、隐患记录和整改反馈，识别问题并整理闭环要求。',
    emptyTitle: '上传现场信息或描述隐患',
    emptyDescription: '可上传巡检照片，或说明隐患位置和现象，智能体会给出判断与整改建议。',
    placeholder: '例如：分析基坑西侧临边防护隐患，并给出整改建议',
    starters: ['分析临边防护隐患', '检查隐患闭环证据是否齐全', '生成现场整改要求'],
    icon: ShieldCheck,
  },
  {
    key: 'trend' as const,
    name: '趋势预测',
    shortDescription: '判断监测与进度变化趋势',
    description: '结合监测数据、计划进度和预警阈值，判断变化趋势和关注时间窗。',
    emptyTitle: '选择需要预测的指标',
    emptyDescription: '提供监测数据、进度记录或指标名称，智能体会判断趋势和关注时间窗。',
    placeholder: '例如：预测 S3 测斜位移未来 24 小时风险趋势',
    starters: ['预测 S3 测斜位移趋势', '判断当前进度偏差是否扩大', '列出未来一周关注窗口'],
    icon: ChartBar,
  },
  {
    key: 'risk' as const,
    name: '风险诊断',
    shortDescription: '诊断风险与证据链缺口',
    description: '按风险源、工序、责任人、资料缺口和监测数据形成诊断结论。',
    emptyTitle: '说明需要诊断的风险场景',
    emptyDescription: '输入工序、风险现象或关注事项，智能体会梳理原因、影响和处置优先级。',
    placeholder: '例如：诊断深基坑开挖窗口当前主要风险',
    starters: ['诊断深基坑开挖风险', '检查重点风险的资料缺口', '梳理风险责任人与措施'],
    icon: Route,
  },
  {
    key: 'writing' as const,
    name: '报告撰写',
    shortDescription: '生成报告草稿和引用清单',
    description: '根据当前项目数据生成专项报告、整改闭环清单或阶段工作周报。',
    emptyTitle: '告诉我需要撰写什么报告',
    emptyDescription: '说明报告类型、统计周期和重点内容，也可以上传已有资料作为写作依据。',
    placeholder: '例如：起草深基坑质量安全监督报告',
    starters: ['起草质量安全监督报告', '生成本周项目简报', '整理整改闭环清单'],
    icon: FileText,
  },
  {
    key: 'review' as const,
    name: '报告审核',
    shortDescription: '核对依据、数据和证据链',
    description: '检查报告依据、来源完整性、数据一致性以及任务闭环证据。',
    emptyTitle: '上传或指定需要审核的报告',
    emptyDescription: '智能体会检查内容依据、数据一致性、缺失来源和闭环证据，并列出修改建议。',
    placeholder: '例如：审核深基坑报告是否缺少来源和证据链',
    starters: ['审核报告的数据一致性', '检查引用依据是否齐全', '列出报告需要补充的证据'],
    icon: CircleCheck,
  },
]

const store = useAppStore()
const message = useMessage()
const selectedToolKey = ref<ToolKey>('analysis')
const command = ref('')
const selectedFiles = ref<File[]>([])
const submitting = ref(false)
const threadViewport = ref<HTMLElement | null>(null)
const toolMessages = ref<Record<ToolKey, ToolMessage[]>>({ analysis: [], safety: [], trend: [], risk: [], writing: [], review: [] })

const selectedTool = computed(() => businessTools.find(tool => tool.key === selectedToolKey.value) || businessTools[0])
const currentProject = computed(() => store.projects.find(project => project.id === store.currentProjectId))
const activeToolMessages = computed(() => toolMessages.value[selectedToolKey.value])
const openTaskCount = computed(() => store.tasks.filter(task => !['done', 'cancelled'].includes(task.status)).length)
const priorityRiskCount = computed(() => store.riskSources.filter(risk => ['critical', 'high'].includes(risk.level)).length)
function selectTool(key: ToolKey) {
  selectedToolKey.value = key
  command.value = ''
  selectedFiles.value = []
  nextTick(() => threadViewport.value?.scrollTo({ top: 0 }))
}

function useStarter(starter: string) {
  command.value = starter
}

function selectFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const accepted = Array.from(input.files || []).filter(file => file.size <= 50 * 1024 * 1024)
  const rejected = Array.from(input.files || []).length - accepted.length
  selectedFiles.value = [...selectedFiles.value, ...accepted]
    .filter((file, index, files) => files.findIndex(item => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified) === index)
    .slice(0, 8)
  input.value = ''
  if (rejected) message.warning('单个附件不能超过 50 MB。')
}

function removeFile(index: number) {
  selectedFiles.value = selectedFiles.value.filter((_, fileIndex) => fileIndex !== index)
}

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function buildToolReply(text: string, attachmentCount: number) {
  const projectName = currentProject.value?.name || '当前项目'
  const attachmentText = attachmentCount ? `已读取你上传的 ${attachmentCount} 个附件，并与当前项目数据一并分析。` : ''
  const replies: Record<ToolKey, string> = {
    analysis: `${projectName}目前有 ${openTaskCount.value} 项开放任务，其中 ${store.overdueTasks.length} 项逾期；已登记 ${store.riskSources.length} 个风险源、${store.qualityMetrics.length} 项质量指标和 ${store.attachments.length} 份工程资料。下一步可以按工序、责任人或时间范围继续拆分统计口径。`,
    safety: `当前项目记录了 ${store.dashboard?.safety_issues ?? 0} 项安全问题，重点风险源 ${priorityRiskCount.value} 个。建议先核对现场照片、整改责任人、完成时限和复核证据，再生成闭环任务。`,
    trend: `当前 WBS 共 ${store.wbsItems.length} 项，平均进度为 ${averageWbsProgress()}%。建议将计划节点、实际进度和监测阈值放在同一时间轴上，重点观察临近预警值和进度持续偏差的工序。`,
    risk: `已按风险源、关联工序、责任人和资料完整性检查。当前有 ${priorityRiskCount.value} 个高等级风险源、${store.overdueTasks.length} 项逾期任务，建议优先补齐监测依据并确认责任人的下一步动作。`,
    writing: `已为“${text}”建立报告结构：项目概况、当前进展、风险与隐患、质量情况、任务闭环、结论与建议。报告可引用 ${store.attachments.length} 份资料和 ${store.informationRecords.length} 条过程信息。`,
    review: `已按依据、数据一致性、来源完整性和闭环证据四项进行预审。建议重点检查报告中的进度值是否与 WBS 一致、风险结论是否有监测数据支撑，以及整改事项是否附有复核记录。`,
  }
  return `${attachmentText}${replies[selectedToolKey.value]}`
}

function averageWbsProgress() {
  if (!store.wbsItems.length) return 0
  return Math.round(store.wbsItems.reduce((sum, item) => sum + item.progress, 0) / store.wbsItems.length)
}

async function submitToolMessage() {
  const text = command.value.trim() || (selectedFiles.value.length ? '请分析我上传的资料' : '')
  if (!text || submitting.value) return
  if (!store.currentProjectId) {
    message.warning('请先选择项目。')
    return
  }
  const files = [...selectedFiles.value]
  submitting.value = true
  try {
    for (const file of files) await store.uploadAttachment(file, `业务工具/${selectedTool.value.name}`)
    const timestamp = Date.now()
    const attachments = files.map(file => ({ id: `${file.name}-${file.lastModified}`, name: file.name, size: file.size }))
    toolMessages.value[selectedToolKey.value].push(
      { id: `${selectedToolKey.value}-user-${timestamp}`, role: 'user', content: text, attachments: attachments.length ? attachments : undefined },
      { id: `${selectedToolKey.value}-assistant-${timestamp + 1}`, role: 'assistant', content: buildToolReply(text, attachments.length) },
    )
    command.value = ''
    selectedFiles.value = []
    await nextTick()
    threadViewport.value?.scrollTo({ top: threadViewport.value.scrollHeight, behavior: 'smooth' })
  } catch {
    message.error('处理失败，请检查附件或网络后重试。')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.business-tools-page {
  height: calc(100dvh - var(--header-height, 56px));
  min-width: 0;
  box-sizing: border-box;
  padding: 18px;
  overflow: hidden;
  background: radial-gradient(circle at 15% 0%, rgba(15, 118, 110, .07), transparent 30rem), linear-gradient(180deg, #f6f7f3, #edf1ee);
}
.business-tools-shell {
  display: grid;
  height: 100%;
  min-width: 0;
  min-height: 0;
  grid-template-columns: minmax(280px, 30%) minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(20, 45, 54, .1);
  border-radius: 9px;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 18px 42px rgba(28, 48, 44, .06);
}
.tool-rail { display: grid; min-width: 0; min-height: 0; grid-template-rows: auto minmax(0, 1fr); border-right: 1px solid #dfe9e5; background: #f9fbfa; }
.tool-rail-head { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 5px 12px; padding: 17px 18px 15px; border-bottom: 1px solid #e2eae7; }
.tool-rail-head > div { display: grid; }
.tool-rail-head span { color: #0f766e; font-size: 12px; font-weight: 800; }
.tool-rail-head strong { margin-top: 3px; color: #173b38; font-size: 18px; font-weight: 850; }
.tool-rail-head em { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 6px; color: #0f766e; background: #e3f1ec; font-size: 13px; font-style: normal; font-weight: 850; font-variant-numeric: tabular-nums; }
.tool-rail-head p { grid-column: 1 / -1; margin: 4px 0 0; color: #71857f; font-size: 12px; line-height: 1.5; }
.tool-list { min-height: 0; padding: 7px 0; overflow-y: auto; overscroll-behavior: contain; }
.tool-list button { position: relative; display: grid; width: 100%; min-height: 76px; grid-template-columns: 42px minmax(0, 1fr) 7px; align-items: center; gap: 11px; padding: 10px 15px; border: 0; border-bottom: 1px solid rgba(31, 66, 62, .065); color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer; transition: background .2s ease, box-shadow .2s ease, transform .2s ease; }
.tool-list button::before { position: absolute; inset: 9px auto 9px 0; width: 3px; border-radius: 0 3px 3px 0; content: ''; background: transparent; }
.tool-list button:hover { background: #f0f6f3; }
.tool-list button:active { transform: scale(.99); }
.tool-list button.active { background: #e9f4f0; box-shadow: inset -1px 0 rgba(15, 118, 110, .12); }
.tool-list button.active::before { background: #0f766e; }
.tool-list button:focus-visible, .tool-composer button:focus-visible, .tool-composer textarea:focus-visible { outline: 2px solid #0f766e; outline-offset: -2px; }
.tool-list-icon { display: grid; width: 40px; height: 40px; place-items: center; border: 1px solid #cfe1db; border-radius: 8px; color: #0f766e; background: #edf7f4; }
.tool-list button.active .tool-list-icon { color: #fff; border-color: #0f766e; background: #0f766e; }
.tool-list-copy { min-width: 0; }
.tool-list-copy strong { display: block; color: #254944; font-size: 14px; font-weight: 800; }
.tool-list-copy small { display: block; overflow: hidden; margin-top: 5px; color: #71857f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.tool-list button > i { width: 6px; height: 6px; border-radius: 50%; background: #c2d0cc; }
.tool-list button.active > i { background: #16a277; box-shadow: 0 0 0 4px rgba(22, 162, 119, .1); }
.tool-workspace { display: grid; min-width: 0; min-height: 0; grid-template-rows: auto minmax(0, 1fr) auto; background: radial-gradient(circle at 92% 8%, rgba(15, 118, 110, .05), transparent 24rem), #fff; }
.tool-workspace-head { display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; align-items: center; gap: 13px; padding: 15px 18px; border-bottom: 1px solid #e2eae7; }
.active-tool-icon { display: grid; width: 46px; height: 46px; place-items: center; border-radius: 9px; color: #e3f3ee; background: #173f3d; box-shadow: 0 9px 20px rgba(23, 63, 61, .16); }
.active-tool-copy { min-width: 0; }
.active-tool-copy > span { display: inline-flex; align-items: center; gap: 5px; color: #0f766e; font-size: 12px; font-weight: 800; }
.active-tool-copy h1 { margin: 4px 0 2px; color: #153733; font-size: 19px; font-weight: 860; letter-spacing: -.015em; }
.active-tool-copy p { overflow: hidden; margin: 0; color: #6e827d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.tool-online-state { display: inline-flex; align-items: center; gap: 7px; color: #60766f; font-size: 12px; }
.tool-online-state i { width: 7px; height: 7px; border-radius: 50%; background: #16a277; box-shadow: 0 0 0 4px rgba(22, 162, 119, .1); }
.tool-thread { display: flex; min-height: 0; flex-direction: column; gap: 13px; padding: 18px clamp(18px, 3vw, 40px) 28px; overflow-y: auto; overscroll-behavior: contain; }
.tool-message { display: grid; max-width: min(830px, 94%); grid-template-columns: 32px minmax(0, 1fr); align-items: start; gap: 10px; }
.tool-message.user { align-self: flex-end; grid-template-columns: minmax(0, 1fr) 32px; }
.tool-message-avatar { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 8px; color: #dff1ec; background: #173f3d; font-size: 12px; font-weight: 800; }
.tool-message.user .tool-message-avatar { grid-column: 2; color: #fff; background: #c95622; }
.tool-message.user .tool-message-stack { grid-column: 1; grid-row: 1; }
.tool-message-stack { min-width: 0; }
.tool-message-stack > span { display: block; margin: 0 0 5px 2px; color: #c45528; font-size: 12px; font-weight: 800; }
.tool-message-bubble { padding: 13px 15px; border: 1px solid #dce7e3; border-radius: 5px 10px 10px; background: #fff; box-shadow: 0 8px 22px rgba(26, 55, 52, .055); }
.tool-message.user .tool-message-bubble { border-radius: 10px 5px 10px 10px; border-color: #efd5c8; background: #fff8f4; }
.tool-message-bubble p { max-width: 72ch; margin: 0; color: #385651; font-size: 14px; line-height: 1.65; white-space: pre-line; }
.tool-message-files, .tool-file-queue { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.tool-message-files > span, .tool-file-queue > span { display: inline-flex; min-width: 0; align-items: center; gap: 6px; padding: 6px 8px; border-radius: 5px; color: #48645e; background: #eef5f2; font-size: 12px; }
.tool-message-files b, .tool-file-queue b { max-width: 210px; overflow: hidden; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.tool-message-files small, .tool-file-queue small { color: #82938e; font-size: 12px; white-space: nowrap; }
.tool-empty-state { display: grid; width: min(680px, 92%); min-height: 360px; place-content: center; justify-items: center; box-sizing: border-box; margin: auto; padding: 42px 24px; text-align: center; }
.tool-empty-icon { display: grid; width: 56px; height: 56px; place-items: center; border-radius: 13px; color: #e3f3ee; background: #173f3d; box-shadow: 0 12px 28px rgba(23, 63, 61, .16); }
.tool-empty-state > span { margin-top: 15px; color: #0f766e; font-size: 12px; font-weight: 800; }
.tool-empty-state h2 { margin: 6px 0 0; color: #244641; font-size: 19px; font-weight: 850; letter-spacing: -.01em; }
.tool-empty-state > p { max-width: 48ch; margin: 8px 0 0; color: #71857f; font-size: 13px; line-height: 1.65; }
.tool-starters { display: flex; max-width: 650px; margin-top: 19px; flex-wrap: wrap; justify-content: center; gap: 7px; }
.tool-starters button { padding: 7px 9px; border: 1px solid #c9ddd7; border-radius: 6px; color: #0e6c65; background: #fff; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; transition: transform .18s ease, border-color .18s ease, background .18s ease; }
.tool-starters button:hover { transform: translateY(-1px); border-color: #0f766e; background: #f2f9f6; }
.tool-composer { display: grid; grid-template-columns: minmax(0, 1fr) 86px; gap: 8px; padding: 12px 16px 15px; border-top: 1px solid #e1e9e6; background: rgba(252, 253, 253, .96); }
.tool-composer-entry { min-width: 0; padding: 6px 8px 7px; border: 1px solid #cddbd7; border-radius: 7px; background: #fff; transition: border-color .18s ease, box-shadow .18s ease; }
.tool-composer-entry:focus-within { border-color: #0f766e; box-shadow: 0 0 0 3px rgba(15, 118, 110, .09); }
.tool-file-queue { margin: 0 0 6px; padding-bottom: 6px; border-bottom: 1px solid #e6eeeb; }
.tool-file-queue button { display: grid; width: 20px; height: 20px; place-items: center; border: 0; border-radius: 4px; color: #78908a; background: transparent; font: inherit; cursor: pointer; }
.tool-file-queue button:hover { color: #b94623; background: #fae8e0; }
.tool-composer-row { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: end; gap: 8px; }
.tool-attach-button { display: inline-flex; min-height: 38px; align-items: center; gap: 6px; padding: 0 9px; border-radius: 5px; color: #58716b; background: #f0f5f3; font-size: 12px; font-weight: 750; cursor: pointer; }
.tool-attach-button:hover { color: #0f766e; background: #e5f1ed; }
.tool-attach-button input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; pointer-events: none; }
.tool-composer textarea { width: 100%; min-height: 38px; max-height: 92px; box-sizing: border-box; padding: 8px 5px; border: 0; outline: 0; color: #294844; background: transparent; font: inherit; font-size: 14px; line-height: 1.5; resize: none; }
.tool-send-button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; border: 0; border-radius: 7px; color: #fff; background: #c95622; font: inherit; font-size: 13px; font-weight: 800; cursor: pointer; transition: transform .18s ease, background .18s ease, box-shadow .18s ease; }
.tool-send-button:hover { transform: translateY(-1px); background: #b94a1b; box-shadow: 0 9px 18px rgba(201, 86, 34, .18); }
.tool-send-button:active { transform: translateY(1px) scale(.98); }
.tool-send-button:disabled { opacity: .45; cursor: not-allowed; transform: none; box-shadow: none; }
@media (max-width: 980px) {
  .business-tools-page { height: auto; min-height: calc(100dvh - var(--header-height, 56px)); overflow: visible; }
  .business-tools-shell { min-height: 820px; grid-template-columns: minmax(240px, 34%) minmax(0, 1fr); }
  .tool-message-bubble p, .tool-composer textarea { font-size: 13px; }
}
@media (max-width: 720px) {
  .business-tools-page { padding: 10px; }
  .business-tools-shell { display: block; min-height: 0; overflow: visible; }
  .tool-rail { border-right: 0; border-bottom: 1px solid #dfe9e5; }
  .tool-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: none; padding: 7px; }
  .tool-list button { min-height: 68px; border: 1px solid transparent; border-radius: 6px; }
  .tool-list button::before, .tool-list button > i { display: none; }
  .tool-list button.active { border-color: #bed8d0; }
  .tool-workspace { min-height: 720px; }
  .tool-workspace-head { grid-template-columns: 42px minmax(0, 1fr); }
  .active-tool-icon { width: 40px; height: 40px; }
  .tool-online-state { display: none; }
  .active-tool-copy p { white-space: normal; }
  .tool-thread { padding-inline: 12px; }
  .tool-empty-state { width: 100%; min-height: 320px; padding-inline: 18px; }
  .tool-composer { grid-template-columns: 1fr; }
  .tool-send-button { min-height: 42px; }
}
</style>
