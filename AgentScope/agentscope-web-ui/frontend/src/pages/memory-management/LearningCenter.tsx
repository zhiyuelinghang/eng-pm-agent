import { useCallback, useEffect, useRef, useState } from 'react';
import { memoryManagementApi } from '@/api/memory-management';
import type { MemoryManagementUser, MemoryManagementProject, LearningDashboard, LearningEvent, ManagedMemoryItem } from '@/api/types';
import { Button } from '@/components/ui/button';
import { formatApiErrorForAlert } from '@/lib/api-error';

export const memoryKinds: Record<string, string> = { fact: '事实', preference: '偏好', decision: '决定', reference: '参考', reflection: '反思', experience: '经验', skill: '操作技能' };
export const learned = (item: ManagedMemoryItem) => ['reflection', 'experience', 'skill'].includes(item.memory_type);
const states: Record<string, string> = { recorded: '仅记录素材', pending: '等待处理', running: '正在提炼', done: '已提炼', skipped: '无须提炼', failed: '处理失败', cancelled: '已取消' };
const triggers: Record<string, string> = { group_chat: '群聊自动学习成果', explicit: '明确复盘', correction: '用户纠正', tool_failure: '工具失败', recovery: '失败后修复', verified_task: '任务完成（附工具结果）', repeated_pattern: '重复操作模式', feedback: '结果反馈', consolidate: '经验合并', skill_compile: '生成操作技能' };
const validation: Record<string, string> = { unverified: '系统处理中', verified: '已通过系统校验', source_changed: '来源已改变 · 停止召回', review_due: '系统复查中 · 暂停召回', contradicted: '发现反例 · 已自动停用', auto_rejected: '校验未通过 · 已自动停用', rejected: '已拒绝', suspended: '已停用' };
export const validationLabel = (item: ManagedMemoryItem) => validation[item.learning?.validation_state ?? 'unverified'] ?? '系统处理中';

export function LearningActivity({ revision, onCandidates, users = [], projects = [] }: { users?: MemoryManagementUser[]; projects?: MemoryManagementProject[]; revision: number; onCandidates: (event: LearningEvent) => void }) {
	const [data, setData] = useState<LearningDashboard | null>(null);
	const [offset, setOffset] = useState(0);
	const [state, setState] = useState('');
	const [error, setError] = useState('');
	const requestSequence = useRef(0);
	const load = useCallback(async () => {
		const sequence = ++requestSequence.current;
		try { const result = await memoryManagementApi.learning(offset, state); if (sequence === requestSequence.current) { setData(result); setError(''); } }
		catch (err) { if (sequence === requestSequence.current) setError(formatApiErrorForAlert(err)); }
	}, [offset, state]);
	useEffect(() => { void load(); return () => { requestSequence.current++; }; }, [load, revision]);
	const pending = data?.events.some((e) => e.state === 'pending' || e.state === 'running');
	useEffect(() => { if (!pending) return; const timer = setInterval(() => void load(), 5000); return () => clearInterval(timer); }, [pending, load]);
	return <section className="rounded-xl border bg-background p-5 text-sm"><h2 className="font-semibold">全部学习任务 <span className="ml-2 font-normal text-muted-foreground">{data?.total ?? 0} 项</span></h2>
		<p className="mt-3 text-xs leading-6 text-muted-foreground">素材记录、后台提炼和成果生效分别管理。单独报错只记录；有价值且校验通过的成果自动生效，无需人工确认。关闭学习不会影响明确记忆保存。</p>
		<div className="my-3 flex flex-wrap items-center gap-3"><select aria-label="学习任务状态" className="h-9 rounded border bg-background px-3 text-sm" value={state} onChange={(e) => { setState(e.target.value); setOffset(0); }}><option value="">全部状态</option>{Object.entries(states).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
			<Button variant="outline" size="sm" onClick={() => void load()}>刷新学习记录</Button>
			{data?.counts.map((c) => <span key={c.state} className="text-xs text-muted-foreground">{states[c.state]} {c.count}</span>)}</div>
		{error && <p role="alert" className="text-destructive">{error}</p>}
		{data?.events.map((event) => <article key={event.id} className="space-y-3 border-t py-4">
			<div className="flex flex-wrap justify-between gap-3"><div><strong>{triggers[event.event_type] ?? event.event_type}</strong><span className="ml-3 text-xs">{states[event.state ?? 'recorded']}</span><p className="mt-1 break-all text-xs text-muted-foreground">{({ user: '用户级', user_project: '用户＋项目级', project: '项目级' })[event.scope_type]} · {event.platform_user_id ? users.find((u) => u.user_id === event.platform_user_id)?.display_name || '未命名用户' : '项目共享'}{event.project_id ? ` · ${projects.find((p) => p.project_id === event.project_id)?.project_name || '未命名项目'}` : ''} · {new Date(event.created_at).toLocaleString()}</p></div>
				<div className="flex flex-wrap gap-2">{!!event.result?.candidates?.length && <Button size="sm" variant="outline" onClick={() => onCandidates(event)}>查看归属记忆</Button>}</div></div>
			{event.result?.reason && <p className="text-sm leading-6">{event.result.reason}</p>}{event.error_code && <p role="status" className="text-sm text-amber-700">{event.error_code} · 尝试 {event.attempts} 次</p>}
			<details><summary className="cursor-pointer text-xs">查看原始证据与来源</summary><p className="my-2 break-all text-xs text-muted-foreground">智能体 {event.agent_id} · 会话 {event.session_id}</p>{event.evidence.map((e) => <div key={e.id} className="my-2 rounded bg-muted p-3"><p className="break-all text-xs text-muted-foreground">{e.kind} · {e.outcome || '用户材料'} · {e.id}</p><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{e.text}</p></div>)}</details>
		</article>)}
		{data?.total === 0 && <p className="py-6 text-muted-foreground">暂无学习事件。可以在对话中要求复盘，或在发生纠正和任务结果时自动记录。</p>}
		<div className="flex justify-end gap-2"><Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</Button><Button size="sm" variant="outline" disabled={offset + 30 >= (data?.total ?? 0)} onClick={() => setOffset(offset + 30)}>下一页</Button></div>
	</section>;
}
