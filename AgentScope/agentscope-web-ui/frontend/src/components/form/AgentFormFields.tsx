import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type {
	PlatformAgentConfig,
	AgentSchemaV2Response,
	JSONSchema,
	JSONSchemaProperty,
} from '@/api';
import { AgentIncomingCollaborationFields } from '@/components/form/AgentIncomingCollaborationFields';
import { AgentModelPolicyFields } from '@/components/form/AgentModelPolicyFields';
import { AgentPlatformConfigFields } from '@/components/form/AgentPlatformConfigFields';
import { SchemaForm, type SchemaFormValue } from '@/components/form/SchemaForm';
import { Textarea } from '@/components/ui/textarea';
import { agentModelPolicyToForm, type AgentModelPolicyFormValues } from '@/lib/agent-model-policy';
import type { Duty } from '@/lib/agent-workbench';

export type AgentSection =
	| 'identity'
	| 'model_policy'
	| 'platform_config'
	| 'context_config'
	| 'react_config'
	| 'invite_config'
	| 'call_config';

export type AgentFormValues = {
	[K in AgentSection]: Record<string, unknown>;
};

interface Props {
	schema: AgentSchemaV2Response;
	values: AgentFormValues;
	initialSection?: EditorSection;
	primaryDuty?: Duty;
	onChange: (section: AgentSection, key: string, value: unknown) => void;
}

/**
 * Section derivation from the flat `AgentData` schema. Ordered — controls
 * the visual order of the fieldsets. "identity" carries every top-level
 * property that is NOT one of the nested-object sections below, so any
 * newly added scalar / boolean / textarea field on `AgentData` shows up
 * in the identity fieldset automatically.
 */
const NESTED_SECTIONS: Array<{ key: Exclude<AgentSection, 'identity'>; i18n: string }> = [
	{ key: 'model_policy', i18n: 'model-policy' },
	{ key: 'platform_config', i18n: 'platform-config' },
	{ key: 'context_config', i18n: 'context-config' },
	{ key: 'react_config', i18n: 'react-config' },
	{ key: 'invite_config', i18n: 'invite-config' },
	{ key: 'call_config', i18n: 'call-config' },
];

const toKebab = (s: string) => s.replace(/_/g, '-');

/** Split the flat `AgentData` schema into the sections the form renders
 * (currently four: `identity` + one per `NESTED_SECTIONS` entry). */
function sliceSchema(root: JSONSchema): Record<AgentSection, JSONSchema> {
	const props = root.properties ?? {};
	const nestedKeys = new Set(NESTED_SECTIONS.map((s) => s.key));

	const identityProps: Record<string, JSONSchemaProperty> = {};
	for (const [k, prop] of Object.entries(props)) {
		if (nestedKeys.has(k as Exclude<AgentSection, 'identity'>)) continue;
		identityProps[k] = prop;
	}

	const identity: JSONSchema = {
		type: 'object',
		title: 'Identity',
		properties: identityProps,
		required: (root.required ?? []).filter(
			(r) => !nestedKeys.has(r as Exclude<AgentSection, 'identity'>),
		),
	};

	return {
		identity,
		model_policy: (props.model_policy as JSONSchema) ?? {
			type: 'object',
			properties: {},
		},
		platform_config: (props.platform_config as JSONSchema) ?? {
			type: 'object',
			properties: {},
		},
		context_config: (props.context_config as JSONSchema) ?? {
			type: 'object',
			properties: {},
		},
		react_config: (props.react_config as JSONSchema) ?? {
			type: 'object',
			properties: {},
		},
		invite_config: (props.invite_config as JSONSchema) ?? {
			type: 'object',
			properties: {},
		},
		call_config: (props.call_config as JSONSchema) ?? {
			type: 'object',
			properties: {},
		},
	};
}

