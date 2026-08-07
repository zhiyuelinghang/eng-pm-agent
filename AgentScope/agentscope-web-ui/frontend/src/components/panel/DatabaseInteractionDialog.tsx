import {
	CircleAlert,
	Link2,
	Loader2,
	Pencil,
	Plus,
	Save,
	Trash2,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import type {
	DatabaseInteraction,
	DatabaseConversationType,
	DatabaseContextBindingMode,
	DatabaseContextBindingSource,
	DatabaseInteractionAccessMode,
	DatabaseInteractionContextBinding,
	DatabaseInteractionJoinRequest,
	DatabaseTableInfo,
	DatabaseTableInteractionRequest,
	DatabaseTableOperation,
	DatabaseTablePolicy,
} from '@/api';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

export type DatabaseInteractionDialogMode = 'view' | 'edit' | 'create';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	mode: DatabaseInteractionDialogMode;
	onModeChange: (mode: DatabaseInteractionDialogMode) => void;
	interaction: DatabaseInteraction | null;
	policies: DatabaseTablePolicy[];
	tables: DatabaseTableInfo[];
	loadTables: () => Promise<DatabaseTableInfo[]>;
	editable: boolean;
	onSaveTable: (id: number | null, payload: DatabaseTableInteractionRequest) => Promise<void>;
	onRequestDelete: (interaction: DatabaseInteraction) => void;
}

interface ParameterInfo {
	name: string;
	type: string;
	required: boolean;
	description: string | null;
}

interface RelationOption {
	key: string;
	sourceAlias: string;
	sourceField: string;
	targetField: string;
	label: string;
}

const OPERATION_KEYS: DatabaseTableOperation[] = ['read', 'create', 'update', 'delete'];
const CONVERSATION_TYPES: DatabaseConversationType[] = ['general', 'business', 'initialization'];

function parameterList(schema: Record<string, unknown>): ParameterInfo[] {
	const properties = schema.properties;
	if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return [];
	const required = new Set(
		Array.isArray(schema.required)
			? schema.required.filter((item): item is string => typeof item === 'string')
			: [],
	);
	return Object.entries(properties).map(([name, raw]) => {
		const definition = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
		const typed = definition as Record<string, unknown>;
		const rawType = typed.type;
		return {
			name,
			type: Array.isArray(rawType)
				? rawType.filter((item) => typeof item === 'string').join(' / ')
				: typeof rawType === 'string'
					? rawType
					: 'object',
			required: required.has(name),
			description: typeof typed.description === 'string' ? typed.description : null,
		};
	});
}

function joinDrafts(interaction: DatabaseInteraction | null): DatabaseInteractionJoinRequest[] {
	return (interaction?.join_rules ?? []).map((rule) => ({
		alias: rule.alias,
		source_alias: rule.source_alias,
		source_field: rule.source_field,
		target_policy_id: rule.target_policy_id,
		target_field: rule.target_field,
		join_type: rule.join_type,
		readable_fields: [...rule.readable_fields],
		filterable_fields: [...rule.filterable_fields],
	}));
}

function fieldTypeLabel(type: unknown): string {
	if (Array.isArray(type)) return type.filter((item) => typeof item === 'string').join(' / ');
	return typeof type === 'string' ? type : 'object';
}

