import { AlertTriangle, Braces } from 'lucide-react';
import { useMemo } from 'react';

import type { AgentModelPolicyMode, ChatModelConfig, JSONSchema, ModelCard } from '@/api';
import { SchemaForm, type SchemaFormValue } from '@/components/form/SchemaForm';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useAvailableModels } from '@/hooks/useAvailableModels';
import { useTranslation } from '@/i18n/useI18n';
import type { AgentModelPolicyFormValues } from '@/lib/agent-model-policy';
import { CUSTOM_REQUEST_BODY_KEY, parseCustomRequestBody } from '@/lib/model-parameters';

interface Props {
	values: AgentModelPolicyFormValues;
	onChange: (key: keyof AgentModelPolicyFormValues, value: unknown) => void;
}

export function AgentModelPolicyFields({ values, onChange }: Props) {
	const { t } = useTranslation();
	const { groups, loading } = useAvailableModels();
	const mode = values.mode ?? 'inherit_session';
	const config = values.chat_model_config ?? null;
	const customRequestText = values.custom_request_text ?? '';

	const credentialOptions = useMemo(
		() =>
			Object.entries(groups).flatMap(([type, entries]) =>
				entries.map(({ credential, models }) => ({
					type,
					credential,
					models,
				})),
			),
		[groups],
	);
	const selectedCredential = config
		? credentialOptions.find(
				(option) =>
					option.type === config.type && option.credential.id === config.credential_id,
			)
		: undefined;
	const selectedModel: ModelCard | undefined = selectedCredential?.models.find(
		(model) => model.name === config?.model,
	);
	const parameterSchema = (selectedModel?.parameter_schema ?? {
		type: 'object',
		properties: {},
	}) as unknown as JSONSchema;
	const parameterEntries = Object.keys(parameterSchema.properties ?? {});
	const parameterValues = Object.fromEntries(
		Object.entries(config?.parameters ?? {})
			.filter(([key]) => key !== CUSTOM_REQUEST_BODY_KEY)
			.map(([key, value]) => [key, value as SchemaFormValue]),
	);

	let customRequestError: string | null = null;
	if (customRequestText.trim()) {
		try {
			parseCustomRequestBody(customRequestText);
		} catch (error) {
			customRequestError =
				error instanceof Error && error.message === 'object_required'
					? t('credential.modelDefaults.customObjectRequired')
					: t('credential.modelDefaults.customInvalid');
		}
	}

	const updateConfig = (next: ChatModelConfig | null) => {
		onChange('chat_model_config', next);
	};

	const selectCredential = (credentialId: string) => {
		const option = credentialOptions.find(
			(candidate) => candidate.credential.id === credentialId,
		);
		const firstModel = option?.models[0];
		if (!option || !firstModel) {
			updateConfig(null);
			return;
		}
		updateConfig({
			type: option.type,
			credential_id: option.credential.id,
			model: firstModel.name,
			parameters: {},
		});
		onChange('custom_request_text', '');
	};

	const selectModel = (modelName: string) => {
		if (!selectedCredential) return;
		updateConfig({
			type: selectedCredential.type,
			credential_id: selectedCredential.credential.id,
			model: modelName,
			parameters: {},
		});
		onChange('custom_request_text', '');
	};

	const updateParameter = (key: string, value: SchemaFormValue) => {
		if (!config) return;
		const parameters = { ...config.parameters, [key]: value };
		if (value === undefined || value === null || value === '') {
			delete parameters[key];
		}
		updateConfig({ ...config, parameters });
	};

	return (
		<div className="grid gap-4">
			<div className="grid gap-1.5">
				<Label htmlFor="agent-model-policy-mode">
					{t('agent-form.model-policy.mode.label')}
				</Label>
				<Select
					value={mode}
					onValueChange={(value) => onChange('mode', value as AgentModelPolicyMode)}
				>
					<SelectTrigger id="agent-model-policy-mode" className="w-full">
						<SelectValue />
					</SelectTrigger>
					<SelectContent>
						<SelectItem value="inherit_session">
							{t('agent-form.model-policy.mode.inherit')}
						</SelectItem>
						<SelectItem value="fixed">
							{t('agent-form.model-policy.mode.fixed')}
						</SelectItem>
					</SelectContent>
				</Select>
				<p className="text-xs text-muted-foreground">
					{t(`agent-form.model-policy.mode.${mode}Description`)}
				</p>
			</div>

			{mode === 'fixed' && (
				<>
					<div className="grid gap-1.5">
						<Label htmlFor="agent-model-policy-credential">
							{t('agent-form.model-policy.credential')}
						</Label>
						<Select
							value={config?.credential_id ?? ''}
							onValueChange={selectCredential}
							disabled={loading || credentialOptions.length === 0}
						>
							<SelectTrigger id="agent-model-policy-credential" className="w-full">
								<SelectValue
									placeholder={t('agent-form.model-policy.credentialPlaceholder')}
								/>
							</SelectTrigger>
							<SelectContent>
								{credentialOptions.map((option) => (
									<SelectItem
										key={option.credential.id}
										value={option.credential.id}
										disabled={option.models.length === 0}
									>
										{String(
											option.credential.data.name ??
												option.credential.id.slice(0, 8),
										)}{' '}
										· {option.type.replace(/_credential$/, '')}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					</div>

					<div className="grid gap-1.5">
						<Label htmlFor="agent-model-policy-model">
							{t('agent-form.model-policy.model')}
						</Label>
						<Select
							value={config?.model ?? ''}
							onValueChange={selectModel}
							disabled={!selectedCredential}
						>
							<SelectTrigger id="agent-model-policy-model" className="w-full">
								<SelectValue
									placeholder={t('agent-form.model-policy.modelPlaceholder')}
								/>
							</SelectTrigger>
							<SelectContent>
								{selectedCredential?.models.map((model) => (
									<SelectItem key={model.name} value={model.name}>
										{model.label || model.name}
									</SelectItem>
								))}
								{config && selectedCredential && !selectedModel && (
									<SelectItem value={config.model}>
										{config.model} · {t('agent-form.model-policy.unavailable')}
									</SelectItem>
								)}
							</SelectContent>
						</Select>
					</div>

					{config && !selectedModel && !loading && (
						<div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-200">
							<AlertTriangle className="mt-0.5 size-4 shrink-0" />
							{t('agent-form.model-policy.unavailableDescription')}
						</div>
					)}

					{selectedModel && (
						<div className="grid gap-3 rounded-lg border p-4">
							<div className="flex items-center justify-between gap-2">
								<div className="text-sm font-medium">
									{t('agent-form.model-policy.parameters')}
								</div>
								{parameterEntries.length > 0 && (
									<Badge variant="secondary">{parameterEntries.length}</Badge>
								)}
							</div>
							<p className="text-xs text-muted-foreground">
								{t('agent-form.model-policy.parametersDescription')}
							</p>
							{parameterEntries.length > 0 ? (
								<SchemaForm
									schema={parameterSchema}
									values={parameterValues}
									onChange={updateParameter}
									idPrefix="agent-model-parameter"
									labelFor={(key, property) =>
										t(`model-parameters.fields.${key}`, {
											defaultValue: property.title ?? key,
										})
									}
									descriptionFor={(key, property) =>
										t(`model-parameters.fieldDescriptions.${key}`, {
											defaultValue: property.description,
										})
									}
									optionFor={(_key, value) =>
										t(`model-parameters.values.${String(value)}`, {
											defaultValue: String(value),
										})
									}
								/>
							) : (
								<p className="text-xs text-muted-foreground">
									{t('model-parameters.empty')}
								</p>
							)}

							<div className="grid gap-2 border-t pt-3">
								<Label
									htmlFor="agent-model-custom-request"
									className="flex items-center gap-2"
								>
									<Braces className="size-4" />
									{t('credential.modelDefaults.customTitle')}
								</Label>
								<p className="text-xs text-muted-foreground">
									{t('agent-form.model-policy.customDescription')}
								</p>
								<Textarea
									id="agent-model-custom-request"
									value={customRequestText}
									onChange={(event) =>
										onChange('custom_request_text', event.target.value)
									}
									placeholder={t('credential.modelDefaults.customPlaceholder')}
									className="min-h-28 resize-y font-mono text-xs"
									aria-invalid={Boolean(customRequestError)}
								/>
								{customRequestError && (
									<p className="text-xs text-destructive">{customRequestError}</p>
								)}
								<pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted/50 p-2 text-[11px] leading-relaxed text-muted-foreground">
									{t('credential.modelDefaults.customExamples')}
								</pre>
							</div>
						</div>
					)}
				</>
			)}
		</div>
	);
}
