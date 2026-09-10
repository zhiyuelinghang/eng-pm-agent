import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DUTIES } from '../src/lib/agent-workbench.ts';
import { saveFixedAgentSetup } from '../src/lib/fixed-agent-setup.ts';

const body = {
	name: '任务助手',
	model_policy: { mode: 'fixed', chat_model_config: { model: 'test' } },
	platform_config: { enabled: true },
};

test('知识库助手由固定职责获得查询能力，不要求勾选权限', async () => {
	const { api, settings, calls } = harness();
	settings.knowledge_assistant_agent_id = null;
	assert.equal(await saveFixedAgentSetup(DUTIES[3], body, { agentId: null }, api), 'task');
	assert.equal(settings.knowledge_assistant_agent_id, 'task');
	assert.deepEqual(calls, ['create', 'configure']);
});
function harness() {
	const settings = {
		global_main_agent_id: 'main',
		project_initializer_agent_id: 'init',
		task_assistant_agent_id: null,
		knowledge_assistant_agent_id: 'docs',
		project_initializer_validation_mcp: { package_id: 'validator', version: '1' },
	};
	const calls = [];
	const api = {
		getPlatformSettings: async () => ({ ...settings }),
		create: async () => {
			calls.push('create');
			return { agent_id: 'task' };
		},
		update: async (id) => {
			calls.push(`update:${id}`);
		},
		updatePlatformSettings: async (value) => {
			calls.push('configure');
			Object.assign(settings, value);
			return { ...settings };
		},
	};
	return { settings, calls, api };
}
test('配置固定任务助手只填写自身，不替换其他主智能体', async () => {
	const { api, settings, calls } = harness();
	assert.equal(await saveFixedAgentSetup(DUTIES[2], body, { agentId: null }, api), 'task');
	assert.equal(settings.task_assistant_agent_id, 'task');
	assert.equal(settings.global_main_agent_id, 'main');
	assert.equal(settings.project_initializer_agent_id, 'init');
	assert.deepEqual(calls, ['create', 'configure']);
});
test('其他会话已完成配置时阻止覆盖和重复创建', async () => {
	const { api, settings, calls } = harness();
	settings.task_assistant_agent_id = 'another-task';
	await assert.rejects(saveFixedAgentSetup(DUTIES[2], body, { agentId: null }, api), /已有配置/);
	assert.deepEqual(calls, []);
});
test('配置第二步失败后重试复用同一对象', async () => {
	const { api, calls } = harness();
	const configure = api.updatePlatformSettings;
	api.updatePlatformSettings = async () => {
		throw new Error('temporarily offline');
	};
	const pending = { agentId: null };
	await assert.rejects(saveFixedAgentSetup(DUTIES[2], body, pending, api), /temporarily offline/);
	assert.equal(pending.agentId, 'task');
	api.updatePlatformSettings = configure;
	assert.equal(await saveFixedAgentSetup(DUTIES[2], body, pending, api), 'task');
	assert.deepEqual(calls, ['create', 'update:task', 'configure']);
	assert.equal(pending.agentId, null);
});
test('保存成功但响应丢失时读回确认，不重复创建', async () => {
	const { api, settings, calls } = harness();
	api.updatePlatformSettings = async (value) => {
		Object.assign(settings, value);
		throw new Error('response lost');
	};
	assert.equal(await saveFixedAgentSetup(DUTIES[2], body, { agentId: null }, api), 'task');
	assert.deepEqual(calls, ['create']);
});
test('缺模型或初始化核验版本时不产生半成品对象', async () => {
	const { api, settings, calls } = harness();
	await assert.rejects(
		saveFixedAgentSetup(
			DUTIES[2],
			{ ...body, model_policy: { mode: 'inherit_session' } },
			{ agentId: null },
			api,
		),
		/固定模型/,
	);
	settings.project_initializer_agent_id = null;
	settings.project_initializer_validation_mcp = null;
	await assert.rejects(saveFixedAgentSetup(DUTIES[1], body, { agentId: null }, api), /核验/);
	assert.deepEqual(calls, []);
});
