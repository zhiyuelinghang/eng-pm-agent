import {
	Eye,
	EyeOff,
	Loader2,
	Plus,
	PlusCircle,
	Pencil,
	RefreshCw,
	RotateCcw,
	Trash2,
} from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

import { credentialApi, ttsModelApi } from '@/api';
import type {
	CredentialModelCatalogResponse,
	CredentialModelDefinition,
	CredentialModelEntry,
	CredentialView,
	CredentialSchema,
	TTSModelCard,
} from '@/api';
import { InputTypeBadges } from '@/components/badge/InputTypeBadges';
import { CreateCredentialDialog } from '@/components/dialog/CreateCredentialDialog';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { EditCredentialDialog } from '@/components/dialog/EditCredentialDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import {
	Sidebar,
	SidebarContent,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
} from '@/components/ui/sidebar';
import { Skeleton } from '@/components/ui/skeleton';
import { useCredentials } from '@/hooks/useCredentials';
import { useTranslation } from '@/i18n/useI18n';
import { formatNumber } from '@/utils/common.ts';

// ─── Masked value ─────────────────────────────────────────────────────────────

function MaskedValue({ value }: { value: string }) {
	const [visible, setVisible] = useState(false);
	const masked = value.length > 8 ? value.slice(0, 4) + '••••••••' + value.slice(-4) : '••••••••';
	return (
		<span className="flex items-center gap-x-1.5 font-mono text-sm">
			{visible ? value : masked}
			<Button size={'icon-sm'} variant={'ghost'} onClick={() => setVisible((v) => !v)}>
				{visible ? <EyeOff /> : <Eye />}
			</Button>
		</span>
	);
}

// ─── Manual model dialog ──────────────────────────────────────────────────────

interface ManualModelDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onSave: (model: CredentialModelDefinition) => Promise<void>;
}

