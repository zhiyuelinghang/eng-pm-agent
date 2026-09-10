import { Loader2, RotateCcw, Save } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import type { CredentialModelEntry, JSONSchema, JSONSchemaProperty } from '@/api';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';
import {
	modelParameterFields,
	modelParameterOverrides,
	modelParameterValues,
	validateModelParameterValues,
} from '@/lib/model-default-parameters';
import { customRequestBodyText, parseCustomRequestBody } from '@/lib/model-parameters';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	model: CredentialModelEntry | null;
	credentialType: string;
	onSave: (modelName: string, parameters: Record<string, unknown>) => Promise<void>;
}

const DEFAULT_OPTION = '__model_default__';

function ParameterField({
	name,
	property,
	value,
	onChange,
	error,
	effortOnlyThinking,
}: {
	name: string;
	property: JSONSchemaProperty;
	value: unknown;
	onChange: (value: unknown) => void;
	error?: string;
	effortOnlyThinking: boolean;
}) {
	const { t } = useTranslation();
	const fieldId = 'model-default-' + name;
	const type =
		property.type ?? property.anyOf?.find((item) => item.type !== 'null')?.type ?? 'string';
	const boolean = type === 'boolean';
	const choices =
		property.enum ??
		property.anyOf?.map((item) => (item as JSONSchemaProperty).enum).find(Boolean);
	const unset = value === undefined || value === null || value === '';
	const booleanDefault = boolean && typeof property.default === 'boolean';
	const selectedValue =
		unset && booleanDefault ? String(property.default) : unset ? DEFAULT_OPTION : String(value);
	const defaultLabel = t(
		name === 'reasoning_effort'
			? 'credential.modelDefaults.unspecifiedEffort'
			: 'credential.modelDefaults.defaultValue',
	);
	const trueLabel = effortOnlyThinking ? 'useReasoningEffort' : 'requestThinking';
	const falseLabel = effortOnlyThinking ? 'noThinkingRequest' : 'requestNoThinking';
	const description = t('model-parameters.fieldDescriptions.' + name, { defaultValue: '' });

	return (
		<div className="grid min-w-0 gap-2">
			<Label htmlFor={fieldId}>
				{t('model-parameters.fields.' + name, { defaultValue: name })}
			</Label>
			{boolean || choices ? (
				<Select
					value={selectedValue}
					onValueChange={(next) => {
						if (next === DEFAULT_OPTION) onChange(undefined);
						else onChange(boolean ? next === 'true' : next);
					}}
				>
					<SelectTrigger
						id={fieldId}
						className="w-full min-w-0"
						aria-invalid={Boolean(error)}
					>
						<SelectValue />
					</SelectTrigger>
					<SelectContent>
						{!booleanDefault && (
							<SelectItem value={DEFAULT_OPTION}>{defaultLabel}</SelectItem>
						)}
						{boolean ? (
							<>
								<SelectItem value="true">
									{t('credential.modelDefaults.' + trueLabel)}
								</SelectItem>
								<SelectItem value="false">
									{t('credential.modelDefaults.' + falseLabel)}
								</SelectItem>
							</>
						) : (
							choices
								?.filter((choice) => choice !== null)
								.map((choice) => (
									<SelectItem key={String(choice)} value={String(choice)}>
										{t('model-parameters.values.' + String(choice), {
											defaultValue: String(choice),
										})}
									</SelectItem>
								))
						)}
					</SelectContent>
				</Select>
			) : (
				<Input
					id={fieldId}
					type="text"
					value={unset ? '' : String(value)}
					placeholder={defaultLabel}
					className="min-w-0 tabular-nums"
					aria-invalid={Boolean(error)}
					onChange={(event) => {
						const raw = event.target.value;
						onChange(raw === '' ? undefined : raw);
					}}
				/>
			)}
			{description && (
				<p className="text-xs leading-relaxed text-muted-foreground">{description}</p>
			)}
			{error && (
				<p role="alert" className="text-xs text-destructive">
					{error}
				</p>
			)}
		</div>
	);
}

