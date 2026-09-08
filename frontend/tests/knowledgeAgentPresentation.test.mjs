import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { h } from 'vue'
import { renderToString } from '@vue/server-renderer'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { knowledgeAgentReferences, knowledgeAgentText } = await server.ssrLoadModule('/src/utils/knowledgeAgentPresentation.ts')
const { createEmptyRuntimeTrace } = await server.ssrLoadModule('/src/types/agentRuntime.ts')
const { default: Content } = await server.ssrLoadModule('/src/components/agent/AgentMessageContent.vue')

test('只从成功的资料工具输出收集引用，并按资料片段去重', () => {
  const reference = { knowledge_id: 'doc-a', chunk_id: 'chunk-a', title: '测试方案' }
  const block = { type: 'tool_result', id: 'query', state: 'success', metadata: { operation: 'weknora_query_project_knowledge' }, output: JSON.stringify({ references: [reference, reference] }) }
  const trace = { messages: [{ role: 'assistant', content: [
    block, { ...block, state: 'error', output: JSON.stringify({ references: [{ knowledge_id: 'denied' }] }) },
    { ...block, metadata: {}, output: JSON.stringify({ references: [{ knowledge_id: 'untrusted' }] }) },
    { type: 'text', text: '方案要求见引用。' }, { type: 'thinking', thinking: '不应成为最终回答' },
  ] }] }
  assert.deepEqual(knowledgeAgentReferences(trace), [reference])
  assert.equal(knowledgeAgentText(trace), '方案要求见引用。')
})

test('资料助手等待状态不冒充知识库已查询，不显示总控身份', async () => {
  const html = await renderToString(h(Content, { runtimeTrace: createEmptyRuntimeTrace(), streaming: true,
    assistantName: '资料助手', startingLabel: '资料助手已接收，正在理解问题…' }))
  assert.match(html, /资料助手已接收，正在理解问题/)
  assert.doesNotMatch(html, /Dobby|正在查阅知识库/)
})

test('支持页面引用渲染器，保留正文与思考展示', async () => {
  const trace = { ...createEmptyRuntimeTrace('finished'), messages: [{ id: 'answer', role: 'assistant', content: [
    { type: 'thinking', id: 'thought', thinking: '正在核对已授权资料。', state: 'finished' },
    { type: 'text', id: 'text', text: '查看资料依据' },
  ] }] }
  const html = await renderToString(h(Content, { runtimeTrace: trace, markdownRenderer: value => '<p class="citation-rendered">' + value + '</p>' }))
  assert.match(html, /思考过程/)
  assert.match(html, /citation-rendered/)
  assert.match(html, /查看资料依据/)
})
