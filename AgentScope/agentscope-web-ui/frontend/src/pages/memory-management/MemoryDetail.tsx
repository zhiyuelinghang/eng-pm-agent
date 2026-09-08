import { useEffect, useState } from 'react';
import { ArrowLeft, History, Trash2, X } from 'lucide-react';
import type { ManagedMemoryItem, MemoryVersion } from '@/api/types';
import { memoryManagementApi } from '@/api/memory-management';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { formatApiErrorForAlert } from '@/lib/api-error';
import { cn } from '@/lib/utils';
import { learned, memoryKinds, validationLabel } from './LearningCenter';

const fields: Record<string, string> = { 'profile.name': '姓名', 'profile.address': '称呼偏好', 'preference.response_detail': '回答偏好' };
export const memoryTitle = (item: ManagedMemoryItem) => item.learning?.title || fields[item.fact_key ?? ''] || item.content.split('\n').find((line) => line.trim())?.slice(0, 70) || '未命名记忆';
export const memoryState = (item: ManagedMemoryItem) => item.status === 'deleted' ? '已删除' : item.status === 'inactive' ? '已停用' : item.status === 'candidate' ? '系统处理中' : learned(item) && item.learning?.validation_state !== 'verified' ? '系统复查中 · 暂停使用' : '正在使用';
const date = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '—';

interface Props {
	item: ManagedMemoryItem; owner: string; project: string; onClose: () => void;
	onChanged: () => Promise<void>; onBusy: (value: boolean) => void;
}

