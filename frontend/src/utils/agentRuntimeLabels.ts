import type { AgentCollaborationActivity } from '@/types/agentRuntime'

export function agentToolLabel(name: string) {
  const labels: Record<string, string> = {
    AgentInvite: '邀请协同智能体',
    agent_search: '查找协同智能体',
    agent_invoke: '调用协同智能体',
    agent_run_status: '查看协同进度',
    agent_retry_or_switch: '重新安排协同任务',
    agent_cancel: '停止协同任务',
    memory_search: '检索记忆',
    memory_read: '读取记忆',
    memory_write: '保存记忆',
    add_memory: '保存记忆',
    search_memory: '检索记忆',
    forget_memory: '忘记指定记忆',
    learn_from_task: '记录复盘素材',
    learning_feedback: '记录经验反馈',
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
  const databaseLabels: Array<[RegExp, string]> = [
    [/dobby_get_project_basic_info_status/i, '读取项目基本信息'],
    [/dobby_update_document_classification/i, '修改资料分类'],
    [/dobby_create_risk/i, '新增风险记录'],
    [/get_project_initialization_state/i, '读取初始化状态'],
    [/list_project_initialization_attachment_chunks/i, '读取附件解析分块'],
    [/get_project_initialization_draft/i, '读取初始化草稿'],
    [/list_project_initialization_sections/i, '读取草稿分区'],
    [/create_project_initialization_draft/i, '创建初始化草稿'],
    [/finalize_project_initialization_draft/i, '核验初始化草稿'],
    [/create_initialization_project_section/i, '提交工程信息草稿'],
    [/update_initialization_project_section/i, '更新工程信息草稿'],
    [/create_initialization_personnel_section/i, '提交人员岗位草稿'],
    [/update_initialization_personnel_section/i, '更新人员岗位草稿'],
    [/create_initialization_wbs_section/i, '提交 WBS 进度草稿'],
    [/update_initialization_wbs_section/i, '更新 WBS 进度草稿'],
    [/create_initialization_risks_section/i, '提交风险源草稿'],
    [/update_initialization_risks_section/i, '更新风险源草稿'],
    [/create_initialization_quality_section/i, '提交质量指标草稿'],
    [/update_initialization_quality_section/i, '更新质量指标草稿'],
  ]
  const databaseLabel = databaseLabels.find(([pattern]) => pattern.test(name))
  if (databaseLabel) return databaseLabel[1]
  if (/memory.*search/i.test(name)) return '检索记忆'
  if (/knowledge|retriev|weknora/i.test(name)) return '检索知识库'
  // Unknown tools still need an identifiable name; do not label every action as a knowledge search.
  return name.split('__').filter(Boolean).pop() || '调用工具'
}

export function agentCollaborationActivityLabel(
  activity: AgentCollaborationActivity,
) {
  if (!activity.tool_name) return activity.label
  const action = agentToolLabel(activity.tool_name)
  if (activity.state === 'running') return `${action}执行中`
  if (activity.state === 'success') return `${action}已完成`
  if (activity.state === 'error') return `${action}失败`
  return action
}
