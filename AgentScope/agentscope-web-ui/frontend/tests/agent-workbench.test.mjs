import assert from 'node:assert/strict';
import { test } from 'node:test';
import { agentDuty, businessAgents, DUTIES, dutyStatus } from '../src/lib/agent-workbench.ts';

const settings = {
	global_main_agent_id: 'main',
	project_initializer_agent_id: 'init',
	task_assistant_agent_id: null,
	knowledge_assistant_agent_id: 'docs',
	project_initializer_validation_mcp: { package_id: 'validator', version: '1' },
};
function agent(id, extra = {}) {
	return {
		id,
		editable: true,
		data: {
			name: id,
			model_policy: { mode: 'fixed', chat_model_config: { model: 'test' } },
			platform_config: {
				enabled: true,
				published: false,
				role: 'system_internal',
				sort_order: 100,
				project_knowledge_enabled: true,
				...extra,
			},
		},
	};
}
test('所有编辑入口按已配置 ID 识别四类固定职责，不依赖名称或运行层级', () => {
	const configured = { ...settings, task_assistant_agent_id: 'task' };
	for (const duty of DUTIES) {
		assert.equal(agentDuty(configured[duty.field], configured), duty);
	}
	assert.equal(agentDuty('internal-manager', configured), undefined);
	assert.equal(agentDuty('Dobby 总控', configured), undefined);
	assert.equal(agentDuty('task', settings), undefined);
});
test('根据四个职责的实际绑定分组，保留内部和未发布业务智能体', () => {
	const items = ['main', 'init', 'docs', 'unpublished-worker', 'internal-manager'].map((id) =>
		agent(id),
	);
	const result = businessAgents(items, settings);
	assert.deepEqual(
		result.map((a) => a.id),
		['internal-manager', 'unpublished-worker'],
	);
	assert.equal(items.length, 5);
	assert.equal(result[0], items[4]);
});
test('更换职责后，原智能体回到业务工具列表，历史对象和 ID 保持不变', () => {
	const items = [agent('main'), agent('replacement')];
	assert.deepEqual(
		businessAgents(items, { ...settings, global_main_agent_id: 'replacement' }).map(
			(a) => a.id,
		),
		['main'],
	);
});
test('绑定对象不可用与职责未配置分别呈现，不能把已有绑定显示成未配置', () => {
	assert.equal(dutyStatus(DUTIES[0], settings, []), 'unavailable');
	assert.equal(dutyStatus(DUTIES[2], settings, []), 'empty');
	assert.equal(dutyStatus(DUTIES[1], settings, [agent('init')]), 'ready');
});
test('知识库助手按固定职责判断，缺模型或初始化校验绑定时提示完善配置', () => {
	const docs = agent('docs', { project_knowledge_enabled: false });
	assert.equal(dutyStatus(DUTIES[3], settings, [docs]), 'ready');
	assert.equal(
		dutyStatus(DUTIES[1], { ...settings, project_initializer_validation_mcp: null }, [
			agent('init'),
		]),
		'invalid',
	);
	const main = agent('main');
	main.data.model_policy.mode = 'inherit_session';
	assert.equal(dutyStatus(DUTIES[0], settings, [main]), 'invalid');
});
