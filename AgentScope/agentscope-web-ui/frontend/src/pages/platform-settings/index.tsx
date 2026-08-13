import {
	Bot,
	CheckCircle2,
	Crown,
	Download,
	FileSearch,
	FolderKanban,
	Loader2,
	PackageCheck,
	ShieldCheck,
	Trash2,
	Upload,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { agentApi, mcpRegistryApi } from '@/api';
import type {
	AgentView,
	ManagedMCPVersion,
	PlatformMCPVersionBinding,
	PlatformSettings,
	ProjectInitializationValidationMCPConfig,
} from '@/api';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useAgents } from '@/hooks/useAgents';
import { useTranslation } from '@/i18n/useI18n';

type AssignmentKey = 'main' | 'initializer' | 'engineeringDocuments';

const validationVersionKey = (binding: PlatformMCPVersionBinding) =>
	`${binding.package_id}@${binding.version}`;

const bindingFromVersion = (
	version: ManagedMCPVersion,
): PlatformMCPVersionBinding => ({
	package_id: version.package_id,
	version: version.version,
});

function isMainCandidate(agent: AgentView) {
	return (
		agent.editable &&
		agent.data.platform_config.enabled &&
		agent.data.model_policy.mode === 'fixed' &&
		agent.data.model_policy.chat_model_config !== null
	);
}

