import { BrainCircuit, Loader2, RefreshCw, RotateCcw, Save } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBeforeUnload, useBlocker, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { agentApi } from '@/api/agent';
import { ApiError } from '@/api/client';
import type { MemorySettings, MemorySettingsResponse } from '@/api/types';
import { LlmSelect } from '@/components/select/LlmSelect';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { useAvailableModels } from '@/hooks/useAvailableModels';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';
import {
	memorySettingsChanges,
	memorySettingsRequest,
	mergeMemorySettings,
	pickMemorySettings,
	sameMemoryValue,
	validateMemorySettings,
	type MemorySettingsKey,
	type MemoryValidationError,
} from '@/lib/memory-settings';

type BooleanSetting =
	| 'learning_enabled'
	| 'learning_interactions_enabled'
	| 'learning_business_events_enabled'
	| 'group_learning_enabled';
type Conflict = { latest: MemorySettingsResponse | null; error: string };

export function MemorySettingsPage() {
	const { i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const text = (cn: string, en: string) => (zh ? cn : en);
	const navigate = useNavigate();
	const catalogue = useAvailableModels();
	const availableModels = useMemo(
		() =>
			Object.entries(catalogue.groups).flatMap(([type, credentials]) =>
				credentials.flatMap(({ credential, models }) =>
					models.map((model) => ({
						type,
						credential_id: credential.id,
						model: model.name,
					})),
				),
			),
		[catalogue.groups],
	);
	const [response, setResponse] = useState<MemorySettingsResponse | null>(null);
	const [settings, setSettings] = useState<MemorySettings | null>(null);
	const [loadVersion, setLoadVersion] = useState(0);
	const [loading, setLoading] = useState(true);
	const [loadError, setLoadError] = useState('');
	const [saveError, setSaveError] = useState('');
	const [validation, setValidation] = useState<MemoryValidationError[]>([]);
	const [saving, setSaving] = useState(false);
	const savingRef = useRef(false);
	const [refreshing, setRefreshing] = useState(false);
	const [conflict, setConflict] = useState<Conflict | null>(null);
	const [choices, setChoices] = useState<Partial<Record<MemorySettingsKey, 'local' | 'remote'>>>(
		{},
	);
	const busy = saving || refreshing;
	const dirty = Boolean(
		settings && response && !sameMemoryValue(settings, pickMemorySettings(response.settings)),
	);
	const blocker = useBlocker(
		({ currentLocation, nextLocation }) =>
			(dirty || busy) &&
			(currentLocation.pathname !== nextLocation.pathname ||
				currentLocation.search !== nextLocation.search ||
				currentLocation.hash !== nextLocation.hash),
	);
	useBeforeUnload(
		useCallback(
			(event) => {
				if (dirty || busy) {
					event.preventDefault();
					event.returnValue = '';
				}
			},
			[dirty, busy],
		),
	);

	useEffect(() => {
		let active = true;
		setLoading(true);
		setLoadError('');
		agentApi
			.getMemorySettings({ silent: true })
			.then((value) => {
				if (active) {
					setResponse(value);
					setSettings(pickMemorySettings(value.settings));
				}
			})
			.catch((error) => {
				if (active) setLoadError(formatApiErrorForAlert(error));
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [loadVersion]);

	const readLatest = async () => {
		setRefreshing(true);
		try {
			const latest = await agentApi.getMemorySettings({ silent: true });
			setConflict({ latest, error: '' });
			setChoices({});
		} catch (error) {
			setConflict({ latest: null, error: formatApiErrorForAlert(error) });
		} finally {
			setRefreshing(false);
		}
	};
	const update = <K extends keyof MemorySettings>(key: K, value: MemorySettings[K]) => {
		setSettings((previous) => (previous ? { ...previous, [key]: value } : previous));
		setValidation([]);
		setSaveError('');
	};
	const validationText = (error: MemoryValidationError) => {
		if (error.code === 'model_required')
			return text(
				'启用后台学习前，请选择学习模型。',
				'Select a learning model before enabling background learning.',
			);
		if (error.code === 'source_required')
			return text(
				'启用后台学习时，至少选择一个学习来源。',
				'Enable at least one learning source.',
			);
		return text(
			'该模型当前不可用，请重新选择或清空。',
			'This model is unavailable. Select another model or clear the selection.',
		);
	};
	const save = async (): Promise<boolean> => {
		if (!settings || !response || savingRef.current || conflict) return false;
		const needsCatalogue =
			settings.learning_enabled ||
			settings.learning_model_config !== null ||
			settings.compression_model_config !== null;
		if (needsCatalogue && (catalogue.loading || catalogue.error)) {
			setSaveError(
				text(
					'模型目录暂不可用，请重新读取后再保存。草稿已保留。',
					'The model catalogue is unavailable. Reload it before saving. Your draft is preserved.',
				),
			);
			return false;
		}
		const errors = validateMemorySettings(settings, availableModels);
		setValidation(errors);
		if (errors.length) {
			setSaveError(
				text(
					'请检查标出的设置后再保存。',
					'Review the highlighted settings before saving.',
				),
			);
			const target = document.getElementById(`memory-${errors[0].field}`);
			(target?.querySelector<HTMLButtonElement>('button') ?? target)?.focus();
			return false;
		}
		savingRef.current = true;
		setSaving(true);
		setSaveError('');
		try {
			const value = await agentApi.updateMemorySettings(
				memorySettingsRequest(settings, response.revision),
				{ silent: true },
			);
			setResponse(value);
			setSettings(pickMemorySettings(value.settings));
			toast.success(text('设置已保存', 'Settings saved'));
			return true;
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setSaveError(
					text(
						'设置已被其他操作更新，尚未覆盖你的草稿。请核对最新设置。',
						'The settings changed elsewhere. Your draft is preserved. Review the latest values.',
					),
				);
				setConflict({ latest: null, error: '' });
				await readLatest();
			} else {
				setSaveError(formatApiErrorForAlert(error));
			}
			return false;
		} finally {
			savingRef.current = false;
			setSaving(false);
		}
	};
	const discard = () => {
		if (!response) return;
		setSettings(pickMemorySettings(response.settings));
		setValidation([]);
		setSaveError('');
	};
	const fieldLabel = (key: MemorySettingsKey) =>
		({
			learning_enabled: text('启用后台学习', 'Background learning'),
			learning_model_config: text('后台学习模型', 'Learning model'),
			learning_interactions_enabled: text('智能体业务交互', 'Agent interactions'),
			learning_business_events_enabled: text('已确认业务事件', 'Confirmed business events'),
			group_learning_enabled: text('群聊消息', 'Group messages'),
			compression_model_config: text('对话压缩模型', 'Conversation compression model'),
		})[key];
	const displayValue = (key: MemorySettingsKey, value: MemorySettings[MemorySettingsKey]) => {
		if (typeof value === 'boolean') return value ? text('开启', 'On') : text('关闭', 'Off');
		if (value === null)
			return key === 'compression_model_config'
				? text('使用当前对话模型', 'Use conversation model')
				: text('未配置', 'Not configured');
		const credential = Object.values(catalogue.groups)
			.flat()
			.find((item) => item.credential.id === value.credential_id)?.credential;
		return `${value.model} · ${String(credential?.data.name || value.credential_id)}`;
	};
	const changes =
		conflict?.latest && settings && response
			? memorySettingsChanges(response.settings, settings, conflict.latest.settings)
			: [];
	const unresolved = changes.some((change) => change.conflict && !choices[change.key]);
	const resolveConflict = (useLatest: boolean) => {
		if (!response || !settings || !conflict?.latest) return;
		const latest = conflict.latest;
		setSettings(
			useLatest
				? pickMemorySettings(latest.settings)
				: mergeMemorySettings(response.settings, settings, latest.settings, choices),
		);
		setResponse(latest);
		setConflict(null);
		setChoices({});
		setValidation([]);
		setSaveError('');
	};
	const fieldError = (field: MemoryValidationError['field']) => {
		const error = validation.find((item) => item.field === field);
		return error ? (
			<p id={`memory-${field}-error`} className="text-sm text-destructive">
				{validationText(error)}
			</p>
		) : null;
	};
	const toggle = (key: BooleanSetting, description: string) => (
		<div key={key} className="flex items-start justify-between gap-6 py-4">
			<div className="min-w-0 space-y-1">
				<label htmlFor={`memory-${key}`} className="font-medium">
					{fieldLabel(key)}
				</label>
				<p id={`memory-${key}-hint`} className="text-sm leading-6 text-muted-foreground">
					{description}
				</p>
			</div>
			<Switch
				id={`memory-${key}`}
				aria-describedby={`memory-${key}-hint`}
				checked={settings?.[key] ?? false}
				disabled={busy || Boolean(conflict)}
				onCheckedChange={(value) => update(key, value)}
				className="mt-1"
			/>
		</div>
	);

	return (
		<div className="flex h-full min-h-0 flex-col bg-muted/20 text-sm">
			<header className="shrink-0 border-b bg-background px-6 py-4">
				<h1 className="flex items-center gap-2 text-lg font-semibold">
					<BrainCircuit className="size-5" />
					{text('记忆与学习', 'Memory and learning')}
				</h1>
				<p className="mt-2 text-sm leading-6 text-muted-foreground">
					{text(
						'系统按职责、业务入口和来源权限安排记忆。这里统一设置后台学习和长对话压缩。',
						'The system manages memory by duty, entry point, and source permissions. Configure background learning and long-conversation compression here.',
					)}
				</p>
			</header>
			<main className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
				{loading ? (
					<div
						role="status"
						aria-label={text('正在读取设置', 'Loading settings')}
						className="space-y-5"
					>
						{[4, 2].map((rows, index) => (
							<div
								key={index}
								aria-hidden="true"
								className="space-y-5 rounded-xl border bg-background p-5"
							>
								<Skeleton className="h-5 w-32" />
								{Array.from({ length: rows }, (_, row) => (
									<div key={row} className="space-y-3">
										<Skeleton className="h-4 w-44" />
										<Skeleton className="h-4 w-3/4" />
									</div>
								))}
							</div>
						))}
						<span className="sr-only">{text('正在读取设置', 'Loading settings')}</span>
					</div>
				) : loadError ? (
					<div className="space-y-4 rounded-xl border bg-background p-5">
						<p className="font-medium">
							{text('暂时无法读取设置', 'Unable to load settings')}
						</p>
						<p role="alert" className="whitespace-pre-wrap text-sm text-destructive">
							{loadError}
						</p>
						<Button
							variant="outline"
							onClick={() => setLoadVersion((value) => value + 1)}
						>
							<RefreshCw />
							{text('重新读取', 'Retry')}
						</Button>
					</div>
				) : settings && response ? (
					<div className="space-y-5">
						{saveError && (
							<div
								role="alert"
								className="space-y-2 rounded-lg border border-destructive/30 bg-background p-4 text-sm"
							>
								<p className="whitespace-pre-wrap text-destructive">{saveError}</p>
								<p className="text-muted-foreground">
									{text(
										'本地更改仍保留在此页面。',
										'Your unsaved changes are preserved on this page.',
									)}
								</p>
								{(catalogue.error ||
									validation.some(
										(item) => item.code === 'model_unavailable',
									)) && (
									<Button
										variant="outline"
										size="sm"
										disabled={catalogue.loading}
										onClick={() => void catalogue.refetch()}
									>
										{text('重新读取模型', 'Reload models')}
									</Button>
								)}
							</div>
						)}
						{conflict && (
							<section
								aria-label={text('处理设置冲突', 'Resolve settings conflict')}
								className="space-y-4 rounded-xl border bg-background p-5"
							>
								<h2 className="font-semibold">
									{text('核对最新设置', 'Review latest settings')}
								</h2>
								<p className="leading-6 text-muted-foreground">
									{text(
										'仅一方修改的设置会自动保留；同一项有不同修改时，由你选择。应用选择后仍需点击保存。',
										'Changes made on only one side are retained. Choose a value when both sides differ. Apply your choices, then save.',
									)}
								</p>
								{refreshing ? (
									<p className="flex items-center gap-2">
										<Loader2 className="size-4 animate-spin" />
										{text('正在读取最新版本', 'Loading latest version')}
									</p>
								) : conflict.latest ? (
									<>
										<div className="overflow-x-auto rounded-lg border">
											<table className="w-full text-left text-sm">
												<thead className="bg-muted/40">
													<tr>
														<th className="p-3 font-medium">
															{text('设置', 'Setting')}
														</th>
														<th className="p-3 font-medium">
															{text('最新保存', 'Latest saved')}
														</th>
														<th className="p-3 font-medium">
															{text('我的草稿', 'My draft')}
														</th>
														<th className="p-3 font-medium">
															{text('采用', 'Keep')}
														</th>
													</tr>
												</thead>
												<tbody>
													{changes.map((change) => (
														<tr key={change.key} className="border-t">
															<td className="p-3">
																{fieldLabel(change.key)}
															</td>
															<td className="p-3 break-words">
																{displayValue(
																	change.key,
																	conflict.latest!.settings[
																		change.key
																	],
																)}
															</td>
															<td className="p-3 break-words">
																{displayValue(
																	change.key,
																	settings[change.key],
																)}
															</td>
															<td className="p-3">
																{change.conflict ? (
																	<div className="flex flex-wrap gap-3">
																		{(
																			[
																				'remote',
																				'local',
																			] as const
																		).map((choice) => (
																			<label
																				key={choice}
																				className="flex items-center gap-2 whitespace-nowrap"
																			>
																				<input
																					type="radio"
																					name={`conflict-${change.key}`}
																					checked={
																						choices[
																							change
																								.key
																						] === choice
																					}
																					onChange={() =>
																						setChoices(
																							(
																								previous,
																							) => ({
																								...previous,
																								[change.key]:
																									choice,
																							}),
																						)
																					}
																					className="size-4 accent-primary"
																				/>
																				{choice === 'local'
																					? text(
																							'我的草稿',
																							'My draft',
																						)
																					: text(
																							'最新设置',
																							'Latest',
																						)}
																			</label>
																		))}
																	</div>
																) : change.localChanged ? (
																	text(
																		'保留我的修改',
																		'Keep my change',
																	)
																) : (
																	text(
																		'采用最新修改',
																		'Keep latest change',
																	)
																)}
															</td>
														</tr>
													))}
												</tbody>
											</table>
										</div>
										<div className="flex flex-wrap justify-end gap-2">
											<Button
												variant="outline"
												onClick={() => resolveConflict(true)}
											>
												{text(
													'使用最新，放弃草稿',
													'Use latest and discard draft',
												)}
											</Button>
											<Button
												disabled={unresolved}
												onClick={() => resolveConflict(false)}
											>
												{text(
													'应用选择，继续编辑',
													'Apply choices and continue',
												)}
											</Button>
										</div>
									</>
								) : (
									<div className="space-y-3">
										<p role="alert" className="text-destructive">
											{conflict.error ||
												text(
													'尚未取得最新版本。',
													'The latest version has not been loaded.',
												)}
										</p>
										<Button variant="outline" onClick={() => void readLatest()}>
											<RefreshCw />
											{text('重新读取最新设置', 'Reload latest settings')}
										</Button>
									</div>
								)}
							</section>
						)}
						<fieldset
							disabled={busy || Boolean(conflict)}
							aria-busy={saving}
							className="space-y-5"
						>
							<section className="space-y-4 rounded-xl border bg-background p-5">
								<div>
									<h2 className="font-semibold">
										{text('后台学习', 'Background learning')}
									</h2>
									<p className="mt-2 leading-6 text-muted-foreground">
										{text(
											'从有来源的交互和正式记录中提炼可复用经验，校验后保存。明确记忆的保存和读取不额外调用学习模型。',
											'Extract reusable lessons from sourced interactions and confirmed records, then validate and save them. Explicit memory saves and retrieval do not require an extra learning-model call.',
										)}
									</p>
								</div>
								{toggle(
									'learning_enabled',
									text(
										'关闭后暂停新的学习，保留已有记忆和待处理材料。',
										'Pausing stops new learning and preserves existing memory and pending material.',
									),
								)}
								<div
									id="memory-learning_model_config"
									role="group"
									aria-labelledby="memory-learning-model-label"
									tabIndex={-1}
									className="space-y-2 border-t pt-5"
								>
									<p id="memory-learning-model-label" className="font-medium">
										{fieldLabel('learning_model_config')}
									</p>
									<LlmSelect
										value={settings.learning_model_config}
										onChange={(value) => update('learning_model_config', value)}
										onAddCredential={() => navigate('/credential')}
										allowClear
										disabled={busy || Boolean(conflict)}
										catalogue={catalogue}
										placeholder={text(
											'请选择后台学习模型',
											'Select a learning model',
										)}
										clearLabel={text('清空学习模型', 'Clear learning model')}
									/>
									<p className="leading-6 text-muted-foreground">
										{text(
											'独立用于提炼经验，不跟随总控或当前对话模型。启用学习时必须选择可用模型。',
											'Used independently to extract lessons. It never follows the orchestrator or current conversation model. Enabling learning requires an available model.',
										)}
									</p>
									{fieldError('learning_model_config')}
								</div>
								<div
									id="memory-learning_sources"
									tabIndex={-1}
									className="border-t pt-5"
								>
									<h3 className="font-medium">
										{text('学习来源', 'Learning sources')}
									</h3>
									<div className="divide-y">
										{toggle(
											'learning_interactions_enabled',
											text(
												'归集用户纠正和实际执行结果。多级协作按同一次业务运行处理。',
												'Collect user corrections and actual execution results. Multi-agent collaboration is processed as one business run.',
											),
										)}
										{toggle(
											'learning_business_events_enabled',
											text(
												'使用初始化确认、任务发布和验收等正式事件；未确认草稿不作为业务事实。',
												'Use confirmed initialization, task publication, and acceptance events. Unconfirmed drafts are not business facts.',
											),
										)}
										{toggle(
											'group_learning_enabled',
											text(
												'后台整理群聊中有价值的信息，不向群内发送总结；成果遵守原消息的可见范围。',
												'Process valuable group messages in the background without sending summaries to the group. Results retain the original visibility restrictions.',
											),
										)}
									</div>
									{fieldError('learning_sources')}
								</div>
								<p
									role="status"
									className="rounded-lg bg-muted/40 p-4 leading-6 text-muted-foreground"
								>
									{settings.learning_enabled
										? text(
												'保存后按所选来源处理新学习。用户本次“不记忆／不学习”的要求继续生效。',
												'Once saved, new learning uses the selected sources. Per-request memory and learning exclusions remain effective.',
											)
										: text(
												'后台学习已设为暂停；模型与来源选择仍可保存，已有记忆的正常读取和明确保存继续可用。',
												'Background learning is set to paused. Model and source selections can still be saved. Existing memory retrieval and explicit saves remain available.',
											)}
								</p>
							</section>
							<section className="space-y-4 rounded-xl border bg-background p-5">
								<div>
									<h2 className="font-semibold">
										{text('长对话压缩', 'Long-conversation compression')}
									</h2>
									<p className="mt-2 leading-6 text-muted-foreground">
										{text(
											'对话变长时自动整理上下文，帮助继续完成当前任务。这与长期记忆学习分别运行。',
											'Automatically summarize context as conversations grow so the current task can continue. This runs independently of long-term learning.',
										)}
									</p>
								</div>
								<div
									id="memory-compression_model_config"
									role="group"
									aria-labelledby="memory-compression-model-label"
									tabIndex={-1}
									className="space-y-2"
								>
									<p id="memory-compression-model-label" className="font-medium">
										{fieldLabel('compression_model_config')}
									</p>
									<LlmSelect
										value={settings.compression_model_config}
										onChange={(value) =>
											update('compression_model_config', value)
										}
										onAddCredential={() => navigate('/credential')}
										allowClear
										disabled={busy || Boolean(conflict)}
										catalogue={catalogue}
										placeholder={text(
											'使用当前对话模型',
											'Use conversation model',
										)}
										clearLabel={text(
											'使用当前对话模型',
											'Use conversation model',
										)}
									/>
									{fieldError('compression_model_config')}
								</div>
								<p className="leading-6 text-muted-foreground">
									{text(
										'不单独选择时，使用当前对话模型。压缩时机、保留内容和执行保护由系统管理。',
										'Leave unselected to use the current conversation model. The system manages compression timing, retained context, and execution safeguards.',
									)}
								</p>
							</section>
						</fieldset>
					</div>
				) : null}
			</main>
			<footer className="flex shrink-0 items-center justify-between gap-4 border-t bg-background px-6 py-3">
				<p role="status" className="text-sm text-muted-foreground">
					{saving
						? text('正在保存设置…', 'Saving settings…')
						: conflict
							? text('请先核对最新设置', 'Review the latest settings')
							: dirty
								? text('有未保存更改', 'Unsaved changes')
								: loading
									? text('正在读取设置', 'Loading settings')
									: loadError
										? text('设置尚未读取', 'Settings not loaded')
										: text('当前设置已保存', 'Settings are saved')}
				</p>
				<div className="flex shrink-0 gap-2">
					<Button
						variant="outline"
						disabled={!dirty || busy || Boolean(conflict)}
						onClick={discard}
					>
						<RotateCcw />
						{text('放弃更改', 'Discard changes')}
					</Button>
					<Button
						disabled={!dirty || busy || Boolean(conflict)}
						onClick={() => void save()}
					>
						{saving ? <Loader2 className="animate-spin" /> : <Save />}
						{text('保存设置', 'Save settings')}
					</Button>
				</div>
			</footer>
			<Dialog
				open={blocker.state === 'blocked'}
				onOpenChange={(open) => {
					if (!open && !busy && blocker.state === 'blocked') blocker.reset();
				}}
			>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{text('更改尚未保存', 'Unsaved changes')}</DialogTitle>
						<DialogDescription>
							{busy
								? text(
										'正在处理设置，请稍候。',
										'Settings are being processed. Please wait.',
									)
								: text(
										'离开会丢失本次更改。你可以继续编辑、放弃并离开，或保存后离开。',
										'Leaving loses your changes. Continue editing, discard and leave, or save before leaving.',
									)}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button
							variant="outline"
							disabled={busy}
							onClick={() => {
								if (blocker.state === 'blocked') blocker.reset();
							}}
						>
							{text('继续编辑', 'Keep editing')}
						</Button>
						<Button
							variant="outline"
							disabled={busy}
							onClick={() => {
								if (blocker.state === 'blocked') blocker.proceed();
							}}
						>
							{text('放弃并离开', 'Discard and leave')}
						</Button>
						<Button
							disabled={busy || Boolean(conflict)}
							onClick={async () => {
								if (blocker.state !== 'blocked') return;
								const proceed = blocker.proceed;
								const reset = blocker.reset;
								if (await save()) proceed();
								else reset();
							}}
						>
							{saving && <Loader2 className="animate-spin" />}
							{text('保存并离开', 'Save and leave')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
