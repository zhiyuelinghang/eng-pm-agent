import {
	ArrowRightLeft,
	BookUser,
	FolderKanban,
	Loader2,
	RefreshCw,
	Search,
	ShieldCheck,
	Trash2,
	UserRound,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { toast } from 'sonner';

import { memoryManagementApi } from '@/api/memory-management';
import type {
	ManagedMemoryItem,
	MemoryManagementResponse,
	MemoryScopeType,
} from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';
import { cn } from '@/lib/utils';

interface Selection {
	userId?: string;
	scopeType?: MemoryScopeType;
	projectId?: string;
}

function formatTime(value: string | null, language: string) {
	if (!value) return '—';
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return value;
	return new Intl.DateTimeFormat(language.startsWith('zh') ? 'zh-CN' : 'en', {
		dateStyle: 'medium',
		timeStyle: 'short',
	}).format(date);
}

export function MemoryManagementPage() {
	const { t, i18n } = useTranslation();
	const [data, setData] = useState<MemoryManagementResponse | null>(null);
	const [selection, setSelection] = useState<Selection>({});
	const [searchInput, setSearchInput] = useState('');
	const [query, setQuery] = useState('');
	const [loading, setLoading] = useState(true);
	const [refreshing, setRefreshing] = useState(false);
	const [editing, setEditing] = useState<ManagedMemoryItem | null>(null);
	const [targetScope, setTargetScope] = useState<MemoryScopeType>('user_project');
	const [targetProject, setTargetProject] = useState<string>('');
	const [mutating, setMutating] = useState(false);

	const load = useCallback(
		async (quiet = false) => {
			if (quiet) setRefreshing(true);
			else setLoading(true);
			try {
				const response = await memoryManagementApi.list({
					platformUserId: selection.userId,
					scopeType: selection.scopeType,
					projectId: selection.projectId,
					query,
				});
				setData(response);
			} catch (error) {
				toast.error(formatApiErrorForAlert(error));
			} finally {
				setLoading(false);
				setRefreshing(false);
			}
		},
		[query, selection.projectId, selection.scopeType, selection.userId],
	);

	useEffect(() => {
		void load();
	}, [load]);

	const selectedUser = useMemo(
		() => data?.users.find((user) => user.user_id === selection.userId),
		[data?.users, selection.userId],
	);

	const editingUser = useMemo(
		() => data?.users.find((user) => user.user_id === editing?.platform_user_id),
		[data?.users, editing?.platform_user_id],
	);

	const openScopeDialog = (memory: ManagedMemoryItem) => {
		setEditing(memory);
		setTargetScope(memory.scope_type);
		setTargetProject(memory.project_id ?? '');
	};

	const saveScope = async () => {
		if (!editing || (targetScope === 'user_project' && !targetProject)) return;
		setMutating(true);
		try {
			await memoryManagementApi.updateScope(editing.id, {
				scope_type: targetScope,
				project_id: targetScope === 'user_project' ? targetProject : null,
			});
			setEditing(null);
			toast.success(t('memory-management.messages.scopeUpdated'));
			await load(true);
		} catch (error) {
			toast.error(formatApiErrorForAlert(error));
		} finally {
			setMutating(false);
		}
	};

	const deleteMemory = async (memory: ManagedMemoryItem) => {
		if (!window.confirm(t('memory-management.messages.deleteConfirm'))) return;
		setMutating(true);
		try {
			await memoryManagementApi.delete(memory.id);
			toast.success(t('memory-management.messages.deleted'));
			await load(true);
		} catch (error) {
			toast.error(formatApiErrorForAlert(error));
		} finally {
			setMutating(false);
		}
	};

	const submitSearch = (event: FormEvent) => {
		event.preventDefault();
		setQuery(searchInput.trim());
	};

	return (
		<div className="flex h-full min-h-0 flex-col bg-muted/25">
			<header className="flex shrink-0 flex-wrap items-center justify-between gap-4 border-b bg-background px-5 py-3">
				<div>
					<div className="flex items-center gap-2">
						<BookUser className="size-5 text-primary" />
						<h1 className="text-lg font-semibold">{t('memory-management.title')}</h1>
					</div>
					<p className="mt-1 text-xs text-muted-foreground">
						{t('memory-management.description')}
					</p>
				</div>
				<Button
					variant="outline"
					onClick={() => void load(true)}
					disabled={refreshing || mutating}
				>
					<RefreshCw className={cn(refreshing && 'animate-spin')} />
					{t('memory-management.refresh')}
				</Button>
			</header>

			<main className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[18rem_minmax(0,1fr)]">
				<aside className="min-h-0 overflow-y-auto border-b bg-background p-3 lg:border-r lg:border-b-0">
					<button
						type="button"
						onClick={() => setSelection({})}
						className={cn(
							'flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted',
							!selection.userId && 'bg-primary/10 font-medium text-primary',
						)}
					>
						<span className="flex items-center gap-2">
							<ShieldCheck className="size-4" />
							{t('memory-management.allUsers')}
						</span>
						<span>{data?.users.reduce((sum, user) => sum + user.memory_count, 0) ?? 0}</span>
					</button>

					<div className="mt-3 space-y-3">
						{data?.users.map((user) => (
							<section key={user.user_id} className="rounded-lg border p-1.5">
								<button
									type="button"
									onClick={() => setSelection({ userId: user.user_id })}
									className={cn(
										'flex w-full items-center justify-between rounded-md px-2.5 py-2 text-left text-sm hover:bg-muted',
										selection.userId === user.user_id &&
											!selection.scopeType &&
											'bg-muted font-medium',
									)}
								>
									<span className="min-w-0">
										<span className="flex items-center gap-2">
											<UserRound className="size-4 shrink-0 text-primary" />
											<span className="truncate">{user.display_name}</span>
										</span>
										<span className="mt-0.5 block truncate pl-6 text-xs text-muted-foreground">
											{user.username}
										</span>
									</span>
									<span className="pl-2 text-xs tabular-nums">{user.memory_count}</span>
								</button>

								<div className="mt-1 space-y-0.5 border-t pt-1">
									<button
										type="button"
										onClick={() =>
											setSelection({ userId: user.user_id, scopeType: 'user' })
										}
										className={cn(
											'flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-xs hover:bg-muted',
											selection.userId === user.user_id &&
												selection.scopeType === 'user' &&
												'bg-primary/10 text-primary',
										)}
									>
										<span>{t('memory-management.scopes.user')}</span>
										<span>{user.user_memory_count}</span>
									</button>
									{user.projects.map((project) => (
										<button
											type="button"
											key={project.project_id}
											onClick={() =>
												setSelection({
													userId: user.user_id,
													scopeType: 'user_project',
													projectId: project.project_id,
												})
											}
											className={cn(
												'flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-xs hover:bg-muted',
												selection.userId === user.user_id &&
													selection.projectId === project.project_id &&
													'bg-primary/10 text-primary',
											)}
										>
											<span className="flex min-w-0 items-center gap-1.5">
												<FolderKanban className="size-3.5 shrink-0" />
												<span className="truncate">{project.project_name}</span>
											</span>
											<span>{project.memory_count}</span>
										</button>
									))}
								</div>
							</section>
						))}
					</div>
				</aside>

				<section className="flex min-h-0 min-w-0 flex-col">
					<div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b bg-background px-4 py-3">
						<div>
							<h2 className="text-base font-semibold">
								{selectedUser?.display_name ?? t('memory-management.allMemories')}
							</h2>
							<p className="text-xs text-muted-foreground">
								{t('memory-management.resultCount', { count: data?.total ?? 0 })}
							</p>
						</div>
						<form onSubmit={submitSearch} className="flex w-full gap-2 sm:w-auto">
							<Input
								value={searchInput}
								onChange={(event) => setSearchInput(event.target.value)}
								placeholder={t('memory-management.searchPlaceholder')}
								className="min-w-0 sm:w-72"
							/>
							<Button type="submit" variant="outline">
								<Search />
								{t('memory-management.search')}
							</Button>
						</form>
					</div>

					<div className="min-h-0 flex-1 overflow-y-auto p-4">
						{loading ? (
							<div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
								<Loader2 className="size-4 animate-spin" />
								{t('memory-management.loading')}
							</div>
						) : data?.memories.length ? (
							<div className="space-y-3">
								{data.memories.map((memory) => {
									const owner = data.users.find(
										(user) => user.user_id === memory.platform_user_id,
									);
									const project = owner?.projects.find(
										(item) => item.project_id === memory.project_id,
									);
									return (
										<article key={memory.id} className="rounded-xl border bg-background p-4">
											<div className="flex flex-wrap items-start justify-between gap-3">
												<div className="flex flex-wrap items-center gap-2">
													<Badge variant={memory.scope_type === 'user' ? 'default' : 'secondary'}>
														{t(`memory-management.scopes.${memory.scope_type}`)}
													</Badge>
													<span className="text-xs text-muted-foreground">
														{owner?.display_name ?? memory.platform_user_id}
														{project ? ` · ${project.project_name}` : ''}
													</span>
												</div>
												<div className="flex items-center gap-1">
													<Button
														variant="ghost"
														size="sm"
														onClick={() => openScopeDialog(memory)}
														disabled={mutating}
													>
														<ArrowRightLeft />
														{t('memory-management.adjustScope')}
													</Button>
													<Button
														variant="destructive"
														size="sm"
														onClick={() => void deleteMemory(memory)}
														disabled={mutating}
													>
														<Trash2 />
														{t('memory-management.delete')}
													</Button>
												</div>
											</div>
											<p className="mt-3 whitespace-pre-wrap text-sm leading-6">{memory.content}</p>
											<div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
												<span>{t('memory-management.meta.type')}: {memory.memory_type}</span>
												<span>{t('memory-management.meta.importance')}: {memory.importance.toFixed(2)}</span>
												<span>{t('memory-management.meta.source')}: {t(`memory-management.sources.${memory.source}`, { defaultValue: memory.source })}</span>
												<span>{t('memory-management.meta.updated')}: {formatTime(memory.updated_at ?? memory.created_at, i18n.language)}</span>
											</div>
										</article>
									);
								})}
								{data.total > data.memories.length && (
									<p className="py-2 text-center text-xs text-muted-foreground">
										{t('memory-management.resultLimited', { count: data.memories.length })}
									</p>
								)}
							</div>
						) : (
							<div className="flex h-full flex-col items-center justify-center text-center">
								<BookUser className="size-10 text-muted-foreground/50" />
								<h3 className="mt-3 text-base font-medium">{t('memory-management.empty.title')}</h3>
								<p className="mt-1 max-w-md text-sm text-muted-foreground">
									{t('memory-management.empty.description')}
								</p>
							</div>
						)}
					</div>
				</section>
			</main>

			<Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
				<DialogContent className="sm:max-w-lg">
					<DialogHeader>
						<DialogTitle>{t('memory-management.dialog.title')}</DialogTitle>
						<DialogDescription>{t('memory-management.dialog.description')}</DialogDescription>
					</DialogHeader>
					<div className="space-y-4 py-1">
						<div className="rounded-lg border bg-muted/30 p-3 text-sm leading-6">
							{editing?.content}
						</div>
						<div className="space-y-2">
							<Label>{t('memory-management.dialog.scope')}</Label>
							<Select
								value={targetScope}
								onValueChange={(value) => {
									const scope = value as MemoryScopeType;
									setTargetScope(scope);
									if (scope === 'user') setTargetProject('');
								}}
							>
								<SelectTrigger className="w-full">
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="user">{t('memory-management.scopes.user')}</SelectItem>
									<SelectItem value="user_project">{t('memory-management.scopes.user_project')}</SelectItem>
								</SelectContent>
							</Select>
						</div>
						{targetScope === 'user_project' && (
							<div className="space-y-2">
								<Label>{t('memory-management.dialog.project')}</Label>
								<Select value={targetProject} onValueChange={setTargetProject}>
									<SelectTrigger className="w-full">
										<SelectValue placeholder={t('memory-management.dialog.selectProject')} />
									</SelectTrigger>
									<SelectContent>
										{editingUser?.projects.map((project) => (
											<SelectItem key={project.project_id} value={project.project_id}>
												{project.project_name}
											</SelectItem>
										))}
									</SelectContent>
								</Select>
							</div>
						)}
					</div>
					<DialogFooter>
						<Button variant="outline" onClick={() => setEditing(null)} disabled={mutating}>
							{t('common.cancel')}
						</Button>
						<Button
							onClick={() => void saveScope()}
							disabled={mutating || (targetScope === 'user_project' && !targetProject)}
						>
							{mutating && <Loader2 className="animate-spin" />}
							{t('memory-management.dialog.save')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
