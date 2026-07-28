import { BrainCircuit, Braces, Loader2, RotateCcw, Save } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import type { CredentialModelEntry, JSONSchema } from '@/api';
import {
	defaultValuesFromSchema,
	SchemaForm,
	type SchemaFormValue,
} from '@/components/form/SchemaForm';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';
import {
	CUSTOM_REQUEST_BODY_KEY,
	customRequestBodyText,
	parseCustomRequestBody,
} from '@/lib/model-parameters';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	model: CredentialModelEntry | null;
	onSave: (modelName: string, parameters: Record<string, unknown>) => Promise<void>;
}

function asFormValues(values: Record<string, unknown>): Record<string, SchemaFormValue> {
	return Object.fromEntries(
		Object.entries(values)
			.filter(([key]) => key !== CUSTOM_REQUEST_BODY_KEY)
			.map(([key, value]) => [key, value as SchemaFormValue]),
	);
}

function compactOverrides(
	schema: JSONSchema,
	values: Record<string, SchemaFormValue>,
): Record<string, unknown> {
	const result: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(values)) {
		if (value === undefined || value === null || value === '') continue;
		const schemaDefault = schema.properties?.[key]?.default;
		if (schemaDefault !== undefined && Object.is(value, schemaDefault)) {
			continue;
		}
		result[key] = value;
	}
	return result;
}

export function ModelDefaultParametersDialog({ open, onOpenChange, model, onSave }: Props) {
	const { t } = useTranslation();
	const [values, setValues] = useState<Record<string, SchemaFormValue>>({});
	const [customRequestText, setCustomRequestText] = useState('');
	const [customRequestError, setCustomRequestError] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const schema = useMemo(
		() =>
			(model?.parameter_schema ?? {
				type: 'object',
				properties: {},
			}) as unknown as JSONSchema,
		[model],
	);
	const hasThinkingParameters = Boolean(
		schema.properties?.thinking_enable ||
		schema.properties?.reasoning_effort ||
		schema.properties?.thinking_budget,
	);

	const resetToProviderDefaults = () => {
		setValues(defaultValuesFromSchema(schema));
		setCustomRequestText('');
		setCustomRequestError(null);
	};

	useEffect(() => {
		if (!open || !model) return;
		setValues({
			...defaultValuesFromSchema(schema),
			...asFormValues(model.default_parameters),
		});
		setCustomRequestText(customRequestBodyText(model.default_parameters));
		setCustomRequestError(null);
	}, [model, open, schema]);

	const handleSave = async () => {
		if (!model) return;
		let customRequestBody: Record<string, unknown> = {};
		const trimmedCustomRequest = customRequestText.trim();
		if (trimmedCustomRequest) {
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
		setCustomRequestError(null);
		setSaving(true);
		try {
			const parameters = compactOverrides(schema, values);
			if (Object.keys(customRequestBody).length > 0) {
				parameters[CUSTOM_REQUEST_BODY_KEY] = customRequestBody;
			}
			await onSave(model.name, parameters);
			onOpenChange(false);
		} finally {
			setSaving(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-h-[85vh] !w-[560px] !max-w-[560px] overflow-y-auto">
				<DialogHeader>
					<div className="flex items-center gap-2">
						<DialogTitle>{t('credential.modelDefaults.title')}</DialogTitle>
						{hasThinkingParameters && (
							<Badge variant="outline">
								<BrainCircuit />
								{t('credential.reasoning')}
							</Badge>
						)}
					</div>
					<DialogDescription>
						{t('credential.modelDefaults.description', {
							model: model?.label || model?.name || '',
						})}
					</DialogDescription>
				</DialogHeader>

				<Alert>
					<BrainCircuit />
					<AlertTitle>{t('credential.modelDefaults.inheritanceTitle')}</AlertTitle>
					<AlertDescription>
						{t('credential.modelDefaults.inheritanceDescription')}
					</AlertDescription>
				</Alert>

				{Object.keys(schema.properties ?? {}).length === 0 ? (
					<div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
						{t('model-parameters.empty')}
					</div>
				) : (
					<SchemaForm
						schema={schema}
						values={values}
						onChange={(key, value) =>
							setValues((previous) => ({
								...previous,
								[key]: value,
							}))
						}
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
						idPrefix={`model-default-${model?.name ?? 'unknown'}`}
					/>
				)}

				<div className="grid gap-2 rounded-lg border bg-muted/20 p-4">
					<div className="flex items-center justify-between gap-3">
						<Label
							htmlFor={`model-custom-request-${model?.name ?? 'unknown'}`}
							className="flex items-center gap-2"
						>
							<Braces className="size-4" />
							{t('credential.modelDefaults.customTitle')}
						</Label>
						{!hasThinkingParameters && (
							<Badge variant="secondary">
								{t('credential.modelDefaults.customRequired')}
							</Badge>
						)}
					</div>
					<p className="text-xs leading-relaxed text-muted-foreground">
						{t('credential.modelDefaults.customDescription')}
					</p>
					<Textarea
						id={`model-custom-request-${model?.name ?? 'unknown'}`}
						value={customRequestText}
						onChange={(event) => {
							setCustomRequestText(event.target.value);
							setCustomRequestError(null);
						}}
						placeholder={t('credential.modelDefaults.customPlaceholder')}
						className="min-h-36 resize-y font-mono text-xs"
						aria-invalid={Boolean(customRequestError)}
						disabled={saving}
					/>
					{customRequestError && (
						<p className="text-xs text-destructive">{customRequestError}</p>
					)}
					<div className="grid gap-1">
						<p className="text-[11px] font-medium text-muted-foreground">
							{t('credential.modelDefaults.customExamplesLabel')}
						</p>
						<pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-background p-2 text-[11px] leading-relaxed text-muted-foreground">
							{t('credential.modelDefaults.customExamples')}
						</pre>
					</div>
				</div>

				<DialogFooter className="sm:justify-between">
					<Button variant="ghost" onClick={resetToProviderDefaults} disabled={saving}>
						<RotateCcw />
						{t('credential.modelDefaults.reset')}
					</Button>
					<div className="flex justify-end gap-2">
						<Button
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={saving}
						>
							{t('common.cancel')}
						</Button>
						<Button onClick={handleSave} disabled={saving || !model}>
							{saving ? <Loader2 className="animate-spin" /> : <Save />}
							{saving ? t('common.saving') : t('credential.modelDefaults.save')}
						</Button>
					</div>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
