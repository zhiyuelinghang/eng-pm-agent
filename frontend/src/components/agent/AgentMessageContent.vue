<template>
  <div class="agent-message-content">
    <section v-if="showPlan && runtimeTrace?.tasksContext?.tasks?.length" class="agent-plan">
      <header>
        <span><n-icon :size="15"><ListCheck /></n-icon>执行计划</span>
        <strong>{{ completedTasks }}/{{ runtimeTrace.tasksContext.tasks.length }}</strong>
      </header>
      <div class="agent-plan-track"><i :style="{ width: `${taskProgress}%` }"></i></div>
      <ul>
        <li
          v-for="task in runtimeTrace.tasksContext.tasks"
          :key="String(task.id)"
          :class="task.state"
        >
          <n-icon :size="14">
            <CircleCheck v-if="task.state === 'completed'" />
            <Loader v-else-if="task.state === 'in_progress'" class="spin" />
            <Circle v-else />
          </n-icon>
          <span>{{ task.subject }}</span>
        </li>
      </ul>
    </section>

    <section v-if="runtimeTrace?.subagentHitl.length && isTraceActive" class="agent-subagent-hitl">
      <header>
        <n-icon :size="16"><Users /></n-icon>
        <div>
          <strong>协同智能体等待确认</strong>
          <span>以下操作由子智能体发起，需要当前用户决策。</span>
        </div>
      </header>
      <article
        v-for="entry in runtimeTrace.subagentHitl"
        :key="`${entry.worker_session_id}:${entry.reply_id}`"
      >
        <div class="agent-subagent-name">
          <span>{{ entry.worker_agent_name }}</span>
          <small>协同成员</small>
        </div>
        <details
          v-for="toolCall in entry.event.tool_calls || []"
          :key="toolCall.id"
          class="agent-tool"
          open
        >
          <summary>
            <span class="agent-tool-icon"><n-icon :size="15"><Tool /></n-icon></span>
            <span class="agent-tool-title">
              <strong>{{ toolLabel(toolCall.name) }}</strong>
              <small>{{ toolCall.name }}</small>
            </span>
            <em class="state-asking">等待确认</em>
            <n-icon class="agent-tool-chevron" :size="15"><ChevronRight /></n-icon>
          </summary>
          <div class="agent-tool-detail">
            <section v-if="toolCall.input">
              <span>调用参数</span>
              <pre>{{ formatJson(toolCall.input) }}</pre>
            </section>
          </div>
          <div class="agent-confirm">
            <div>
              <strong>需要人工确认</strong>
              <span>确认结果会安全转发给发起请求的协同智能体。</span>
            </div>
            <button type="button" class="deny" @click.prevent="$emit('confirm', entry.reply_id, toolCall, false)">拒绝</button>
            <button type="button" class="allow" @click.prevent="$emit('confirm', entry.reply_id, toolCall, true)">允许本次</button>
          </div>
        </details>
      </article>
    </section>

    <template v-if="runtimeTrace?.messages.length">
      <section
        v-for="runtimeMessage in runtimeTrace.messages"
        :key="runtimeMessage.id"
        class="agent-runtime-message"
      >
        <template v-for="block in runtimeMessage.content" :key="block.id">
          <div
            v-if="block.type === 'text' && block.text"
            class="agent-markdown"
            v-html="renderMarkdown(block.text)"
          ></div>

          <details v-else-if="block.type === 'thinking'" class="agent-thinking">
            <summary>
              <span><n-icon :size="14"><Bulb /></n-icon>思考过程</span>
              <em v-if="isMessageRunning(runtimeMessage)"><i></i>生成中</em>
              <em v-else>已完成</em>
            </summary>
            <div>{{ block.thinking || '正在推理…' }}</div>
          </details>

          <details
            v-else-if="block.type === 'tool_call'"
            class="agent-tool"
            :open="block.state === 'asking' || block.state === 'pending' || block.state === 'allowed'"
          >
            <summary>
              <span class="agent-tool-icon"><n-icon :size="15"><Tool /></n-icon></span>
              <span class="agent-tool-title">
                <strong>{{ toolLabel(block.name) }}</strong>
                <small>{{ block.name }}</small>
              </span>
              <em :class="`state-${toolState(block, runtimeMessage)}`">
                <i v-if="toolState(block, runtimeMessage) === 'running'" class="spin-dot"></i>
                {{ toolStateLabel(block, runtimeMessage) }}
              </em>
              <n-icon class="agent-tool-chevron" :size="15"><ChevronRight /></n-icon>
            </summary>
            <div class="agent-tool-detail">
              <section v-if="block.input">
                <span>调用参数</span>
                <pre>{{ formatJson(block.input) }}</pre>
              </section>
              <section v-if="toolResult(runtimeMessage, block.id)">
                <span>执行结果</span>
                <pre :class="{ error: toolResult(runtimeMessage, block.id)?.state === 'error' }">{{ formatToolResult(toolResult(runtimeMessage, block.id)) }}</pre>
              </section>
              <p v-else class="agent-tool-waiting">{{ block.state === 'asking' ? '该操作需要人工确认。' : '等待工具返回结果…' }}</p>
            </div>
            <div v-if="block.state === 'asking' && isMessageRunning(runtimeMessage)" class="agent-confirm">
              <div>
                <strong>需要人工确认</strong>
                <span>请核对工具和参数后决定是否继续。</span>
              </div>
              <button type="button" class="deny" @click.prevent="$emit('confirm', runtimeMessage.id, block, false)">拒绝</button>
              <button type="button" class="allow" @click.prevent="$emit('confirm', runtimeMessage.id, block, true)">允许本次</button>
            </div>
          </details>

          <details v-else-if="block.type === 'hint'" class="agent-hint">
            <summary>
              <n-icon :size="15"><Messages /></n-icon>
              <span>{{ hintLabel(block.source) }}</span>
              <n-icon class="agent-tool-chevron" :size="15"><ChevronRight /></n-icon>
            </summary>
            <div
              v-if="typeof block.hint === 'string'"
              class="agent-markdown"
              v-html="renderMarkdown(block.hint)"
            ></div>
            <div v-else class="agent-hint-blocks">
              <template v-for="item in block.hint" :key="item.id">
                <div v-if="item.type === 'text'" class="agent-markdown" v-html="renderMarkdown(item.text)"></div>
                <img v-else-if="dataUrl(item)" :src="dataUrl(item)!" :alt="item.name || '智能体返回图片'">
              </template>
            </div>
          </details>

          <figure v-else-if="block.type === 'data' && dataUrl(block)" class="agent-media">
            <img v-if="block.source.media_type.startsWith('image/')" :src="dataUrl(block)!" :alt="block.name || '智能体返回图片'">
            <a v-else :href="dataUrl(block)!" target="_blank" rel="noopener noreferrer">{{ block.name || '查看智能体返回文件' }}</a>
          </figure>
        </template>

        <div v-if="runtimeMessage.error" class="agent-runtime-error">
          <n-icon :size="16"><AlertTriangle /></n-icon>
          <div>
            <strong>执行失败</strong>
            <span>{{ runtimeMessage.error.message || runtimeMessage.error.type || '智能体运行时发生未知错误。' }}</span>
          </div>
        </div>

        <footer v-if="runtimeMessage.role === 'assistant'">
          <div class="agent-runtime-status">
            <span class="agent-runtime-state" :class="{ running: isMessageRunning(runtimeMessage) || isMessageWaiting(runtimeMessage), interrupted: isMessageInterrupted(runtimeMessage), error: Boolean(runtimeMessage.error) }">
              <n-icon :size="13">
                <Loader v-if="isMessageRunning(runtimeMessage) || isMessageWaiting(runtimeMessage)" class="spin" />
                <AlertTriangle v-else-if="runtimeMessage.error" />
                <Circle v-else-if="isMessageInterrupted(runtimeMessage)" />
                <CircleCheck v-else />
              </n-icon>
              {{ messageStatusLabel(runtimeMessage) }}
            </span>
            <span>{{ elapsedLabel(runtimeMessage) }}</span>
          </div>
          <div v-if="runtimeMessage.model_names?.length || runtimeTrace.modelNames.length || runtimeMessage.usage" class="agent-runtime-metrics">
            <span v-if="runtimeMessage.model_names?.length" class="agent-runtime-model" :title="runtimeMessage.model_names.join('、')">{{ runtimeMessage.model_names.join('、') }}</span>
            <span v-else-if="runtimeTrace.modelNames.length" class="agent-runtime-model" :title="runtimeTrace.modelNames.join('、')">{{ runtimeTrace.modelNames.join('、') }}</span>
            <span v-if="runtimeMessage.usage" class="agent-runtime-usage">
              ↑ {{ formatNumber(runtimeMessage.usage.input_tokens) }}
              · ↓ {{ formatNumber(runtimeMessage.usage.output_tokens) }}
            </span>
          </div>
        </footer>
      </section>
    </template>

    <div v-else class="agent-markdown" v-html="renderMarkdown(content)"></div>

    <div v-if="streaming && !runtimeTrace?.messages.length" class="agent-starting">
      <span><i></i><i></i><i></i></span>
      正在建立智能体执行上下文…
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { NIcon } from 'naive-ui'
import {
  AlertTriangle,
  Bulb,
  ChevronRight,
  Circle,
  CircleCheck,
  ListCheck,
  Loader,
  Messages,
  Tool,
  Users,
} from '@vicons/tabler'
import MarkdownIt from 'markdown-it'
import type {
  AgentDataBlock,
  AgentRuntimeMessage,
  AgentRuntimeTrace,
  AgentToolCallBlock,
  AgentToolResultBlock,
} from '@/types/agentRuntime'

