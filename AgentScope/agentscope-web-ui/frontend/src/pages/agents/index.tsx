import {
	BookOpen,
	Bot,
	FileSearch,
	ListTodo,
	Loader2,
	Pencil,
	Play,
	Search,
	Settings2,
	Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { agentApi, type AgentView, type PlatformSettings } from '@/api';
import { AgentDebugDialog } from '@/components/dialog/AgentDebugDialog';
import { AgentDialog } from '@/components/dialog/AgentDialog';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { EditAgentDialog } from '@/components/dialog/EditAgentDialog';
import { InitializationValidationDialog } from '@/components/dialog/InitializationValidationDialog';
import type { EditorSection } from '@/components/form/AgentFormFields';
import { AgentCapabilitiesPanel } from '@/components/panel/AgentCapabilitiesPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAvailableModels } from '@/hooks/useAvailableModels';
import { DUTIES, businessAgents, dutyStatus } from '@/lib/agent-workbench';

const ICONS = { bot: Bot, file: FileSearch, task: ListTodo, book: BookOpen };

export function AgentWorkbenchPage({ mode }: { mode: 'primary' | 'business' }) {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const { groups: modelGroups } = useAvailableModels();
	const primary = mode === 'primary';
	const navigate = useNavigate();
	const { selection } = useParams<{ selection: string }>();
	const [data, setData] = useState<{ agents: AgentView[]; settings: PlatformSettings } | null>(
		null,
	);
	const [error, setError] = useState('');
	const [loading, setLoading] = useState(true);
	const [query, setQuery] = useState('');
	const [edit, setEdit] = useState<EditorSection | null>(null);
	const [debug, setDebug] = useState(false);
	const [validation, setValidation] = useState(false);
	const [deleting, setDeleting] = useState(false);
	const load = useCallback(async () => {
		setLoading(true);
		setError('');
		try {
			const [list, settings] = await Promise.all([
				agentApi.list(),
				agentApi.getPlatformSettings(),
			]);
			setData({ agents: list.agents, settings });
		} catch (e) {
			setError(e instanceof Error ? e.message : '加载失败');
		} finally {
			setLoading(false);
		}
	}, []);
	useEffect(() => {
		void load();
	}, [load]);
	const duty = DUTIES.find((d) => d.key === selection) ?? DUTIES[0];
	const agents = data?.agents ?? [];
	const business = data ? businessAgents(agents, data.settings) : [];
	const current = primary
		? agents.find((a) => a.id === data?.settings[duty.field])
		: (business.find((a) => a.id === selection) ?? (!selection ? business[0] : undefined));
	const list = business.filter((a) =>
		`${a.data.name} ${a.data.platform_config.description ?? ''} ${a.data.platform_config.category}`
			.toLowerCase()
			.includes(query.trim().toLowerCase()),
	);
	const title = primary
		? zh
			? '平台主智能体'
			: 'Platform agents'
		: zh
			? '业务智能体'
			: 'Business agents';
	const Icon = primary ? ICONS[duty.icon] : Bot;
	const name = primary ? (zh ? duty.name : duty.en) : current?.data.name;
	const description = primary
		? zh
			? duty.description
			: duty.descriptionEn
		: current?.data.platform_config.description;
	const model = current?.data.model_policy.chat_model_config;
	const modelLabel =
		Object.values(modelGroups)
			.flat()
			.find((entry) => entry.credential.id === model?.credential_id)
			?.models.find((card) => card.name === model?.model)?.label || model?.model;
	const statusLabels = zh
		? { ready: '已配置', empty: '未配置', invalid: '需完善', unavailable: '不可用' }
		: {
				ready: 'Configured',
				empty: 'Not configured',
				invalid: 'Needs attention',
				unavailable: 'Unavailable',
			};
	const select = (key: string) =>
		navigate(`/${primary ? 'platform-agents' : 'business-tools'}/${key}`);
	return (
		<div className="flex h-full min-h-0 flex-col bg-background">
			<header className="flex min-h-20 shrink-0 items-center justify-between gap-4 border-b px-6 py-4">
				<div>
					<h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
					<p className="mt-1 text-sm text-muted-foreground">
						{primary
							? zh
								? '平台职责与智能体配置'
								: 'Platform duties and configuration'
							: zh
								? '配置专业能力，按需接入平台'
								: 'Configure specialist capabilities'}
					</p>
				</div>
				{!primary && (
					<AgentDialog
						triggerLabel={zh ? '新增业务智能体' : 'New business agent'}
						onCreated={async (id) => {
							await load();
							select(id);
						}}
					/>
				)}
			</header>
			{error ? (
				<div role="alert" className="space-y-4 p-8">
					<p>{error}</p>
					<Button variant="outline" onClick={load}>
						{zh ? '重新加载' : 'Retry'}
					</Button>
				</div>
			) : !data ? (
				<div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
					<Loader2 className="size-4 animate-spin" />
					{zh ? '正在加载配置…' : 'Loading configuration…'}
				</div>
			) : (
				<div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[260px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)]">
					<aside className="flex min-h-0 flex-col border-b bg-muted/10 md:border-r md:border-b-0">
						<div className="flex items-center justify-between px-5 py-5">
							<h2 className="text-sm font-semibold">
								{primary
									? zh
										? '智能体职责'
										: 'Duties'
									: zh
										? '全部智能体'
										: 'All agents'}
							</h2>
							<span className="text-xs tabular-nums text-muted-foreground">
								{primary ? 4 : business.length}
							</span>
						</div>
						{!primary && (
							<div className="relative mx-4 mb-4">
								<Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
								<Input
									aria-label={zh ? '搜索业务智能体' : 'Search business agents'}
									placeholder={
										zh ? '搜索名称或职责' : 'Search name or description'
									}
									className="pl-9"
									value={query}
									onChange={(e) => setQuery(e.target.value)}
								/>
							</div>
						)}
						<nav
							aria-label={title}
							className="flex gap-2 overflow-x-auto px-3 pb-4 md:block md:space-y-2 md:overflow-y-auto"
						>
							{primary
								? DUTIES.map((item) => {
										const ItemIcon = ICONS[item.icon];
										const status = dutyStatus(item, data.settings, agents);
										return (
											<button
												key={item.key}
												type="button"
												aria-current={
													duty.key === item.key ? 'page' : undefined
												}
												onClick={() => select(item.key)}
												className={`w-full min-w-48 rounded-lg border px-3 py-4 text-left transition-colors ${duty.key === item.key ? 'border-[#c95622]/20 bg-[#c95622]/5' : 'border-transparent hover:bg-muted/60'}`}
											>
												<div className="flex items-start gap-3">
													<span
														className={`rounded-xl p-2.5 ${duty.key === item.key ? 'bg-[#c95622] text-white' : 'bg-muted'}`}
													>
														<ItemIcon className="size-5" />
													</span>
													<div className="min-w-0 flex-1">
														<div className="flex flex-wrap items-center justify-between gap-1">
															<span className="text-sm font-semibold">
																{zh ? item.name : item.en}
															</span>
															<span className="flex items-center gap-1.5 text-xs text-muted-foreground">
																<span
																	className={`size-1.5 rounded-full ${status === 'ready' ? 'bg-emerald-500' : 'bg-amber-500'}`}
																/>
																{statusLabels[status]}
															</span>
														</div>
														<p className="mt-1.5 text-xs leading-5 text-muted-foreground">
															{zh
																? item.description
																: item.descriptionEn}
														</p>
													</div>
												</div>
											</button>
										);
									})
								: list.map((agent) => (
										<button
											key={agent.id}
											type="button"
											aria-current={
												current?.id === agent.id ? 'page' : undefined
											}
											onClick={() => select(agent.id)}
											className={`w-full min-w-48 rounded-lg border px-3 py-3 text-left ${current?.id === agent.id ? 'border-[#c95622]/20 bg-[#c95622]/5' : 'border-transparent hover:bg-muted/60'}`}
										>
											<div className="flex gap-3">
												<span
													className={`rounded-xl p-2.5 ${current?.id === agent.id ? 'bg-[#c95622] text-white' : 'bg-muted'}`}
												>
													<Bot className="size-5" />
												</span>
												<div className="min-w-0">
													<p className="truncate text-sm font-semibold">
														{agent.data.name}
													</p>
													<div className="mt-2 flex flex-wrap gap-1.5">
														<Badge
															variant="outline"
															className={`text-xs ${agent.data.platform_config.role === 'system_internal' ? 'border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-800 dark:bg-violet-950 dark:text-violet-200' : 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200'}`}
														>
															{agent.data.platform_config.role ===
															'system_internal'
																? zh
																	? '内部'
																	: 'Internal'
																: zh
																	? '公开'
																	: 'Public'}
														</Badge>
														<Badge
															variant="outline"
															className={`text-xs ${agent.data.platform_config.role !== 'system_internal' && agent.data.platform_config.published ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200'}`}
														>
															{agent.data.platform_config.role !==
																'system_internal' &&
															agent.data.platform_config.published
																? zh
																	? '已发布'
																	: 'Published'
																: zh
																	? '未发布'
																	: 'Unpublished'}
														</Badge>
														{!agent.data.platform_config.enabled && (
															<Badge
																variant="outline"
																className="text-xs"
															>
																{zh ? '已停用' : 'Disabled'}
															</Badge>
														)}
													</div>
												</div>
											</div>
										</button>
									))}
							{!primary && list.length === 0 && (
								<p className="px-3 py-6 text-sm text-muted-foreground">
									{zh ? '没有匹配的业务智能体' : 'No matching agents'}
								</p>
							)}
						</nav>
					</aside>
					<main className="flex min-h-0 flex-col overflow-y-auto px-5 py-5 lg:px-7">
						<div className="mx-auto flex w-full max-w-6xl min-h-[650px] flex-1 flex-col md:min-h-0">
							<div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-4 gap-y-2 border-b pb-5">
								<span className="col-start-1 row-span-2 row-start-1 h-fit rounded-2xl bg-muted p-3.5">
									<Icon className="size-7" />
								</span>
								<h2 className="col-start-2 row-start-1 min-w-0 break-words text-xl font-semibold">
									{name ?? (zh ? '选择业务智能体' : 'Select an agent')}
								</h2>
								{current && (
									<div className="col-start-3 row-start-1 flex shrink-0 items-center justify-end gap-2">
										<Button
											variant="outline"
											disabled={!current.editable}
											onClick={() => setEdit('identity')}
										>
											<Pencil />
											{zh ? '编辑智能体' : 'Edit agent'}
										</Button>
										<Button
											className="bg-[#c95622] text-white hover:bg-[#ae461a]"
											disabled={!current.data.platform_config.enabled}
											onClick={() => setDebug(true)}
										>
											<Play />
											{zh ? '调试' : 'Debug'}
										</Button>
										{primary && duty.key === 'initializer' && (
											<Button
												variant="outline"
												onClick={() => setValidation(true)}
											>
												<Settings2 />
												{zh ? '初始化核验' : 'Validation'}
											</Button>
										)}
										{!primary && current.editable && (
											<Button
												variant="ghost"
												onClick={() => setDeleting(true)}
												aria-label={zh ? '删除业务智能体' : 'Delete agent'}
											>
												<Trash2 />
											</Button>
										)}
									</div>
								)}
								{description && (
									<p className="col-span-2 col-start-2 row-start-2 min-w-0 break-words text-sm leading-6 text-muted-foreground">
										{description}
									</p>
								)}
							</div>
							{current ? (
								<>
									<section
										className="shrink-0 py-5"
										aria-label={zh ? '基本信息' : 'Overview'}
									>
										<dl className="grid grid-cols-[auto_minmax(0,1fr)] lg:grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)] gap-x-5 gap-y-2.5 text-sm">
											<dt className="text-muted-foreground">
												{zh ? '当前智能体' : 'Agent'}
											</dt>
											<dd className="break-words">
												{current.data.name}
												{!current.editable && (
													<Badge className="ml-2" variant="secondary">
														{zh ? '只读' : 'Read only'}
													</Badge>
												)}
											</dd>
											<dt className="text-muted-foreground">
												{zh ? '使用模型' : 'Model'}
											</dt>
											<dd>
												{current.data.model_policy.mode === 'fixed'
													? (modelLabel ??
														(zh ? '尚未配置' : 'Not configured'))
													: zh
														? '跟随会话模型'
														: 'Session model'}
											</dd>
										</dl>
									</section>
									<AgentCapabilitiesPanel
										settings={data.settings}
										key={current.id}
										agent={current}
										primaryDuty={primary ? duty : undefined}
										agents={agents}
										onUpdated={load}
									/>
								</>
							) : (
								<div className="py-14 text-center">
									<Icon className="mx-auto mb-4 size-9 text-muted-foreground" />
									<h3 className="text-base font-medium">
										{primary
											? data.settings[duty.field]
												? zh
													? '智能体配置暂时不可用'
													: 'Agent configuration is unavailable'
												: zh
													? '尚未完成配置'
													: 'Configuration is not complete'
											: zh
												? '暂无可显示的业务智能体'
												: 'No agent selected'}
									</h3>
									<p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
										{primary
											? zh
												? '填写模型和工作指令，保存后即可配置能力并调试。'
												: 'Set the model and instructions, then configure capabilities and debug.'
											: zh
												? '从左侧选择智能体，或新增一个业务智能体。'
												: 'Choose an agent or create one.'}
									</p>
									{primary && !data.settings[duty.field] && (
										<div className="mt-5 space-x-2">
											<AgentDialog
												key={duty.key}
												primaryDuty={duty}
												triggerLabel={zh ? '配置智能体' : 'Configure agent'}
												onCreated={load}
											/>
											{duty.key === 'initializer' && (
												<Button
													variant="outline"
													onClick={() => setValidation(true)}
												>
													{zh ? '初始化核验' : 'Validation'}
												</Button>
											)}
										</div>
									)}
									{primary && data.settings[duty.field] && (
										<Button className="mt-5" variant="outline" onClick={load}>
											{zh ? '重新加载' : 'Retry'}
										</Button>
									)}
								</div>
							)}
						</div>
					</main>
				</div>
			)}
			{loading && data && (
				<span className="sr-only" role="status">
					{zh ? '正在刷新配置' : 'Refreshing'}
				</span>
			)}
			{edit && current && (
				<EditAgentDialog
					open
					agent={current}
					initialSection={edit}
					onOpenChange={(open) => {
						if (!open) setEdit(null);
					}}
					onUpdated={load}
				/>
			)}
			{debug && current && (
				<AgentDebugDialog
					agent={current}
					agents={agents}
					onClose={() => setDebug(false)}
					onUpdated={load}
				/>
			)}
			{validation && primary && duty.key === 'initializer' && (
				<InitializationValidationDialog
					onClose={() => {
						setValidation(false);
						void load();
					}}
				/>
			)}

			{current && !primary && (
				<DeleteDialog
					open={deleting}
					onOpenChange={setDeleting}
					title={zh ? '删除业务智能体' : 'Delete business agent'}
					description={
						zh
							? `确定删除「${current.data.name}」？关联调试会话也将一并删除。`
							: `Delete ${current.data.name} and its sessions?`
					}
					onConfirm={async () => {
						await agentApi.delete(current.id);
						await load();
						navigate('/business-tools', { replace: true });
					}}
				/>
			)}
		</div>
	);
}