export function DatabaseInteractionDialog({
	open,
	onOpenChange,
	mode,
	onModeChange,
	interaction,
	policies,
	tables,
	loadTables,
	editable,
	onSaveTable,
	onRequestDelete,
}: Props) {
	const { t } = useTranslation();
	const [key, setKey] = useState('');
	const [displayName, setDisplayName] = useState('');
	const [description, setDescription] = useState('');
	const [policyId, setPolicyId] = useState('');
	const [operation, setOperation] = useState<DatabaseTableOperation>('read');
	const [joinRules, setJoinRules] = useState<DatabaseInteractionJoinRequest[]>([]);
	const [contextBindings, setContextBindings] = useState<DatabaseInteractionContextBinding[]>([]);
	const [conversationTypes, setConversationTypes] = useState<DatabaseConversationType[]>(CONVERSATION_TYPES);
	const [accessMode, setAccessMode] = useState<DatabaseInteractionAccessMode>('agent');
	const [requiresConfirmation, setRequiresConfirmation] = useState(false);
	const [enabled, setEnabled] = useState(true);
	const [submitting, setSubmitting] = useState(false);
	const [loadingTables, setLoadingTables] = useState(false);
	const [errorMsg, setErrorMsg] = useState('');
	const [relationNotice, setRelationNotice] = useState('');

	const isView = mode === 'view';
	const canEditFields = editable && !isView && !submitting;
	const confirmationRequired = operation !== 'read' && accessMode === 'agent';
	const selectedPolicy = useMemo(
		() => policies.find((policy) => String(policy.id) === policyId) ?? null,
		[policies, policyId],
	);
	const tableByName = useMemo(
		() => new Map(tables.map((table) => [table.name, table])),
		[tables],
	);
	const policyById = useMemo(
		() => new Map(policies.map((policy) => [policy.id, policy])),
		[policies],
	);
	const availableOperations = selectedPolicy?.allowed_operations ?? ['read'];
	const detailParameters = interaction ? parameterList(interaction.input_schema) : [];

	useEffect(() => {
		if (!open) return;
		setKey(interaction?.key ?? '');
		setDisplayName(interaction?.display_name ?? '');
		setDescription(interaction?.description ?? '');
		setPolicyId(interaction?.table_policy_id ? String(interaction.table_policy_id) : '');
		setOperation(interaction?.table_operation ?? 'read');
		setJoinRules(joinDrafts(interaction));
		setContextBindings((interaction?.context_bindings ?? []).map((binding) => ({ ...binding })));
		setConversationTypes([...(interaction?.allowed_conversation_types ?? CONVERSATION_TYPES)]);
		setAccessMode(interaction?.access_mode ?? 'agent');
		setRequiresConfirmation(interaction?.requires_confirmation ?? false);
		setEnabled(interaction?.enabled ?? true);
		setErrorMsg('');
		setRelationNotice('');
	}, [interaction, open]);

	useEffect(() => {
		if (!open || tables.length) return;
		setLoadingTables(true);
		void loadTables()
			.catch((error) => setErrorMsg(formatApiErrorForAlert(error)))
			.finally(() => setLoadingTables(false));
	}, [loadTables, open, tables.length]);

	useEffect(() => {
		if (!selectedPolicy || selectedPolicy.allowed_operations.includes(operation)) return;
		setOperation(selectedPolicy.allowed_operations[0] ?? 'read');
	}, [operation, selectedPolicy]);

	useEffect(() => {
		if (confirmationRequired) setRequiresConfirmation(true);
		if (operation !== 'read') {
			if (joinRules.length) setJoinRules([]);
			setRelationNotice('');
		}
	}, [confirmationRequired, joinRules.length, operation]);

	useEffect(() => {
		setContextBindings((current) => current.filter((binding) => {
			if (operation === 'read') return binding.mode === 'scope';
			return true;
		}));
	}, [operation]);

	const sourcePoliciesAt = (index: number) => {
		const result: Array<{ alias: string; policy: DatabaseTablePolicy }> = [];
		if (selectedPolicy) result.push({ alias: 'main', policy: selectedPolicy });
		joinRules.slice(0, index).forEach((rule) => {
			const policy = policyById.get(rule.target_policy_id);
			if (policy) result.push({ alias: rule.alias, policy });
		});
		return result;
	};

	const relationOptions = (index: number, targetPolicyId: number): RelationOption[] => {
		const targetPolicy = policyById.get(targetPolicyId);
		if (!targetPolicy) return [];
		const targetTable = tableByName.get(targetPolicy.table_name);
		if (!targetTable) return [];
		const options: RelationOption[] = [];
		for (const source of sourcePoliciesAt(index)) {
			const sourceTable = tableByName.get(source.policy.table_name);
			if (!sourceTable) continue;
			for (const sourceColumn of sourceTable.columns) {
				for (const targetColumn of targetTable.columns) {
					const targetName = `${targetTable.name}.${targetColumn.name}`;
					const sourceName = `${sourceTable.name}.${sourceColumn.name}`;
					if (
						!sourceColumn.foreign_keys.includes(targetName) &&
						!targetColumn.foreign_keys.includes(sourceName)
					) continue;
					const keyValue = `${source.alias}|${sourceColumn.name}|${targetColumn.name}`;
					options.push({
						key: keyValue,
						sourceAlias: source.alias,
						sourceField: sourceColumn.name,
						targetField: targetColumn.name,
						label: `${source.alias}.${sourceColumn.name} → ${targetPolicy.table_name}.${targetColumn.name}`,
					});
				}
			}
		}
		return options;
	};

	const uniqueAlias = (tableName: string) => {
		const base = tableName.toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 28) || 'relation';
		const used = new Set(['main', ...joinRules.map((rule) => rule.alias)]);
		if (!used.has(base)) return base;
		let suffix = 2;
		while (used.has(`${base.slice(0, 28)}_${suffix}`)) suffix += 1;
		return `${base.slice(0, 28)}_${suffix}`;
	};

	const createJoinForPolicy = (index: number, targetPolicy: DatabaseTablePolicy) => {
		const options = relationOptions(index, targetPolicy.id);
		const first = options[0];
		if (!first) return null;
		const defaultReadable = targetPolicy.readable_fields.filter(
			(field) => !['id', 'created_at', 'updated_at', first.targetField].includes(field),
		);
		return {
			alias: uniqueAlias(targetPolicy.table_name),
			source_alias: first.sourceAlias,
			source_field: first.sourceField,
			target_policy_id: targetPolicy.id,
			target_field: first.targetField,
			join_type: 'left' as const,
			readable_fields: defaultReadable.length ? defaultReadable : [...targetPolicy.readable_fields],
			filterable_fields: [...targetPolicy.filterable_fields],
		};
	};

	const addJoin = () => {
		const index = joinRules.length;
		for (const policy of policies) {
			const draft = createJoinForPolicy(index, policy);
			if (draft) {
				setJoinRules((current) => [...current, draft]);
				setRelationNotice('');
				return;
			}
		}
		setRelationNotice(t('panel.database.editor.noJoinPath'));
	};

	const replaceJoin = (index: number, rule: DatabaseInteractionJoinRequest) => {
		setJoinRules((current) => current.map((item, itemIndex) => itemIndex === index ? rule : item));
	};

	const changeJoinPolicy = (index: number, targetPolicyId: number) => {
		const policy = policyById.get(targetPolicyId);
		if (!policy) return;
		const current = joinRules[index];
		const next = createJoinForPolicy(index, policy);
		if (!next) {
			setRelationNotice(t('panel.database.editor.noJoinPathForTable'));
			return;
		}
		next.alias = current.alias;
		replaceJoin(index, next);
		setRelationNotice('');
	};

	const toggleJoinField = (
		index: number,
		field: 'readable_fields' | 'filterable_fields',
		name: string,
		checked: boolean,
	) => {
		const rule = joinRules[index];
		const values = rule[field];
		replaceJoin(index, {
			...rule,
			[field]: checked ? [...new Set([...values, name])] : values.filter((item) => item !== name),
		});
	};

	const selectedTableColumns = tableByName.get(selectedPolicy?.table_name ?? '')?.columns ?? [];
	const compatibleSources = (field: string): DatabaseContextBindingSource[] => {
		const column = selectedTableColumns.find((item) => item.name === field);
		if (!column) return [];
		return /^((VAR)?CHAR|TEXT)/i.test(column.type)
			? ['actor_agent_id']
			: /INT/i.test(column.type)
				? ['project_id', 'conversation_id', 'user_id']
				: [];
	};
	const addContextBinding = () => {
		const used = new Set(contextBindings.map((item) => item.field));
		const column = selectedTableColumns.find(
			(item) => !used.has(item.name) && compatibleSources(item.name).length > 0,
		);
		if (!column) return;
		const sources = compatibleSources(column.name);
		const preferred = sources.find((source) => column.name === source) ?? sources[0];
		setContextBindings((current) => [
			...current,
			{
				field: column.name,
				source: preferred,
				mode: 'scope',
			},
		]);
	};
	const replaceContextBinding = (
		index: number,
		binding: DatabaseInteractionContextBinding,
	) => {
		setContextBindings((current) => current.map(
			(item, itemIndex) => itemIndex === index ? binding : item,
		));
	};
	const toggleConversationType = (
		conversationType: DatabaseConversationType,
		checked: boolean,
	) => {
		setConversationTypes((current) => checked
			? [...new Set([...current, conversationType])]
			: current.filter((item) => item !== conversationType));
	};

	const aliases = joinRules.map((rule) => rule.alias);
	const joinsValid = joinRules.every((rule, index) => {
		const options = relationOptions(index, rule.target_policy_id);
		return (
			/^[a-z][a-z0-9_]{1,31}$/.test(rule.alias) &&
			rule.alias !== 'main' &&
			aliases.indexOf(rule.alias) === index &&
			(rule.readable_fields.length > 0 || rule.filterable_fields.length > 0) &&
			options.some((option) =>
				option.sourceAlias === rule.source_alias &&
				option.sourceField === rule.source_field &&
				option.targetField === rule.target_field)
		);
	});
	const bindingFields = contextBindings.map((binding) => binding.field);
	const bindingsValid = contextBindings.every((binding, index) => {
		const column = tableByName.get(selectedPolicy?.table_name ?? '')?.columns.find(
			(item) => item.name === binding.field,
		);
		if (!column || bindingFields.indexOf(binding.field) !== index) return false;
		if (binding.source === 'actor_agent_id') return /^((VAR)?CHAR|TEXT)/i.test(column.type);
		return /INT/i.test(column.type);
	});
	const canSubmit =
		canEditFields &&
		displayName.trim().length > 0 &&
		key.trim().length > 0 &&
		Boolean(selectedPolicy) &&
		conversationTypes.length > 0 &&
		bindingsValid &&
		joinsValid;

	const handleSubmit = async () => {
		if (!canSubmit) return;
		setSubmitting(true);
		setErrorMsg('');
		try {
			await onSaveTable(interaction?.id ?? null, {
				key: key.trim(),
				display_name: displayName.trim(),
				description: description.trim(),
				table_policy_id: Number(policyId),
				table_operation: operation,
				join_rules: operation === 'read' ? joinRules : [],
				context_bindings: contextBindings,
				allowed_conversation_types: conversationTypes,
				access_mode: accessMode,
				requires_confirmation: confirmationRequired ? true : requiresConfirmation,
				enabled,
				sort_order: interaction?.sort_order ?? 1000,
			});
			onOpenChange(false);
		} catch (error) {
			setErrorMsg(formatApiErrorForAlert(error));
		} finally {
			setSubmitting(false);
		}
	};

	const resetDraft = () => {
		setKey(interaction?.key ?? '');
		setDisplayName(interaction?.display_name ?? '');
		setDescription(interaction?.description ?? '');
		setPolicyId(interaction?.table_policy_id ? String(interaction.table_policy_id) : '');
		setOperation(interaction?.table_operation ?? 'read');
		setJoinRules(joinDrafts(interaction));
		setContextBindings((interaction?.context_bindings ?? []).map((binding) => ({ ...binding })));
		setConversationTypes([...(interaction?.allowed_conversation_types ?? CONVERSATION_TYPES)]);
		setAccessMode(interaction?.access_mode ?? 'agent');
		setRequiresConfirmation(interaction?.requires_confirmation ?? false);
		setEnabled(interaction?.enabled ?? true);
		setErrorMsg('');
		setRelationNotice('');
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="flex h-[min(800px,calc(100dvh-2rem))] flex-col sm:max-w-5xl">
				<DialogHeader>
					<DialogTitle>
						{mode === 'create'
							? t('panel.database.editor.createTitle')
							: displayName || t('panel.database.editor.editTitle')}
					</DialogTitle>
					<DialogDescription>
						{mode === 'view' ? key : t('panel.database.editor.tableDescription')}
					</DialogDescription>
				</DialogHeader>
				{errorMsg ? (
					<Alert variant="destructive" className="shrink-0">
						<CircleAlert />
						<AlertDescription className="whitespace-pre-wrap">{errorMsg}</AlertDescription>
					</Alert>
				) : null}

				<div className="grid min-h-0 flex-1 overflow-hidden rounded-lg border md:grid-cols-[12rem_minmax(0,1fr)]">
					<nav className="border-b bg-muted/20 p-2 md:border-r md:border-b-0">
						<a href="#database-interaction-basic" className="block rounded-md px-3 py-2 text-sm font-medium hover:bg-muted">{t('panel.database.editor.basic')}</a>
						<a href="#database-interaction-source" className="mt-1 block rounded-md px-3 py-2 text-sm font-medium hover:bg-muted">{t('panel.database.editor.source')}</a>
						<a href="#database-interaction-boundary" className="mt-1 block rounded-md px-3 py-2 text-sm font-medium hover:bg-muted">{t('panel.database.editor.runtimeBoundary')}</a>
						<a href="#database-interaction-relations" className="mt-1 block rounded-md px-3 py-2 text-sm font-medium hover:bg-muted">{t('panel.database.editor.relations')}</a>
						<a href="#database-interaction-parameters" className="mt-1 block rounded-md px-3 py-2 text-sm font-medium hover:bg-muted">{t('panel.database.parameters')}</a>
						<a href="#database-interaction-settings" className="mt-1 block rounded-md px-3 py-2 text-sm font-medium hover:bg-muted">{t('panel.database.editor.settings')}</a>
					</nav>

					<div className="min-h-0 space-y-7 overflow-y-auto p-4 scroll-smooth">
						<section id="database-interaction-basic" className="scroll-mt-4 space-y-4">
							<h3 className="text-sm font-semibold">{t('panel.database.editor.basic')}</h3>
							<div className="grid gap-4 sm:grid-cols-2">
								<Field>
									<FieldLabel htmlFor="database-interaction-name">{t('panel.database.editor.name')}</FieldLabel>
									<Input id="database-interaction-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} readOnly={!canEditFields} />
								</Field>
								<Field>
									<FieldLabel htmlFor="database-interaction-key">{t('panel.database.editor.key')}</FieldLabel>
									<Input id="database-interaction-key" value={key} onChange={(event) => setKey(event.target.value)} readOnly={!canEditFields || Boolean(interaction)} className="font-mono" />
									<FieldDescription>{t('panel.database.editor.keyHelp')}</FieldDescription>
								</Field>
							</div>
							<Field>
								<FieldLabel htmlFor="database-interaction-description">{t('panel.database.editor.description')}</FieldLabel>
								<Textarea id="database-interaction-description" value={description} onChange={(event) => setDescription(event.target.value)} readOnly={!canEditFields} rows={4} />
							</Field>
						</section>

						<section id="database-interaction-source" className="scroll-mt-4 space-y-4">
							<h3 className="text-sm font-semibold">{t('panel.database.editor.source')}</h3>
							{loadingTables ? (
								<div className="flex items-center text-sm text-muted-foreground">
									<Loader2 className="mr-2 size-4 animate-spin" />
									{t('panel.database.policy.loadingTables')}
								</div>
							) : null}
							<div className="grid gap-4 sm:grid-cols-2">
								<Field>
									<FieldLabel>{t('panel.database.editor.primaryPolicy')}</FieldLabel>
									<Select value={policyId} onValueChange={(value) => { setPolicyId(value); setJoinRules([]); setContextBindings([]); setRelationNotice(''); }} disabled={!canEditFields}>
										<SelectTrigger className="w-full disabled:opacity-100"><SelectValue placeholder={t('panel.database.editor.selectPolicy')} /></SelectTrigger>
										<SelectContent>{policies.map((policy) => <SelectItem key={policy.id} value={String(policy.id)}>{policy.display_name} · {policy.table_name}</SelectItem>)}</SelectContent>
									</Select>
								</Field>
								<Field>
									<FieldLabel>{t('panel.database.editor.operation')}</FieldLabel>
									<Select value={operation} onValueChange={(value) => setOperation(value as DatabaseTableOperation)} disabled={!canEditFields || !selectedPolicy}>
										<SelectTrigger className="w-full disabled:opacity-100"><SelectValue /></SelectTrigger>
										<SelectContent>{OPERATION_KEYS.filter((item) => availableOperations.includes(item)).map((item) => <SelectItem key={item} value={item}>{t(`panel.database.operations.${item}`)}</SelectItem>)}</SelectContent>
									</Select>
								</Field>
							</div>
							{selectedPolicy ? (
								<div className="grid gap-2 rounded-lg bg-muted/35 px-3 py-3 text-sm sm:grid-cols-2">
									<span><span className="text-muted-foreground">{t('panel.database.source')}：</span>{selectedPolicy.table_name}</span>
									<span><span className="text-muted-foreground">{t('panel.database.scope')}：</span>{t(`panel.database.scopes.${selectedPolicy.scope_type}`)}</span>
								</div>
							) : null}
						</section>

						<section id="database-interaction-boundary" className="scroll-mt-4 space-y-4">
							<div>
								<h3 className="text-sm font-semibold">{t('panel.database.editor.runtimeBoundary')}</h3>
								<p className="mt-1 text-sm text-muted-foreground">{t('panel.database.editor.runtimeBoundaryHelp')}</p>
							</div>
							<div className="grid gap-4 sm:grid-cols-2">
								<Field>
									<FieldLabel>{t('panel.database.editor.accessMode')}</FieldLabel>
									<Select value={accessMode} onValueChange={(value) => setAccessMode(value as DatabaseInteractionAccessMode)} disabled={!canEditFields}>
										<SelectTrigger className="w-full disabled:opacity-100"><SelectValue /></SelectTrigger>
										<SelectContent>
											<SelectItem value="agent">{t('panel.database.editor.accessModes.agent')}</SelectItem>
											<SelectItem value="workflow">{t('panel.database.editor.accessModes.workflow')}</SelectItem>
										</SelectContent>
									</Select>
									<FieldDescription>{t(`panel.database.editor.accessModeHelp.${accessMode}`)}</FieldDescription>
								</Field>
								<Field>
									<FieldLabel>{t('panel.database.editor.conversationTypes')}</FieldLabel>
									<div className="grid grid-cols-3 gap-2">
										{CONVERSATION_TYPES.map((conversationType) => (
											<label key={conversationType} className="flex items-center gap-2 rounded-md border px-2.5 py-2 text-sm">
												<Checkbox checked={conversationTypes.includes(conversationType)} disabled={!canEditFields} onCheckedChange={(checked) => toggleConversationType(conversationType, checked === true)} />
												{t(`panel.database.editor.conversations.${conversationType}`)}
											</label>
										))}
									</div>
								</Field>
							</div>

							<div className="space-y-3">
								<div className="flex items-center justify-between gap-3">
									<div>
										<h4 className="text-sm font-medium">{t('panel.database.editor.contextBindings')}</h4>
										<p className="mt-1 text-sm text-muted-foreground">{t('panel.database.editor.contextBindingsHelp')}</p>
									</div>
									{canEditFields ? <Button type="button" size="sm" variant="outline" onClick={addContextBinding} disabled={contextBindings.length >= selectedTableColumns.filter((item) => compatibleSources(item.name).length > 0).length}><Plus />{t('panel.database.editor.addContextBinding')}</Button> : null}
								</div>
								{contextBindings.length === 0 ? (
									<div className="rounded-lg border border-dashed px-4 py-5 text-center text-sm text-muted-foreground">{t('panel.database.editor.noContextBindings')}</div>
								) : (
									<div className="space-y-2">
										{contextBindings.map((binding, index) => {
											const sourceOptions = compatibleSources(binding.field);
											return (
												<div key={`${binding.field}-${index}`} className="grid items-end gap-2 rounded-lg border p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
													<Field><FieldLabel>{t('panel.database.editor.bindingField')}</FieldLabel><Select value={binding.field} onValueChange={(field) => { const options = compatibleSources(field); replaceContextBinding(index, { ...binding, field, source: options.includes(binding.source) ? binding.source : options[0] }); }} disabled={!canEditFields}><SelectTrigger className="w-full disabled:opacity-100"><SelectValue /></SelectTrigger><SelectContent>{selectedTableColumns.filter((column) => compatibleSources(column.name).length > 0 && (column.name === binding.field || !bindingFields.includes(column.name))).map((column) => <SelectItem key={column.name} value={column.name}>{column.name}</SelectItem>)}</SelectContent></Select></Field>
													<Field><FieldLabel>{t('panel.database.editor.bindingSource')}</FieldLabel><Select value={binding.source} onValueChange={(source) => replaceContextBinding(index, { ...binding, source: source as DatabaseContextBindingSource })} disabled={!canEditFields}><SelectTrigger className="w-full disabled:opacity-100"><SelectValue /></SelectTrigger><SelectContent>{sourceOptions.map((source) => <SelectItem key={source} value={source}>{t(`panel.database.editor.contextSources.${source}`)}</SelectItem>)}</SelectContent></Select></Field>
													<Field><FieldLabel>{t('panel.database.editor.bindingMode')}</FieldLabel><Select value={binding.mode} onValueChange={(value) => replaceContextBinding(index, { ...binding, mode: value as DatabaseContextBindingMode })} disabled={!canEditFields}><SelectTrigger className="w-full disabled:opacity-100"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="scope">{t('panel.database.editor.bindingModes.scope')}</SelectItem><SelectItem value="value" disabled={operation === 'read'}>{t('panel.database.editor.bindingModes.value')}</SelectItem></SelectContent></Select></Field>
													{canEditFields ? <Button type="button" size="icon" variant="ghost" onClick={() => setContextBindings((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 /><span className="sr-only">{t('common.delete')}</span></Button> : <span />}
												</div>
											);
										})}
									</div>
								)}
							</div>
						</section>

						<section id="database-interaction-relations" className="scroll-mt-4 space-y-3">
							<div className="flex items-center justify-between gap-3">
								<div>
									<h3 className="text-sm font-semibold">{t('panel.database.editor.relations')}</h3>
									<p className="mt-1 text-sm text-muted-foreground">{t('panel.database.editor.relationsHelp')}</p>
								</div>
								{canEditFields && operation === 'read' ? <Button type="button" variant="outline" size="sm" onClick={addJoin}><Plus />{t('panel.database.editor.addRelation')}</Button> : null}
							</div>
							{relationNotice ? (
								<Alert variant="destructive" className="border-destructive/30 bg-destructive/5">
									<CircleAlert />
									<AlertDescription>{relationNotice}</AlertDescription>
								</Alert>
							) : null}
							{operation !== 'read' ? (
								<Alert><CircleAlert /><AlertDescription>{t('panel.database.editor.writeSingleTable')}</AlertDescription></Alert>
							) : joinRules.length === 0 ? (
								<div className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">{t('panel.database.editor.noRelations')}</div>
							) : (
								<div className="space-y-3">
									{joinRules.map((rule, index) => {
										const targetPolicy = policyById.get(rule.target_policy_id) ?? null;
										const options = relationOptions(index, rule.target_policy_id);
										const relationValue = `${rule.source_alias}|${rule.source_field}|${rule.target_field}`;
										return (
											<article key={`${rule.alias}-${index}`} className="overflow-hidden rounded-lg border">
												<header className="flex items-center justify-between gap-3 border-b bg-muted/30 px-3 py-2.5">
													<div className="flex min-w-0 items-center gap-2"><Link2 className="size-4 shrink-0" /><span className="truncate text-sm font-medium">{targetPolicy?.display_name ?? t('panel.database.editor.unknownPolicy')}</span><Badge variant="outline">{rule.alias}</Badge></div>
													{canEditFields ? <Button type="button" variant="ghost" size="icon-xs" onClick={() => setJoinRules((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 /><span className="sr-only">{t('common.delete')}</span></Button> : null}
												</header>
												<div className="space-y-4 p-3">
													<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
														<Field><FieldLabel>{t('panel.database.editor.relationTable')}</FieldLabel><Select value={String(rule.target_policy_id)} onValueChange={(value) => changeJoinPolicy(index, Number(value))} disabled={!canEditFields}><SelectTrigger className="w-full disabled:opacity-100"><SelectValue /></SelectTrigger><SelectContent>{policies.map((policy) => <SelectItem key={policy.id} value={String(policy.id)}>{policy.display_name}</SelectItem>)}</SelectContent></Select></Field>
														<Field><FieldLabel>{t('panel.database.editor.alias')}</FieldLabel><Input value={rule.alias} onChange={(event) => replaceJoin(index, { ...rule, alias: event.target.value })} readOnly={!canEditFields} className="font-mono" /></Field>
														<Field><FieldLabel>{t('panel.database.editor.joinCondition')}</FieldLabel><Select value={relationValue} onValueChange={(value) => { const option = options.find((item) => item.key === value); if (option) replaceJoin(index, { ...rule, source_alias: option.sourceAlias, source_field: option.sourceField, target_field: option.targetField }); }} disabled={!canEditFields}><SelectTrigger className="w-full disabled:opacity-100"><SelectValue /></SelectTrigger><SelectContent>{options.map((option) => <SelectItem key={option.key} value={option.key}>{option.label}</SelectItem>)}</SelectContent></Select></Field>
														<Field><FieldLabel>{t('panel.database.editor.joinType')}</FieldLabel><Select value={rule.join_type} onValueChange={(value) => replaceJoin(index, { ...rule, join_type: value as 'left' | 'inner' })} disabled={!canEditFields}><SelectTrigger className="w-full disabled:opacity-100"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="left">{t('panel.database.editor.leftJoin')}</SelectItem><SelectItem value="inner">{t('panel.database.editor.innerJoin')}</SelectItem></SelectContent></Select></Field>
													</div>
													{targetPolicy ? (
														<div className="overflow-hidden rounded-md border">
															<div className="grid grid-cols-[minmax(0,1fr)_5rem_5rem] border-b bg-muted/30 px-3 py-2 text-sm font-medium text-muted-foreground"><span>{t('panel.database.policy.fieldName')}</span><span className="text-center">{t('panel.database.editor.returnField')}</span><span className="text-center">{t('panel.database.policy.filterable')}</span></div>
															<div className="max-h-52 divide-y overflow-y-auto">{[...new Set([...targetPolicy.readable_fields, ...targetPolicy.filterable_fields])].map((field) => <div key={field} className="grid grid-cols-[minmax(0,1fr)_5rem_5rem] items-center px-3 py-2"><code className="truncate text-xs">{field}</code><div className="flex justify-center"><Checkbox checked={rule.readable_fields.includes(field)} disabled={!canEditFields || !targetPolicy.readable_fields.includes(field)} onCheckedChange={(checked) => toggleJoinField(index, 'readable_fields', field, checked === true)} /></div><div className="flex justify-center"><Checkbox checked={rule.filterable_fields.includes(field)} disabled={!canEditFields || !targetPolicy.filterable_fields.includes(field)} onCheckedChange={(checked) => toggleJoinField(index, 'filterable_fields', field, checked === true)} /></div></div>)}</div>
														</div>
													) : null}
												</div>
											</article>
										);
									})}
								</div>
							)}
						</section>

						<section id="database-interaction-parameters" className="scroll-mt-4 space-y-3">
							<h3 className="text-sm font-semibold">{t('panel.database.parameters')}</h3>
							{detailParameters.length ? <div className="divide-y rounded-lg border">{detailParameters.map((parameter) => <div key={parameter.name} className="px-3 py-2.5"><div className="flex items-center justify-between gap-2"><code className="text-xs font-medium">{parameter.name}</code><span className="text-xs text-muted-foreground">{parameter.required ? t('panel.database.required') : t('panel.database.optional')} · {fieldTypeLabel(parameter.type)}</span></div>{parameter.description ? <p className="mt-1 text-sm text-muted-foreground">{parameter.description}</p> : null}</div>)}</div> : <p className="text-sm text-muted-foreground">{mode === 'create' ? t('panel.database.editor.parametersAfterSave') : t('panel.database.noParameters')}</p>}
						</section>

						<section id="database-interaction-settings" className="scroll-mt-4 space-y-3">
							<h3 className="text-sm font-semibold">{t('panel.database.editor.settings')}</h3>
							<div className="divide-y rounded-lg border">
								<label className="flex items-center justify-between gap-4 px-3 py-3"><span><span className="block text-sm font-medium">{t('panel.database.editor.enabled')}</span><span className="block text-sm text-muted-foreground">{t('panel.database.editor.enabledHelp')}</span></span><Switch checked={enabled} onCheckedChange={setEnabled} disabled={!canEditFields} className="disabled:opacity-100" /></label>
								<label className="flex items-center justify-between gap-4 px-3 py-3"><span><span className="block text-sm font-medium">{t('panel.database.editor.confirmation')}</span><span className="block text-sm text-muted-foreground">{confirmationRequired ? t('panel.database.editor.writeConfirmationHelp') : t('panel.database.editor.confirmationHelp')}</span></span><Switch checked={requiresConfirmation} onCheckedChange={setRequiresConfirmation} disabled={!canEditFields || confirmationRequired} className="disabled:opacity-100" /></label>
							</div>
						</section>

					</div>
				</div>

				<DialogFooter className="sm:justify-between">
					<div>{interaction && editable && !isView ? <Button variant="ghost" onClick={() => onRequestDelete(interaction)} disabled={submitting}><Trash2 />{t('common.delete')}</Button> : null}</div>
					<div className="flex justify-end gap-2">
						{isView ? (
							<><Button variant="outline" onClick={() => onOpenChange(false)}>{t('common.close')}</Button>{editable ? <Button onClick={() => onModeChange('edit')}><Pencil />{t('panel.database.edit')}</Button> : null}</>
						) : (
							<><Button variant="outline" onClick={() => { if (interaction) { resetDraft(); onModeChange('view'); } else onOpenChange(false); }} disabled={submitting}>{t('common.cancel')}</Button><Button onClick={() => void handleSubmit()} disabled={!canSubmit || submitting}>{submitting ? <Loader2 className="animate-spin" /> : <Save />}{t('common.save')}</Button></>
						)}
					</div>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