const props = withDefaults(defineProps<{
  content?: string
  runtimeTrace?: AgentRuntimeTrace | null
  streaming?: boolean
  showPlan?: boolean
}>(), {
  content: '',
  runtimeTrace: null,
  streaming: false,
  showPlan: true,
})

defineEmits<{
  confirm: [replyId: string, toolCall: AgentToolCallBlock, confirmed: boolean]
}>()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: false,
})
const defaultLinkOpen = markdown.renderer.rules.link_open
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen
    ? defaultLinkOpen(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}
const markdownCache = new Map<string, string>()
const markdownCacheLimit = 256

const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  clock = setInterval(() => { now.value = Date.now() }, 1000)
})
onBeforeUnmount(() => {
  if (clock) clearInterval(clock)
})

const completedTasks = computed(() =>
  props.runtimeTrace?.tasksContext?.tasks.filter(task => task.state === 'completed').length || 0,
)
const taskProgress = computed(() => {
  const total = props.runtimeTrace?.tasksContext?.tasks.length || 0
  return total ? Math.round(completedTasks.value * 100 / total) : 0
})
const activeTraceStatuses = new Set([
  'creating',
  'running',
  'interrupting',
  'awaiting_permission',
  'awaiting_external_result',
])
const isTraceActive = computed(() =>
  activeTraceStatuses.has(props.runtimeTrace?.status || ''),
)

