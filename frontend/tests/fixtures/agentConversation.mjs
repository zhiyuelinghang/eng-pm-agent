export const at = seconds => `2026-09-05T08:00:${String(seconds).padStart(2, '0')}.000Z`
export const textBlock = (text, id = text) => ({ type: 'text', id, text })
// Simulated server-provided snapshots; the production renderer has no name dictionary.
export const workPresentation = label => ({ label, source: 'registration', category: 'general' })
const fixtureTitles = { Read: '读取文件', dobby_get_project_basic_info_status: '读取项目基本信息',
  agent_invoke: '协同处理任务', weknora_search: '检索知识库', dobby_update_document_classification: '修改资料分类',
  dobby_list_project_personnel: '查看项目人员', dobby_list_project_tasks: '查看项目任务' }
export const toolCall = (id, name, input = {}, state = 'finished') => ({ type: 'tool_call', id, name,
  presentation: fixtureTitles[name] ? workPresentation(fixtureTitles[name]) : null, input: JSON.stringify(input), state })
export const toolResult = (id, name, metadata = {}, state = 'success') => ({ type: 'tool_result', id, name, state, metadata, output: '操作完成' })
export const message = (id, content, second = 0) => ({ id, name: 'Dobby', role: 'assistant', content, created_at: at(second), finished_at: at(second + 1) })
export const trace = (messages = [], overrides = {}) => ({
  messages, modelNames: ['示例模型'], tasksContext: null, teamUpdateCount: 0, collaborations: [], subagentHitl: [],
  stages: [], status: 'completed', turnStartedAt: at(0), turnFinishedAt: at(6), ...overrides,
})
export const activity = (name, state = 'success') => ({ kind: 'tool', label: '工具执行完成', state,
  tool_name: name, presentation: fixtureTitles[name] ? workPresentation(fixtureTitles[name]) : null, tool_call_id: name, reply_id: 'worker-reply', created_at: at(3) })
export const member = (overrides = {}) => ({
  team_id: 'team', team_name: '资料协同', worker_session_id: 'worker-session', worker_agent_id: 'documents',
  worker_agent_name: '资料助手', work_revision: 1, work_status: 'reported', assigned_at: at(1), started_at: at(2),
  settled_at: at(4), reply_id: 'worker-reply', current_activity: null, activities: [activity('weknora_search')],
  updated_at: at(4), ...overrides,
})
export const metadata = (overrides = {}) => ({ collaboration_member: {
  worker_session_id: 'worker-session', worker_agent_id: 'documents', worker_agent_name: '资料助手',
  work_revision: 1, assigned_at: at(1), ...overrides,
} })
export const runtimeHint = { type: 'hint', id: 'runtime-hint', source: JSON.stringify({ label: 'System', sublabel: 'Runtime State' }),
  hint: '内部上下文：项目白名单与会话同步' }
export const greetingTrace = () => trace([
  { ...message('system-message', [textBlock('只供模型读取的系统正文')]), role: 'system' },
  message('greeting', [runtimeHint, textBlock('你好！我是 Dobby，有什么可以帮你？')]),
], {
  tasksContext: { tasks: [{ id: 1, subject: '内部计划不可外露', state: 'completed' }] },
  stages: ['平台鉴权与项目边界', '上下文权限白名单', 'AgentScope 会话同步', '请求上下文装配'].map((label, index) => ({
    stage_id: String(index), label, status: 'completed', started_at: at(index), finished_at: at(index + 1), duration_ms: 1000,
  })),
})
export const collaborationTrace = () => trace([
  message('prepare', [
    runtimeHint, textBlock('我先核对项目资料。'), toolCall('read', 'dobby_get_project_basic_info_status'),
    toolResult('read', 'dobby_get_project_basic_info_status'), textBlock('接着请资料助手检查分类。'),
    toolCall('invoke', 'agent_invoke', { agent_id: 'documents', task: '检查施工方案与验收资料的分类' }),
    toolResult('invoke', 'agent_invoke', metadata()),
  ]),
  message('answer', [textBlock('已完成分类核对，施工方案和验收资料的分类均正确。')], 5),
], { collaborations: [member()] })
export const confirmationCall = () => ({
  ...toolCall('change-category', 'dobby_update_document_classification', { record_id: 17, category: '施工方案' }, 'asking'),
  confirmation_revision: 3,
  confirmation_preview: { operation: 'update', operation_label: '修改资料分类', target_name: '施工方案.pdf', record_id: 17,
    project_name: '示例工程', scope: '当前工程资料', impact: '仅修改这份资料的分类', affected_count: 1,
    changes: [{ field: 'category', before: '未分类', after: '施工方案' }] },
})
export const pendingEntry = () => ({ worker_session_id: 'worker-session', worker_agent_id: 'documents', worker_agent_name: '资料助手',
  reply_id: 'worker-reply', event_type: 'require_user_confirm', event: { tool_calls: [confirmationCall()] }, created_at: at(3) })
export const confirmationTrace = () => {
  const run = collaborationTrace()
  run.messages.pop()
  run.messages[0].finished_reason = 'waiting_for_collaboration'
  run.collaborations[0] = member({ work_status: 'running', settled_at: null })
  run.subagentHitl = [pendingEntry()]
  run.status = 'awaiting_permission'
  run.turnFinishedAt = null
  return run
}
export const persistedExtra = run => ({
  status: run.status, runtime_status: run.status, requester_user_id: 7, agentscope_messages: run.messages,
  runtime_trace: { model_names: run.modelNames, tasks_context: run.tasksContext, collaborations: run.collaborations,
    subagent_hitl: run.subagentHitl, stages: run.stages, turn_started_at: run.turnStartedAt, turn_finished_at: run.turnFinishedAt },
})