export function MemoryDetail({ item, owner, project, onClose, onChanged, onBusy }: Props) {
	const [tab, setTab] = useState<'content' | 'history'>('content');
	const [history, setHistory] = useState<MemoryVersion[] | null>(null);
	const [error, setError] = useState('');
	const [loadingHistory, setLoadingHistory] = useState(false);
	const [historyRevision, setHistoryRevision] = useState(0);
	const [busy, setBusy] = useState(false);
	const [deleting, setDeleting] = useState(false);
	useEffect(() => {
		if (tab !== 'history') return;
		let active = true;
		setLoadingHistory(true); setError('');
		memoryManagementApi.history(item.id).then((rows) => { if (active) setHistory(rows); })
			.catch((err) => { if (active) setError(formatApiErrorForAlert(err)); }).finally(() => { if (active) setLoadingHistory(false); });
		return () => { active = false; };
	}, [tab, item.id, item.version, historyRevision]);
	const run = async (fn: () => Promise<unknown>) => {
		setBusy(true); onBusy(true); setError('');

		try { await fn();  setDeleting(false); await onChanged(); }
		catch (err) { setError(formatApiErrorForAlert(err)); }
		finally { setBusy(false); onBusy(false); }
	};
	const visibility = item.scope_type === 'project' ? '有权限的项目成员可以使用' : item.scope_type === 'user_project' ? '仅该用户在此项目中使用' : '仅该用户使用，可跨项目';
	return <aside aria-label="记忆详情" className="flex h-full min-h-0 flex-col bg-background">
		<header className="flex items-center justify-between gap-3 border-b px-5 py-4"><span className="text-sm font-medium">记忆详情</span><Button size="sm" variant="ghost" disabled={busy} onClick={onClose} aria-label="关闭详情返回列表"><ArrowLeft className="size-4 lg:hidden" /><X className="hidden size-4 lg:block" /><span className="lg:hidden">返回列表</span></Button></header>
		<div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
			<div className="mb-3 flex flex-wrap items-center gap-2 text-xs"><span className="rounded bg-muted px-2 py-1">{memoryKinds[item.memory_type] ?? item.memory_type}</span><span className={cn('flex items-center gap-1.5', memoryState(item) === '正在使用' ? 'text-emerald-700 dark:text-emerald-400' : 'text-muted-foreground')}><span className="size-1.5 rounded-full bg-current" />{memoryState(item)}</span></div>
			<h2 className="break-words text-lg leading-7 font-semibold">{memoryTitle(item)}</h2>
			<p className="mt-2 text-sm text-muted-foreground">{owner}{project && ` · ${project}`}</p>
			<p className="mt-1 text-xs leading-6 text-muted-foreground">{visibility}{item.source.kind === 'group_learning' ? '，并保留来源群的访问限制' : ''}。</p>
			<div className="mt-5 flex gap-5 border-b"><button type="button" aria-pressed={tab === 'content'} disabled={busy} onClick={() => setTab('content')} className={cn('border-b-2 py-2.5 text-sm focus-visible:outline-2', tab === 'content' ? 'border-primary font-medium' : 'border-transparent text-muted-foreground')}>内容与依据</button><button type="button" aria-pressed={tab === 'history'} disabled={busy} onClick={() => setTab('history')} className={cn('flex items-center gap-1.5 border-b-2 py-2.5 text-sm focus-visible:outline-2', tab === 'history' ? 'border-primary font-medium' : 'border-transparent text-muted-foreground')}><History className="size-3.5" />历史版本</button></div>
			{error && <div role="alert" className="mt-4 rounded border border-destructive/30 p-3 text-sm text-destructive">{error}{tab === 'history' && <Button size="sm" variant="outline" className="mt-2" onClick={() => setHistoryRevision((n) => n + 1)}>重新读取历史</Button>}</div>}
			{tab === 'content' ? <div className="space-y-6 py-5">
				<p className="whitespace-pre-wrap break-words text-sm leading-7">{item.content}</p>
				{learned(item) && <section className="space-y-4 border-t pt-5"><div><h3 className="text-sm font-medium">适用条件</h3><p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{item.learning?.conditions || '尚未补充'}</p></div><div><h3 className="text-sm font-medium">限制与反例</h3><p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{item.learning?.limitations || '尚未补充'}</p></div>{!!item.learning?.steps?.length && <ol className="list-decimal space-y-2 pl-5 text-sm leading-6">{item.learning.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>}<p className="text-xs text-muted-foreground">{validationLabel(item)}</p></section>}
				<section className="border-t pt-5"><h3 className="text-sm font-medium">来源与依据</h3><p className="mt-2 text-sm text-muted-foreground">{item.source.kind === 'group_learning' ? '群聊自动整理' : item.origin === 'learning' ? '从对话或任务中提炼' : '明确保存的记忆'}</p>{item.learning?.reason && <p className="mt-2 text-sm leading-6">{item.learning.reason}</p>}{item.learning?.review_note && <p className="mt-2 text-sm leading-6">最近校验：{item.learning.review_note}</p>}
					{!!item.learning?.evidence?.length && <details className="mt-3 rounded-lg bg-muted/40 p-3"><summary className="cursor-pointer text-sm">查看原始证据 · {item.learning.evidence.length} 条</summary>{item.learning.evidence.map((e) => <p key={e.id} className="mt-3 whitespace-pre-wrap break-words border-t pt-3 text-sm leading-6">{e.text}</p>)}</details>}
				</section>
				<details className="border-t pt-4 text-xs text-muted-foreground"><summary className="cursor-pointer">记录信息</summary><div className="mt-3 space-y-2 break-all"><div>版本：{item.version}</div><div>更新于：{date(item.updated_at)}</div><div>记录编号：{item.id}</div><div>索引：{({ ready: '已就绪', pending: '等待建立', failed: '暂时失败，后台自动重试', deleted: '已删除' })[item.index_status]}</div></div><pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-all text-xs leading-5">{JSON.stringify(item.source, null, 2)}</pre></details>
			</div> : <div className="space-y-5 py-5">{loadingHistory ? <p className="text-sm text-muted-foreground">正在读取历史版本…</p> : history?.map((v) => <section key={v.version} className="border-l-2 border-muted pl-4"><p className="text-xs text-muted-foreground">版本 {v.version} · {date(v.created_at)}</p><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7">{v.snapshot.content}</p><details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">来源及操作信息</summary><p className="mt-2">{v.action} · {v.actor_id}</p><pre className="mt-2 whitespace-pre-wrap break-all text-xs">{JSON.stringify(v.snapshot.source, null, 2)}</pre></details></section>)}</div>}
		</div>
		{item.status !== 'deleted' && <footer className="flex items-center justify-between gap-3 border-t bg-background px-5 py-4"><span className="text-xs text-muted-foreground">系统自动维护，无需人工审核</span><Button variant="ghost" className="text-muted-foreground hover:text-destructive" disabled={busy} onClick={() => setDeleting(true)}><Trash2 className="size-3.5" />删除</Button></footer>}
		<Dialog open={deleting} onOpenChange={(open) => { if (!busy) setDeleting(open); }}><DialogContent><DialogHeader><DialogTitle>删除这条记忆？</DialogTitle><DialogDescription>删除后停止使用，历史版本保留供审计。</DialogDescription></DialogHeader><p className="text-sm leading-6">{memoryTitle(item)}</p><DialogFooter><Button variant="outline" disabled={busy} onClick={() => setDeleting(false)}>取消</Button><Button variant="destructive" disabled={busy} onClick={() => void run(() => memoryManagementApi.delete(item.id, item.version))}>确认删除</Button></DialogFooter></DialogContent></Dialog>
	</aside>;
}