export type EditorSection = 'identity' | 'model' | 'platform' | 'collaboration';
export function AgentFormFields({
	schema,
	values,
	initialSection = 'identity',
	primaryDuty,
	onChange,
}: Props) {
	const { t, i18n } = useTranslation();
	const zh = i18n.language.startsWith('zh');
	const sections = sliceSchema(schema.schema);
	const [active, setActive] = useState<EditorSection>(initialSection);
	const id = useId();
	const rows: [EditorSection, string, string][] = [
		[
			'identity',
			zh ? '基本信息' : 'Identity',
			zh ? '设置名称与工作指令。' : 'Name and working instructions.',
		],
		[
			'model',
			zh ? '模型配置' : 'Model',
			zh ? '选择此智能体使用的模型。' : 'Choose the model used by this agent.',
		],
		[
			'platform',
			primaryDuty
				? zh
					? '高级设置'
					: 'Advanced settings'
				: zh
					? '平台接入'
					: 'Platform access',
			primaryDuty
				? zh
					? '设置运行时的操作确认方式。'
					: 'Set how actions are confirmed during execution.'
				: zh
					? '设置平台可见范围与调用权限。'
					: 'Visibility and platform access.',
		],
		[
			'collaboration',
			zh ? '协作设置' : 'Collaboration',
			zh
				? '说明此智能体如何承接协作任务。'
				: 'Describe how this agent handles delegated work.',
		],
	];
	const renderSchema = (section: AgentSection) => (
		<SchemaForm
			schema={sections[section]}
			values={values[section] as Record<string, SchemaFormValue>}
			onChange={(k, v) => onChange(section, k, v)}
			idPrefix={`${id}-${section}`}
			labelFor={(k, prop) =>
				t(`agent-form.${toKebab(section)}.${toKebab(k)}.label`, {
					defaultValue: prop.title ?? k.replace(/_/g, ' '),
				})
			}
			placeholderFor={(k, prop) =>
				t(`agent-form.${toKebab(section)}.${toKebab(k)}.placeholder`, {
					defaultValue: prop.description ?? '',
				}) || undefined
			}
			descriptionFor={(k) =>
				t(`agent-form.${toKebab(section)}.${toKebab(k)}.description`, {
					defaultValue: '',
				}) || undefined
			}
		/>
	);
	const row = rows.find(([key]) => key === active)!;
	return (
		<div className="grid h-full min-h-0 grid-cols-1 md:grid-cols-[12rem_minmax(0,1fr)]">
			<nav
				aria-label={zh ? '智能体配置' : 'Agent settings'}
				className="flex gap-1 overflow-x-auto border-b bg-muted/20 p-3 md:flex-col md:border-r md:border-b-0 md:py-5"
			>
				{rows.map(([key, label]) => (
					<button
						key={key}
						type="button"
						aria-current={key === active ? 'page' : undefined}
						aria-controls={`${id}-content`}
						onClick={() => setActive(key)}
						className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-3 text-left text-sm font-medium transition-colors ${active === key ? 'bg-[#c95622]/8 text-[#c95622]' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
					>
						<span
							aria-hidden="true"
							className={`size-1.5 rounded-full ${key === active ? 'bg-[#c95622]' : 'bg-border'}`}
						/>
						{label}
					</button>
				))}
			</nav>
			<div id={`${id}-content`} className="min-h-0 overflow-y-auto px-6 py-6 sm:px-8">
				<div className="mx-auto max-w-2xl space-y-6">
					<div>
						<h3 className="text-lg font-semibold">{row[1]}</h3>
						<p className="mt-1 text-sm text-muted-foreground">{row[2]}</p>
					</div>
					<div hidden={active !== 'identity'} className="space-y-6">
						<div className="[&_textarea]:min-h-48">{renderSchema('identity')}</div>
						<div className="space-y-2">
							<label htmlFor={`${id}-description`} className="text-sm font-medium">
								{zh ? '职责说明' : 'Description'}
							</label>
							<Textarea
								id={`${id}-description`}
								rows={3}
								value={String(values.platform_config.description ?? '')}
								onChange={(e) =>
									onChange(
										'platform_config',
										'description',
										e.target.value || null,
									)
								}
							/>
						</div>
					</div>
					<div hidden={active !== 'model'} className="space-y-6">
						<AgentModelPolicyFields
							values={values.model_policy as AgentModelPolicyFormValues}
							onChange={(k, v) => onChange('model_policy', String(k), v)}
						/>
					</div>
					<div hidden={active !== 'platform'} className="space-y-6">
						<AgentPlatformConfigFields
							fixedDuty={!!primaryDuty}
							mainDuty={primaryDuty?.key === 'main'}
							values={values.platform_config as Partial<PlatformAgentConfig>}
							onChange={(k, v) => onChange('platform_config', String(k), v)}
						/>
					</div>
					<div hidden={active !== 'collaboration'}>
						<AgentIncomingCollaborationFields
							primaryDuty={primaryDuty?.key}
							mainDuty={primaryDuty?.key === 'main'}
							invitable={values.invite_config.invitable === true}
							onInvitableChange={(allowed) =>
								onChange('invite_config', 'invitable', allowed)
							}
							allowGlobalMainCall={
								values.platform_config.allow_global_main_call === true
							}
							onAllowGlobalMainCallChange={(allowed) =>
								onChange('platform_config', 'allow_global_main_call', allowed)
							}
							description={String(values.invite_config.invite_description ?? '')}
							onChange={(value) =>
								onChange('invite_config', 'invite_description', value)
							}
						/>
					</div>
				</div>
			</div>
		</div>
	);
}

/** Build a fresh `AgentFormValues` populated from each section schema's defaults. */
export function defaultAgentFormValues(schema: AgentSchemaV2Response): AgentFormValues {
	const sections = sliceSchema(schema.schema);
	const fromDefaults = (section: JSONSchema): Record<string, SchemaFormValue> => {
		const out: Record<string, SchemaFormValue> = {};
		for (const [k, prop] of Object.entries(section.properties ?? {})) {
			if (prop.const !== undefined) continue;
			if (prop.default !== undefined) out[k] = prop.default as SchemaFormValue;
		}
		return out;
	};
	return {
		identity: fromDefaults(sections.identity),
		model_policy: agentModelPolicyToForm(),
		platform_config: {
			role: 'business',
			enabled: true,
			published: true,
			allow_global_main_call: false,
			description: null,
			category: '通用',
			sort_order: 100,
			permission_mode: 'auto',
			knowledge_config: null,
		},
		context_config: fromDefaults(sections.context_config),
		react_config: fromDefaults(sections.react_config),
		invite_config: fromDefaults(sections.invite_config),
		call_config: fromDefaults(sections.call_config),
	};
}
