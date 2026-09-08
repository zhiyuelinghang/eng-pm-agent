import type { ToolPresentation } from '@/api/types';

export function ToolPresentationInfo({ value }: { value?: ToolPresentation | null }) {
  const sources: Record<string, string> = {
    registration: '工具注册名称', mcp_title: 'MCP 提供的展示标题',
    database_catalog: '数据库交互名称', fallback: '自动使用通用描述',
  };
  return <div className="rounded-md border bg-muted/20 p-3 text-sm leading-6">
    <p>用户聊天显示：{value?.label || '处理相关事项'}</p>
    <p className="text-xs text-muted-foreground">来源：{sources[value?.source || ''] || '旧记录暂无展示信息'}。函数名称和调用参数仅供管理与排查。</p>
  </div>;
}
