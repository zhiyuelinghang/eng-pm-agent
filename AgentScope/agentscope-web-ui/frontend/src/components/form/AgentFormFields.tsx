import { useTranslation } from 'react-i18next';

import type {
	AgentCallConfig,
	PlatformAgentConfig,
	AgentSchemaV2Response,
	AgentView,
	JSONSchema,
	JSONSchemaProperty,
} from '@/api';
import { AgentCallConfigFields } from '@/components/form/AgentCallConfigFields';
import { AgentModelPolicyFields } from '@/components/form/AgentModelPolicyFields';
import { AgentPlatformConfigFields } from '@/components/form/AgentPlatformConfigFields';
import { SchemaForm, type SchemaFormValue } from '@/components/form/SchemaForm';
import {
	FieldDescription,
	FieldGroup,
	FieldLegend,
	FieldSeparator,
	FieldSet,
} from '@/components/ui/field';
import { agentModelPolicyToForm, type AgentModelPolicyFormValues } from '@/lib/agent-model-policy';

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
	agents: AgentView[];
	currentAgentId?: string;
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

const IDENTITY_I18N = 'identity';

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

export function AgentFormFields({ schema, values, agents, currentAgentId, onChange }: Props) {
	const { t } = useTranslation();
	const sections = sliceSchema(schema.schema);

	const rows: Array<{ key: AgentSection; i18n: string; sectionSchema: JSONSchema }> = [
		{ key: 'identity', i18n: IDENTITY_I18N, sectionSchema: sections.identity },
		...NESTED_SECTIONS.map((s) => ({
			key: s.key as AgentSection,
			i18n: s.i18n,
			sectionSchema: sections[s.key],
		})),
	];

	return (
		<FieldGroup>
			{rows.map(({ key: sectionKey, i18n: sectionI18n, sectionSchema }, idx) => {
				const legend = t(`agent-form.${sectionI18n}.legend`, {
					defaultValue: sectionSchema.title ?? sectionKey,
				});
				const description = t(`agent-form.${sectionI18n}.description`, {
					defaultValue: '',
				});
				return (
					<div key={sectionKey}>
						{idx > 0 && <FieldSeparator className="my-0" />}
						<FieldSet>
							<FieldLegend>{legend}</FieldLegend>
							{description && <FieldDescription>{description}</FieldDescription>}
							{sectionKey === 'model_policy' ? (
								<AgentModelPolicyFields
									values={values.model_policy as AgentModelPolicyFormValues}
									onChange={(k, v) =>
										onChange('model_policy', String(k), v)
									}
								/>
							) : sectionKey === 'platform_config' ? (
								<AgentPlatformConfigFields
									values={values.platform_config as Partial<PlatformAgentConfig>}
									onChange={(k, v) =>
										onChange('platform_config', String(k), v)
									}
								/>
							) : sectionKey === 'call_config' ? (
								<AgentCallConfigFields
									values={values.call_config as Partial<AgentCallConfig>}
									agents={agents}
									currentAgentId={currentAgentId}
									onChange={(k, v) => onChange('call_config', k, v)}
								/>
							) : (
								<SchemaForm
									schema={sectionSchema}
									values={values[sectionKey] as Record<string, SchemaFormValue>}
									onChange={(k, v) => onChange(sectionKey, k, v)}
									idPrefix={`agent-form-${sectionI18n}`}
									labelFor={(k, prop) =>
										t(`agent-form.${sectionI18n}.${toKebab(k)}.label`, {
											defaultValue: prop.title ?? k.replace(/_/g, ' '),
										})
									}
									placeholderFor={(k, prop) =>
										t(`agent-form.${sectionI18n}.${toKebab(k)}.placeholder`, {
											defaultValue: prop.description ?? '',
										}) || undefined
									}
								/>
							)}
						</FieldSet>
					</div>
				);
			})}
		</FieldGroup>
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
