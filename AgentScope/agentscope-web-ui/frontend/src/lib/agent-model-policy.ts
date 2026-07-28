import type { AgentModelPolicy, AgentModelPolicyMode, ChatModelConfig } from '@/api';
import {
	CUSTOM_REQUEST_BODY_KEY,
	customRequestBodyText,
	parseCustomRequestBody,
} from '@/lib/model-parameters';

export interface AgentModelPolicyFormValues extends Record<string, unknown> {
	mode?: AgentModelPolicyMode;
	chat_model_config?: ChatModelConfig | null;
	custom_request_text?: string;
}

export type AgentModelPolicyFormErrorCode = 'model_required' | 'invalid_json' | 'object_required';

export class AgentModelPolicyFormError extends Error {
	readonly code: AgentModelPolicyFormErrorCode;

	constructor(code: AgentModelPolicyFormErrorCode) {
		super(code);
		this.name = 'AgentModelPolicyFormError';
		this.code = code;
	}
}

export function agentModelPolicyToForm(
	policy?: AgentModelPolicy | null,
): AgentModelPolicyFormValues {
	const resolved = policy ?? {
		mode: 'inherit_session' as const,
		chat_model_config: null,
	};
	return {
		mode: resolved.mode,
		chat_model_config: resolved.chat_model_config,
		custom_request_text: resolved.chat_model_config
			? customRequestBodyText(resolved.chat_model_config.parameters)
			: '',
	};
}

export function agentModelPolicyFromForm(values: AgentModelPolicyFormValues): AgentModelPolicy {
	const mode = values.mode ?? 'inherit_session';
	const config = values.chat_model_config ?? null;
	if (mode === 'fixed' && !config) {
		throw new AgentModelPolicyFormError('model_required');
	}

	if (!config) {
		return { mode, chat_model_config: null };
	}

	let customRequestBody: Record<string, unknown>;
	try {
		customRequestBody = parseCustomRequestBody(values.custom_request_text ?? '');
	} catch (error) {
		const code =
			error instanceof Error && error.message === 'object_required'
				? 'object_required'
				: 'invalid_json';
		throw new AgentModelPolicyFormError(code);
	}

	const parameters = { ...config.parameters };
	delete parameters[CUSTOM_REQUEST_BODY_KEY];
	if (Object.keys(customRequestBody).length > 0) {
		parameters[CUSTOM_REQUEST_BODY_KEY] = customRequestBody;
	}
	return {
		mode,
		chat_model_config: {
			...config,
			parameters,
		},
	};
}
