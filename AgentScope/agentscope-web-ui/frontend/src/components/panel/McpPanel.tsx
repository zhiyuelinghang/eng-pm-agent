import {
	CircleAlert,
	Loader2,
	PackageOpen,
	RotateCcw,
	Save,
	Search,
	SearchX,
	Trash2,
	Upload,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import type { AgentMCPConfig, AgentView, ManagedMCPPackage, ManagedMCPTool } from '@/api';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { PanelCatalogRow } from '@/components/panel/PanelCatalogRow';
import { PanelEmpty } from '@/components/panel/PanelEmpty';
import { Alert, AlertDescription } from '@/components/ui/alert';
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
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface McpPanelProps {
	agent: AgentView | null;
	packages: ManagedMCPPackage[];
	loading?: boolean;
	uploading?: boolean;
	loadError?: Error | null;
	onUpload: (file: File) => Promise<void>;
	onRemove: (packageId: string) => Promise<void>;
	onSave: (agentId: string, config: AgentMCPConfig) => Promise<void>;
}

function sameIds(left: string[], right: string[]): boolean {
	if (left.length !== right.length) return false;
	const rightIds = new Set(right);
	return left.every((id) => rightIds.has(id));
}

function assignedIds(agent: AgentView | null): string[] {
	return [...(agent?.data.mcp_config?.allowed_mcp_ids ?? [])];
}

function isPlatformManaged(item: ManagedMCPPackage): boolean {
	return (item.platform_capabilities ?? []).includes('project_initialization_validation');
}

interface McpToolParameter {
	name: string;
	type: string;
	description: string | null;
	required: boolean;
}

function schemaTypeLabel(definition: Record<string, unknown>): string {
	const rawType = definition.type;
	if (Array.isArray(rawType)) {
		return rawType.filter((value): value is string => typeof value === 'string').join(' / ');
	}
	if (typeof rawType === 'string') {
		if (rawType !== 'array') return rawType;
		const items = definition.items;
		if (!items || typeof items !== 'object' || Array.isArray(items)) return rawType;
		return `array<${schemaTypeLabel(items as Record<string, unknown>)}>`;
	}
	const alternatives = Array.isArray(definition.anyOf)
		? definition.anyOf
		: Array.isArray(definition.oneOf)
			? definition.oneOf
			: [];
	if (alternatives.length) {
		const labels = alternatives
			.map((item) => {
				if (!item || typeof item !== 'object' || Array.isArray(item)) return '';
				const value = item as Record<string, unknown>;
				return typeof value.title === 'string' ? value.title : schemaTypeLabel(value);
			})
			.filter(Boolean);
		return [...new Set(labels)].join(' | ') || 'any';
	}
	return 'any';
}

function readMcpToolParameters(tool: ManagedMCPTool): McpToolParameter[] {
	const properties = tool.input_schema.properties;
	if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return [];
	const required = new Set(
		Array.isArray(tool.input_schema.required)
			? tool.input_schema.required.filter(
					(value): value is string => typeof value === 'string',
				)
			: [],
	);
	return Object.entries(properties).map(([name, rawDefinition]) => {
		const definition =
			rawDefinition && typeof rawDefinition === 'object' && !Array.isArray(rawDefinition)
				? (rawDefinition as Record<string, unknown>)
				: {};
		return {
			name,
			type: schemaTypeLabel(definition),
			description: typeof definition.description === 'string' ? definition.description : null,
			required: required.has(name),
		};
	});
}

function mcpToolDisplayName(tool: ManagedMCPTool): string {
	return tool.display_name?.trim() || tool.name;
}

/** Platform MCP catalogue, upload entry and agent-level assignment editor. */
export function McpPanel({
	agent,
	packages,
	loading = false,
	uploading = false,
	loadError = null,
	onUpload,
	onRemove,
	onSave,
}: McpPanelProps) {
	const { t } = useTranslation();
	const fileInputRef = useRef<HTMLInputElement>(null);
	const detailScrollRef = useRef<HTMLDivElement>(null);
	const detailSectionRefs = useRef<Record<string, HTMLElement | null>>({});
	const [search, setSearch] = useState('');
	const [draftIds, setDraftIds] = useState<string[]>(() => assignedIds(agent));
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [activeDetailSection, setActiveDetailSection] = useState('overview');
	const [deleteTarget, setDeleteTarget] = useState<ManagedMCPPackage | null>(null);
	const [submitting, setSubmitting] = useState(false);
	const [errorMsg, setErrorMsg] = useState('');

	useEffect(() => {
		setDraftIds(assignedIds(agent));
		setErrorMsg('');
	}, [agent]);

	useEffect(() => {
		if (loading) return;
		const assignableIds = new Set(
			packages.filter((item) => !isPlatformManaged(item)).map((item) => item.id),
		);
		setDraftIds((current) => current.filter((id) => assignableIds.has(id)));
	}, [loading, packages]);

	useEffect(() => {
		setActiveDetailSection('overview');
		detailScrollRef.current?.scrollTo({ top: 0 });
	}, [selectedId]);

	const persistedIds = useMemo(() => {
		if (loading) return assignedIds(agent);
		const assignableIds = new Set(
			packages.filter((item) => !isPlatformManaged(item)).map((item) => item.id),
		);
		return assignedIds(agent).filter((id) => assignableIds.has(id));
	}, [agent, loading, packages]);
	const persistedSet = useMemo(() => new Set(persistedIds), [persistedIds]);
	const selectedSet = useMemo(() => new Set(draftIds), [draftIds]);
	const assignablePackages = useMemo(
		() => packages.filter((item) => !isPlatformManaged(item)),
		[packages],
	);
	const isDirty = !sameIds(draftIds, persistedIds);
	const selectedPackage = packages.find((item) => item.id === selectedId) ?? null;
	const detailSections = selectedPackage
		? [
				{ id: 'overview', label: t('panel.mcp.details') },
				...selectedPackage.tools.map((tool) => ({
					id: `tool:${tool.name}`,
					label: mcpToolDisplayName(tool),
				})),
			]
		: [];
	const query = search.trim().toLowerCase();
	const filtered = query
		? packages.filter((item) =>
				[item.display_name, item.name, item.description, item.version]
					.join(' ')
					.toLowerCase()
					.includes(query),
			)
		: packages;

	const togglePackage = (packageId: string, checked: boolean) => {
		if (!agent?.editable || submitting) return;
		setErrorMsg('');
		setDraftIds((current) =>
			checked
				? [...new Set([...current, packageId])]
				: current.filter((id) => id !== packageId),
		);
	};

	const scrollToDetailSection = (sectionId: string) => {
		const container = detailScrollRef.current;
		const section = detailSectionRefs.current[sectionId];
		if (!container || !section) return;
		container.scrollTo({
			top: Math.max(0, section.offsetTop - 24),
			behavior: 'smooth',
		});
		setActiveDetailSection(sectionId);
	};

	const handleDetailScroll = () => {
		const container = detailScrollRef.current;
		if (!container) return;
		const position = container.scrollTop + 48;
		let current = 'overview';
		for (const section of detailSections) {
			const element = detailSectionRefs.current[section.id];
			if (!element || element.offsetTop > position) break;
			current = section.id;
		}
		setActiveDetailSection(current);
	};

	const handleUpload = async (file: File) => {
		setErrorMsg('');
		try {
			await onUpload(file);
			toast.success(t('panel.mcp.uploaded'));
		} catch (error) {
			setErrorMsg(formatApiErrorForAlert(error));
		} finally {
			if (fileInputRef.current) fileInputRef.current.value = '';
		}
	};

	const handleSave = async () => {
		if (!agent?.editable || !isDirty) return;
		setSubmitting(true);
		setErrorMsg('');
		try {
			await onSave(agent.id, { allowed_mcp_ids: draftIds });
			toast.success(t('panel.mcp.saved'));
		} catch (error) {
			setErrorMsg(formatApiErrorForAlert(error));
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<input
				ref={fileInputRef}
				type="file"
				accept=".zip,.mcp,.mcpb,application/zip"
				className="hidden"
				onChange={(event) => {
					const file = event.target.files?.[0];
					if (file) void handleUpload(file);
				}}
			/>

			<Dialog
				open={selectedPackage !== null}
				onOpenChange={(open) => {
					if (!open) setSelectedId(null);
				}}
			>
				{selectedPackage ? (
					<DialogContent className="grid h-[min(820px,calc(100dvh-2rem))] max-h-[calc(100dvh-2rem)] !w-[min(900px,calc(100vw-2rem))] !max-w-[900px] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
						<DialogHeader className="border-b px-6 py-5 pr-14">
							<DialogTitle className="text-xl leading-tight">
								{selectedPackage.display_name}
							</DialogTitle>
							<DialogDescription>
								{selectedPackage.name} · v{selectedPackage.version}
							</DialogDescription>
						</DialogHeader>
						<div className="grid min-h-0 grid-cols-1 md:grid-cols-[12rem_minmax(0,1fr)]">
							<nav
								aria-label={t('panel.mcp.directory')}
								className="flex gap-1 overflow-x-auto border-b bg-muted/20 p-3 md:flex-col md:overflow-x-hidden md:border-r md:border-b-0 md:px-3 md:py-5"
							>
								{detailSections.map((section, index) => {
									const active = activeDetailSection === section.id;
									return (
										<button
											key={section.id}
											type="button"
											aria-current={active ? 'location' : undefined}
											onClick={() => scrollToDetailSection(section.id)}
											className={`group flex min-w-max items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring md:min-w-0 ${
												active
													? 'bg-background text-[#c95622] shadow-sm ring-1 ring-border/70'
													: 'text-muted-foreground hover:bg-background/80 hover:text-foreground'
											}`}
											title={section.label}
										>
											<span
												aria-hidden="true"
												className={`flex size-5 shrink-0 items-center justify-center rounded-md text-xs tabular-nums ${
													active
														? 'bg-[#c95622]/10 text-[#c95622]'
														: 'bg-muted text-muted-foreground'
												}`}
											>
												{index === 0 ? 'i' : index}
											</span>
											<span className="truncate">{section.label}</span>
										</button>
									);
								})}
							</nav>

							<div
								ref={detailScrollRef}
								onScroll={handleDetailScroll}
								className="no-scrollbar relative min-h-0 overflow-y-auto scroll-smooth px-6 py-6"
							>
								<article className="mx-auto max-w-2xl">
									<section
										ref={(element) => {
											detailSectionRefs.current.overview = element;
										}}
										className="scroll-mt-6 pb-7"
									>
										<div className="flex items-baseline justify-between gap-3">
											<h2 className="text-lg font-semibold">
												{t('panel.mcp.details')}
											</h2>
											<span className="text-xs tabular-nums text-muted-foreground">
												{t('panel.mcp.tools', {
													count: selectedPackage.tools.length,
												})}
											</span>
										</div>
										<p className="mt-3 max-w-[65ch] whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
											{selectedPackage.description ||
												t('panel.mcp.noDescription')}
										</p>
									</section>

									{selectedPackage.tools.length ? (
										selectedPackage.tools.map((tool) => {
											const sectionId = `tool:${tool.name}`;
											const parameters = readMcpToolParameters(tool);
											return (
												<section
													key={tool.name}
													ref={(element) => {
														detailSectionRefs.current[sectionId] =
															element;
													}}
													className="scroll-mt-6 border-t py-7 first:border-t-0"
												>
													<div className="flex items-start justify-between gap-4">
														<div className="min-w-0">
															<h2 className="text-lg font-semibold">
																{mcpToolDisplayName(tool)}
															</h2>
															<code className="mt-1 block break-all text-xs text-muted-foreground">
																{tool.name}
															</code>
														</div>
														{tool.read_only ? (
															<Badge variant="outline">
																{t('panel.mcp.readOnly')}
															</Badge>
														) : null}
													</div>
													<p className="mt-3 max-w-[65ch] whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
														{tool.description ||
															t('panel.mcp.noToolDescription')}
													</p>

													<div className="mt-5 space-y-2">
														<h3 className="text-sm font-medium">
															{t('panel.mcp.parameters')}
														</h3>
														{parameters.length ? (
															<div className="divide-y rounded-lg border bg-background">
																{parameters.map((parameter) => (
																	<div
																		key={parameter.name}
																		className="px-3.5 py-3"
																	>
																		<div className="flex items-start justify-between gap-3">
																			<code className="break-all text-sm font-medium">
																				{parameter.name}
																			</code>
																			<span className="shrink-0 text-xs text-muted-foreground">
																				{parameter.required
																					? t(
																							'panel.mcp.required',
																						)
																					: t(
																							'panel.mcp.optional',
																						)}
																				{' · '}
																				{parameter.type}
																			</span>
																		</div>
																		{parameter.description ? (
																			<p className="mt-1.5 text-sm leading-5 text-muted-foreground">
																				{
																					parameter.description
																				}
																			</p>
																		) : null}
																	</div>
																))}
															</div>
														) : (
															<p className="text-sm text-muted-foreground">
																{t('panel.mcp.noParameters')}
															</p>
														)}
													</div>
												</section>
											);
										})
									) : (
										<p className="border-t py-7 text-sm text-muted-foreground">
											{t('panel.mcp.noTools')}
										</p>
									)}
								</article>
							</div>
						</div>
					<DialogFooter className="m-0 rounded-none border-t bg-background px-6 py-4 sm:justify-between">
						<Button
							variant="ghost"
							disabled={submitting}
							onClick={() => {
								setSelectedId(null);
								setDeleteTarget(selectedPackage);
							}}
						>
							<Trash2 />
							{t('common.delete')}
						</Button>
						<Button variant="outline" onClick={() => setSelectedId(null)}>
							{t('common.close')}
						</Button>
					</DialogFooter>
					</DialogContent>
				) : null}
			</Dialog>

			<div className="flex-none space-y-3 pb-3">
				<div className="flex items-center justify-between gap-3">
					<div className="flex min-w-0 items-baseline gap-1.5">
						<span className="truncate text-sm font-medium">{t('panel.mcp.catalogTitle')}</span>
						<span className="shrink-0 text-xs tabular-nums text-muted-foreground">
							{t('panel.mcp.selectedSummary', {
								selected: assignablePackages.filter((item) => selectedSet.has(item.id))
									.length,
								total: assignablePackages.length,
							})}
						</span>
					</div>
					<Button
						variant="outline"
						size="xs"
						disabled={uploading}
						onClick={() => fileInputRef.current?.click()}
					>
						{uploading ? <Loader2 className="animate-spin" /> : <Upload />}
						{uploading ? t('panel.mcp.uploading') : t('panel.mcp.upload')}
					</Button>
				</div>
				<InputGroup>
					<InputGroupInput
						value={search}
						placeholder={t('panel.mcp.searchPlaceholder')}
						onChange={(event) => setSearch(event.target.value)}
					/>
					<InputGroupAddon align="inline-end">
						<Search />
					</InputGroupAddon>
				</InputGroup>
			</div>

			<div className="min-h-0 flex-1">
				{loading ? (
					<div className="flex h-full items-center justify-center">
						<Loader2 className="size-5 animate-spin text-muted-foreground" />
					</div>
				) : filtered.length === 0 ? (
					<PanelEmpty
						icon={query ? SearchX : PackageOpen}
						title={query ? t('panel.search.emptyTitle') : t('panel.mcp.emptyTitle')}
						description={
							query
								? t('panel.search.emptyDescription', { query: search })
								: t('panel.mcp.emptyDescription')
						}
					/>
				) : (
					<div className="h-full overflow-y-auto rounded-lg border bg-background">
						<div className="divide-y">
							{filtered.map((item) => {
								const platformManaged = isPlatformManaged(item);
								const checked = selectedSet.has(item.id);
								return (
									<PanelCatalogRow
										key={item.id}
										title={item.display_name}
										description={item.description}
										metadata={<>{item.name} · {t('panel.mcp.tools', { count: item.tools.length })}</>}
										badge={
											<span className="flex items-center gap-1">
												{platformManaged ? (
													<Badge>{t('panel.mcp.platformManaged')}</Badge>
												) : null}
												<Badge variant="outline">v{item.version}</Badge>
											</span>
										}
										selected={!platformManaged && checked}
										checkbox={
											platformManaged
												? undefined
												: {
														checked,
														disabled: !agent?.editable || submitting,
														ariaLabel: item.display_name,
														onChange: (value) => togglePackage(item.id, value),
													}
										}
										onOpen={() => setSelectedId(item.id)}
										openLabel={item.display_name}
									/>
								);
							})}
						</div>
					</div>
				)}
			</div>

			<div className="flex-none space-y-2 pt-3">
				{!agent?.editable && agent ? (
					<Alert>
						<CircleAlert />
						<AlertDescription>{t('panel.mcp.readOnlyNotice')}</AlertDescription>
					</Alert>
				) : null}
				{errorMsg || loadError ? (
					<Alert variant="destructive">
						<CircleAlert />
						<AlertDescription className="whitespace-pre-wrap">
							{errorMsg || formatApiErrorForAlert(loadError)}
						</AlertDescription>
					</Alert>
				) : null}
				<div className="flex items-center justify-between border-t pt-3">
					<Button
						variant="ghost"
						size="sm"
						disabled={!isDirty || submitting}
						onClick={() => setDraftIds(persistedIds)}
					>
						<RotateCcw />
						{t('panel.mcp.discard')}
					</Button>
					<Button
						size="sm"
						disabled={!agent?.editable || !isDirty || submitting}
						onClick={() => void handleSave()}
					>
						{submitting ? <Loader2 className="animate-spin" /> : <Save />}
						{submitting ? t('common.saving') : t('panel.mcp.saveChanges')}
					</Button>
				</div>
			</div>

			<DeleteDialog
				open={deleteTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDeleteTarget(null);
				}}
				title={t('common.deleteTitle', {
					entity: 'MCP',
					name: deleteTarget?.display_name ?? '',
				})}
				description={t('panel.mcp.deleteDescription')}
				onConfirm={async () => {
					if (!deleteTarget) return;
					const packageId = deleteTarget.id;
					try {
						if (agent?.editable && persistedSet.has(packageId)) {
							const remainingIds = persistedIds.filter((id) => id !== packageId);
							await onSave(agent.id, { allowed_mcp_ids: remainingIds });
							setDraftIds(remainingIds);
						}
						await onRemove(packageId);
						setDraftIds((current) => current.filter((id) => id !== packageId));
						toast.success(t('panel.mcp.deleted'));
					} catch (error) {
						setErrorMsg(formatApiErrorForAlert(error));
					}
				}}
			/>
		</div>
	);
}