export function ModelDefaultParametersDialog({
	open,
	onOpenChange,
	model,
	credentialType,
	onSave,
}: Props) {
	const { t } = useTranslation();
	const effortOnlyThinking = [
		'openai_credential',
		'custom_openai_credential',
		'xai_credential',
	].includes(credentialType);
	const [values, setValues] = useState<Record<string, unknown>>({});
	const [customRequestText, setCustomRequestText] = useState('');
	const [customRequestError, setCustomRequestError] = useState<string | null>(null);
	const [parameterError, setParameterError] = useState<string | null>(null);
	const [focusRequest, setFocusRequest] = useState<{ id: string } | null>(null);
	const [activeTab, setActiveTab] = useState('common');
	const [saving, setSaving] = useState(false);
	const savingRef = useRef(false);
	const schema = useMemo(
		() =>
			(model?.parameter_schema ?? {
				type: 'object',
				properties: {},
			}) as unknown as JSONSchema,
		[model?.parameter_schema],
	);
	const editableSchema = useMemo<JSONSchema>(
		() => ({
			type: 'object',
			properties: Object.fromEntries(modelParameterFields(schema)),
		}),
		[schema],
	);
	const commonFields = modelParameterFields(editableSchema);

	useEffect(() => {
		if (!open || !model) return;
		setValues(modelParameterValues(model.default_parameters));
		setCustomRequestText(customRequestBodyText(model.default_parameters));
		setCustomRequestError(null);
		setParameterError(null);
		setFocusRequest(null);
		setActiveTab(modelParameterFields(schema).length > 0 ? 'common' : 'extensions');
	}, [model, open, schema]);

	useEffect(() => {
		if (!open || !focusRequest) return;
		const frame = requestAnimationFrame(() => {
			const field = document.getElementById(focusRequest.id);
			field?.scrollIntoView({ block: 'nearest' });
			field?.focus({ preventScroll: true });
		});
		return () => cancelAnimationFrame(frame);
	}, [open, focusRequest]);

	const resetToDefaults = () => {
		setValues((previous) => {
			const next = { ...previous };
			for (const [key] of commonFields) delete next[key];
			return next;
		});
		setCustomRequestText('');
		setCustomRequestError(null);
		setParameterError(null);
	};

	const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		if (!model || savingRef.current) return;
		const invalidParameter = validateModelParameterValues(editableSchema, values);
		if (invalidParameter) {
			setParameterError(invalidParameter);
			setActiveTab('common');
			setFocusRequest({ id: 'model-default-' + invalidParameter });
			return;
		}
		setParameterError(null);
		let requestBody: Record<string, unknown>;
		try {
			requestBody = parseCustomRequestBody(customRequestText);
		} catch (error) {
			setCustomRequestError(
				t(
					error instanceof Error && error.message === 'object_required'
						? 'credential.modelDefaults.customObjectRequired'
						: 'credential.modelDefaults.customInvalid',
				),
			);
			setActiveTab('extensions');
			setFocusRequest({ id: 'model-custom-request' });
			return;
		}
		setCustomRequestError(null);
		savingRef.current = true;
		setSaving(true);
		try {
			await onSave(model.name, modelParameterOverrides(values, requestBody));
			onOpenChange(false);
		} catch {
			// The API client reports the failure; retain the complete draft for retry.
		} finally {
			savingRef.current = false;
			setSaving(false);
		}
	};

	const renderField = ([key, property]: [string, JSONSchemaProperty]) => (
		<ParameterField
			key={key}
			name={key}
			property={property}
			value={values[key]}
			effortOnlyThinking={effortOnlyThinking}
			error={
				parameterError === key
					? t('credential.modelDefaults.invalidParameter', {
							field: t('model-parameters.fields.' + key, { defaultValue: key }),
						})
					: undefined
			}
			onChange={(value) => {
				setValues((previous) => ({ ...previous, [key]: value }));
				setParameterError(null);
			}}
		/>
	);

	return (
		<Dialog
			open={open}
			onOpenChange={(next) => {
				if (!savingRef.current) onOpenChange(next);
			}}
		>
			<DialogContent className="flex max-h-[85dvh] w-[calc(100vw-2rem)] max-w-[40rem] flex-col gap-0 overflow-hidden p-0 sm:max-w-[40rem]">
				<DialogHeader className="shrink-0 px-5 pt-5 pb-4 pr-12">
					<DialogTitle>{t('credential.modelDefaults.title')}</DialogTitle>
					<DialogDescription className="break-words">
						{t('credential.modelDefaults.description', {
							model: model?.label || model?.name || '',
						})}
					</DialogDescription>
				</DialogHeader>
				<form noValidate onSubmit={handleSave} className="flex min-h-0 flex-1 flex-col">
					<Tabs
						value={activeTab}
						onValueChange={setActiveTab}
						className="min-h-0 flex-1 gap-0"
					>
						<div className="shrink-0 border-b px-5">
							<TabsList variant="line" className="gap-4">
								{commonFields.length > 0 && (
									<TabsTrigger value="common" disabled={saving}>
										{t('credential.modelDefaults.commonTab')}
									</TabsTrigger>
								)}
								<TabsTrigger value="extensions" disabled={saving}>
									{t('credential.modelDefaults.extensionsTab')}
								</TabsTrigger>
							</TabsList>
						</div>
						<div className="@container min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5">
							<fieldset disabled={saving} className="min-w-0">
								<TabsContent value="common" className="min-h-40 space-y-5">
									{commonFields.length > 0 ? (
										<>
											<div className="grid items-start gap-5 @lg:grid-cols-2">
												{commonFields.map(renderField)}
											</div>
											<p className="text-xs leading-relaxed text-muted-foreground">
												{t(
													effortOnlyThinking &&
														commonFields.some(
															([key]) => key === 'thinking_enable',
														)
														? 'credential.modelDefaults.reasoningEffortHint'
														: 'credential.modelDefaults.interfaceHint',
												)}
											</p>
										</>
									) : (
										<p className="py-8 text-center text-sm text-muted-foreground">
											{t('credential.modelDefaults.noCommonSettings')}
										</p>
									)}
									{customRequestText.trim() && (
										<p className="text-xs leading-relaxed text-muted-foreground">
											{t('credential.modelDefaults.customActive')}
										</p>
									)}
								</TabsContent>
								<TabsContent value="extensions" className="space-y-5">
									<div className="grid gap-2">
										<Label htmlFor="model-custom-request">
											{t('credential.modelDefaults.extensionTitle')}
										</Label>
										<Textarea
											id="model-custom-request"
											value={customRequestText}
											onChange={(event) => {
												setCustomRequestText(event.target.value);
												setCustomRequestError(null);
											}}
											placeholder="{}"
											spellCheck={false}
											className="min-h-28 resize-y font-mono text-sm"
											aria-invalid={Boolean(customRequestError)}
										/>
										<p className="text-xs leading-relaxed text-muted-foreground">
											{t('credential.modelDefaults.extensionHint')}
										</p>
										{customRequestError && (
											<p role="alert" className="text-sm text-destructive">
												{customRequestError}
											</p>
										)}
									</div>
								</TabsContent>
							</fieldset>
						</div>
					</Tabs>
					<DialogFooter className="mx-0 mb-0 shrink-0 flex-col rounded-none px-5 py-3 sm:justify-between">
						<Button
							type="button"
							variant="ghost"
							className="self-start"
							onClick={resetToDefaults}
							disabled={saving}
						>
							<RotateCcw />
							{t('credential.modelDefaults.reset')}
						</Button>
						<div className="flex justify-end gap-2">
							<Button
								type="button"
								variant="outline"
								onClick={() => onOpenChange(false)}
								disabled={saving}
							>
								{t('common.cancel')}
							</Button>
							<Button type="submit" disabled={saving || !model}>
								{saving ? <Loader2 className="animate-spin" /> : <Save />}
								{t(saving ? 'common.saving' : 'credential.modelDefaults.save')}
							</Button>
						</div>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
