import type { AgentModelPolicy, AgentModelPolicyMode, ChatModelConfig } from '@/api';

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

	return {
		mode,
		chat_model_config: {
			...config,
			parameters: {},
		},
	};
}

/** Editing another section must not rewrite a saved model's legacy parameters. */
export function agentModelPolicyUpdateFromForm(
	values: AgentModelPolicyFormValues,
	original?: AgentModelPolicy | null,
): AgentModelPolicy | undefined {
	if (JSON.stringify(values) === JSON.stringify(agentModelPolicyToForm(original)))
		return undefined;
	return agentModelPolicyFromForm(values);
}
