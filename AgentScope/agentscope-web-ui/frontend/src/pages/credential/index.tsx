import {
	CircleAlert,
	CircleCheck,
	CircleX,
	FlaskConical,
	KeyRound,
	Loader2,
	Plus,
	PlusCircle,
	Pencil,
	RefreshCw,
	SlidersHorizontal,
	Trash2,
} from 'lucide-react';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useBeforeUnload, useBlocker } from 'react-router-dom';

import { credentialApi, ttsModelApi } from '@/api';
import type {
	CredentialEmbeddingModelEntry,
	CredentialModelCatalogResponse,
	CredentialModelDefinition,
	CredentialModelEntry,
	CredentialModelTestResponse,
	CredentialView,
	CredentialSchema,
	JSONSchema,
	TTSModelCard,
} from '@/api';
import { InputTypeBadges } from '@/components/badge/InputTypeBadges';
import {
	CredentialFields,
	type CredentialEditState,
} from '@/components/credential/CredentialFields';
import { ModelDefaultParametersDialog } from '@/components/credential/ModelDefaultParametersDialog';
import { CreateCredentialDialog } from '@/components/dialog/CreateCredentialDialog';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardAction,
	CardContent,
	CardFooter,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
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
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useCredentials } from '@/hooks/useCredentials';
import { useTranslation } from '@/i18n/useI18n';
import { modelParameterFields } from '@/lib/model-default-parameters';
import { CUSTOM_REQUEST_BODY_KEY } from '@/lib/model-parameters';
import { formatNumber } from '@/utils/common.ts';

class ModelProbeFailure extends Error {
	readonly result: CredentialModelTestResponse;

	constructor(message: string, result: CredentialModelTestResponse) {
		super(message);
		this.name = 'ModelProbeFailure';
		this.result = result;
	}
}

function ProviderRawResponse({ result }: { result: CredentialModelTestResponse }) {
	const { t } = useTranslation();
	if (!result.raw_response) return null;

	return (
		<div className="mt-2 min-w-0 rounded-md border border-border/70 bg-muted/60 p-2 text-foreground">
			<div className="mb-1.5 flex items-center justify-between gap-2 text-xs font-medium">
				<span>{t('credential.modelTest.rawResponse')}</span>
				{result.status_code != null && (
					<Badge variant="outline" className="h-5 font-mono text-xs">
						HTTP {result.status_code}
					</Badge>
				)}
			</div>
			<pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-xs leading-relaxed text-muted-foreground">
				{result.raw_response}
			</pre>
		</div>
	);
}

function ModelTestFeedback({
	result,
	successText,
}: {
	result: CredentialModelTestResponse;
	successText: string;
}) {
	const { t } = useTranslation();
	const message = result.success
		? successText
		: t(`messageBubble.error.${result.error_type ?? 'unknown'}`, {
				defaultValue: result.message,
			});

	return (
		<div aria-live="polite" className="min-w-0 text-xs">
			<div
				className={`flex items-start gap-1.5 ${
					result.success ? 'text-emerald-600' : 'text-destructive'
				}`}
			>
				{result.success ? (
					<CircleCheck className="mt-0.5 size-3.5 shrink-0" />
				) : (
					<CircleX className="mt-0.5 size-3.5 shrink-0" />
				)}
				<span>{message}</span>
			</div>
			{!result.success && <ProviderRawResponse result={result} />}
		</div>
	);
}

// ─── Manual model dialog ──────────────────────────────────────────────────────

interface ManualModelInput {
	model_type: 'chat' | 'embedding';
	name: string;
	label: string | null;
}

interface ManualModelDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onSave: (model: ManualModelInput) => Promise<void>;
	initialModel?: ManualModelInput | null;
}

