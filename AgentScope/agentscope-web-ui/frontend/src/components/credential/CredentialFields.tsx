import { Eye, EyeOff, Loader2, Save, Undo2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import type { CredentialSchema, CredentialView } from '@/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { useTranslation } from '@/i18n/useI18n';
import {
	credentialFields,
	credentialFieldValue,
	credentialUpdateData,
} from '@/lib/credential-fields';

export interface CredentialEditState {
	dirty: boolean;
	busy: boolean;
}

interface Props {
	credential: CredentialView;
	schema: CredentialSchema | null;
	schemaLoading: boolean;
	onReloadSchema: () => void;
	onSave: (data: Record<string, unknown>) => Promise<CredentialView>;
	onStateChange: (state: CredentialEditState) => void;
	busy?: boolean;
}

export function CredentialFields({
	credential,
	schema,
	schemaLoading,
	onReloadSchema,
	onSave,
	onStateChange,
	busy = false,
}: Props) {
	const { t } = useTranslation();
	const [savedData, setSavedData] = useState(credential.data);
	const [changes, setChanges] = useState<Record<string, string>>({});
	const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
	const [saving, setSaving] = useState(false);
	const savingRef = useRef(false);
	const [saveError, setSaveError] = useState(false);
	const fields = schema ? credentialFields(schema) : [];
	const dirty = fields.some(
		([key]) =>
			Object.hasOwn(changes, key) && changes[key] !== credentialFieldValue(savedData, key),
	);

	useEffect(() => {
		setSavedData(credential.data);
	}, [credential.data]);

	useEffect(() => {
		onStateChange({ dirty, busy: saving || busy });
	}, [dirty, saving, busy, onStateChange]);

	const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		if (!schema || !credential.editable || !dirty || busy || savingRef.current) return;
		savingRef.current = true;
		setSaving(true);
		setSaveError(false);
		try {
			const updated = await onSave(credentialUpdateData(savedData, schema, changes));
			setSavedData(updated.data);
			setChanges({});
			setVisibleSecrets({});
			toast.success(t('credential.inlineEdit.saved'));
		} catch {
			setSaveError(true);
		} finally {
			savingRef.current = false;
			setSaving(false);
		}
	};

	if (!schema)
		return schemaLoading ? (
			<Skeleton className="h-36 w-full shrink-0 rounded-xl" />
		) : (
			<div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4">
				<p role="alert" className="text-sm text-destructive">
					{t('credential.inlineEdit.loadFailed')}
				</p>
				<Button variant="outline" onClick={onReloadSchema}>
					{t('credential.inlineEdit.retry')}
				</Button>
			</div>
		);

	return (
		<form className="@container rounded-xl border bg-muted/15 p-4" onSubmit={handleSave}>
			<fieldset
				disabled={!credential.editable || saving || busy}
				className="min-w-0"
				aria-busy={saving}
			>
				<div className="grid grid-cols-1 gap-4 @md:grid-cols-2 @2xl:grid-cols-3">
					{fields.map(([key, prop]) => {
						if (!credential.editable && savedData[key] == null) return null;
						const label = prop.title ?? key.replace(/_/g, ' ');
						const fieldId = `credential-${credential.id}-${key}`;
						const secret = prop.writeOnly || prop.format === 'password';
						const visible = !!visibleSecrets[key];
						const value = changes[key] ?? credentialFieldValue(savedData, key);
						const knownValue =
							Object.hasOwn(savedData, key) || Object.hasOwn(changes, key);
						const required = !!schema.required?.includes(key) && knownValue;
						return (
							<div key={key} className="grid min-w-0 gap-2">
								<Label
									htmlFor={fieldId}
									className="text-xs font-medium text-muted-foreground"
								>
									{label}
								</Label>
								<div className="relative min-w-0">
									<Input
										id={fieldId}
										name={fieldId}
										type={secret && !visible ? 'password' : 'text'}
										value={value}
										onChange={(event) => {
											const next = event.target.value;
											setChanges((previous) => {
												const updated = { ...previous };
												if (next === credentialFieldValue(savedData, key))
													delete updated[key];
												else updated[key] = next;
												return updated;
											});
											setSaveError(false);
										}}
										required={required}
										pattern={required ? '.*\\S.*' : undefined}
										placeholder={
											!knownValue
												? t('credential.inlineEdit.keepValue')
												: undefined
										}
										autoComplete={secret ? 'new-password' : 'off'}
										autoCapitalize="none"
										spellCheck={false}
										className={`h-9 min-w-0 bg-background text-sm ${key !== 'name' ? 'font-mono' : ''} ${secret ? 'pr-10' : ''}`}
									/>
									{secret && (
										<Button
											type="button"
											size="icon-sm"
											variant="ghost"
											className="absolute right-1 top-1/2 -translate-y-1/2"
											aria-label={t(
												visible
													? 'credential.inlineEdit.hideSecret'
													: 'credential.inlineEdit.showSecret',
												{ field: label },
											)}
											aria-pressed={visible}
											onClick={() =>
												setVisibleSecrets((previous) => ({
													...previous,
													[key]: !visible,
												}))
											}
										>
											{visible ? <EyeOff /> : <Eye />}
										</Button>
									)}
								</div>
							</div>
						);
					})}
				</div>
				{credential.editable && (
					<div className="mt-4 flex flex-wrap items-center justify-end gap-2">
						{saveError && (
							<p role="alert" className="mr-auto text-sm text-destructive">
								{t('credential.inlineEdit.saveFailed')}
							</p>
						)}
						<Button
							type="button"
							variant="ghost"
							disabled={!dirty || saving}
							onClick={() => {
								setChanges({});
								setVisibleSecrets({});
								setSaveError(false);
							}}
						>
							<Undo2 />
							{t('credential.inlineEdit.discard')}
						</Button>
						<Button type="submit" disabled={!dirty || saving}>
							{saving ? <Loader2 className="animate-spin" /> : <Save />}
							{t(saving ? 'common.saving' : 'common.save')}
						</Button>
					</div>
				)}
			</fieldset>
		</form>
	);
}