function renderMarkdown(value: string) {
  const source = value || ''
  const cached = markdownCache.get(source)
  if (cached !== undefined) return cached
  const rendered = markdown.render(source)
  if (markdownCache.size >= markdownCacheLimit) {
    const oldest = markdownCache.keys().next().value
    if (oldest !== undefined) markdownCache.delete(oldest)
  }
  markdownCache.set(source, rendered)
  return rendered
}

function toolResult(message: AgentRuntimeMessage, id: string) {
  return message.content.find(
    (block): block is AgentToolResultBlock => block.type === 'tool_result' && block.id === id,
  )
}

function toolState(call: AgentToolCallBlock, message: AgentRuntimeMessage) {
  const result = toolResult(message, call.id)
  if (call.state === 'asking') {
    if (isMessageRunning(message)) return 'asking'
    if (isMessageInterrupted(message)) return 'interrupted'
    return result?.state || 'finished'
  }
  if (!result || result.state === 'running') {
    if (isMessageRunning(message)) return 'running'
    if (isMessageInterrupted(message)) return 'interrupted'
    return 'finished'
  }
  return result.state
}

function toolStateLabel(call: AgentToolCallBlock, message: AgentRuntimeMessage) {
  const state = toolState(call, message)
  return ({
    asking: '等待确认',
    running: '执行中',
    success: '已完成',
    error: '失败',
    denied: '已拒绝',
    interrupted: '已中断',
    finished: '已结束',
  } as Record<string, string>)[state] || state
}