function ManualModelDialog({ open, onOpenChange, onSave, initialModel }: ManualModelDialogProps) {
	const { t } = useTranslation();
	const [name, setName] = useState('');
	const [label, setLabel] = useState('');
	const [modelType, setModelType] = useState<'chat' | 'embedding'>('chat');
	const [submitting, setSubmitting] = useState(false);
	const [errorMessage, setErrorMessage] = useState<string | null>(null);
	const [probeFailure, setProbeFailure] = useState<CredentialModelTestResponse | null>(null);

	useEffect(() => {
		if (!open) return;
		setName(initialModel?.name ?? '');
		setLabel(initialModel?.label ?? '');
		setModelType(initialModel?.model_type ?? 'chat');
		setErrorMessage(null);
		setProbeFailure(null);
	}, [initialModel, open]);

	const handleSave = async () => {
		const trimmedName = name.trim();
		if (!trimmedName) return;

		setSubmitting(true);
		setErrorMessage(null);
		setProbeFailure(null);
		try {
			await onSave({
				model_type: modelType,
				name: trimmedName,
				label: label.trim() || null,
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ModelProbeFailure) {
				setProbeFailure(error.result);
			}
			setErrorMessage(
				error instanceof Error ? error.message : t('credential.modelProbe.failed'),
			);
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-h-[85dvh] w-[calc(100vw-2rem)] max-w-[35rem] overflow-y-auto sm:max-w-[35rem]">
				<DialogHeader>
					<DialogTitle>
						{t(
							initialModel
								? 'credential.editModelTitle'
								: 'credential.manualModelTitle',
						)}
					</DialogTitle>
					<DialogDescription>
						{t(
							initialModel
								? 'credential.editModelDescription'
								: 'credential.manualModelDescription',
						)}
					</DialogDescription>
				</DialogHeader>
				<div className="grid gap-4">
					<div className="grid gap-1.5">
						<Label htmlFor="manual-model-type">{t('credential.modelType')}</Label>
						<Select
							value={modelType}
							onValueChange={(value) => setModelType(value as 'chat' | 'embedding')}
							disabled={submitting}
						>
							<SelectTrigger id="manual-model-type" className="w-full">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="chat">
									{t('credential.modelTypes.chat')}
								</SelectItem>
								<SelectItem value="embedding">
									{t('credential.modelTypes.embedding')}
								</SelectItem>
							</SelectContent>
						</Select>
						{modelType === 'embedding' && (
							<p className="text-xs text-muted-foreground">
								{t('credential.embeddingProbeHint')}
							</p>
						)}
					</div>
					<div className="grid gap-1.5">
						<Label htmlFor="manual-model-name">{t('credential.modelId')}</Label>
						<Input
							id="manual-model-name"
							value={name}
							onChange={(event) => setName(event.target.value)}
							placeholder="qwen/qwen3-max"
							autoFocus
							disabled={submitting}
						/>
					</div>
					<div className="grid gap-1.5">
						<Label htmlFor="manual-model-label">{t('credential.modelLabel')}</Label>
						<Input
							id="manual-model-label"
							value={label}
							onChange={(event) => setLabel(event.target.value)}
							placeholder={t('credential.modelLabelPlaceholder')}
							disabled={submitting}
						/>
					</div>
					{errorMessage && (
						<div className="rounded-lg border border-destructive/25 bg-destructive/5 px-3 py-2 text-sm">
							<div className="flex items-start gap-2 text-destructive">
								<CircleAlert className="mt-0.5 size-4 shrink-0" />
								<span>{errorMessage}</span>
							</div>
							{probeFailure && <ProviderRawResponse result={probeFailure} />}
						</div>
					)}
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
						{t(initialModel ? 'credential.saveModel' : 'credential.addModel')}
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
	onEdit?: () => void;
	onConfigure: () => void;
	onTest: () => void;
	disabled: boolean;
	testDisabled: boolean;
	testing: boolean;
	testResult?: CredentialModelTestResponse;
}

function ModelCardItem({
	model,
	onRemove,
	onEdit,
	onConfigure,
	onTest,
	disabled,
	testDisabled,
	testing,
	testResult,
}: ModelCardItemProps) {
	const { t } = useTranslation();
	const ctx = model.context_size ? formatNumber(model.context_size) : null;

	const output = model.output_size ? formatNumber(model.output_size) : null;

	const statusVariant =
		model.status === 'active'
			? 'default'
			: model.status === 'deprecated'
				? 'secondary'
				: 'outline';

	const parameterProperties =
		(model.parameter_schema.properties as Record<string, unknown> | undefined) ?? {};
	const reasoning =
		model.output_types.includes('application/x-thinking') ||
		'thinking_enable' in parameterProperties ||
		'reasoning_effort' in parameterProperties ||
		'thinking_budget' in parameterProperties;
	const editableParameterKeys = new Set([
		...modelParameterFields(model.parameter_schema as unknown as JSONSchema).map(
			([key]) => key,
		),
		CUSTOM_REQUEST_BODY_KEY,
	]);
	const configuredParameterCount = Object.entries(model.default_parameters).filter(
		([key, value]) =>
			editableParameterKeys.has(key) &&
			value !== undefined &&
			value !== null &&
			value !== '' &&
			(key !== CUSTOM_REQUEST_BODY_KEY ||
				(typeof value === 'object' && Object.keys(value).length > 0)),
	).length;

	return (
		<Card className="h-full gap-4 border-border/80 py-4 shadow-none">
			<CardHeader>
				<div className="min-w-0">
					<CardTitle
						className="text-sm font-semibold leading-tight truncate"
						title={model.name}
					>
						{model.label || model.name}
					</CardTitle>
					<div
						className="mt-1 truncate font-mono text-xs text-muted-foreground"
						title={model.name}
					>
						{t('credential.modelId')}: {model.name}
					</div>
					<div className="mt-1 flex items-center gap-1.5">
						<Badge variant="secondary" className="text-xs">
							{t(`credential.modelSource.${model.source}`)}
						</Badge>
						{reasoning ? (
							<Badge variant={'outline'} className="text-xs">
								{t('credential.reasoning')}
							</Badge>
						) : null}
						{configuredParameterCount > 0 && (
							<Badge variant="default" className="text-xs">
								{t('credential.modelDefaults.configured', {
									count: configuredParameterCount,
								})}
							</Badge>
						)}
					</div>
				</div>
				<CardAction>
					<div className="flex items-center gap-1">
						<Button
							size="icon-sm"
							variant="ghost"
							onClick={onConfigure}
							disabled={disabled}
							tooltip={t('credential.modelDefaults.action')}
						>
							<SlidersHorizontal />
						</Button>
						{onEdit && (
							<Button
								size="icon-sm"
								variant="ghost"
								onClick={onEdit}
								disabled={disabled}
								tooltip={t('credential.editManualModel')}
							>
								<Pencil />
							</Button>
						)}
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
					</div>
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
						{output !== null && (
							<div className="flex justify-between items-center text-[14px]">
								<span className="text-muted-foreground">
									{t('credential.maxOutput')}
								</span>
								<span>{output}</span>
							</div>
						)}
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
			<CardFooter className="mt-auto flex-col items-stretch gap-2">
				<Button
					size="sm"
					variant="outline"
					className="w-full"
					onClick={onTest}
					disabled={testDisabled}
					tooltip={t('credential.modelTest.tooltip')}
				>
					{testing ? <Loader2 className="animate-spin" /> : <FlaskConical />}
					{testing
						? t('credential.modelTest.testing')
						: testResult
							? t('credential.modelTest.retest')
							: t('credential.modelTest.action')}
				</Button>
				{testResult && (
					<ModelTestFeedback
						result={testResult}
						successText={t('credential.modelTest.passed', {
							latency: testResult.latency_ms,
						})}
					/>
				)}
			</CardFooter>
		</Card>
	);
}

interface EmbeddingModelCardItemProps {
	model: CredentialEmbeddingModelEntry;
	onRemove: () => void;
	onEdit?: () => void;
	onTest: () => void;
	disabled: boolean;
	testDisabled: boolean;
	testing: boolean;
	testResult?: CredentialModelTestResponse;
}

function EmbeddingModelCardItem({
	model,
	onRemove,
	onEdit,
	onTest,
	disabled,
	testDisabled,
	testing,
	testResult,
}: EmbeddingModelCardItemProps) {
	const { t } = useTranslation();

	return (
		<Card className="h-full gap-4 border-border/80 py-4 shadow-none">
			<CardHeader>
				<div className="min-w-0">
					<CardTitle
						className="truncate text-sm font-semibold leading-tight"
						title={model.name}
					>
						{model.label || model.name}
					</CardTitle>
					<div
						className="mt-1 truncate font-mono text-xs text-muted-foreground"
						title={model.name}
					>
						{t('credential.modelId')}: {model.name}
					</div>
					<div className="mt-1 flex items-center gap-1.5">
						<Badge variant="secondary" className="text-xs">
							{t(`credential.modelSource.${model.source}`)}
						</Badge>
						<Badge variant="outline" className="text-xs">
							{t('credential.modelTypes.embedding')}
						</Badge>
					</div>
				</div>
				<CardAction>
					<div className="flex items-center gap-1">
						{onEdit && (
							<Button
								size="icon-sm"
								variant="ghost"
								onClick={onEdit}
								disabled={disabled}
								tooltip={t('credential.editManualModel')}
							>
								<Pencil />
							</Button>
						)}
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
					</div>
				</CardAction>
			</CardHeader>
			<CardContent className="flex flex-col gap-1">
				<div className="flex items-center justify-between text-[14px]">
					<span className="text-muted-foreground">
						{t('credential.embeddingDimensions')}
					</span>
					<span>{formatNumber(model.dimensions)}</span>
				</div>
				<div className="flex items-center justify-between text-[14px]">
					<span className="text-muted-foreground">{t('credential.inputTypes')}</span>
					<InputTypeBadges inputTypes={model.input_types} />
				</div>
			</CardContent>
			<CardFooter className="mt-auto flex-col items-stretch gap-2">
				<Button
					size="sm"
					variant="outline"
					className="w-full"
					onClick={onTest}
					disabled={testDisabled}
					tooltip={t('credential.modelTest.tooltip')}
				>
					{testing ? <Loader2 className="animate-spin" /> : <FlaskConical />}
					{testing
						? t('credential.modelTest.testing')
						: testResult
							? t('credential.modelTest.retest')
							: t('credential.modelTest.action')}
				</Button>
				{testResult && (
					<ModelTestFeedback
						result={testResult}
						successText={t('credential.modelTest.embeddingPassed', {
							latency: testResult.latency_ms,
							dimensions: testResult.dimensions ?? model.dimensions,
						})}
					/>
				)}
			</CardFooter>
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
		<Card className="h-full gap-4 border-border/80 py-4 shadow-none">
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
	schemaLoading: boolean;
	onReloadSchema: () => void;
	onUpdate: (id: string, body: { data: Record<string, unknown> }) => Promise<CredentialView>;
	editState: CredentialEditState;
	onEditStateChange: (state: CredentialEditState) => void;
	onDelete: () => void;
}

function DetailPanel({
	credential,
	schema,
	schemaLoading,
	onReloadSchema,
	onUpdate,
	editState,
	onEditStateChange,
	onDelete,
}: DetailPanelProps) {
	const { t } = useTranslation();
	const [catalog, setCatalog] = useState<CredentialModelCatalogResponse | null>(null);
	const [ttsModels, setTtsModels] = useState<TTSModelCard[]>([]);
	const [modelsLoading, setModelsLoading] = useState(false);
	const [discovering, setDiscovering] = useState(false);
	const [catalogSaving, setCatalogSaving] = useState(false);
	const [manualModelOpen, setManualModelOpen] = useState(false);
	const [editingManualModel, setEditingManualModel] = useState<CredentialModelDefinition | null>(
		null,
	);
	const [configuringModel, setConfiguringModel] = useState<CredentialModelEntry | null>(null);
	const [testingModel, setTestingModel] = useState<string | null>(null);
	const [testResults, setTestResults] = useState<Record<string, CredentialModelTestResponse>>({});
	const modelRequestSequence = useRef(0);

	const type = credential.data.type as string | undefined;

	const loadModels = useCallback(async () => {
		if (!type) return;
		const sequence = ++modelRequestSequence.current;
		setModelsLoading(true);
		try {
			const [chatCatalog, tts] = await Promise.all([
				credentialApi.models(credential.id),
				ttsModelApi
					.list(type)
					.then((res) => res.models)
					.catch(() => [] as TTSModelCard[]),
			]);
			if (sequence === modelRequestSequence.current) {
				setCatalog(chatCatalog);
				setTtsModels(tts);
			}
		} catch {
			if (sequence === modelRequestSequence.current) setCatalog(null);
		} finally {
			if (sequence === modelRequestSequence.current) setModelsLoading(false);
		}
	}, [credential.id, type]);

	const invalidateModelRequests = useCallback(() => {
		modelRequestSequence.current++;
	}, []);

	useEffect(() => {
		setTestingModel(null);
		setTestResults({});
		setEditingManualModel(null);
		setManualModelOpen(false);
		setConfiguringModel(null);
		void loadModels();
		return invalidateModelRequests;
	}, [loadModels, invalidateModelRequests]);

	const saveCatalog = useCallback(
		async (
			manualModels: CredentialModelDefinition[],
			hiddenModelIds: string[],
			hiddenEmbeddingModelIds: string[],
			modelDefaultParameters?: Record<string, Record<string, unknown>>,
		) => {
			setCatalogSaving(true);
			try {
				const result = await credentialApi.updateModels(credential.id, {
					manual_models: manualModels,
					hidden_model_ids: hiddenModelIds,
					hidden_embedding_model_ids: hiddenEmbeddingModelIds,
					model_default_parameters:
						modelDefaultParameters ?? catalog?.model_default_parameters ?? {},
				});
				setCatalog(result);
			} finally {
				setCatalogSaving(false);
			}
		},
		[credential.id, catalog?.model_default_parameters],
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

	const handleAddManualModel = async (input: ManualModelInput) => {
		if (!catalog) return;
		const original = editingManualModel;
		let model: CredentialModelDefinition;
		const canReuseEmbeddingMetadata =
			input.model_type === 'embedding' &&
			original?.model_type === 'embedding' &&
			original.name === input.name &&
			original.dimensions != null;

		if (canReuseEmbeddingMetadata) {
			model = {
				...original,
				...input,
			};
		} else if (input.model_type === 'embedding') {
			const probe = await credentialApi.probeEmbeddingModel(credential.id, {
				model: input.name,
				model_type: 'embedding',
			});
			if (!probe.success || probe.dimensions == null) {
				throw new ModelProbeFailure(
					t(`messageBubble.error.${probe.error_type ?? 'unknown'}`, {
						defaultValue: probe.message,
					}),
					probe,
				);
			}
			model = {
				...input,
				context_size: 8191,
				output_size: null,
				input_types: ['text/plain'],
				output_types: ['application/x-embedding'],
				dimensions: probe.dimensions,
			};
		} else {
			const existingChat = original?.model_type === 'chat' ? original : null;
			model = {
				...(existingChat ?? {}),
				...input,
				context_size: existingChat?.context_size ?? 128000,
				output_size: existingChat?.output_size ?? null,
				input_types: existingChat?.input_types ?? ['text/plain'],
				output_types: existingChat?.output_types ?? ['text/plain'],
				dimensions: null,
			};
		}
		const replacedNames = new Set(
			[model.name, original?.name].filter((value): value is string => Boolean(value)),
		);
		const manualModels = [
			...catalog.manual_models.filter((item) => !replacedNames.has(item.name)),
			model,
		];
		const modelDefaultParameters = {
			...catalog.model_default_parameters,
		};
		const previousParameters =
			input.model_type === 'chat'
				? {
						...(original
							? catalog.model_default_parameters[original.name]
							: catalog.model_default_parameters[model.name]),
					}
				: {};
		if (original && original.name !== model.name) {
			delete modelDefaultParameters[original.name];
		}
		if (Object.keys(previousParameters).length > 0) {
			modelDefaultParameters[model.name] = previousParameters;
		} else {
			delete modelDefaultParameters[model.name];
		}
		await saveCatalog(
			manualModels,
			catalog.hidden_model_ids.filter((id) => !replacedNames.has(id)),
			catalog.hidden_embedding_model_ids.filter((id) => !replacedNames.has(id)),
			modelDefaultParameters,
		);
	};

	const handleOpenAddModel = () => {
		setEditingManualModel(null);
		setManualModelOpen(true);
	};

	const handleOpenEditModel = (modelType: 'chat' | 'embedding', modelName: string) => {
		if (!catalog) return;
		const definition = catalog.manual_models.find(
			(item) => item.model_type === modelType && item.name === modelName,
		);
		if (!definition) return;
		setEditingManualModel(definition);
		setManualModelOpen(true);
	};

	const handleRemoveModel = async (model: CredentialModelEntry) => {
		if (!catalog) return;
		if (model.source === 'manual') {
			await saveCatalog(
				catalog.manual_models.filter(
					(item) => item.name !== model.name || item.model_type !== 'chat',
				),
				catalog.hidden_model_ids,
				catalog.hidden_embedding_model_ids,
			);
			return;
		}
		await saveCatalog(
			catalog.manual_models,
			[...catalog.hidden_model_ids.filter((id) => id !== model.name), model.name],
			catalog.hidden_embedding_model_ids,
		);
	};

	const handleRemoveEmbeddingModel = async (model: CredentialEmbeddingModelEntry) => {
		if (!catalog) return;
		if (model.source === 'manual') {
			await saveCatalog(
				catalog.manual_models.filter(
					(item) => item.name !== model.name || item.model_type !== 'embedding',
				),
				catalog.hidden_model_ids,
				catalog.hidden_embedding_model_ids,
			);
			return;
		}
		await saveCatalog(catalog.manual_models, catalog.hidden_model_ids, [
			...catalog.hidden_embedding_model_ids.filter((id) => id !== model.name),
			model.name,
		]);
	};

	const handleTestModel = async (modelType: 'chat' | 'embedding', modelName: string) => {
		const testKey = `${modelType}:${modelName}`;
		setTestingModel(testKey);
		try {
			const result = await credentialApi.testModel(credential.id, {
				model: modelName,
				model_type: modelType,
			});
			setTestResults((previous) => ({
				...previous,
				[testKey]: result,
			}));
		} finally {
			setTestingModel(null);
		}
	};

	const handleSaveModelDefaults = async (
		modelName: string,
		parameters: Record<string, unknown>,
	) => {
		if (!catalog) return;
		const nextDefaults = {
			...catalog.model_default_parameters,
		};
		if (Object.keys(parameters).length === 0) {
			delete nextDefaults[modelName];
		} else {
			nextDefaults[modelName] = parameters;
		}
		await saveCatalog(
			catalog.manual_models,
			catalog.hidden_model_ids,
			catalog.hidden_embedding_model_ids,
			nextDefaults,
		);
		setTestResults((previous) => {
			const next = { ...previous };
			delete next[`chat:${modelName}`];
			return next;
		});
	};

	const name = (credential.data.name as string | undefined) ?? credential.id;
	const activeModels = catalog?.models.filter((model) => model.enabled) ?? [];
	const activeEmbeddingModels = catalog?.embedding_models.filter((model) => model.enabled) ?? [];

	return (
		<div className="flex h-full min-h-0 flex-col">
			{/* Header */}
			<div className="flex min-h-16 shrink-0 items-center justify-between gap-4 border-b px-5 py-3">
				<div className="flex min-w-0 items-center gap-3">
					<div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
						<KeyRound className="size-4.5" />
					</div>
					<div className="min-w-0">
						<div className="flex items-center gap-2">
							<h2 className="truncate text-base font-semibold">{name}</h2>
							{!credential.editable && (
								<Badge variant="secondary" title={t('common.readOnlyTooltip')}>
									{t('common.readOnly')}
								</Badge>
							)}
						</div>
						<p className="mt-0.5 truncate text-sm text-muted-foreground">
							{schema?.title ?? type}
						</p>
					</div>
				</div>
				<div className="flex shrink-0 items-center gap-2">
					<Button
						size="icon-sm"
						variant="ghost"
						className="text-destructive hover:bg-destructive/10 hover:text-destructive"
						onClick={onDelete}
						disabled={!credential.editable || editState.busy}
						tooltip={credential.editable ? undefined : t('common.readOnlyTooltip')}
					>
						<Trash2 />
					</Button>
				</div>
			</div>

			<div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-5">
				<CredentialFields
					credential={credential}
					schema={schema}
					schemaLoading={schemaLoading}
					onReloadSchema={onReloadSchema}
					busy={discovering || catalogSaving || testingModel !== null}
					onStateChange={onEditStateChange}
					onSave={async (data) => {
						const updated = await onUpdate(credential.id, { data });
						setTestResults({});
						await loadModels();
						return updated;
					}}
				/>

				<fieldset
					disabled={editState.dirty || editState.busy}
					className="flex min-w-0 flex-col gap-5"
				>
					{/* Credential-scoped model catalog */}
					<section className="flex flex-col gap-4 rounded-xl border p-4">
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
										catalogSaving ||
										testingModel !== null
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
									onClick={handleOpenAddModel}
									disabled={
										!credential.editable ||
										catalogSaving ||
										testingModel !== null
									}
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
								<div className="mt-0.5 text-xs">{catalog.last_discovery_error}</div>
							</div>
						)}

						{modelsLoading ? (
							<div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
								{Array.from({ length: 4 }).map((_, i) => (
									<Skeleton key={i} className="h-20 rounded-lg" />
								))}
							</div>
						) : activeModels.length + activeEmbeddingModels.length === 0 ? (
							<Empty className="border-none py-6">
								<EmptyHeader>
									<EmptyTitle>{t('credential.noModels')}</EmptyTitle>
									<EmptyDescription>
										{t('credential.noModelsManualHint')}
									</EmptyDescription>
								</EmptyHeader>
							</Empty>
						) : (
							<div className="flex flex-col gap-5">
								{activeModels.length > 0 && (
									<section className="flex flex-col gap-2.5">
										<h4 className="text-xs font-semibold text-muted-foreground">
											{t('credential.modelTypes.chat')} ({activeModels.length}
											)
										</h4>
										<div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
											{activeModels.map((model) => {
												const testKey = `chat:${model.name}`;
												return (
													<ModelCardItem
														key={model.name}
														model={model}
														onRemove={() => handleRemoveModel(model)}
														onConfigure={() =>
															setConfiguringModel(model)
														}
														onEdit={
															model.source === 'manual'
																? () =>
																		handleOpenEditModel(
																			'chat',
																			model.name,
																		)
																: undefined
														}
														onTest={() =>
															handleTestModel('chat', model.name)
														}
														disabled={
															!credential.editable ||
															catalogSaving ||
															testingModel !== null
														}
														testDisabled={
															testingModel !== null || catalogSaving
														}
														testing={testingModel === testKey}
														testResult={testResults[testKey]}
													/>
												);
											})}
										</div>
									</section>
								)}
								{activeEmbeddingModels.length > 0 && (
									<section className="flex flex-col gap-2.5">
										<h4 className="text-xs font-semibold text-muted-foreground">
											{t('credential.modelTypes.embedding')} (
											{activeEmbeddingModels.length})
										</h4>
										<div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
											{activeEmbeddingModels.map((model) => {
												const testKey = `embedding:${model.name}`;
												return (
													<EmbeddingModelCardItem
														key={model.name}
														model={model}
														onRemove={() =>
															handleRemoveEmbeddingModel(model)
														}
														onEdit={
															model.source === 'manual'
																? () =>
																		handleOpenEditModel(
																			'embedding',
																			model.name,
																		)
																: undefined
														}
														onTest={() =>
															handleTestModel('embedding', model.name)
														}
														disabled={
															!credential.editable ||
															catalogSaving ||
															testingModel !== null
														}
														testDisabled={
															testingModel !== null || catalogSaving
														}
														testing={testingModel === testKey}
														testResult={testResults[testKey]}
													/>
												);
											})}
										</div>
									</section>
								)}
							</div>
						)}
					</section>

					{/* Available TTS Models */}
					{ttsModels.length > 0 && (
						<section className="flex flex-col gap-4 rounded-xl border p-4">
							<h3 className="text-sm font-semibold">
								{t('credential.availableTTSModels')} ({ttsModels.length})
							</h3>
							<div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
								{ttsModels.map((m) => (
									<TTSModelCardItem key={m.name} model={m} />
								))}
							</div>
						</section>
					)}
				</fieldset>
			</div>

			<ModelDefaultParametersDialog
				open={configuringModel !== null}
				onOpenChange={(open) => {
					if (!open) setConfiguringModel(null);
				}}
				model={configuringModel}
				credentialType={String(credential.data.type)}
				onSave={handleSaveModelDefaults}
			/>

			<ManualModelDialog
				open={manualModelOpen}
				onOpenChange={(open) => {
					setManualModelOpen(open);
					if (!open) setEditingManualModel(null);
				}}
				onSave={handleAddManualModel}
				initialModel={editingManualModel}
			/>
		</div>
	);
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export const CredentialPage = () => {
	const { t } = useTranslation();
	const { credentials, loading, remove, refetch, update } = useCredentials();
	const [schemas, setSchemas] = useState<CredentialSchema[]>([]);
	const [schemaLoading, setSchemaLoading] = useState(true);
	const [schemaRevision, setSchemaRevision] = useState(0);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [createOpen, setCreateOpen] = useState(false);
	const [createDefaultType, setCreateDefaultType] = useState<string | undefined>();
	const [deleteOpen, setDeleteOpen] = useState(false);
	const [editState, setEditState] = useState<CredentialEditState>({ dirty: false, busy: false });
	const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
	const blocker = useBlocker(
		({ currentLocation, nextLocation }) =>
			(editState.dirty || editState.busy) &&
			(currentLocation.pathname !== nextLocation.pathname ||
				currentLocation.search !== nextLocation.search ||
				currentLocation.hash !== nextLocation.hash),
	);
	const leave = (next: () => void) => {
		if (editState.busy) return;
		if (editState.dirty) setPendingAction(() => next);
		else next();
	};
	const cancelLeave = () => {
		setPendingAction(null);
		if (blocker.state === 'blocked') blocker.reset();
	};
	useEffect(() => {
		if (blocker.state === 'blocked' && !editState.dirty && !editState.busy) blocker.proceed();
	}, [blocker, editState.dirty, editState.busy]);
	useBeforeUnload(
		useCallback(
			(event) => {
				if (editState.dirty || editState.busy) {
					event.preventDefault();
					event.returnValue = '';
				}
			},
			[editState.dirty, editState.busy],
		),
	);

	useEffect(() => {
		let active = true;
		setSchemaLoading(true);
		credentialApi
			.schemas()
			.then((res) => {
				if (active) setSchemas(res.schemas);
			})
			.catch(() => {
				/* The field section offers a persistent retry. */
			})
			.finally(() => {
				if (active) setSchemaLoading(false);
			});
		return () => {
			active = false;
		};
	}, [schemaRevision]);

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
		setEditState({ dirty: false, busy: false });
		setSelectedId(null);
	}, [selectedCredential, remove]);

	return (
		<div className="flex h-full min-h-0 flex-col bg-muted/25">
			<header className="flex h-16 shrink-0 items-center justify-between gap-4 border-b bg-background px-5">
				<div className="min-w-0">
					<div className="flex items-center gap-2">
						<KeyRound className="size-5 text-primary" />
						<h1 className="text-lg font-semibold">{t('common.credential')}</h1>
					</div>
					<p className="mt-1 truncate text-xs text-muted-foreground">
						{t('credential.subtitle')}
					</p>
				</div>
				<Button onClick={() => handleOpenCreate()} disabled={editState.busy}>
					<Plus />
					{t('credential.addProvider')}
				</Button>
			</header>

			<main className="flex min-h-0 flex-1 p-4">
				<div className="grid min-h-0 min-w-0 flex-1 overflow-hidden rounded-xl border bg-background lg:grid-cols-[18rem_minmax(0,1fr)]">
					<aside className="flex min-h-0 flex-col border-b bg-muted/20 lg:border-r lg:border-b-0">
						<div className="border-b px-4 py-4">
							<div className="flex items-center justify-between gap-3">
								<h2 className="text-sm font-semibold">
									{t('credential.configured')}
								</h2>
								<Badge variant="secondary" className="tabular-nums">
									{totalConfigured}
								</Badge>
							</div>
							<p className="mt-1 text-xs leading-5 text-muted-foreground">
								{t('credential.selectHintDescription')}
							</p>
						</div>

						<nav className="min-h-0 flex-1 overflow-y-auto p-3">
							{loading ? (
								<div className="flex flex-col gap-2">
									{Array.from({ length: 3 }).map((_, i) => (
										<Skeleton key={i} className="h-12 rounded-lg" />
									))}
								</div>
							) : configuredGroups.length === 0 ? (
								<div className="rounded-lg border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">
									{groupedByType.length === 0
										? t('credential.noProviders')
										: t('credential.noConfigs')}
								</div>
							) : (
								<div className="flex flex-col gap-4">
									{configuredGroups.map(({ type, title, records }) => (
										<section key={type}>
											<div className="flex items-center justify-between gap-2 px-2 pb-1.5">
												<span className="truncate text-xs font-medium text-muted-foreground">
													{title}
												</span>
												<span className="text-xs tabular-nums text-muted-foreground">
													{records.length}
												</span>
											</div>
											<div className="flex flex-col gap-1">
												{records.map((rec) => {
													const name =
														(rec.data.name as string | undefined) ??
														rec.id;
													const isActive = selectedId === rec.id;
													return (
														<button
															type="button"
															key={rec.id}
															onClick={() => {
																if (selectedId !== rec.id)
																	leave(() =>
																		setSelectedId(rec.id),
																	);
															}}
															className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors active:translate-y-px ${
																isActive
																	? 'border-primary/25 bg-primary/8 text-foreground'
																	: 'border-transparent hover:bg-muted/80'
															}`}
														>
															<KeyRound className="size-4 shrink-0 text-muted-foreground" />
															<span className="min-w-0 flex-1 truncate text-sm font-medium">
																{name}
															</span>
															{!rec.editable && (
																<Badge
																	variant="secondary"
																	className="text-xs"
																	title={t(
																		'common.readOnlyTooltip',
																	)}
																>
																	{t('common.readOnly')}
																</Badge>
															)}
														</button>
													);
												})}
											</div>
										</section>
									))}
								</div>
							)}
						</nav>
					</aside>

					<section className="min-h-0 min-w-0 overflow-hidden bg-background">
						{selectedCredential ? (
							<DetailPanel
								key={selectedCredential.id}
								credential={selectedCredential}
								schema={selectedSchema}
								schemaLoading={schemaLoading}
								onReloadSchema={() => setSchemaRevision((current) => current + 1)}
								onUpdate={update}
								editState={editState}
								onEditStateChange={setEditState}
								onDelete={() => leave(() => setDeleteOpen(true))}
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
					</section>
				</div>
			</main>

			{/* Dialogs */}
			<Dialog
				open={pendingAction !== null || blocker.state === 'blocked'}
				onOpenChange={(open) => {
					if (!open && !editState.busy) cancelLeave();
				}}
			>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('credential.inlineEdit.unsavedTitle')}</DialogTitle>
						<DialogDescription>
							{t(
								editState.busy
									? 'credential.inlineEdit.waitForOperation'
									: 'credential.inlineEdit.unsavedDescription',
							)}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button variant="outline" disabled={editState.busy} onClick={cancelLeave}>
							{t('credential.inlineEdit.keepEditing')}
						</Button>
						<Button
							variant="destructive"
							disabled={editState.busy}
							onClick={() => {
								const next = pendingAction;
								setPendingAction(null);
								if (blocker.state === 'blocked') blocker.proceed();
								else next?.();
							}}
						>
							{t('credential.inlineEdit.discardAndLeave')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
			<CreateCredentialDialog
				open={createOpen}
				onOpenChange={setCreateOpen}
				defaultType={createDefaultType}
				onCreated={(credentialId) => {
					void refetch();
					leave(() => setSelectedId(credentialId));
				}}
			/>
			{selectedCredential && (
				<>
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
