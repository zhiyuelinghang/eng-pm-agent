import {
	Braces,
	CircleAlert,
	CircleCheck,
	CircleX,
	Eye,
	EyeOff,
	FlaskConical,
	Loader2,
	Plus,
	PlusCircle,
	Pencil,
	RefreshCw,
	RotateCcw,
	SlidersHorizontal,
	ShieldCheck,
	Trash2,
} from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

import { credentialApi, ttsModelApi } from '@/api';
import type {
	CredentialEmbeddingModelEntry,
	CredentialModelCatalogResponse,
	CredentialModelDefinition,
	CredentialModelEntry,
	CredentialModelTestResponse,
	CredentialView,
	CredentialSchema,
	TTSModelCard,
} from '@/api';
import { InputTypeBadges } from '@/components/badge/InputTypeBadges';
import { ModelDefaultParametersDialog } from '@/components/credential/ModelDefaultParametersDialog';
import { PermissionReviewerPanel } from '@/components/credential/PermissionReviewerPanel';
import { CreateCredentialDialog } from '@/components/dialog/CreateCredentialDialog';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { EditCredentialDialog } from '@/components/dialog/EditCredentialDialog';
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
import { Textarea } from '@/components/ui/textarea';
import { useCredentials } from '@/hooks/useCredentials';
import { useTranslation } from '@/i18n/useI18n';
import { CUSTOM_REQUEST_BODY_KEY, parseCustomRequestBody } from '@/lib/model-parameters';
import { formatNumber } from '@/utils/common.ts';

const SYSTEM_PERMISSION_REVIEWER_ID = '__system_permission_reviewer__';

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
			<div className="mb-1.5 flex items-center justify-between gap-2 text-[11px] font-medium">
				<span>{t('credential.modelTest.rawResponse')}</span>
				{result.status_code != null && (
					<Badge variant="outline" className="h-5 font-mono text-[10px]">
						HTTP {result.status_code}
					</Badge>
				)}
			</div>
			<pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-muted-foreground">
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
	onSave: (model: ManualModelInput, customRequestBody: Record<string, unknown>) => Promise<void>;
	initialModel?: ManualModelInput | null;
	initialCustomRequestBody?: Record<string, unknown>;
}

