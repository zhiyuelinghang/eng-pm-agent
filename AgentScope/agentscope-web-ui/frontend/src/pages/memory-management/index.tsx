import { BookUser, FolderKanban, UserRound, RefreshCw, Sparkles, Activity, Search } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { GroupLearningActivity } from './GroupLearningActivity';
import { memoryKinds, LearningActivity } from './LearningCenter';
import { MemoryDetail, memoryTitle, memoryState } from './MemoryDetail';
import { MemoryDiagnostics } from './MemoryDiagnostics';
import { memoryManagementApi } from '@/api/memory-management';
import type { ManagedMemoryItem, MemoryManagementResponse, MemoryScopeType, MemoryIndexJob } from '@/api/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';
import { cn } from '@/lib/utils';

const SELECT = 'h-9 rounded-md border bg-background px-3 text-sm';
const PAGE_SIZE = 30;

export function MemoryManagementPage() {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const text = (cnText: string, en: string) => zh ? cnText : en;
	const scopes: { id: MemoryScopeType; title: string; help: string; icon: typeof UserRound }[] = [
		{ id: 'user', title: text('用户级', 'User'), help: text('跨项目的个人资料与稳定偏好', 'Personal facts and preferences across projects'), icon: UserRound },
		{ id: 'user_project', title: text('用户＋项目级', 'User + project'), help: text('仅属于该用户在这个项目的私人上下文', 'Private context for one person in one project'), icon: BookUser },
		{ id: 'project', title: text('项目级', 'Project'), help: text('向有权限的项目成员共享的事实与决定', 'Facts and decisions shared with authorized members'), icon: FolderKanban },
	];
	const [section, setSection] = useState<'library' | 'learning' | 'diagnostics'>('library');
	const [learningTab, setLearningTab] = useState<'group' | 'conversation'>('group');
	const [detailId, setDetailId] = useState<string | null>(null);
	const [detailBusy, setDetailBusy] = useState(false);
	const [scope, setScope] = useState<MemoryScopeType>('user');
	const [user, setUser] = useState('');
	const [project, setProject] = useState('');
	const [status, setStatus] = useState<'active' | 'candidate' | 'inactive' | 'deleted'>('active');
	const [memoryType, setMemoryType] = useState('');
	const [learningRevision, setLearningRevision] = useState(0);
	const [query, setQuery] = useState('');
	const [search, setSearch] = useState('');
	const [offset, setOffset] = useState(0);
	const [data, setData] = useState<MemoryManagementResponse | null>(null);
	const [jobs, setJobs] = useState<MemoryIndexJob[] | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState('');
	const sequence = useRef(0);
	const load = useCallback(async () => {
		const ticket = ++sequence.current;
		setLoading(true); setError('');
		try {
			if (section === 'diagnostics') {
				const tasks = await memoryManagementApi.jobs();
				if (ticket === sequence.current) setJobs(tasks);
			} else if (section !== 'learning') {
				const page = await memoryManagementApi.list({ scopeType: scope, platformUserId: scope === 'project' ? undefined : user,
					projectId: scope === 'user' ? undefined : project, query, status: status === 'candidate' ? 'active' : status, offset, limit: PAGE_SIZE, memoryType });
				if (ticket === sequence.current) { setData(page); }
			}
		} catch (err) { if (ticket === sequence.current) setError(formatApiErrorForAlert(err)); }
		finally { if (ticket === sequence.current) setLoading(false); }
	}, [section, scope, user, project, query, status, offset, memoryType]);
	useEffect(() => { void load(); return () => { sequence.current++; }; }, [load]);
	useEffect(() => { setDetailId(null); }, [section, scope, user, project, query, status, memoryType, offset]);
	const currentItem = data?.memories.find((item) => item.id === detailId) ?? null;
	const ownerName = (item: ManagedMemoryItem) => item.identity_type === 'management_user' ? '管理端测试身份' : item.scope_type === 'project' ? '项目共享' : data?.users.find((u) => u.user_id === item.platform_user_id)?.display_name || '未命名用户';
	const projectName = (item: ManagedMemoryItem) => data?.projects.find((p) => p.project_id === item.project_id)?.project_name || (item.project_id ? '未命名项目' : '');
	const browse = section === 'library';
	const locked = detailBusy;
	const navigateMemory = (nextScope: string, nextUser: string, nextProject: string, nextStatus: 'active' | 'candidate') => {
		setSection('library'); setScope(nextScope as MemoryScopeType); setUser(nextUser); setProject(nextProject); setStatus(nextStatus === 'candidate' ? 'active' : nextStatus); setMemoryType(''); setQuery(''); setSearch(''); setOffset(0); setDetailId(null);
	};
	const sections = [
		{ id: 'library', title: '记忆库', icon: BookUser, help: '记忆由系统自动整理和更新，你可以查看来源或删除不需要的内容。' },
		{ id: 'learning', title: '学习记录', icon: Sparkles, help: '查看后台整理进度、产出和未入库原因。' },
		{ id: 'diagnostics', title: '运行诊断', icon: Activity, help: '查看索引状态与自动重试情况。' },
	] as const;
	return <div className="flex h-full min-h-0 flex-col bg-muted/20 text-sm">
		<header className="shrink-0 border-b bg-background px-4 pt-5 sm:px-6">
			<div className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-xl font-semibold tracking-tight">记忆管理</h1><p className="mt-1.5 text-sm text-muted-foreground">{sections.find((s) => s.id === section)?.help}</p></div>
				<Button variant="outline" disabled={loading || locked} onClick={() => { if (section === 'learning') setLearningRevision((n) => n + 1); else void load(); }}><RefreshCw className={cn('size-4', loading && 'animate-spin')} />刷新</Button></div>
			<nav aria-label="记忆管理功能" className="mt-5 flex gap-4 overflow-x-auto sm:gap-7">{sections.map(({ id, title, icon: Icon }) => <button key={id} type="button" disabled={locked} aria-current={section === id ? 'page' : undefined} onClick={() => { setSection(id); setDetailId(null); setOffset(0); }} className={cn('flex shrink-0 items-center gap-2 border-b-2 pb-3 text-sm transition-colors focus-visible:outline-2 disabled:opacity-50', section === id ? 'border-primary font-semibold text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground')}><Icon className="hidden size-4 sm:block" />{title}</button>)}</nav>
		</header>
		{browse ? <div className="flex min-h-0 flex-1 flex-col">
			<div className={cn('shrink-0 space-y-3 border-b bg-background px-4 py-4 sm:px-6', currentItem && 'hidden lg:block')}>
				<div className="flex flex-wrap items-center gap-x-5 gap-y-2"><div className="inline-flex max-w-full gap-1 overflow-x-auto rounded-lg bg-muted p-1" aria-label="记忆抽屉">{scopes.map(({ id, title, icon: Icon }) => <button key={id} type="button" disabled={locked} aria-pressed={scope === id} onClick={() => { setScope(id); setOffset(0); }} className={cn('flex shrink-0 items-center gap-1.5 rounded-md px-3 py-2 text-sm focus-visible:outline-2 disabled:opacity-50', scope === id ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground')}><Icon className="hidden size-4 sm:block" />{title}</button>)}</div><p className="text-xs leading-5 text-muted-foreground">{scopes.find((s) => s.id === scope)?.help}</p></div>
				<form onSubmit={(event) => { event.preventDefault(); setQuery(search.trim()); setOffset(0); }}><fieldset disabled={locked} className="flex min-w-0 flex-wrap gap-2 disabled:opacity-60">
					{scope !== 'project' && <select aria-label="用户" className={`${SELECT} max-w-full`} value={user} onChange={(e) => { setUser(e.target.value); setOffset(0); }}><option value="">所有用户</option>{data?.users.map((u) => <option key={u.user_id} value={u.user_id}>{u.display_name}{data.users.filter((other) => other.display_name === u.display_name).length > 1 ? `（${u.username || u.user_id}）` : ''}</option>)}</select>}
					{scope !== 'user' && <select aria-label="项目" className={`${SELECT} max-w-full`} value={project} onChange={(e) => { setProject(e.target.value); setOffset(0); }}><option value="">所有项目</option>{data?.projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.project_name}</option>)}</select>}
					{section === 'library' && <select aria-label="状态" className={SELECT} value={status === 'candidate' ? 'active' : status} onChange={(e) => { setStatus(e.target.value as typeof status); setOffset(0); }}><option value="active">有效记忆</option><option value="inactive">已停用／拒绝</option><option value="deleted">已删除</option></select>}
					<select aria-label="记忆类型" className={SELECT} value={memoryType} onChange={(e) => { setMemoryType(e.target.value); setOffset(0); }}><option value="">全部类型</option>{Object.entries(memoryKinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
					<div className="flex min-w-48 flex-1 gap-2"><Input className="min-w-0" aria-label="搜索记忆正文" placeholder="搜索记忆内容…" value={search} onChange={(e) => setSearch(e.target.value)} /><Button variant="outline" type="submit"><Search className="size-4" /><span>搜索</span></Button></div>
				</fieldset></form>
				{data?.catalog_warning && <p role="status" className="text-xs leading-5 text-amber-700">{data.catalog_warning}</p>}
			</div>
			{error && <div role="alert" className="shrink-0 border-b border-destructive/30 bg-background px-6 py-3 text-destructive">{error}<Button variant="ghost" size="sm" disabled={locked || loading} onClick={() => void load()}>重新读取</Button></div>}
			<div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(300px,0.9fr)_minmax(0,1.1fr)]">
				<section aria-label="记忆列表" aria-busy={loading} className={cn('flex min-h-0 min-w-0 flex-col bg-background lg:border-r', currentItem && 'hidden lg:flex')}>
					<div className="flex shrink-0 items-center justify-between border-b px-5 py-3"><span className="font-medium">记忆列表</span><span role="status" className="text-xs text-muted-foreground">{loading ? '正在读取…' : error ? '读取失败' : `${data?.total ?? 0} 条`}</span></div>
					<div className="min-h-0 flex-1 overflow-y-auto">
						{loading && !data ? <div className="space-y-4 p-5" aria-label="正在读取记忆">{[1, 2, 3].map((n) => <div key={n} className="h-24 animate-pulse rounded bg-muted" />)}</div> : !error && !data?.memories.length ? <div className="px-6 py-16 text-center"><BookUser className="mx-auto mb-4 size-8 text-muted-foreground/60" /><h2 className="font-medium">{query || user || project || memoryType ? '没有匹配的记忆' : '这个抽屉还没有记忆'}</h2><p className="mt-2 text-xs leading-6 text-muted-foreground">{query || user || project || memoryType ? '试试其他关键词，或清除筛选条件。' : '对话中保存或后台整理的内容会出现在这里。'}</p>{(query || user || project || memoryType) && <Button variant="outline" size="sm" className="mt-4" onClick={() => { setUser(''); setProject(''); setMemoryType(''); setSearch(''); setQuery(''); setOffset(0); }}>清除筛选</Button>}</div> : !error && data?.memories.map((item) => <article key={item.id} className={cn('relative flex border-b transition-colors hover:bg-muted/40', detailId === item.id && 'bg-primary/5 shadow-[inset_3px_0_0_var(--primary)]')}>
							<button type="button" disabled={locked || loading} aria-pressed={detailId === item.id} aria-label={`查看记忆：${memoryTitle(item)}`} onClick={() => setDetailId(item.id)} className="min-w-0 flex-1 px-5 py-4 text-left focus-visible:z-10 focus-visible:outline-2 disabled:opacity-60">
								<div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span className="rounded bg-muted px-1.5 py-0.5">{memoryKinds[item.memory_type] || item.memory_type}</span><span>{ownerName(item)}{projectName(item) && ` · ${projectName(item)}`}</span></div>
								<h3 className="line-clamp-1 break-all text-sm font-semibold leading-6">{memoryTitle(item)}</h3><p className="mt-1 line-clamp-2 whitespace-pre-line break-all text-sm leading-6 text-muted-foreground">{item.content}</p>
								<div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground"><span className={cn('flex items-center gap-1.5', memoryState(item) === '正在使用' && 'text-emerald-700 dark:text-emerald-400')}><span className="size-1.5 rounded-full bg-current" />{memoryState(item)}</span><time>{item.updated_at ? new Date(item.updated_at).toLocaleDateString('zh-CN') : '—'}</time></div>
							</button>
						</article>)}
					</div>
					<div className="flex shrink-0 items-center justify-between gap-2 border-t px-4 py-3 text-xs text-muted-foreground"><span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={offset === 0 || loading || locked} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</Button><Button size="sm" variant="outline" disabled={loading || locked || offset + PAGE_SIZE >= (data?.total ?? 0)} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</Button></div></div>
				</section>
				<div className={cn('min-h-0 min-w-0', !currentItem && 'hidden lg:block')}>{currentItem ? <MemoryDetail key={`${currentItem.id}:${currentItem.version}`} item={currentItem} owner={ownerName(currentItem)} project={projectName(currentItem)} onClose={() => setDetailId(null)} onBusy={setDetailBusy} onChanged={async () => { await load(); setLearningRevision((n) => n + 1); }} /> : <div className="flex h-full flex-col items-center justify-center px-8 text-center"><BookUser className="mb-4 size-9 text-muted-foreground/40" /><h2 className="font-medium">选择一条记忆查看详情</h2><p className="mt-2 max-w-xs text-sm leading-6 text-muted-foreground">在这里查看完整内容、来源和历史，删除不需要的记忆。</p></div>}</div>
			</div>
		</div> : section === 'learning' ? <div className="flex min-h-0 flex-1 flex-col">
			<div className="shrink-0 border-b bg-background px-4 py-4 sm:px-6">
				<div className="inline-flex max-w-full gap-1 overflow-x-auto rounded-lg bg-muted p-1" aria-label="学习记录类型">
					{([{ id: 'group', title: '群聊持续学习' }, { id: 'conversation', title: '全部学习任务' }] as const).map(({ id, title }) => <button key={id} type="button" aria-pressed={learningTab === id} onClick={() => setLearningTab(id)} className={cn('shrink-0 rounded-md px-3 py-2 text-sm focus-visible:outline-2', learningTab === id ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground')}>{title}</button>)}
				</div>
			</div>
			{learningTab === 'group' ? <GroupLearningActivity revision={learningRevision} onMemory={navigateMemory} users={data?.users} projects={data?.projects} /> : <LearningActivity revision={learningRevision} users={data?.users} projects={data?.projects} onCandidates={(event) => navigateMemory(event.scope_type, event.platform_user_id, event.project_id, 'active')} />}
		</div>
		: <MemoryDiagnostics jobs={jobs} loading={loading} error={error} locale={zh ? 'zh-CN' : 'en'} onRefresh={() => void load()} />}
	</div>;
}