function ManualModelDialog({ open, onOpenChange, onSave }: ManualModelDialogProps) {
	const { t } = useTranslation();
	const [name, setName] = useState('');
	const [label, setLabel] = useState('');
	const [submitting, setSubmitting] = useState(false);

	useEffect(() => {
		if (!open) return;
		setName('');
		setLabel('');
	}, [open]);

	const handleSave = async () => {
		const trimmedName = name.trim();
		if (!trimmedName) return;

		setSubmitting(true);
		try {
			await onSave({
				name: trimmedName,
				label: label.trim() || null,
				// OpenAI-compatible GET /models responses normally do not
				// publish trustworthy token limits. Keep internal catalogue
				// defaults instead of asking the user to guess them.
				context_size: 128000,
				output_size: 8192,
				input_types: ['text/plain'],
				output_types: ['text/plain'],
			});
			onOpenChange(false);
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="!w-[460px] !max-w-[460px]">
				<DialogHeader>
					<DialogTitle>{t('credential.manualModelTitle')}</DialogTitle>
					<DialogDescription>
						{t('credential.manualModelDescription')}
					</DialogDescription>
				</DialogHeader>
				<div className="grid gap-4">
					<div className="grid gap-1.5">
						<Label htmlFor="manual-model-name">
							{t('credential.modelId')}
						</Label>
						<Input
							id="manual-model-name"
							value={name}
							onChange={(event) => setName(event.target.value)}
							placeholder="qwen/qwen3-max"
							autoFocus
						/>
					</div>
					<div className="grid gap-1.5">
						<Label htmlFor="manual-model-label">
							{t('credential.modelLabel')}
						</Label>
						<Input
							id="manual-model-label"
							value={label}
							onChange={(event) => setLabel(event.target.value)}
							placeholder={t('credential.modelLabelPlaceholder')}
						/>
					</div>
				</div>
				<DialogFooter>
					<Button
						variant="ghost"
						onClick={() => onOpenChange(false)}
						disabled={submitting}
					>
						{t('common.cancel')}
					</Button>
					<Button onClick={handleSave} disabled={submitting || !name.trim()}>
						{submitting ? (
							<Loader2 className="size-3.5 animate-spin" />
						) : (
							<PlusCircle className="size-3.5" />
						)}
						{t('credential.addModel')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

// ─── Model Card ───────────────────────────────────────────────────────────────

interface ModelCardItemProps {
	model: CredentialModelEntry;
	onRemove: () => void;
	disabled: boolean;
}

function ModelCardItem({ model, onRemove, disabled }: ModelCardItemProps) {
	const { t } = useTranslation();
	const ctx = model.context_size ? formatNumber(model.context_size) : null;

	const output = model.output_size ? formatNumber(model.output_size) : null;

	const statusVariant =
		model.status === 'active'
			? 'default'
			: model.status === 'deprecated'
				? 'secondary'
				: 'outline';

	const reasoning = model.input_types.includes('application/x-thinking');

	return (
		<Card className="shadow">
			<CardHeader>
				<div className="min-w-0">
					<CardTitle
						className="text-sm font-semibold leading-tight truncate"
						title={model.name}
					>
						{model.label || model.name}
					</CardTitle>
					<div className="mt-1 flex items-center gap-1.5">
						<Badge variant="secondary" className="text-[10px]">
							{t(`credential.modelSource.${model.source}`)}
						</Badge>
						{reasoning ? (
							<Badge variant={'outline'} className="text-[10px]">
								{t('credential.reasoning')}
							</Badge>
						) : null}
					</div>
				</div>
				<CardAction>
					<Button
						size="icon-sm"
						variant="ghost"
						onClick={onRemove}
						disabled={disabled}
						tooltip={t(
							model.source === 'manual'
								? 'credential.deleteManualModel'
								: 'credential.hideModel',
						)}
					>
						<Trash2 />
					</Button>
				</CardAction>
			</CardHeader>
			<CardContent className="flex flex-col">
				{model.status !== 'active' && (
					<Badge variant={statusVariant} className="text-xs">
						{model.status}
					</Badge>
				)}

				{model.source === 'builtin' && (
					<>
						<div className="flex justify-between items-center text-[14px]">
							<span className="text-muted-foreground">
								{t('credential.maxContext')}
							</span>
							<span>{ctx}</span>
						</div>
						<div className="flex justify-between items-center text-[14px]">
							<span className="text-muted-foreground">
								{t('credential.maxOutput')}
							</span>
							<span>{output}</span>
						</div>
					</>
				)}
				<div className="flex justify-between items-center text-[14px]">
					<span className="text-muted-foreground">{t('credential.inputTypes')}</span>
					<InputTypeBadges inputTypes={model.input_types} />
				</div>
				<div className="flex justify-between items-center text-[14px]">
					<span className="text-muted-foreground">{t('credential.outputTypes')}</span>
					<InputTypeBadges inputTypes={model.output_types} />
				</div>
			</CardContent>
		</Card>
	);
}

// ─── TTS Model Card ──────────────────────────────────────────────────────────

function TTSModelCardItem({ model }: { model: TTSModelCard }) {
	const { t } = useTranslation();

	const statusVariant =
		model.status === 'active'
			? 'default'
			: model.status === 'deprecated'
				? 'secondary'
				: 'outline';

	return (
		<Card className="shadow">
			<CardHeader>
				<CardTitle
					className="text-sm font-semibold leading-tight truncate"
					title={model.name}
				>
					{model.label || model.name}
				</CardTitle>
				{model.realtime && (
					<CardAction>
						<Badge variant="outline">Realtime</Badge>
					</CardAction>
				)}
			</CardHeader>
			<CardContent className="flex flex-col">
				{model.status !== 'active' && (
					<Badge variant={statusVariant} className="text-xs">
						{model.status}
					</Badge>
				)}
				<div className="flex justify-between items-center text-[14px]">
					<span className="text-muted-foreground">{t('credential.inputTypes')}</span>
					<InputTypeBadges inputTypes={model.input_types} />
				</div>
				<div className="flex justify-between items-center text-[14px]">
					<span className="text-muted-foreground">{t('credential.outputTypes')}</span>
					<InputTypeBadges inputTypes={model.output_types} />
				</div>
			</CardContent>
		</Card>
	);
}

// ─── Detail panel ─────────────────────────────────────────────────────────────

interface DetailPanelProps {
	credential: CredentialView;
	schema: CredentialSchema | null;
	onEdit: () => void;
	onDelete: () => void;
}

function DetailPanel({ credential, schema, onEdit, onDelete }: DetailPanelProps) {
	const { t } = useTranslation();
	const [catalog, setCatalog] = useState<CredentialModelCatalogResponse | null>(null);
	const [ttsModels, setTtsModels] = useState<TTSModelCard[]>([]);
	const [modelsLoading, setModelsLoading] = useState(false);
	const [discovering, setDiscovering] = useState(false);
	const [catalogSaving, setCatalogSaving] = useState(false);
	const [manualModelOpen, setManualModelOpen] = useState(false);

	const type = credential.data.type as string | undefined;

	const loadModels = useCallback(async () => {
		if (!type) return;
		setModelsLoading(true);
		try {
			const [chatCatalog, tts] = await Promise.all([
				credentialApi.models(credential.id),
				ttsModelApi
					.list(type)
					.then((res) => res.models)
					.catch(() => [] as TTSModelCard[]),
			]);
			setCatalog(chatCatalog);
			setTtsModels(tts);
		} catch {
			setCatalog(null);
		} finally {
			setModelsLoading(false);
		}
	}, [credential.id, type]);

	useEffect(() => {
		void loadModels();
	}, [loadModels]);

	const saveCatalog = useCallback(
		async (
			manualModels: CredentialModelDefinition[],
			hiddenModelIds: string[],
		) => {
			setCatalogSaving(true);
			try {
				const result = await credentialApi.updateModels(credential.id, {
					manual_models: manualModels,
					hidden_model_ids: hiddenModelIds,
				});
				setCatalog(result);
			} finally {
				setCatalogSaving(false);
			}
		},
		[credential.id],
	);

	const handleDiscover = async () => {
		if (!catalog?.discovery_supported) return;
		setDiscovering(true);
		try {
			const result = await credentialApi.discoverModels(credential.id);
			setCatalog(result);
		} catch {
			// The POST persists a safe discovery error on the credential.
			// Re-read it so the inline state explains the manual fallback.
			const current = await credentialApi.models(credential.id);
			setCatalog(current);
		} finally {
			setDiscovering(false);
		}
	};

	const handleAddManualModel = async (model: CredentialModelDefinition) => {
		if (!catalog) return;
		const manualModels = [
			...catalog.manual_models.filter((item) => item.name !== model.name),
			model,
		];
		await saveCatalog(
			manualModels,
			catalog.hidden_model_ids.filter((id) => id !== model.name),
		);
	};

	const handleRemoveModel = async (model: CredentialModelEntry) => {
		if (!catalog) return;
		if (model.source === 'manual') {
			await saveCatalog(
				catalog.manual_models.filter((item) => item.name !== model.name),
				catalog.hidden_model_ids,
			);
			return;
		}
		await saveCatalog(catalog.manual_models, [
			...catalog.hidden_model_ids.filter((id) => id !== model.name),
			model.name,
		]);
	};

	const handleRestoreModel = async (modelName: string) => {
		if (!catalog) return;
		await saveCatalog(
			catalog.manual_models,
			catalog.hidden_model_ids.filter((id) => id !== modelName),
		);
	};

	// Fields to display: use schema properties order, skip id/type/const fields
	const displayFields = schema
		? Object.entries(schema.properties).filter(
				([key, prop]) => key !== 'id' && key !== 'type' && prop.const === undefined,
			)
		: Object.entries(credential.data)
				.filter(([key]) => key !== 'id' && key !== 'type')
				.map(
					([key]) =>
						[key, { title: key, writeOnly: false }] as [
							string,
							{ title: string; writeOnly: boolean },
						],
				);

	const name = (credential.data.name as string | undefined) ?? credential.id;
	const activeModels = catalog?.models.filter((model) => model.enabled) ?? [];
	const hiddenModels = catalog?.models.filter((model) => !model.enabled) ?? [];

	return (
		<div className="flex flex-col gap-y-6 p-6 overflow-y-auto h-full">
			{/* Header */}
			<div className="flex items-start justify-between gap-x-4">
				<div className="flex flex-col gap-y-1">
					<h2 className="text-lg font-semibold">{name}</h2>
					<p className="text-muted-foreground text-sm">{type}</p>
					{!credential.editable && (
						<Badge variant="secondary" title={t('common.readOnlyTooltip')}>
							{t('common.readOnly')}
						</Badge>
					)}
				</div>
				<div className="flex items-center gap-x-2 shrink-0">
					<Button
						size="icon-sm"
						variant="outline"
						onClick={onEdit}
						disabled={!credential.editable}
						tooltip={credential.editable ? undefined : t('common.readOnlyTooltip')}
					>
						<Pencil />
					</Button>
					<Button
						size="icon-sm"
						variant="destructive"
						onClick={onDelete}
						disabled={!credential.editable}
						tooltip={credential.editable ? undefined : t('common.readOnlyTooltip')}
					>
						<Trash2 />
					</Button>
				</div>
			</div>

			{/* Fields */}
			<div className="flex flex-col gap-y-3">
				{displayFields.map(([key, prop]) => {
					const schemaProp = prop as {
						title?: string;
						writeOnly?: boolean;
						format?: string;
					};
					const label = schemaProp.title ?? key.replace(/_/g, ' ');
					const isSecret = schemaProp.writeOnly || schemaProp.format === 'password';
					const val = credential.data[key];
					if (val === undefined || val === null) return null;
					const strVal = String(val);
					return (
						<div key={key} className="flex flex-col gap-y-0.5">
							<span className="text-muted-foreground text-xs uppercase tracking-wide">
								{label}
							</span>
							{isSecret ? (
								<MaskedValue value={strVal} />
							) : (
								<span className="text-sm font-mono break-all">{strVal}</span>
							)}
						</div>
					);
				})}
			</div>

			<Separator />

			{/* Credential-scoped model catalog */}
			<div className="flex flex-col gap-y-4">
				<div className="flex items-start justify-between gap-4">
					<div>
						<h3 className="text-sm font-semibold">
							{t('credential.modelCatalog')}
							{catalog ? ` (${catalog.total})` : ''}
						</h3>
						<p className="mt-1 text-xs text-muted-foreground">
							{t('credential.modelCatalogDescription')}
						</p>
					</div>
					<div className="flex shrink-0 items-center gap-2">
						<Button
							size="sm"
							variant="outline"
							onClick={handleDiscover}
							disabled={
								!credential.editable ||
								!catalog?.discovery_supported ||
								discovering ||
								catalogSaving
							}
							tooltip={
								catalog?.discovery_supported
									? t('credential.discoverModels')
									: t('credential.discoveryUnsupported')
							}
						>
							<RefreshCw className={discovering ? 'animate-spin' : ''} />
							{t('credential.discoverModels')}
						</Button>
						<Button
							size="sm"
							onClick={() => setManualModelOpen(true)}
							disabled={!credential.editable || catalogSaving}
						>
							<Plus />
							{t('credential.manualAdd')}
						</Button>
					</div>
				</div>

				{catalog?.last_discovery_error && (
					<div className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">
						<div className="font-medium">
							{t('credential.discoveryFallbackTitle')}
						</div>
						<div className="mt-0.5 text-xs">
							{catalog.last_discovery_error}
						</div>
					</div>
				)}

				{modelsLoading ? (
					<div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
						{Array.from({ length: 4 }).map((_, i) => (
							<Skeleton key={i} className="h-20 rounded-lg" />
						))}
					</div>
				) : activeModels.length === 0 ? (
					<Empty className="border-none py-6">
						<EmptyHeader>
							<EmptyTitle>{t('credential.noModels')}</EmptyTitle>
							<EmptyDescription>
								{t('credential.noModelsManualHint')}
							</EmptyDescription>
						</EmptyHeader>
					</Empty>
				) : (
					<div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
						{activeModels.map((model) => (
							<ModelCardItem
								key={model.name}
								model={model}
								onRemove={() => handleRemoveModel(model)}
								disabled={!credential.editable || catalogSaving}
							/>
						))}
					</div>
				)}

				{hiddenModels.length > 0 && (
					<div className="rounded-lg border bg-muted/20">
						<div className="border-b px-3 py-2 text-xs font-medium text-muted-foreground">
							{t('credential.hiddenModels')} ({hiddenModels.length})
						</div>
						<div className="divide-y">
							{hiddenModels.map((model) => (
								<div
									key={model.name}
									className="flex items-center justify-between gap-3 px-3 py-2"
								>
									<div className="min-w-0">
										<div className="truncate text-sm font-medium">
											{model.label || model.name}
										</div>
										<div className="truncate font-mono text-xs text-muted-foreground">
											{model.name}
										</div>
									</div>
									<Button
										size="sm"
										variant="ghost"
										onClick={() => handleRestoreModel(model.name)}
										disabled={!credential.editable || catalogSaving}
									>
										<RotateCcw />
										{t('credential.restoreModel')}
									</Button>
								</div>
							))}
						</div>
					</div>
				)}
			</div>

			{/* Available TTS Models */}
			{ttsModels.length > 0 && (
				<>
					<Separator />
					<div className="flex flex-col gap-y-4">
						<h3 className="text-sm font-semibold">
							{t('credential.availableTTSModels')}({ttsModels.length})
						</h3>
						<div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
							{ttsModels.map((m) => (
								<TTSModelCardItem key={m.name} model={m} />
							))}
						</div>
					</div>
				</>
			)}

			<ManualModelDialog
				open={manualModelOpen}
				onOpenChange={setManualModelOpen}
				onSave={handleAddManualModel}
			/>
		</div>
	);
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export const CredentialPage = () => {
	const { t } = useTranslation();
	const { credentials, loading, remove, refetch } = useCredentials();
	const [schemas, setSchemas] = useState<CredentialSchema[]>([]);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [createOpen, setCreateOpen] = useState(false);
	const [createDefaultType, setCreateDefaultType] = useState<string | undefined>();
	const [editOpen, setEditOpen] = useState(false);
	const [deleteOpen, setDeleteOpen] = useState(false);

	useEffect(() => {
		credentialApi.schemas().then((res) => setSchemas(res.schemas));
	}, []);

	// Auto-select first credential
	useEffect(() => {
		if (!selectedId && credentials.length > 0) {
			setSelectedId(credentials[0].id);
		}
	}, [credentials, selectedId]);

	const selectedCredential = credentials.find((c) => c.id === selectedId) ?? null;
	const selectedSchema = selectedCredential
		? (schemas.find(
				(s) =>
					(s.properties.type?.const as string) ===
					(selectedCredential.data.type as string),
			) ?? null)
		: null;

	// Group credentials by type, then list all schema types (even empty ones)
	const groupedByType: Array<{ type: string; title: string; records: CredentialView[] }> =
		schemas.map((s) => {
			const type = s.properties.type?.const as string;
			return {
				type,
				title: s.title,
				records: credentials.filter((c) => c.data.type === type),
			};
		});

	// Split providers so the user's actual configuration leads, and the
	// (mostly empty) "add a provider" entries don't drown it out.
	const configuredGroups = groupedByType.filter((g) => g.records.length > 0);
	const totalConfigured = configuredGroups.reduce((n, g) => n + g.records.length, 0);

	const handleOpenCreate = useCallback((type?: string) => {
		setCreateDefaultType(type);
		setCreateOpen(true);
	}, []);

	const handleDelete = useCallback(async () => {
		if (!selectedCredential) return;
		await remove(selectedCredential.id);
		setSelectedId(null);
	}, [selectedCredential, remove]);

	return (
		<div className="flex h-full w-full">
			{/* Left sidebar */}
			<Sidebar collapsible="none" className="border-r">
				<SidebarHeader className={'flex flex-col mt-5 gap-y-1'}>
					<div className="text-lg font-semibold">{t('common.credential')}</div>
					<div className="text-muted-foreground text-xs">{t('credential.subtitle')}</div>
				</SidebarHeader>
				{/*<Separator />*/}
				<SidebarContent>
					{loading ? (
						<div className="flex flex-col gap-y-2 p-4">
							{Array.from({ length: 3 }).map((_, i) => (
								<Skeleton key={i} className="h-8 rounded" />
							))}
						</div>
					) : groupedByType.length === 0 ? (
						<Empty className="border-none py-8">
							<EmptyHeader>
								<EmptyTitle>{t('credential.noProviders')}</EmptyTitle>
							</EmptyHeader>
						</Empty>
					) : (
						<>
							{/* Configured credentials lead — this is what the user actually set up. */}
							{configuredGroups.length > 0 && (
								<SidebarGroup>
									<SidebarGroupLabel>
										{t('credential.configured')} ({totalConfigured})
									</SidebarGroupLabel>
									<SidebarGroupContent className="flex flex-col gap-y-4">
										{configuredGroups.map(({ type, title, records }) => (
											<div key={type}>
												<div className="px-2 pb-1.5 text-xs font-semibold text-foreground/70">
													{title}
												</div>
												<SidebarMenu className="pl-4">
													{records.map((rec) => {
														const name =
															(rec.data.name as string | undefined) ??
															rec.id;
														return (
															<SidebarMenuItem key={rec.id}>
																<SidebarMenuButton
																	isActive={selectedId === rec.id}
																	onClick={() =>
																		setSelectedId(rec.id)
																	}
																>
																	<span className="min-w-0 flex-1 truncate">
																		{name}
																	</span>
																	{!rec.editable && (
																		<Badge
																			variant="secondary"
																			className="text-[10px] px-1 py-0"
																			title={t(
																				'common.readOnlyTooltip',
																			)}
																		>
																			{t('common.readOnly')}
																		</Badge>
																	)}
																</SidebarMenuButton>
															</SidebarMenuItem>
														);
													})}
												</SidebarMenu>
											</div>
										))}
									</SidebarGroupContent>
								</SidebarGroup>
							)}

							{/* Add credential — every provider is an entry point (including
							    configured ones, to add more under the same provider). */}
							<SidebarGroup>
								<SidebarGroupLabel>{t('credential.addProvider')}</SidebarGroupLabel>
								<SidebarGroupContent>
									<SidebarMenu>
										{groupedByType.map(({ type, title }) => (
											<SidebarMenuItem key={type}>
												<SidebarMenuButton
													onClick={() => handleOpenCreate(type)}
												>
													<Plus />
													<span className="min-w-0 flex-1 truncate">
														{title}
													</span>
												</SidebarMenuButton>
											</SidebarMenuItem>
										))}
									</SidebarMenu>
								</SidebarGroupContent>
							</SidebarGroup>
						</>
					)}
				</SidebarContent>
			</Sidebar>

			{/* Right detail */}
			<main className="flex-1 min-h-0 overflow-hidden">
				{selectedCredential ? (
					<DetailPanel
						credential={selectedCredential}
						schema={selectedSchema}
						onEdit={() => setEditOpen(true)}
						onDelete={() => setDeleteOpen(true)}
					/>
				) : (
					<div className="flex h-full items-center justify-center">
						<Empty className="border-none">
							<EmptyHeader>
								<EmptyTitle>{t('credential.selectHint')}</EmptyTitle>
								<EmptyDescription>
									{t('credential.selectHintDescription')}
								</EmptyDescription>
							</EmptyHeader>
						</Empty>
					</div>
				)}
			</main>

			{/* Dialogs */}
			<CreateCredentialDialog
				open={createOpen}
				onOpenChange={setCreateOpen}
				defaultType={createDefaultType}
				onCreated={(credentialId) => {
					setSelectedId(credentialId);
					void refetch();
				}}
			/>
			{selectedCredential && (
				<>
					<EditCredentialDialog
						open={editOpen}
						onOpenChange={setEditOpen}
						credential={selectedCredential}
						onUpdated={() => refetch()}
					/>
					<DeleteDialog
						open={deleteOpen}
						onOpenChange={setDeleteOpen}
						title={t('common.deleteTitle', {
							entity: t('credential.deleteEntity'),
							name:
								(selectedCredential.data.name as string | undefined) ??
								selectedCredential.id,
						})}
						description={t('common.deleteDescription')}
						onConfirm={handleDelete}
					/>
				</>
			)}
		</div>
	);
};