function ManualModelDialog({
	open,
	onOpenChange,
	onSave,
	initialModel,
	initialCustomRequestBody,
}: ManualModelDialogProps) {
	const { t } = useTranslation();
	const [name, setName] = useState('');
	const [label, setLabel] = useState('');
	const [modelType, setModelType] = useState<'chat' | 'embedding'>('chat');
	const [customRequestText, setCustomRequestText] = useState('');
	const [submitting, setSubmitting] = useState(false);
	const [errorMessage, setErrorMessage] = useState<string | null>(null);
	const [customRequestError, setCustomRequestError] = useState<string | null>(null);
	const [probeFailure, setProbeFailure] = useState<CredentialModelTestResponse | null>(null);

	useEffect(() => {
		if (!open) return;
		setName(initialModel?.name ?? '');
		setLabel(initialModel?.label ?? '');
		setModelType(initialModel?.model_type ?? 'chat');
		setCustomRequestText(
			initialCustomRequestBody && Object.keys(initialCustomRequestBody).length > 0
				? JSON.stringify(initialCustomRequestBody, null, 2)
				: '',
		);
		setErrorMessage(null);
		setCustomRequestError(null);
		setProbeFailure(null);
	}, [initialCustomRequestBody, initialModel, open]);

	const handleSave = async () => {
		const trimmedName = name.trim();
		if (!trimmedName) return;

		let customRequestBody: Record<string, unknown> = {};
		const trimmedCustomRequest = customRequestText.trim();
		if (modelType === 'chat' && trimmedCustomRequest) {
			try {
				customRequestBody = parseCustomRequestBody(trimmedCustomRequest);
			} catch (error) {
				if (error instanceof Error && error.message === 'object_required') {
					setCustomRequestError(t('credential.modelDefaults.customObjectRequired'));
					return;
				}
				setCustomRequestError(t('credential.modelDefaults.customInvalid'));
				return;
			}
		}

		setSubmitting(true);
		setErrorMessage(null);
		setCustomRequestError(null);
		setProbeFailure(null);
		try {
			await onSave(
				{
					model_type: modelType,
					name: trimmedName,
					label: label.trim() || null,
				},
				customRequestBody,
			);
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
			<DialogContent className="max-h-[85vh] !w-[560px] !max-w-[560px] overflow-y-auto">
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
						/>
					</div>
					<div className="grid gap-1.5">
						<Label htmlFor="manual-model-label">{t('credential.modelLabel')}</Label>
						<Input
							id="manual-model-label"
							value={label}
							onChange={(event) => setLabel(event.target.value)}
							placeholder={t('credential.modelLabelPlaceholder')}
						/>
					</div>
					{modelType === 'chat' && (
						<div className="grid gap-2 rounded-lg border bg-muted/20 p-4">
							<Label
								htmlFor="manual-model-custom-request"
								className="flex items-center gap-2"
							>
								<Braces className="size-4" />
								{t('credential.modelDefaults.customTitle')}
							</Label>
							<p className="text-xs leading-relaxed text-muted-foreground">
								{t('credential.manualModelCustomParametersDescription')}
							</p>
							<Textarea
								id="manual-model-custom-request"
								value={customRequestText}
								onChange={(event) => {
									setCustomRequestText(event.target.value);
									setCustomRequestError(null);
								}}
								placeholder={t('credential.modelDefaults.customPlaceholder')}
								className="min-h-28 resize-y font-mono text-xs"
								aria-invalid={Boolean(customRequestError)}
								disabled={submitting}
							/>
							{customRequestError && (
								<p className="text-xs text-destructive">{customRequestError}</p>
							)}
							<pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-background p-2 text-[11px] leading-relaxed text-muted-foreground">
								{t('credential.modelDefaults.customExamples')}
							</pre>
						</div>
					)}
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
	const configuredParameterCount = Object.keys(model.default_parameters).length;

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
					<div
						className="mt-1 truncate font-mono text-[11px] text-muted-foreground"
						title={model.name}
					>
						{t('credential.modelId')}: {model.name}
					</div>
					<div className="mt-1 flex items-center gap-1.5">
						<Badge variant="secondary" className="text-[10px]">
							{t(`credential.modelSource.${model.source}`)}
						</Badge>
						{reasoning ? (
							<Badge variant={'outline'} className="text-[10px]">
								{t('credential.reasoning')}
							</Badge>
						) : null}
						{configuredParameterCount > 0 && (
							<Badge variant="default" className="text-[10px]">
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
		<Card className="shadow">
			<CardHeader>
				<div className="min-w-0">
					<CardTitle
						className="truncate text-sm font-semibold leading-tight"
						title={model.name}
					>
						{model.label || model.name}
					</CardTitle>
					<div
						className="mt-1 truncate font-mono text-[11px] text-muted-foreground"
						title={model.name}
					>
						{t('credential.modelId')}: {model.name}
					</div>
					<div className="mt-1 flex items-center gap-1.5">
						<Badge variant="secondary" className="text-[10px]">
							{t(`credential.modelSource.${model.source}`)}
						</Badge>
						<Badge variant="outline" className="text-[10px]">
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
	const [editingManualModel, setEditingManualModel] = useState<CredentialModelDefinition | null>(
		null,
	);
	const [configuringModel, setConfiguringModel] = useState<CredentialModelEntry | null>(null);
	const [testingModel, setTestingModel] = useState<string | null>(null);
	const [testResults, setTestResults] = useState<Record<string, CredentialModelTestResponse>>({});

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
		setTestingModel(null);
		setTestResults({});
		setEditingManualModel(null);
		setManualModelOpen(false);
		setConfiguringModel(null);
		void loadModels();
	}, [loadModels]);

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

	const handleAddManualModel = async (
		input: ManualModelInput,
		customRequestBody: Record<string, unknown>,
	) => {
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
				output_size: 1,
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
				output_size: existingChat?.output_size ?? 8192,
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
		if (input.model_type === 'chat' && Object.keys(customRequestBody).length > 0) {
			previousParameters[CUSTOM_REQUEST_BODY_KEY] = customRequestBody;
		} else {
			delete previousParameters[CUSTOM_REQUEST_BODY_KEY];
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

	const handleRestoreModel = async (modelName: string) => {
		if (!catalog) return;
		await saveCatalog(
			catalog.manual_models,
			catalog.hidden_model_ids.filter((id) => id !== modelName),
			catalog.hidden_embedding_model_ids,
		);
	};

	const handleRestoreEmbeddingModel = async (modelName: string) => {
		if (!catalog) return;
		await saveCatalog(
			catalog.manual_models,
			catalog.hidden_model_ids,
			catalog.hidden_embedding_model_ids.filter((id) => id !== modelName),
		);
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
	const activeEmbeddingModels = catalog?.embedding_models.filter((model) => model.enabled) ?? [];
	const hiddenEmbeddingModels = catalog?.embedding_models.filter((model) => !model.enabled) ?? [];

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
								!credential.editable || catalogSaving || testingModel !== null
							}
						>
							<Plus />
							{t('credential.manualAdd')}
						</Button>
					</div>
				</div>

				{catalog?.last_discovery_error && (
					<div className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">
						<div className="font-medium">{t('credential.discoveryFallbackTitle')}</div>
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
									{t('credential.modelTypes.chat')} ({activeModels.length})
								</h4>
								<div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
									{activeModels.map((model) => {
										const testKey = `chat:${model.name}`;
										return (
											<ModelCardItem
												key={model.name}
												model={model}
												onRemove={() => handleRemoveModel(model)}
												onConfigure={() => setConfiguringModel(model)}
												onEdit={
													model.source === 'manual'
														? () =>
																handleOpenEditModel(
																	'chat',
																	model.name,
																)
														: undefined
												}
												onTest={() => handleTestModel('chat', model.name)}
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
												onRemove={() => handleRemoveEmbeddingModel(model)}
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
										<div className="flex items-center gap-2">
											<div className="truncate text-sm font-medium">
												{model.label || model.name}
											</div>
											<Badge variant="outline" className="text-[10px]">
												{t('credential.modelTypes.chat')}
											</Badge>
										</div>
										<div className="truncate font-mono text-xs text-muted-foreground">
											{model.name}
										</div>
									</div>
									<Button
										size="sm"
										variant="ghost"
										onClick={() => handleRestoreModel(model.name)}
										disabled={
											!credential.editable ||
											catalogSaving ||
											testingModel !== null
										}
									>
										<RotateCcw />
										{t('credential.restoreModel')}
									</Button>
								</div>
							))}
						</div>
					</div>
				)}

				{hiddenEmbeddingModels.length > 0 && (
					<div className="rounded-lg border bg-muted/20">
						<div className="border-b px-3 py-2 text-xs font-medium text-muted-foreground">
							{t('credential.hiddenModels')} ({hiddenEmbeddingModels.length})
						</div>
						<div className="divide-y">
							{hiddenEmbeddingModels.map((model) => (
								<div
									key={model.name}
									className="flex items-center justify-between gap-3 px-3 py-2"
								>
									<div className="min-w-0">
										<div className="flex items-center gap-2">
											<div className="truncate text-sm font-medium">
												{model.label || model.name}
											</div>
											<Badge variant="outline" className="text-[10px]">
												{t('credential.modelTypes.embedding')}
											</Badge>
										</div>
										<div className="truncate font-mono text-xs text-muted-foreground">
											{model.name}
										</div>
									</div>
									<Button
										size="sm"
										variant="ghost"
										onClick={() => handleRestoreEmbeddingModel(model.name)}
										disabled={
											!credential.editable ||
											catalogSaving ||
											testingModel !== null
										}
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

			<ModelDefaultParametersDialog
				open={configuringModel !== null}
				onOpenChange={(open) => {
					if (!open) setConfiguringModel(null);
				}}
				model={configuringModel}
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
				initialCustomRequestBody={
					editingManualModel
						? (catalog?.model_default_parameters[editingManualModel.name]?.[
								CUSTOM_REQUEST_BODY_KEY
							] as Record<string, unknown> | undefined)
						: undefined
				}
			/>
		</div>
	);
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export const CredentialPage = () => {
	const { t } = useTranslation();
	const { credentials, loading, remove, refetch } = useCredentials();
	const [schemas, setSchemas] = useState<CredentialSchema[]>([]);
	const [selectedId, setSelectedId] = useState<string | null>(SYSTEM_PERMISSION_REVIEWER_ID);
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
							<SidebarGroup>
								<SidebarGroupLabel>
									{t('credential.permissionReviewer.systemGroup')}
								</SidebarGroupLabel>
								<SidebarGroupContent>
									<SidebarMenu>
										<SidebarMenuItem>
											<SidebarMenuButton
												isActive={
													selectedId === SYSTEM_PERMISSION_REVIEWER_ID
												}
												onClick={() =>
													setSelectedId(SYSTEM_PERMISSION_REVIEWER_ID)
												}
											>
												<ShieldCheck />
												<span className="min-w-0 flex-1 truncate">
													{t('credential.permissionReviewer.shortTitle')}
												</span>
												<Badge
													variant="secondary"
													className="text-[10px] px-1 py-0"
												>
													{t('credential.permissionReviewer.builtIn')}
												</Badge>
											</SidebarMenuButton>
										</SidebarMenuItem>
									</SidebarMenu>
								</SidebarGroupContent>
							</SidebarGroup>

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
				{selectedId === SYSTEM_PERMISSION_REVIEWER_ID ? (
					<PermissionReviewerPanel credentials={credentials} />
				) : selectedCredential ? (
					<DetailPanel
						key={selectedCredential.id}
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
