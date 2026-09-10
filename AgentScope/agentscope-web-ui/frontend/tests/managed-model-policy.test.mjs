import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	agentModelPolicyFromForm,
	agentModelPolicyToForm,
	agentModelPolicyUpdateFromForm,
} from '../src/lib/agent-model-policy.ts';

test('编辑只保存模型选择，旧参数不会继续覆盖统一模型配置', () => {
	const saved = {
		mode: 'fixed',
		chat_model_config: {
			type: 'custom_openai_credential',
			credential_id: 'credential',
			model: 'model',
			parameters: { max_tokens: 128, __request_body__: { enable_thinking: false } },
		},
	};
	const result = agentModelPolicyFromForm(agentModelPolicyToForm(saved));
	assert.deepEqual(result.chat_model_config, { ...saved.chat_model_config, parameters: {} });
	assert.equal(saved.chat_model_config.parameters.max_tokens, 128);
});

test('固定模型仍须选定模型，跟随会话仍可保存', () => {
	assert.throws(() => agentModelPolicyFromForm({ mode: 'fixed' }), /model_required/);
	assert.deepEqual(agentModelPolicyFromForm({ mode: 'inherit_session' }), {
		mode: 'inherit_session',
		chat_model_config: null,
	});
});

test('只编辑协作说明时不提交模型配置，保留已有参数', () => {
	const saved = {
		mode: 'fixed',
		chat_model_config: {
			type: 'custom_openai_credential',
			credential_id: 'credential',
			model: 'original',
			parameters: { max_tokens: 384000 },
		},
	};
	assert.equal(agentModelPolicyUpdateFromForm(agentModelPolicyToForm(saved), saved), undefined);
	assert.equal(saved.chat_model_config.parameters.max_tokens, 384000);
});

test('修改模型后仍按系统统一参数保存', () => {
	const saved = {
		mode: 'fixed',
		chat_model_config: {
			type: 'custom_openai_credential',
			credential_id: 'credential',
			model: 'original',
			parameters: { max_tokens: 384000 },
		},
	};
	const values = agentModelPolicyToForm(saved);
	values.chat_model_config = { ...values.chat_model_config, model: 'new-model' };
	const updated = agentModelPolicyUpdateFromForm(values, saved);
	assert.equal(updated.chat_model_config.model, 'new-model');
	assert.deepEqual(updated.chat_model_config.parameters, {});
});