export function PlatformSettingsPage() {
	const { t } = useTranslation();
	const { agents, loading: agentsLoading, refetch } = useAgents();
	const [settings, setSettings] = useState<PlatformSettings | null>(null);
	const [validationConfig, setValidationConfig] =
		useState<ProjectInitializationValidationMCPConfig | null>(null);
	const [validationSelectedKey, setValidationSelectedKey] = useState('');
	const [uploadingValidation, setUploadingValidation] = useState(false);
	const [downloadingValidation, setDownloadingValidation] = useState(false);
	const [validationDeleteTarget, setValidationDeleteTarget] =
		useState<ManagedMCPVersion | null>(null);
	const validationUploadRef = useRef<HTMLInputElement>(null);
	const [activeAssignment, setActiveAssignment] =
		useState<AssignmentKey>('main');
	const [mainSelectedId, setMainSelectedId] = useState<string>('');
	const [initializerSelectedId, setInitializerSelectedId] =
		useState<string>('');
	const [engineeringDocumentSelectedId, setEngineeringDocumentSelectedId] =
		useState<string>('');
	const [loading, setLoading] = useState(true);
	const [savingMain, setSavingMain] = useState(false);
	const [savingInitializer, setSavingInitializer] = useState(false);
	const [savingEngineeringDocument, setSavingEngineeringDocument] =
		useState(false);

	useEffect(() => {
		let active = true;
		Promise.all([
			agentApi.getPlatformSettings(),
			mcpRegistryApi.getInitializationValidationConfig(),
		])
			.then(async ([value, validation]) => {
				if (!active) return;
				setSettings(value);
				setValidationConfig(validation);
				setMainSelectedId(value.global_main_agent_id ?? '');
				setInitializerSelectedId(value.project_initializer_agent_id ?? '');
				setEngineeringDocumentSelectedId(
					value.engineering_document_agent_id ?? '',
				);
				const selectedBinding =
					value.project_initializer_validation_mcp ?? validation.current;
				setValidationSelectedKey(
					selectedBinding ? validationVersionKey(selectedBinding) : '',
				);
				await refetch();
			})
			.catch(() => undefined)
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [refetch]);

	const refreshValidationConfig = async () => {
		const next = await mcpRegistryApi.getInitializationValidationConfig();
		setValidationConfig(next);
		return next;
	};

	const candidates = useMemo(
		() =>
			agents
				.filter(isMainCandidate)
				.sort(
					(a, b) =>
						a.data.platform_config.sort_order -
							b.data.platform_config.sort_order ||
						a.data.name.localeCompare(b.data.name),
				),
		[agents],
	);
	const mainCandidates = candidates.filter(
		(agent) => agent.id !== initializerSelectedId,
	);
	const initializerCandidates = candidates.filter(
		(agent) => agent.id !== mainSelectedId,
	);
	const selectedAgent =
		agents.find((agent) => agent.id === mainSelectedId) ?? null;
	const selectedInitializer =
		agents.find((agent) => agent.id === initializerSelectedId) ?? null;
	const selectedEngineeringDocument =
		agents.find((agent) => agent.id === engineeringDocumentSelectedId) ?? null;
	const currentAgent =
		agents.find((agent) => agent.id === settings?.global_main_agent_id) ?? null;
	const currentInitializer =
		agents.find(
			(agent) => agent.id === settings?.project_initializer_agent_id,
		) ?? null;
	const currentEngineeringDocument =
		agents.find(
			(agent) => agent.id === settings?.engineering_document_agent_id,
		) ?? null;
	const selectedIsValid =
		selectedAgent !== null && isMainCandidate(selectedAgent);
	const initializerAgentIsValid =
		selectedInitializer !== null && isMainCandidate(selectedInitializer);
	const engineeringDocumentIsValid =
		selectedEngineeringDocument !== null &&
		isMainCandidate(selectedEngineeringDocument);
	const selectedValidationVersion =
		validationConfig?.versions.find(
			(version) =>
				validationVersionKey(bindingFromVersion(version)) ===
				validationSelectedKey,
		) ?? null;
	const currentValidationVersion =
		validationConfig?.versions.find((version) => {
			const current = settings?.project_initializer_validation_mcp;
			return (
				current !== null &&
				current !== undefined &&
				validationVersionKey(bindingFromVersion(version)) ===
					validationVersionKey(current)
			);
		}) ?? null;
	const initializerIsValid =
		initializerAgentIsValid && selectedValidationVersion !== null;
	const mainUnchanged =
		mainSelectedId === (settings?.global_main_agent_id ?? '');
	const validationUnchanged =
		validationSelectedKey ===
		(settings?.project_initializer_validation_mcp
			? validationVersionKey(settings.project_initializer_validation_mcp)
			: '');
	const initializerUnchanged =
		initializerSelectedId ===
			(settings?.project_initializer_agent_id ?? '') &&
		validationUnchanged;
	const engineeringDocumentUnchanged =
		engineeringDocumentSelectedId ===
		(settings?.engineering_document_agent_id ?? '');

	const saveMain = async () => {
		if (!mainSelectedId || !selectedIsValid) return;
		setSavingMain(true);
		try {
			const updated = await agentApi.updatePlatformSettings({
				global_main_agent_id: mainSelectedId,
			});
			setSettings(updated);
			await refetch();
			toast.success(t('platform-settings.saved'));
		} finally {
			setSavingMain(false);
		}
	};

	const saveInitializer = async () => {
		if (
			!initializerSelectedId ||
			!initializerIsValid ||
			!selectedValidationVersion
		)
			return;
		setSavingInitializer(true);
		try {
			const updated = await agentApi.updatePlatformSettings({
				project_initializer_agent_id: initializerSelectedId,
				project_initializer_validation_mcp: bindingFromVersion(
					selectedValidationVersion,
				),
			});
			setSettings(updated);
			await refreshValidationConfig();
			await refetch();
			toast.success(t('platform-settings.initializer.saved'));
		} finally {
			setSavingInitializer(false);
		}
	};

	const saveEngineeringDocument = async () => {
		if (!engineeringDocumentSelectedId || !engineeringDocumentIsValid) return;
		setSavingEngineeringDocument(true);
		try {
			const updated = await agentApi.updatePlatformSettings({
				engineering_document_agent_id: engineeringDocumentSelectedId,
			});
			setSettings(updated);
			await refetch();
			toast.success(t('platform-settings.engineeringDocuments.saved'));
		} finally {
			setSavingEngineeringDocument(false);
		}
	};

	const uploadValidationVersion = async (file: File) => {
		setUploadingValidation(true);
		try {
			const uploaded =
				await mcpRegistryApi.uploadInitializationValidationVersion(file);
			await refreshValidationConfig();
			if (!validationSelectedKey) {
				setValidationSelectedKey(
					validationVersionKey(bindingFromVersion(uploaded)),
				);
			}
			toast.success(t('platform-settings.initializer.validation.uploaded'));
		} catch (error) {
			toast.error(
				error instanceof Error
					? error.message
					: t('platform-settings.initializer.validation.uploadFailed'),
			);
		} finally {
			setUploadingValidation(false);
			if (validationUploadRef.current) validationUploadRef.current.value = '';
		}
	};

	const downloadValidationVersion = async () => {
		if (!selectedValidationVersion) return;
		setDownloadingValidation(true);
		try {
			await mcpRegistryApi.downloadInitializationValidationVersion(
				selectedValidationVersion.package_id,
				selectedValidationVersion.version,
			);
		} finally {
			setDownloadingValidation(false);
		}
	};

	const deleteValidationVersion = async () => {
		if (!validationDeleteTarget) return;
		const targetKey = validationVersionKey(
			bindingFromVersion(validationDeleteTarget),
		);
		await mcpRegistryApi.deleteInitializationValidationVersion(
			validationDeleteTarget.package_id,
			validationDeleteTarget.version,
		);
		const next = await refreshValidationConfig();
		if (validationSelectedKey === targetKey) {
			const fallback =
				next.current ??
				(next.versions[0] ? bindingFromVersion(next.versions[0]) : null);
			setValidationSelectedKey(
				fallback ? validationVersionKey(fallback) : '',
			);
		}
		toast.success(t('platform-settings.initializer.validation.deleted'));
	};

	const busy = loading || agentsLoading;
	const isMain = activeAssignment === 'main';
	const isInitializer = activeAssignment === 'initializer';
	const activeAgent = isMain
		? selectedAgent
		: isInitializer
			? selectedInitializer
			: selectedEngineeringDocument;
	const activeCandidates = isMain
		? mainCandidates
		: isInitializer
			? initializerCandidates
			: candidates;
	const activeSelectedId = isMain
		? mainSelectedId
		: isInitializer
			? initializerSelectedId
			: engineeringDocumentSelectedId;
	const activeValid = isMain
		? selectedIsValid
		: isInitializer
			? initializerIsValid
			: engineeringDocumentIsValid;
	const activeUnchanged = isMain
		? mainUnchanged
		: isInitializer
			? initializerUnchanged
			: engineeringDocumentUnchanged;
	const activeSaving = isMain
		? savingMain
		: isInitializer
			? savingInitializer
			: savingEngineeringDocument;
	const activeCurrent = isMain
		? currentAgent
		: isInitializer
			? currentInitializer
			: currentEngineeringDocument;
	const activeCurrentInvalid =
		activeCurrent !== null && !isMainCandidate(activeCurrent);
	const activePrefix = isMain
		? 'platform-settings.main'
		: isInitializer
			? 'platform-settings.initializer'
			: 'platform-settings.engineeringDocuments';
	const ActiveIcon = isMain ? Bot : isInitializer ? FileSearch : FolderKanban;
	const handleAgentSelection = (agentId: string) => {
		if (isMain) {
			setMainSelectedId(agentId);
		} else if (isInitializer) {
			setInitializerSelectedId(agentId);
		} else {
			setEngineeringDocumentSelectedId(agentId);
		}
	};
	const saveActiveAssignment = isMain
		? saveMain
		: isInitializer
			? saveInitializer
			: saveEngineeringDocument;
	const selectedValidationIsCurrent = Boolean(
		selectedValidationVersion &&
		settings?.project_initializer_validation_mcp &&
		validationVersionKey(bindingFromVersion(selectedValidationVersion)) ===
			validationVersionKey(settings.project_initializer_validation_mcp),
	);
	const canDeleteSelectedValidation = Boolean(
		selectedValidationVersion &&
		!selectedValidationIsCurrent &&
		selectedValidationVersion.active_instances === 0,
	);

	const assignmentItems = [
		{
			key: 'main' as const,
			icon: Bot,
			title: t('platform-settings.main.title'),
			agent: selectedAgent,
			isValid: selectedIsValid,
			isDirty: !mainUnchanged,
		},
		{
			key: 'initializer' as const,
			icon: FileSearch,
			title: t('platform-settings.initializer.title'),
			agent: selectedInitializer,
			isValid: initializerIsValid,
			isDirty: !initializerUnchanged,
		},
		{
			key: 'engineeringDocuments' as const,
			icon: FolderKanban,
			title: t('platform-settings.engineeringDocuments.title'),
			agent: selectedEngineeringDocument,
			isValid: engineeringDocumentIsValid,
			isDirty: !engineeringDocumentUnchanged,
		},
	];

	return (
		<div className="flex h-full min-h-0 flex-col bg-muted/25">
			<header className="flex h-16 shrink-0 items-center border-b bg-background px-5">
				<div>
					<div className="flex items-center gap-2">
						<Crown className="size-5 text-primary" />
						<h1 className="text-lg font-semibold">
							{t('platform-settings.title')}
						</h1>
					</div>
					<p className="mt-1 text-xs text-muted-foreground">
						{t('platform-settings.description')}
					</p>
				</div>
			</header>

			<main className="flex min-h-0 flex-1 flex-col p-4">
				<div className="grid min-h-0 flex-1 overflow-hidden rounded-xl border bg-background lg:grid-cols-[17.5rem_minmax(0,1fr)]">
					<aside className="flex min-h-0 flex-col border-b bg-muted/20 lg:border-r lg:border-b-0">
						<div className="border-b px-5 py-5">
							<div className="flex items-center justify-between gap-3">
								<h2 className="font-semibold">
									{t('platform-settings.assignments.title')}
								</h2>
								<Badge variant="secondary" className="tabular-nums">
									{assignmentItems.length}
								</Badge>
							</div>
							<p className="mt-1 text-sm leading-relaxed text-muted-foreground">
								{t('platform-settings.assignments.description')}
							</p>
						</div>

						<nav
							aria-label={t('platform-settings.assignments.title')}
							className="grid gap-2 overflow-y-auto p-3 sm:grid-cols-2 lg:grid-cols-1"
						>
							{assignmentItems.map((item) => {
								const ItemIcon = item.icon;
								const isActive = activeAssignment === item.key;
								return (
									<button
										key={item.key}
										type="button"
										aria-pressed={isActive}
										onClick={() => setActiveAssignment(item.key)}
										className={`group rounded-xl border px-3.5 py-3 text-left transition-all duration-200 active:translate-y-px ${
											isActive
												? 'border-[#c95622]/30 bg-[#c95622]/5 shadow-sm'
												: 'border-transparent hover:border-border hover:bg-background'
										}`}
									>
										<div className="flex items-start gap-3">
											<div
												className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
													isActive
														? 'bg-[#c95622] text-white'
														: 'bg-muted text-muted-foreground group-hover:text-foreground'
												}`}
											>
												<ItemIcon className="size-4" />
											</div>
											<div className="min-w-0 flex-1">
												<div className="flex items-center gap-2">
													<span className="truncate text-sm font-semibold">
														{item.title}
													</span>
													{item.isDirty && (
														<span className="size-1.5 shrink-0 rounded-full bg-[#c95622]" />
													)}
												</div>
												<p className="mt-1 truncate text-xs text-muted-foreground">
													{item.agent?.data.name ??
														t('platform-settings.assignments.unassigned')}
												</p>
												<div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
													<span
														className={`size-1.5 rounded-full ${
															item.isValid ? 'bg-emerald-500' : 'bg-muted-foreground/40'
														}`}
													/>
													{item.isDirty
														? t('platform-settings.assignments.pending')
														: item.isValid
															? t('platform-settings.assignments.assigned')
															: t('platform-settings.assignments.unassigned')}
												</div>
											</div>
										</div>
									</button>
								);
							})}
						</nav>
					</aside>

					<section className="flex min-h-0 flex-col">
						<header className="flex flex-wrap items-start justify-between gap-4 border-b px-6 py-5 sm:px-8 sm:py-6">
							<div className="flex min-w-0 items-start gap-3">
								<div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
									<ActiveIcon className="size-5" />
								</div>
								<div className="min-w-0">
									<p className="text-xs font-medium tracking-wide text-muted-foreground">
										{t('platform-settings.assignments.editor')}
									</p>
									<h2 className="mt-1 text-xl font-semibold tracking-tight">
										{t(`${activePrefix}.title`)}
									</h2>
									<p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
										{t(`${activePrefix}.description`)}
									</p>
								</div>
							</div>
							{activeValid && (
								<Badge className="gap-1.5">
									<CheckCircle2 className="size-3.5" />
									{t('platform-settings.main.ready')}
								</Badge>
							)}
						</header>

						<div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 sm:px-8">
							{busy ? (
								<div className="space-y-5">
									<Skeleton className="h-10 w-full" />
									<Skeleton className="h-44 w-full" />
								</div>
							) : (
								<div className="space-y-6">
									<div className="space-y-2">
										<label
											className="text-sm font-medium"
											htmlFor={`${activeAssignment}-agent`}
										>
											{t(`${activePrefix}.selector`)}
										</label>
										<Select
											value={activeSelectedId}
											onValueChange={handleAgentSelection}
										>
											<SelectTrigger
												id={`${activeAssignment}-agent`}
												className="w-full"
											>
												<SelectValue placeholder={t(`${activePrefix}.placeholder`)} />
											</SelectTrigger>
											<SelectContent>
												{activeCandidates.map((agent) => (
													<SelectItem key={agent.id} value={agent.id}>
														{agent.data.name}
													</SelectItem>
												))}
											</SelectContent>
										</Select>
										<p className="text-xs leading-relaxed text-muted-foreground">
											{t(`${activePrefix}.requirement`)}
										</p>
									</div>

									{activeAgent ? (
										<section className="rounded-xl border bg-muted/20 p-4 sm:p-5">
											<div className="flex flex-wrap items-start justify-between gap-4">
												<div className="flex min-w-0 items-start gap-3">
													<div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-background shadow-sm ring-1 ring-border">
														<Bot className="size-5 text-muted-foreground" />
													</div>
													<div className="min-w-0">
														<div className="flex flex-wrap items-center gap-2">
															<h3 className="font-semibold">{activeAgent.data.name}</h3>
															<Badge variant="secondary">
																{isMain
																	? activeAgent.data.platform_config.category
																	: isInitializer
																		? t('platform-settings.initializer.internal')
																			: t(
																				'platform-settings.engineeringDocuments.roleBadge',
																			)}
															</Badge>
														</div>
														<p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
															{activeAgent.data.platform_config.description ||
																activeAgent.data.invite_config.invite_description ||
																t('platform-settings.main.noDescription')}
														</p>
													</div>
												</div>
												{activeValid && (
													<Badge variant="outline" className="gap-1.5 bg-background">
														<span className="size-1.5 rounded-full bg-emerald-500" />
														{t('platform-settings.assignments.available')}
													</Badge>
												)}
											</div>

											<dl className={`mt-5 grid gap-3 ${isMain ? 'sm:grid-cols-2' : ''}`}>
												<div className="rounded-lg bg-background px-3.5 py-3 ring-1 ring-border/70">
													<dt className="text-xs text-muted-foreground">
														{t('platform-settings.main.model')}
													</dt>
													<dd className="mt-1 font-mono text-sm font-medium">
														{activeAgent.data.model_policy.chat_model_config?.model ??
															t('platform-settings.main.notConfigured')}
													</dd>
												</div>
												{isMain && (
													<div className="rounded-lg bg-background px-3.5 py-3 ring-1 ring-border/70">
														<dt className="text-xs text-muted-foreground">
															{t('platform-settings.main.permission')}
														</dt>
														<dd className="mt-1 font-mono text-sm font-medium">
															{activeAgent.data.platform_config.permission_mode}
														</dd>
													</div>
												)}
											</dl>
										</section>
									) : (
										<Alert>
											{isMain ? (
												<ShieldCheck />
											) : isInitializer ? (
												<FileSearch />
											) : (
												<FolderKanban />
											)}
											<AlertTitle>{t(`${activePrefix}.unconfiguredTitle`)}</AlertTitle>
											<AlertDescription>
												{activeCandidates.length === 0
													? t(`${activePrefix}.noCandidates`)
													: t(`${activePrefix}.unconfigured`)}
											</AlertDescription>
										</Alert>
									)}

									{isInitializer && (
										<section className="rounded-xl border bg-muted/20 p-4 sm:p-5">
											<div className="flex flex-wrap items-start justify-between gap-3">
												<div className="flex min-w-0 items-start gap-3">
													<div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-background shadow-sm ring-1 ring-border">
														<PackageCheck className="size-5 text-muted-foreground" />
													</div>
													<div className="min-w-0">
														<div className="flex flex-wrap items-center gap-2">
															<h3 className="font-semibold">
																{t('platform-settings.initializer.validation.title')}
															</h3>
															<Badge variant="secondary">
																{t('platform-settings.initializer.validation.required')}
															</Badge>
														</div>
														<p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
															{t('platform-settings.initializer.validation.description')}
														</p>
													</div>
												</div>
												<input
													ref={validationUploadRef}
													type="file"
													accept=".zip,.mcp,.mcpb"
													className="hidden"
													onChange={(event) => {
														const file = event.target.files?.[0];
														if (file) void uploadValidationVersion(file);
													}}
												/>
												<Button
													variant="outline"
													size="sm"
													disabled={uploadingValidation}
													onClick={() => validationUploadRef.current?.click()}
												>
													{uploadingValidation ? (
														<Loader2 className="animate-spin" />
													) : (
														<Upload />
													)}
													{t('platform-settings.initializer.validation.upload')}
												</Button>
											</div>

											<div className="mt-5 space-y-2">
												<label
													className="text-sm font-medium"
													htmlFor="initialization-validation-version"
												>
													{t('platform-settings.initializer.validation.selector')}
												</label>
												<div className="flex min-w-0 items-center gap-2">
													<div className="min-w-0 flex-1">
														<Select
															value={validationSelectedKey}
															onValueChange={setValidationSelectedKey}
															disabled={!validationConfig?.versions.length}
														>
															<SelectTrigger
																id="initialization-validation-version"
																className="w-full"
															>
																<SelectValue
																	placeholder={t(
																		'platform-settings.initializer.validation.placeholder',
																	)}
																/>
															</SelectTrigger>
															<SelectContent>
																{validationConfig?.versions.map((version) => {
																	const binding = bindingFromVersion(version);
																	return (
																		<SelectItem
																			key={validationVersionKey(binding)}
																			value={validationVersionKey(binding)}
																		>
																			{version.display_name} · v{version.version}
																		</SelectItem>
																	);
																})}
															</SelectContent>
														</Select>
													</div>
													<div className="flex shrink-0 flex-nowrap items-center gap-2 whitespace-nowrap">
														<Button
															variant="outline"
															size="sm"
															className="whitespace-nowrap"
															disabled={!selectedValidationVersion || downloadingValidation}
															onClick={() => void downloadValidationVersion()}
														>
															{downloadingValidation ? (
																<Loader2 className="animate-spin" />
															) : (
																<Download />
															)}
															{t('platform-settings.initializer.validation.download')}
														</Button>
														<Button
															variant="outline"
															size="sm"
															className="whitespace-nowrap"
															disabled={!canDeleteSelectedValidation}
															title={
																selectedValidationIsCurrent
																	? t(
																		'platform-settings.initializer.validation.deleteCurrentHint',
																	)
																	: selectedValidationVersion?.active_instances
																		? t(
																			'platform-settings.initializer.validation.deleteRunningHint',
																			)
																		: undefined
															}
															onClick={() =>
																setValidationDeleteTarget(selectedValidationVersion)
															}
														>
															<Trash2 />
															{t('platform-settings.initializer.validation.delete')}
														</Button>
													</div>
												</div>
												<p className="text-xs leading-relaxed text-muted-foreground">
													{t('platform-settings.initializer.validation.current')}{' '}
													<span className="font-medium text-foreground">
														{currentValidationVersion
															? `${currentValidationVersion.display_name} · v${currentValidationVersion.version}`
															: t('platform-settings.initializer.validation.unconfigured')}
													</span>
												</p>
											</div>
										</section>
									)}

									{activeCurrentInvalid && (
										<Alert variant="destructive">
											<AlertTitle>{t(`${activePrefix}.invalidCurrentTitle`)}</AlertTitle>
											<AlertDescription>{t(`${activePrefix}.invalidCurrent`)}</AlertDescription>
										</Alert>
									)}
								</div>
							)}
						</div>

						<footer className="flex flex-col items-stretch justify-between gap-4 border-t bg-muted/20 px-6 py-4 sm:flex-row sm:items-center sm:px-8">
							<p className="max-w-2xl text-xs leading-relaxed text-muted-foreground">
								{t(`${activePrefix}.effect`)}
							</p>
							<Button
								onClick={saveActiveAssignment}
								disabled={busy || activeSaving || activeUnchanged || !activeValid}
								className="shrink-0"
							>
								{activeSaving && <Loader2 className="animate-spin" />}
								{activeSaving
									? t('common.saving')
									: t(`${activePrefix}.save`)}
							</Button>
						</footer>
					</section>
				</div>
			</main>

			<DeleteDialog
				open={validationDeleteTarget !== null}
				onOpenChange={(open) => {
					if (!open) setValidationDeleteTarget(null);
				}}
				title={t('platform-settings.initializer.validation.deleteTitle', {
					version: validationDeleteTarget?.version ?? '',
				})}
				description={t(
					'platform-settings.initializer.validation.deleteDescription',
				)}
				confirmLabel={t('common.delete')}
				onConfirm={deleteValidationVersion}
			/>
		</div>
	);
}