function toolLabel(name: string) {
  const labels: Record<string, string> = {
    AgentInvite: '邀请协同智能体',
    AgentCreate: '创建协同智能体',
    TeamCreate: '创建智能体团队',
    TeamSay: '发送团队消息',
    TeamDelete: '结束智能体团队',
    TaskCreate: '创建执行计划',
    TaskUpdate: '更新执行进度',
    TaskList: '读取执行计划',
    Bash: '执行命令',
    Read: '读取文件',
    Write: '写入文件',
    Edit: '修改文件',
    Grep: '检索内容',
    Glob: '查找文件',
  }
  if (labels[name]) return labels[name]
  if (/knowledge|retriev|search/i.test(name)) return '检索知识库'
  if (name.startsWith('mcp__')) return '调用 MCP 工具'
  return '调用工具'
}

function formatJson(value: string) {
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

function formatToolResult(result?: AgentToolResultBlock) {
  if (!result) return ''
  if (typeof result.output === 'string') return result.output
  return result.output
    .map(block => block.type === 'text' ? block.text : `[${block.source.media_type} 数据]`)
    .join('\n')
}

function hintLabel(source?: string | null) {
  if (!source) return '智能体消息'
  try {
    const parsed = JSON.parse(source)
    const labels: Record<string, string> = {
      team_message: '协同智能体反馈',
      schedule: '计划任务消息',
      tool_output: '后台工具结果',
    }
    const label = labels[parsed.label] || parsed.label || '智能体消息'
    return parsed.sublabel ? `${label} · ${parsed.sublabel}` : label
  } catch {
    return source
  }
}

function dataUrl(block: AgentDataBlock) {
  if (block.source.type === 'url') return block.source.url || null
  if (!block.source.data) return null
  return `data:${block.source.media_type};base64,${block.source.data}`
}

function isMessageRunning(message: AgentRuntimeMessage) {
  return !message.finished_at
    && !isMessageWaiting(message)
    && isTraceActive.value
}

function isMessageWaiting(message: AgentRuntimeMessage) {
  return message.finished_reason === 'waiting_for_collaboration'
}

function isMessageInterrupted(message: AgentRuntimeMessage) {
  return message.finished_reason === 'interrupted'
}

function messageStatusLabel(message: AgentRuntimeMessage) {
  if (isMessageWaiting(message)) return '等待协同'
  if (isMessageRunning(message)) return '执行中'
  if (message.error || message.finished_reason === 'error') return '执行失败'
  if (isMessageInterrupted(message)) return '已中断'
  if (message.finished_reason === 'exceed_max_iters') return '已达执行上限'
  if (message.finished_reason === 'collaboration_continued') return '协同已接续'
  return '已完成'
}

function isLatestRuntimeMessage(message: AgentRuntimeMessage) {
  const messages = props.runtimeTrace?.messages || []
  return messages[messages.length - 1]?.id === message.id
}

function elapsed(message: AgentRuntimeMessage) {
  const isLatest = isLatestRuntimeMessage(message)
  const startedAt = isLatest
    ? props.runtimeTrace?.turnStartedAt || message.created_at
    : message.created_at
  const finishedAt = isLatest
    ? props.runtimeTrace?.turnFinishedAt || message.finished_at
    : message.finished_at
  const start = Date.parse(startedAt)
  const end = finishedAt ? Date.parse(finishedAt) : now.value
  if (!Number.isFinite(start) || !Number.isFinite(end)) return ''
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function elapsedLabel(message: AgentRuntimeMessage) {
  const value = elapsed(message)
  if (!value) return ''
  return isLatestRuntimeMessage(message)
    ? `总耗时 ${value}`
    : value
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN', { notation: value > 9999 ? 'compact' : 'standard' }).format(value)
}
</script>

<style scoped>
.agent-message-content { display:grid; min-width:0; gap:10px; color:inherit; }
.agent-markdown { min-width:0; color:inherit; font-size:13px; line-height:1.72; overflow-wrap:anywhere; }
.agent-markdown :deep(p) { margin:0 0 .72em; white-space:normal; }
.agent-markdown :deep(p:last-child) { margin-bottom:0; }
.agent-markdown :deep(ul),.agent-markdown :deep(ol) { margin:.5em 0; padding-left:1.5em; }
.agent-markdown :deep(li) { margin:.2em 0; }
.agent-markdown :deep(h1),.agent-markdown :deep(h2),.agent-markdown :deep(h3) { margin:.9em 0 .45em; color:#183d38; line-height:1.35; }
.agent-markdown :deep(h1) { font-size:18px; }.agent-markdown :deep(h2) { font-size:16px; }.agent-markdown :deep(h3) { font-size:14px; }
.agent-markdown :deep(blockquote) { margin:.65em 0; border-left:3px solid #8abbb0; padding:.25em .8em; color:#607b76; background:#f5faf8; }
.agent-markdown :deep(code) { border-radius:4px; padding:2px 5px; color:#91501f; background:#f4eee8; font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; }
.agent-markdown :deep(pre) { max-width:100%; margin:.7em 0; overflow:auto; border:1px solid #dbe6e3; border-radius:7px; padding:11px 12px; background:#f7faf9; }
.agent-markdown :deep(pre code) { padding:0; color:#294944; background:transparent; }
.agent-markdown :deep(table) { display:block; width:100%; max-width:100%; overflow:auto; border-collapse:collapse; }
.agent-markdown :deep(th),.agent-markdown :deep(td) { border:1px solid #dbe5e2; padding:6px 9px; text-align:left; }
.agent-markdown :deep(a) { color:#0b766b; text-decoration:underline; text-underline-offset:2px; }
.agent-runtime-message { display:grid; gap:10px; min-width:0; }
.agent-runtime-message + .agent-runtime-message { margin-top:4px; border-top:1px dashed #d9e6e2; padding-top:12px; }
.agent-plan { display:grid; gap:8px; border:1px solid #d8e7e3; border-radius:8px; padding:11px 12px; background:#f6faf9; }
.agent-plan header { display:flex; align-items:center; justify-content:space-between; color:#315c56; font-size:12px; }
.agent-plan header span { display:flex; align-items:center; gap:6px; font-weight:800; }.agent-plan header strong { font-size:12px; }
.agent-plan-track { height:4px; overflow:hidden; border-radius:99px; background:#dce9e6; }.agent-plan-track i { display:block; height:100%; border-radius:inherit; background:#0e8b79; transition:width .2s; }
.agent-plan ul { display:grid; gap:5px; max-height:150px; margin:0; padding:0; overflow:auto; list-style:none; }
.agent-plan li { display:flex; align-items:flex-start; gap:7px; color:#647d78; font-size:12px; line-height:1.45; }.agent-plan li.completed { opacity:.65; }.agent-plan li.completed span { text-decoration:line-through; }
.agent-subagent-hitl { display:grid; gap:9px; border:1px solid #e6c77e; border-radius:9px; padding:10px; background:#fffaf0; }
.agent-subagent-hitl>header { display:flex; align-items:flex-start; gap:8px; color:#875c13; }.agent-subagent-hitl>header>div { display:grid; gap:2px; }.agent-subagent-hitl>header strong { font-size:12px; }.agent-subagent-hitl>header span { color:#967743; font-size:12px; line-height:1.45; }
.agent-subagent-hitl>article { display:grid; gap:6px; }.agent-subagent-name { display:flex; align-items:center; gap:7px; color:#654b20; }.agent-subagent-name span { font-size:12px; font-weight:800; }.agent-subagent-name small { border-radius:999px; padding:2px 6px; color:#886a35; background:#f8ebcf; font-size:12px; }
.agent-thinking,.agent-tool,.agent-hint { overflow:hidden; border:1px solid #dbe7e4; border-radius:8px; background:#f8fbfa; }
.agent-thinking summary,.agent-hint summary { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:9px 11px; color:#54706b; font-size:12px; cursor:pointer; list-style:none; }
.agent-thinking summary::-webkit-details-marker,.agent-tool summary::-webkit-details-marker,.agent-hint summary::-webkit-details-marker { display:none; }
.agent-thinking summary span,.agent-hint summary { font-weight:750; }.agent-thinking summary span { display:flex; align-items:center; gap:6px; }
.agent-thinking summary em { display:flex; align-items:center; gap:5px; color:#7c908c; font-size:12px; font-style:normal; font-weight:500; }
.agent-thinking summary em i { width:6px; height:6px; border-radius:50%; background:#17a680; box-shadow:0 0 0 3px rgba(23,166,128,.1); }
.agent-thinking>div { max-height:240px; overflow:auto; border-top:1px solid #e2ebe9; padding:10px 12px; color:#607672; font-size:12px; line-height:1.65; white-space:pre-wrap; }
.agent-tool>summary { display:grid; grid-template-columns:28px minmax(0,1fr) auto 16px; align-items:center; gap:8px; padding:9px 10px; cursor:pointer; list-style:none; }
.agent-tool-icon { display:grid; width:27px; height:27px; place-items:center; border-radius:6px; color:#176b61; background:#e5f3ef; }
.agent-tool-title { display:grid; min-width:0; gap:1px; }.agent-tool-title strong { color:#31534e; font-size:12px; }.agent-tool-title small { overflow:hidden; color:#849792; font:12px/1.25 ui-monospace,Consolas,monospace; text-overflow:ellipsis; white-space:nowrap; }
.agent-tool summary>em { display:flex; align-items:center; gap:5px; border-radius:999px; padding:3px 7px; color:#60746f; background:#edf3f1; font-size:12px; font-style:normal; white-space:nowrap; }
.agent-tool summary>em.state-asking { color:#9b5b00; background:#fff2d9; }.agent-tool summary>em.state-error,.agent-tool summary>em.state-denied { color:#ae472b; background:#fff0eb; }.agent-tool summary>em.state-success { color:#08735f; background:#e7f5f0; }
.spin-dot { width:6px; height:6px; border:1px solid #57958a; border-top-color:transparent; border-radius:50%; animation:spin .7s linear infinite; }
.agent-tool-chevron { color:#81938f; transition:transform .15s; }.agent-tool[open]>summary .agent-tool-chevron,.agent-hint[open]>summary .agent-tool-chevron { transform:rotate(90deg); }
.agent-tool-detail { display:grid; gap:9px; border-top:1px solid #e0eae7; padding:10px; background:#f2f7f5; }
.agent-tool-detail section { min-width:0; }.agent-tool-detail section>span { display:block; margin-bottom:5px; color:#687f7a; font-size:12px; font-weight:800; text-transform:uppercase; }
.agent-tool-detail pre { max-height:240px; margin:0; overflow:auto; border:1px solid #d9e4e1; border-radius:6px; padding:9px 10px; color:#34534e; background:#fff; font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; white-space:pre-wrap; overflow-wrap:anywhere; }
.agent-tool-detail pre.error { border-color:#efd4ca; color:#9e452d; background:#fff8f5; }.agent-tool-waiting { margin:0; color:#7c908b; font-size:12px; }
.agent-confirm { display:flex; align-items:center; gap:7px; border-top:1px solid #efdcb9; padding:10px; background:#fffaf0; }.agent-confirm>div { display:grid; flex:1; gap:2px; }.agent-confirm strong { color:#84520b; font-size:12px; }.agent-confirm span { color:#967549; font-size:12px; }
.agent-confirm button { border-radius:5px; padding:6px 9px; font:inherit; font-size:12px; font-weight:750; cursor:pointer; }.agent-confirm .deny { border:1px solid #d9cbb7; color:#725f45; background:#fff; }.agent-confirm .allow { border:1px solid #177b6d; color:#fff; background:#177b6d; }
.agent-hint summary { justify-content:flex-start; }.agent-hint summary span { flex:1; }.agent-hint>.agent-markdown,.agent-hint-blocks { border-top:1px solid #e1ebe8; padding:10px 12px; background:#fff; }.agent-hint-blocks { display:grid; gap:8px; }.agent-hint-blocks img { max-width:100%; max-height:300px; border-radius:6px; }
.agent-media { margin:0; }.agent-media img { max-width:100%; max-height:360px; border-radius:8px; object-fit:contain; }.agent-media a { color:#0d7469; font-size:12px; }
.agent-runtime-error { display:flex; align-items:flex-start; gap:8px; border:1px solid #efcfc5; border-radius:7px; padding:9px 10px; color:#a23f25; background:#fff5f1; }.agent-runtime-error>div { display:grid; gap:2px; }.agent-runtime-error strong { font-size:12px; }.agent-runtime-error span { font-size:12px; line-height:1.5; }
.agent-runtime-message footer { display:flex; min-width:0; align-items:center; gap:12px; color:#82928f; font-size:12px; }
.agent-runtime-message footer span { display:inline-flex; align-items:center; gap:4px; white-space:nowrap; }
.agent-runtime-status { display:flex; min-width:0; align-items:center; gap:8px; }
.agent-runtime-state { border-radius:999px; padding:3px 7px; color:#4e6e68; background:#edf3f1; }
.agent-runtime-state.running { color:#0b7768; background:#e6f5f1; }
.agent-runtime-state.interrupted { color:#8a5b19; background:#fff3dc; }
.agent-runtime-state.error { color:#a4472d; background:#fff0ea; }
.agent-runtime-metrics { display:flex; min-width:0; flex:0 1 auto; align-items:center; gap:10px; margin-left:auto; font-variant-numeric:tabular-nums; }
.agent-runtime-model { display:block !important; max-width:160px; overflow:hidden; text-overflow:ellipsis; }
.agent-runtime-usage { flex:0 0 auto; }
.agent-starting { display:flex; align-items:center; gap:8px; color:#6f8580; font-size:12px; }.agent-starting>span { display:flex; gap:3px; }.agent-starting i { width:5px; height:5px; border-radius:50%; background:#2f8e80; animation:pulse 1.1s ease-in-out infinite; }.agent-starting i:nth-child(2){animation-delay:.15s}.agent-starting i:nth-child(3){animation-delay:.3s}
.spin { animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@keyframes pulse { 0%,100%{opacity:.3;transform:translateY(0)}50%{opacity:1;transform:translateY(-2px)} }
</style>
