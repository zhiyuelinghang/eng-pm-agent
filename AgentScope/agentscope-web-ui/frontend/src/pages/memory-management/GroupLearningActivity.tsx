import { useCallback, useEffect, useRef, useState } from 'react';
import type { MemoryManagementUser, MemoryManagementProject } from '@/api/types';
import { client } from '@/api/client';
import { Button } from '@/components/ui/button';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface Channel { channel_id: number; title: string; project_id: string; cursor: number; observed_revision: number; paused: boolean; last_scan_at: string | null; last_result: { reason?: string } }
interface Batch { id: string; channel_id: number; from_revision: number; to_revision: number; state: string; attempts: number; created_at: string; error_code: string | null; result: { reason?: string; candidates?: { memory_id: string; status: string; scope_type?: string; platform_user_id?: string }[] }; snapshot: { title: string; project_id: string; full_project: boolean; messages: { id: string; text?: string; kind?: string; user_id?: string; deleted?: boolean; context_only?: boolean }[] } }
interface Dashboard { channels: Channel[]; batches: Batch[]; total: number }
const states: Record<string, string> = { pending: '等待处理', running: '正在整理', done: '已完成', skipped: '无须入库', failed: '处理失败', cancelled: '已取消' };
const outcomes: Record<string, string> = { active: '已自动生效', candidate: '系统处理中', duplicate: '重复，已跳过', suppressed: '保留已有人工决定', conflict: '版本冲突，保留原记录' };

const drawers: Record<string, string> = { user: '用户级', user_project: '用户＋项目级', project: '项目级' };
export function GroupLearningActivity({ revision, onMemory, users = [], projects = [] }: { users?: MemoryManagementUser[]; projects?: MemoryManagementProject[]; revision: number; onMemory: (scope: string, user: string, project: string, status: 'active' | 'candidate') => void }) {
	const [data, setData] = useState<Dashboard | null>(null);
	const [offset, setOffset] = useState(0);
	const [error, setError] = useState('');
	const sequence = useRef(0);
	const load = useCallback(async () => {
		const current = ++sequence.current;
		try { const result = await client.get<Dashboard>('/memory-management/group-learning', { offset: String(offset) }); if (current === sequence.current) { setData(result); setError(''); } }
		catch (err) { if (current === sequence.current) setError(formatApiErrorForAlert(err)); }
	}, [offset]);
	useEffect(() => { void load(); const timer = setInterval(() => void load(), 15000); return () => { sequence.current++; clearInterval(timer); }; }, [load, revision]);
	return <section className="rounded-xl border bg-background p-5 text-sm"><h2 className="font-semibold">群聊持续学习 <span className="ml-2 font-normal text-muted-foreground">{data?.total ?? 0} 批</span></h2>
		<p className="mt-3 text-xs leading-6 text-muted-foreground">自动检查新增和变更消息，无须 @ 或主动复盘，过程不向群里发送消息。有价值的事实和经验经系统校验后自动生效，无需人工确认。全体群可产生项目记忆，子群成果仅归有权查看来源的成员。</p>
		<p className="text-xs leading-6 text-muted-foreground">处理范围从本次功能启用后的消息变更开始；尚未处理的内容会保留。已完成和无价值批次不会重复排队。</p>
		<Button className="my-3" variant="outline" size="sm" onClick={() => void load()}>刷新群聊学习</Button>
		{error && <p role="alert" className="text-destructive">{error}</p>}
		<div className="space-y-2">{data?.channels.map((c) => <div key={c.channel_id} className="flex flex-wrap items-center justify-between gap-3 rounded border p-3"><div><strong>{c.title}</strong><p className="text-xs leading-6 text-muted-foreground">{projects.find((p) => p.project_id === c.project_id)?.project_name || '未命名项目'} · 待处理 {Math.max(0, c.observed_revision - c.cursor)} 项变更 · {c.paused ? '已暂停' : '自动学习中'} · 最近检查 {c.last_scan_at ? new Date(c.last_scan_at).toLocaleString() : '尚未检查'}</p>{c.last_result.reason && <p className="text-xs leading-6">{c.last_result.reason}</p>}</div></div>)}</div>
		{data?.batches.map((b) => <article key={b.id} className="mt-4 space-y-2 border-t pt-4"><div className="flex flex-wrap items-center justify-between gap-3"><strong>{b.snapshot.title} · {states[b.state] ?? b.state}</strong></div>
			<p className="text-xs text-muted-foreground">变更 {b.from_revision + 1}–{b.to_revision} · {b.snapshot.full_project ? '全体群' : '子群'} · 尝试 {b.attempts} 次 · {new Date(b.created_at).toLocaleString()}</p><p className="leading-6">{b.result.reason}</p>{b.error_code && <p role="status" className="text-amber-700">{b.error_code} · 进度尚未推进，重试会重新核对来源和权限。</p>}
			{b.result.candidates?.map((r, i) => <div key={`${r.memory_id}-${i}`} className="flex flex-wrap items-center gap-2 text-xs leading-6"><span className="break-all">{outcomes[r.status] ?? r.status} · {drawers[r.scope_type ?? ''] ?? '原抽屉'} {r.platform_user_id ? `· ${users.find((u) => u.user_id === r.platform_user_id)?.display_name || '未命名用户'}` : ''}</span>{r.scope_type && ['active','candidate'].includes(r.status) && <Button variant="outline" size="sm" onClick={() => onMemory(r.scope_type!, r.platform_user_id ?? '', r.scope_type === 'user' ? '' : b.snapshot.project_id, 'active')}>查看归属记忆</Button>}</div>)}
			<details><summary className="cursor-pointer text-xs">查看证据与发言者</summary><p className="mt-2 break-all text-xs text-muted-foreground">批次 {b.id} · 来源群 {b.channel_id}</p>{b.snapshot.messages.map((m) => <div key={m.id} className="my-2 rounded bg-muted p-3"><p className="text-xs text-muted-foreground">消息 {m.id} · {m.kind} {m.user_id} · {m.context_only ? '历史参考' : '本批变更'}</p><p className="mt-2 whitespace-pre-wrap break-words leading-6">{m.deleted ? '消息已撤回' : m.text}</p></div>)}</details>
		</article>)}
		{data?.total === 0 && <p className="py-5 text-muted-foreground">尚无群聊学习批次。满足消息量、空闲或最长等待条件后，后台自动处理。</p>}
		<div className="mt-4 flex justify-end gap-2"><Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</Button><Button size="sm" variant="outline" disabled={offset + 30 >= (data?.total ?? 0)} onClick={() => setOffset(offset + 30)}>下一页</Button></div>
	</section>;
}
