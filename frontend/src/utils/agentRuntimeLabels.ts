import type { AgentCollaborationActivity } from '@/types/agentRuntime'

export function agentToolLabel(name: string) {
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
  const databaseLabels: Array<[RegExp, string]> = [
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
  if (/knowledge|retriev|search/i.test(name)) return '检索知识库'
  if (name.startsWith('mcp__')) return '调用 MCP 工具'
  return '调用工具'
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
