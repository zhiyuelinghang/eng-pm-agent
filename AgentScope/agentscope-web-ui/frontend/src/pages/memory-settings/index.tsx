import {
	Blend,
	BrainCircuit,
	Cpu,
	Gauge,
	History,
	Loader2,
	MessageSquareText,
	RotateCcw,
	Save,
	Search,
	Sparkles,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { agentApi } from '@/api/agent';
import type { MemorySettings, MemorySettingsResponse } from '@/api/types';
import { LlmSelect } from '@/components/select/LlmSelect';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

interface NumberFieldProps {
	label: string;
	description: string;
	value: number;
	onChange: (value: number) => void;
	min?: number;
	max?: number;
	step?: number;
}

function NumberField({
	label,
	description,
	value,
	onChange,
	min,
	max,
	step = 1,
}: NumberFieldProps) {
	return (
		<div className="space-y-2 rounded-lg border bg-background p-4">
			<Label className="text-sm font-medium">{label}</Label>
			<Input
				type="number"
				value={Number.isFinite(value) ? value : ''}
				min={min}
				max={max}
				step={step}
				onChange={(event) => onChange(Number(event.target.value))}
				className="font-mono tabular-nums"
			/>
			<p className="text-xs leading-relaxed text-muted-foreground">{description}</p>
		</div>
	);
}

interface SwitchRowProps {
	label: string;
	description: string;
	checked: boolean;
	onCheckedChange: (checked: boolean) => void;
}

function SwitchRow({ label, description, checked, onCheckedChange }: SwitchRowProps) {
	return (
		<div className="flex items-start justify-between gap-4 rounded-lg border bg-background p-4">
			<div className="min-w-0">
				<Label className="text-sm font-medium">{label}</Label>
				<p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
			</div>
			<Switch checked={checked} onCheckedChange={onCheckedChange} />
		</div>
	);
}

interface PromptEditorProps {
	label: string;
	description: string;
	value: string;
	onChange: (value: string) => void;
	rows?: number;
}

function PromptEditor({ label, description, value, onChange, rows = 12 }: PromptEditorProps) {
	return (
		<div className="space-y-2 rounded-lg border bg-background p-4">
			<Label className="text-sm font-medium">{label}</Label>
			<p className="text-xs leading-relaxed text-muted-foreground">{description}</p>
			<Textarea
				value={value}
				onChange={(event) => onChange(event.target.value)}
				rows={rows}
				className="min-h-52 resize-y font-mono text-xs leading-relaxed"
			/>
		</div>
	);
}

const TAB_TRIGGER_CLASS =
	'group h-10 min-w-max flex-none justify-start gap-2.5 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors group-data-vertical/tabs:w-auto! group-data-vertical/tabs:justify-start! hover:bg-background/80 hover:text-foreground data-active:bg-background data-active:text-primary data-active:shadow-sm data-active:ring-1 data-active:ring-border/70 lg:min-w-0 lg:flex-none lg:group-data-vertical/tabs:w-full!';

const TAB_CONTENT_CLASS =
	'min-h-0 w-full overflow-y-auto bg-muted/10 p-4 sm:p-5 lg:col-start-2 lg:row-start-1 lg:p-6';

export function MemorySettingsPage() {
	const { t } = useTranslation();
	const navigate = useNavigate();
	const [response, setResponse] = useState<MemorySettingsResponse | null>(null);
	const [settings, setSettings] = useState<MemorySettings | null>(null);
	const [savedSettings, setSavedSettings] = useState<MemorySettings | null>(null);
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const [resetting, setResetting] = useState(false);

	useEffect(() => {
		let active = true;
		agentApi
			.getMemorySettings()
			.then((value) => {
				if (!active) return;
				setResponse(value);
				setSettings(value.settings);
				setSavedSettings(value.settings);
			})
			.catch((error) => {
				if (active) toast.error(formatApiErrorForAlert(error));
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, []);

	const isDirty = useMemo(
		() => JSON.stringify(settings) !== JSON.stringify(savedSettings),
		[settings, savedSettings],
	);

	const update = <K extends keyof MemorySettings>(key: K, value: MemorySettings[K]) => {
		setSettings((current) => (current ? { ...current, [key]: value } : current));
	};

	const save = async () => {
		if (!settings || !response) return;
		setSaving(true);
		try {
			const updated = await agentApi.updateMemorySettings({
				settings,
				expected_revision: response.revision,
			});
			setResponse(updated);
			setSettings(updated.settings);
			setSavedSettings(updated.settings);
			toast.success(t('memory-settings.messages.saved'));
		} catch (error) {
			toast.error(formatApiErrorForAlert(error));
		} finally {
			setSaving(false);
		}
	};

	const reset = async () => {
		if (!response || !window.confirm(t('memory-settings.messages.resetConfirm'))) return;
		setResetting(true);
		try {
			const updated = await agentApi.resetMemorySettings(response.revision);
			setResponse(updated);
			setSettings(updated.settings);
			setSavedSettings(updated.settings);
			toast.success(t('memory-settings.messages.reset'));
		} catch (error) {
			toast.error(formatApiErrorForAlert(error));
		} finally {
			setResetting(false);
		}
	};

	if (loading || !settings || !response) {
		return (
			<div className="flex h-full items-center justify-center bg-muted/25">
				<div className="flex items-center gap-2 text-sm text-muted-foreground">
					<Loader2 className="size-4 animate-spin" />
					{t('memory-settings.loading')}
				</div>
			</div>
		);
	}

	return (
		<div className="flex h-full min-h-0 flex-col bg-muted/25">
			<header className="flex shrink-0 flex-wrap items-center justify-between gap-4 border-b bg-background px-5 py-3">
				<div>
					<div className="flex items-center gap-2">
						<BrainCircuit className="size-5 text-primary" />
						<h1 className="text-lg font-semibold">{t('memory-settings.title')}</h1>
					</div>
					<p className="mt-1 text-xs text-muted-foreground">
						{t('memory-settings.description')}
					</p>
				</div>
				<div className="flex items-center gap-2">
					<Button variant="outline" onClick={reset} disabled={saving || resetting}>
						{resetting ? <Loader2 className="animate-spin" /> : <RotateCcw />}
						{t('memory-settings.actions.reset')}
					</Button>
					<Button onClick={save} disabled={!isDirty || saving || resetting}>
						{saving ? <Loader2 className="animate-spin" /> : <Save />}
						{t('memory-settings.actions.save')}
					</Button>
				</div>
			</header>

			<main className="flex min-h-0 flex-1 p-4 sm:p-5">
				<Tabs
					defaultValue="model"
					orientation="vertical"
					className="grid min-h-0 min-w-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden rounded-xl border bg-background lg:grid-cols-[14rem_minmax(0,1fr)] lg:grid-rows-1"
				>
					<aside className="min-h-0 border-b bg-muted/20 lg:border-r lg:border-b-0">
						<nav
							aria-label={t('memory-settings.title')}
							className="overflow-x-auto p-3 lg:h-full lg:overflow-x-visible lg:overflow-y-auto lg:py-5"
						>
							<TabsList className="h-auto w-max min-w-full flex-row! items-stretch justify-start gap-1 bg-transparent p-0 group-data-vertical/tabs:flex-row! lg:w-full lg:min-w-0 lg:flex-col! lg:group-data-vertical/tabs:flex-col!">
								<TabsTrigger value="model" className={TAB_TRIGGER_CLASS}>
									<Cpu />
									{t('memory-settings.tabs.model')}
								</TabsTrigger>
								<TabsTrigger value="retrieval" className={TAB_TRIGGER_CLASS}>
									<Search />
									{t('memory-settings.tabs.retrieval')}
								</TabsTrigger>
								<TabsTrigger value="compression" className={TAB_TRIGGER_CLASS}>
									<History />
									{t('memory-settings.tabs.compression')}
								</TabsTrigger>
								<TabsTrigger value="budgets" className={TAB_TRIGGER_CLASS}>
									<Gauge />
									{t('memory-settings.tabs.budgets')}
								</TabsTrigger>
								<TabsTrigger value="maintenance" className={TAB_TRIGGER_CLASS}>
									<Sparkles />
									{t('memory-settings.tabs.maintenance')}
								</TabsTrigger>
								<TabsTrigger value="prompts" className={TAB_TRIGGER_CLASS}>
									<MessageSquareText />
									{t('memory-settings.tabs.prompts')}
								</TabsTrigger>
							</TabsList>
						</nav>
					</aside>

					<TabsContent value="model" className={`${TAB_CONTENT_CLASS} space-y-4`}>
						<Card>
							<CardHeader>
								<CardTitle>{t('memory-settings.model.title')}</CardTitle>
								<CardDescription>
									{t('memory-settings.model.description')}
								</CardDescription>
							</CardHeader>
							<CardContent>
								<div className="space-y-3 rounded-lg border bg-background p-4">
									<div className="space-y-1">
										<Label className="text-sm font-medium">
											{t('memory-settings.fields.memoryModel')}
										</Label>
										<p className="text-xs leading-relaxed text-muted-foreground">
											{t('memory-settings.help.memoryModel')}
										</p>
									</div>
									<LlmSelect
										value={settings.memory_model_config}
										onChange={(value) => update('memory_model_config', value)}
										onAddCredential={() => navigate('/credential')}
										placeholder={t('memory-settings.model.followDefault')}
										allowClear
										clearLabel={t('memory-settings.model.followDefault')}
									/>
									<p className="text-xs leading-relaxed text-muted-foreground">
										{settings.memory_model_config
											? t('memory-settings.model.selectedNotice')
											: t('memory-settings.model.defaultNotice')}
									</p>
								</div>
							</CardContent>
						</Card>
					</TabsContent>

					<TabsContent value="retrieval" className={`${TAB_CONTENT_CLASS} space-y-4`}>
						<Card>
							<CardHeader>
								<CardTitle>{t('memory-settings.retrieval.title')}</CardTitle>
								<CardDescription>
									{t('memory-settings.retrieval.description')}
								</CardDescription>
							</CardHeader>
							<CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
								<NumberField
									label={t('memory-settings.fields.recallTopK')}
									description={t('memory-settings.help.recallTopK')}
									value={settings.recall_top_k}
									min={1}
									max={50}
									onChange={(value) => update('recall_top_k', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.recallThreshold')}
									description={t('memory-settings.help.recallThreshold')}
									value={settings.recall_threshold}
									min={0}
									max={1}
									step={0.01}
									onChange={(value) => update('recall_threshold', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.reinforceThreshold')}
									description={t('memory-settings.help.reinforceThreshold')}
									value={settings.recall_reinforce_threshold}
									min={0}
									max={1}
									step={0.01}
									onChange={(value) =>
										update('recall_reinforce_threshold', value)
									}
								/>
							</CardContent>
						</Card>

						<Card>
							<CardHeader>
								<CardTitle className="flex items-center gap-2">
									<Blend className="size-4" />
									{t('memory-settings.fusion.title')}
								</CardTitle>
								<CardDescription>
									{t('memory-settings.fusion.description')}
								</CardDescription>
							</CardHeader>
							<CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
								<NumberField
									label={t('memory-settings.fields.sourceLongTerm')}
									description={t('memory-settings.help.fusionWeight')}
									value={settings.fusion_weight_mem0}
									min={0}
									max={2}
									step={0.05}
									onChange={(value) => update('fusion_weight_mem0', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.sourceKnowledge')}
									description={t('memory-settings.help.fusionWeight')}
									value={settings.fusion_weight_kb}
									min={0}
									max={2}
									step={0.05}
									onChange={(value) => update('fusion_weight_kb', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.sourceTimeline')}
									description={t('memory-settings.help.fusionWeight')}
									value={settings.fusion_weight_timeline}
									min={0}
									max={2}
									step={0.05}
									onChange={(value) => update('fusion_weight_timeline', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.sourceExperience')}
									description={t('memory-settings.help.fusionWeight')}
									value={settings.fusion_weight_experience}
									min={0}
									max={2}
									step={0.05}
									onChange={(value) => update('fusion_weight_experience', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.sourceRelations')}
									description={t('memory-settings.help.fusionWeight')}
									value={settings.fusion_weight_graphrag}
									min={0}
									max={2}
									step={0.05}
									onChange={(value) => update('fusion_weight_graphrag', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.diversityBalance')}
									description={t('memory-settings.help.mmrLambda')}
									value={settings.fusion_mmr_lambda}
									min={0}
									max={1}
									step={0.05}
									onChange={(value) => update('fusion_mmr_lambda', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.rankingSmoothing')}
									description={t('memory-settings.help.rrfK')}
									value={settings.rrf_k}
									min={1}
									max={500}
									onChange={(value) => update('rrf_k', value)}
								/>
							</CardContent>
						</Card>

						<div className="grid gap-3 md:grid-cols-2">
							<SwitchRow
								label={t('memory-settings.fields.mem0Infer')}
								description={t('memory-settings.help.mem0Infer')}
								checked={settings.mem0_infer_enabled}
								onCheckedChange={(value) => update('mem0_infer_enabled', value)}
							/>
							<SwitchRow
								label={t('memory-settings.fields.mem0InferAsync')}
								description={t('memory-settings.help.mem0InferAsync')}
								checked={settings.mem0_infer_async}
								onCheckedChange={(value) => update('mem0_infer_async', value)}
							/>
						</div>
					</TabsContent>

					<TabsContent value="compression" className={`${TAB_CONTENT_CLASS} space-y-4`}>
						<Card>
							<CardHeader>
								<CardTitle>{t('memory-settings.compression.title')}</CardTitle>
								<CardDescription>
									{t('memory-settings.compression.description')}
								</CardDescription>
							</CardHeader>
							<CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
								<NumberField
									label={t('memory-settings.fields.compressionTrigger')}
									description={t('memory-settings.help.compressionTrigger')}
									value={settings.compression_trigger_ratio}
									min={0.1}
									max={0.9}
									step={0.01}
									onChange={(value) => update('compression_trigger_ratio', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.keepMessages')}
									description={t('memory-settings.help.keepMessages')}
									value={settings.compression_keep_messages}
									min={2}
									max={200}
									onChange={(value) => update('compression_keep_messages', value)}
								/>
								<div className="space-y-2 rounded-lg border bg-background p-4">
									<Label className="text-sm font-medium">
										{t('memory-settings.fields.compressionMode')}
									</Label>
									<select
										className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
										value={settings.compression_mode}
										onChange={(event) =>
											update(
												'compression_mode',
												event.target
													.value as MemorySettings['compression_mode'],
											)
										}
									>
										<option value="incremental">
											{t('memory-settings.options.incremental')}
										</option>
										<option value="full">
											{t('memory-settings.options.full')}
										</option>
									</select>
									<p className="text-xs leading-relaxed text-muted-foreground">
										{t('memory-settings.help.compressionMode')}
									</p>
								</div>
								<NumberField
									label={t('memory-settings.fields.emergencyRatio')}
									description={t('memory-settings.help.emergencyRatio')}
									value={settings.emergency_compression_ratio}
									min={0.9}
									max={1}
									step={0.01}
									onChange={(value) =>
										update('emergency_compression_ratio', value)
									}
								/>
								<NumberField
									label={t('memory-settings.fields.historianRatio')}
									description={t('memory-settings.help.historianRatio')}
									value={settings.historian_trigger_ratio}
									min={0.1}
									max={0.89}
									step={0.01}
									onChange={(value) => update('historian_trigger_ratio', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.maxConsecutive')}
									description={t('memory-settings.help.maxConsecutive')}
									value={settings.compression_max_consecutive}
									min={1}
									max={20}
									onChange={(value) =>
										update('compression_max_consecutive', value)
									}
								/>
								<NumberField
									label={t('memory-settings.fields.qualityThreshold')}
									description={t('memory-settings.help.qualityThreshold')}
									value={settings.compression_quality_threshold}
									min={0}
									max={1}
									step={0.01}
									onChange={(value) =>
										update('compression_quality_threshold', value)
									}
								/>
								<NumberField
									label={t('memory-settings.fields.minRounds')}
									description={t('memory-settings.help.minRounds')}
									value={settings.compression_min_rounds_between}
									min={0}
									max={100}
									onChange={(value) =>
										update('compression_min_rounds_between', value)
									}
								/>
							</CardContent>
						</Card>
						<SwitchRow
							label={t('memory-settings.fields.backgroundCompression')}
							description={t('memory-settings.help.backgroundCompression')}
							checked={settings.compression_background}
							onCheckedChange={(value) => update('compression_background', value)}
						/>
					</TabsContent>

					<TabsContent value="budgets" className={TAB_CONTENT_CLASS}>
						<Card>
							<CardHeader>
								<CardTitle>{t('memory-settings.budgets.title')}</CardTitle>
								<CardDescription>
									{t('memory-settings.budgets.description')}
								</CardDescription>
							</CardHeader>
							<CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
								<NumberField
									label={t('memory-settings.fields.systemBudget')}
									description={t('memory-settings.help.layerBudget')}
									value={settings.token_budget_system_prompt}
									min={256}
									max={200000}
									onChange={(value) =>
										update('token_budget_system_prompt', value)
									}
								/>
								<NumberField
									label={t('memory-settings.fields.skillBudget')}
									description={t('memory-settings.help.layerBudget')}
									value={settings.token_budget_skill_injection}
									min={0}
									max={200000}
									onChange={(value) =>
										update('token_budget_skill_injection', value)
									}
								/>
								<NumberField
									label={t('memory-settings.fields.summaryBudget')}
									description={t('memory-settings.help.layerBudget')}
									value={settings.token_budget_summary}
									min={256}
									max={200000}
									onChange={(value) => update('token_budget_summary', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.retrievalBudget')}
									description={t('memory-settings.help.layerBudget')}
									value={settings.token_budget_ltm_kb_timeline}
									min={256}
									max={200000}
									onChange={(value) =>
										update('token_budget_ltm_kb_timeline', value)
									}
								/>
								<NumberField
									label={t('memory-settings.fields.runtimeBudget')}
									description={t('memory-settings.help.layerBudget')}
									value={settings.token_budget_runtime}
									min={128}
									max={200000}
									onChange={(value) => update('token_budget_runtime', value)}
								/>
								<NumberField
									label={t('memory-settings.fields.historyBudget')}
									description={t('memory-settings.help.layerBudget')}
									value={settings.token_budget_recent_history}
									min={256}
									max={200000}
									onChange={(value) =>
										update('token_budget_recent_history', value)
									}
								/>
								<NumberField
									label={t('memory-settings.fields.outputReserve')}
									description={t('memory-settings.help.outputReserve')}
									value={settings.token_budget_output_reserve}
									min={256}
									max={200000}
									onChange={(value) =>
										update('token_budget_output_reserve', value)
									}
								/>
							</CardContent>
						</Card>
					</TabsContent>

					<TabsContent value="maintenance" className={`${TAB_CONTENT_CLASS} space-y-4`}>
						<div className="grid gap-3 md:grid-cols-2">
							<SwitchRow
								label={t('memory-settings.fields.dreamer')}
								description={t('memory-settings.help.dreamer')}
								checked={settings.dreamer_enabled}
								onCheckedChange={(value) => update('dreamer_enabled', value)}
							/>
							<SwitchRow
								label={t('memory-settings.fields.experienceConsolidation')}
								description={t('memory-settings.help.experienceConsolidation')}
								checked={settings.experience_event_driven_enabled}
								onCheckedChange={(value) =>
									update('experience_event_driven_enabled', value)
								}
							/>
						</div>
					</TabsContent>

					<TabsContent value="prompts" className={`${TAB_CONTENT_CLASS} space-y-4`}>
						<div className="flex items-start gap-3 rounded-lg border border-primary/20 bg-primary/5 p-4 text-sm">
							<BrainCircuit className="mt-0.5 size-4 shrink-0 text-primary" />
							<p className="leading-relaxed">{t('memory-settings.prompts.notice')}</p>
						</div>
						<PromptEditor
							label={t('memory-settings.fields.compressionSystemPrompt')}
							description={t('memory-settings.help.compressionSystemPrompt')}
							value={settings.compression_system_prompt}
							onChange={(value) => update('compression_system_prompt', value)}
						/>
						<PromptEditor
							label={t('memory-settings.fields.compressionUserPrompt')}
							description={t('memory-settings.help.compressionUserPrompt')}
							value={settings.compression_user_prompt}
							onChange={(value) => update('compression_user_prompt', value)}
						/>
						<PromptEditor
							label={t('memory-settings.fields.compressionIncrementalPrompt')}
							description={t('memory-settings.help.compressionUserPrompt')}
							value={settings.compression_incremental_prompt}
							onChange={(value) => update('compression_incremental_prompt', value)}
							rows={16}
						/>
						<PromptEditor
							label={t('memory-settings.fields.historianSystemPrompt')}
							description={t('memory-settings.help.historianSystemPrompt')}
							value={settings.historian_system_prompt}
							onChange={(value) => update('historian_system_prompt', value)}
						/>
					</TabsContent>
				</Tabs>
			</main>
		</div>
	);
}
