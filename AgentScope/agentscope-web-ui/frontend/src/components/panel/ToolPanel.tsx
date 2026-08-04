import {
	CircleAlert,
	Globe,
	Info,
	Loader2,
	RotateCcw,
	Save,
	Search,
	SearchX,
	Wrench,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import type { AgentToolConfig, AgentView, WorkspaceTool } from '@/api';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface ToolPanelProps {
	agent: AgentView | null;
	tools: WorkspaceTool[];
	loading?: boolean;
	onSave: (agentId: string, config: AgentToolConfig) => Promise<void>;
}

interface ToolParameter {
	name: string;
	type: string;
	description: string | null;
	required: boolean;
}

const WORKSPACE_TOOL_KEYS: Record<string, string> = {
	Edit: 'edit',
	Glob: 'glob',
	Grep: 'grep',
	Read: 'read',
	Write: 'write',
};

function readToolParameters(inputSchema: Record<string, unknown>): ToolParameter[] {
	const rawProperties = inputSchema.properties;
	if (!rawProperties || typeof rawProperties !== 'object' || Array.isArray(rawProperties)) {
		return [];
	}
	const required = new Set(
		Array.isArray(inputSchema.required)
			? inputSchema.required.filter((value): value is string => typeof value === 'string')
			: [],
	);
	return Object.entries(rawProperties).map(([name, rawDefinition]) => {
		const definition =
			rawDefinition && typeof rawDefinition === 'object' && !Array.isArray(rawDefinition)
				? (rawDefinition as Record<string, unknown>)
				: {};
		const rawType = definition.type;
		const type = Array.isArray(rawType)
			? rawType.filter((value) => typeof value === 'string').join(' / ')
			: typeof rawType === 'string'
				? rawType
				: 'any';
		return {
			name,
			type,
			description: typeof definition.description === 'string' ? definition.description : null,
			required: required.has(name),
		};
	});
}

function sameNames(left: string[], right: string[]): boolean {
	if (left.length !== right.length) return false;
	const rightNames = new Set(right);
	return left.every((name) => rightNames.has(name));
}

function assignedNames(agent: AgentView | null, tools: WorkspaceTool[]): string[] {
	const explicit = agent?.data.tool_config?.allowed_tool_names;
	if (explicit) return [...explicit];
	return tools.filter((tool) => tool.assigned).map((tool) => tool.name);
}

export function ToolPanel({ agent, tools, loading = false, onSave }: ToolPanelProps) {
	const { t, i18n } = useTranslation();
	const [search, setSearch] = useState('');
	const [selectedName, setSelectedName] = useState<string | null>(null);
	const [draftNames, setDraftNames] = useState<string[]>(() => assignedNames(agent, tools));
	const [submitting, setSubmitting] = useState(false);
	const [errorMsg, setErrorMsg] = useState('');
	const isChinese = i18n.language.startsWith('zh');

	useEffect(() => {
		setDraftNames(assignedNames(agent, tools));
		setErrorMsg('');
	}, [agent, tools]);

	const persistedNames = useMemo(() => assignedNames(agent, tools), [agent, tools]);
	const selectedSet = useMemo(() => new Set(draftNames), [draftNames]);
	const isDirty = !sameNames(draftNames, persistedNames);

	const getPresentation = (tool: WorkspaceTool) => {
		const workspaceKey = WORKSPACE_TOOL_KEYS[tool.name];
		const rawDescription = tool.description?.trim() ?? '';
		return {
			name:
				tool.display_name?.trim() ||
				(workspaceKey ? t(`panel.tool.workspaceTools.${workspaceKey}.name`) : tool.name),
			description: workspaceKey
				? t(`panel.tool.workspaceTools.${workspaceKey}.description`)
				: isChinese && rawDescription && !/[\u3400-\u9fff]/u.test(rawDescription)
					? t('panel.tool.untranslatedDescription')
					: rawDescription,
		};
	};

	const query = search.trim().toLowerCase();
	const filtered = query
		? tools.filter((tool) => {
				const presentation = getPresentation(tool);
				return (
					tool.name.toLowerCase().includes(query) ||
					presentation.name.toLowerCase().includes(query) ||
					presentation.description.toLowerCase().includes(query)
				);
			})
		: tools;
	const groups = [
		{
			key: 'platform' as const,
			label: t('panel.tool.platform'),
			tools: filtered.filter((tool) => tool.source === 'platform'),
		},
		{
			key: 'workspace' as const,
			label: t('panel.tool.workspace'),
			tools: filtered.filter((tool) => tool.source === 'workspace'),
		},
	];
	const selectedTool = tools.find((tool) => tool.name === selectedName) ?? null;
	const selectedPresentation = selectedTool ? getPresentation(selectedTool) : null;
	const selectedParameters = selectedTool ? readToolParameters(selectedTool.input_schema) : [];
	const selectedCandidateCount = tools.filter((tool) => selectedSet.has(tool.name)).length;

	const toggleTool = (toolName: string, checked: boolean) => {
		if (!agent?.editable || submitting) return;
		setErrorMsg('');
		setDraftNames((current) =>
			checked
				? [...new Set([...current, toolName])]
				: current.filter((name) => name !== toolName),
		);
	};

	const resetDraft = () => {
		setDraftNames(persistedNames);
		setErrorMsg('');
	};

	const handleSave = async () => {
		if (!agent || !agent.editable || !isDirty) return;
		setSubmitting(true);
		setErrorMsg('');
		try {
			await onSave(agent.id, { allowed_tool_names: draftNames });
			toast.success(t('panel.tool.saved'));
		} catch (error) {
			setErrorMsg(formatApiErrorForAlert(error));
		} finally {
			setSubmitting(false);
		}
	};

	const footer = (
		<div className="flex-none space-y-2 pt-3">
			{!agent?.editable && agent ? (
				<Alert>
					<CircleAlert />
					<AlertDescription>{t('panel.tool.readOnlyNotice')}</AlertDescription>
				</Alert>
			) : null}
			{errorMsg ? (
				<Alert variant="destructive">
					<CircleAlert />
					<AlertDescription className="whitespace-pre-wrap">{errorMsg}</AlertDescription>
				</Alert>
			) : null}
			<div className="flex items-center justify-between border-t pt-3">
				<Button
					variant="ghost"
					size="sm"
					onClick={resetDraft}
					disabled={!isDirty || submitting}
				>
					<RotateCcw />
					{t('panel.tool.discard')}
				</Button>
				<Button
					size="sm"
					onClick={() => void handleSave()}
					disabled={!agent?.editable || !isDirty || submitting}
				>
					{submitting ? <Loader2 className="animate-spin" /> : <Save />}
					{submitting ? t('common.saving') : t('panel.tool.saveChanges')}
				</Button>
			</div>
		</div>
	);

	if (loading && !agent) {
		return (
			<div className="flex flex-1 items-center justify-center">
				<p className="text-sm text-muted-foreground">{t('panel.loading')}</p>
			</div>
		);
	}

	if (!agent) {
		return (
			<PanelEmpty
				icon={Wrench}
				title={t('panel.tool.noAgentTitle')}
				description={t('panel.tool.noAgentDescription')}
			/>
		);
	}

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<Dialog
				open={selectedTool !== null}
				onOpenChange={(open) => {
					if (!open) setSelectedName(null);
				}}
			>
				{selectedTool && selectedPresentation ? (
					<DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-2xl">
						<DialogHeader>
							<DialogTitle>{selectedPresentation.name}</DialogTitle>
							<DialogDescription>
								<code className="break-all text-xs">{selectedTool.name}</code>
							</DialogDescription>
						</DialogHeader>

						<div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-1">
							<section className="space-y-2">
								<h3 className="text-sm font-medium">{t('panel.tool.details')}</h3>
								<p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
									{selectedPresentation.description ||
										t('panel.tool.noDescription')}
								</p>
							</section>

							<section className="space-y-2">
								<h3 className="text-sm font-medium">
									{t('panel.tool.parameters')}
								</h3>
								{selectedParameters.length ? (
									<div className="divide-y rounded-md border">
										{selectedParameters.map((parameter) => {
											const translatedName = t(
												`panel.tool.parameterNames.${parameter.name}`,
												{ defaultValue: parameter.name },
											);
											const visibleDescription =
												!isChinese ||
												(parameter.description &&
													/[\u3400-\u9fff]/u.test(parameter.description))
													? parameter.description
													: null;
											return (
												<div key={parameter.name} className="px-3 py-2.5">
													<div className="flex items-center justify-between gap-2">
														<div className="min-w-0">
															<span className="text-sm font-medium">
																{translatedName}
															</span>
															{translatedName !== parameter.name ? (
																<code className="ml-2 text-xs text-muted-foreground">
																	{parameter.name}
																</code>
															) : null}
														</div>
														<span className="shrink-0 text-xs text-muted-foreground">
															{parameter.required
																? t('panel.tool.required')
																: t('panel.tool.optional')}
															{' · '}
															{parameter.type}
														</span>
													</div>
													{visibleDescription ? (
														<p className="mt-1 text-sm text-muted-foreground">
															{visibleDescription}
														</p>
													) : null}
												</div>
											);
										})}
									</div>
								) : (
									<p className="text-sm text-muted-foreground">
										{t('panel.tool.noParameters')}
									</p>
								)}
							</section>
						</div>

						<DialogFooter>
							<Button variant="outline" onClick={() => setSelectedName(null)}>
								{t('common.close')}
							</Button>
						</DialogFooter>
					</DialogContent>
				) : null}
			</Dialog>

			<div className="flex-none space-y-3 pb-3">
				<p className="text-sm leading-relaxed text-muted-foreground">
					{t('panel.tool.description')}
				</p>
				<div className="flex items-center gap-2 rounded-md bg-muted/50 px-2.5 py-2 text-xs text-muted-foreground">
					<Globe className="size-3.5 shrink-0" />
					<span>{t('panel.tool.globalNotice')}</span>
				</div>
				<div className="flex items-center justify-between gap-3">
					<div className="flex items-baseline gap-1.5">
						<span className="text-sm font-medium">{t('panel.tool.catalogTitle')}</span>
						<span className="text-xs tabular-nums text-muted-foreground">
							{t('panel.tool.selectedSummary', {
								selected: selectedCandidateCount,
								total: tools.length,
							})}
						</span>
					</div>
					<div className="flex items-center gap-0.5">
						<Button
							variant="ghost"
							size="xs"
							disabled={
								!agent.editable ||
								submitting ||
								selectedCandidateCount === tools.length
							}
							onClick={() => setDraftNames(tools.map((tool) => tool.name))}
						>
							{t('panel.tool.selectAll')}
						</Button>
						<Button
							variant="ghost"
							size="xs"
							disabled={!agent.editable || submitting || selectedCandidateCount === 0}
							onClick={() => setDraftNames([])}
						>
							{t('panel.tool.clear')}
						</Button>
					</div>
				</div>
				<InputGroup>
					<InputGroupInput
						placeholder={t('panel.tool.searchPlaceholder')}
						value={search}
						onChange={(event) => setSearch(event.target.value)}
					/>
					<InputGroupAddon align="inline-end">
						<Search />
					</InputGroupAddon>
				</InputGroup>
			</div>

			<div className="min-h-0 flex-1 overflow-y-auto rounded-lg border">
				{loading ? (
					<div className="flex h-full items-center justify-center">
						<p className="text-sm text-muted-foreground">{t('panel.loading')}</p>
					</div>
				) : filtered.length === 0 ? (
					<PanelEmpty
						icon={search ? SearchX : Wrench}
						title={search ? t('panel.search.emptyTitle') : t('panel.tool.emptyTitle')}
						description={
							search
								? t('panel.search.emptyDescription', { query: search })
								: t('panel.tool.emptyDescription')
						}
					/>
				) : (
					<div className="divide-y">
						{groups.map((group) =>
							group.tools.length ? (
								<section key={group.key}>
									<h3 className="bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground">
										{group.label}
									</h3>
									<div className="divide-y">
										{group.tools.map((tool) => {
											const presentation = getPresentation(tool);
											const checked = selectedSet.has(tool.name);
											return (
												<div
													key={tool.name}
													data-selected={checked || undefined}
													className="group flex items-start gap-3 px-3 py-3 transition-colors hover:bg-muted/30 data-[selected=true]:bg-primary/[0.04]"
												>
													<Checkbox
														checked={checked}
														disabled={!agent.editable || submitting}
														onCheckedChange={(value) =>
															toggleTool(tool.name, value === true)
														}
														aria-label={t(
															'panel.tool.toggleAssignment',
															{
																name: presentation.name,
															},
														)}
														className="mt-0.5"
													/>
													<button
														type="button"
														className="min-w-0 flex-1 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
														onClick={() => setSelectedName(tool.name)}
													>
														<span className="block text-sm font-medium group-hover:underline group-hover:underline-offset-4">
															{presentation.name}
														</span>
														{presentation.description ? (
															<span className="mt-1 line-clamp-2 block text-xs leading-relaxed text-muted-foreground">
																{presentation.description}
															</span>
														) : null}
													</button>
													<Button
														type="button"
														variant="ghost"
														size="icon-xs"
														aria-label={t('panel.tool.viewDetails', {
															name: presentation.name,
														})}
														onClick={() => setSelectedName(tool.name)}
													>
														<Info />
													</Button>
												</div>
											);
										})}
									</div>
								</section>
							) : null,
						)}
					</div>
				)}
			</div>
			{footer}
		</div>
	);
}
