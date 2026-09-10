import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	collaborationCandidates,
	collaborationSelection,
	collaborationUpdate,
} from '../src/lib/agent-collaboration.ts';

function agent(id, enabled = true, allowMain = false, invitable = false) {
	return {
		id,
		data: {
			name: id,
			platform_config: { enabled, allow_global_main_call: allowMain },
			invite_config: { invitable },
		},
	};
}

test('固定入口不进入协作候选；任务和知识库助手自动供总控调用', () => {
	const settings = { global_main_agent_id: 'main', project_initializer_agent_id: 'initializer', task_assistant_agent_id: 'task', knowledge_assistant_agent_id: 'knowledge' };
	const main = agent('main', true, true, true);
	const candidates = [main, agent('initializer', true, true, true), agent('task'), agent('knowledge'), agent('business', true, true, true)];
	assert.deepEqual(collaborationCandidates(main, candidates, true, settings).map(a => a.id), ['business', 'knowledge', 'task']);
	assert.deepEqual(collaborationCandidates(agent('other'), candidates, false, settings).map(a => a.id), ['business']);
});

test('总控只自动纳入已启用且允许总控调用的智能体', () => {
	const main = agent('main');
	assert.deepEqual(
		collaborationCandidates(
			main,
			[
				main,
				agent('initializer', true, true),
				agent('business', true, true),
				agent('not-authorized'),
				agent('disabled', false, true),
			],
			true,
		).map((row) => row.id),
		['business', 'initializer'],
	);
});

test('目标关闭总控调用后移出名单，重新开启后自动出现', () => {
	const main = agent('main');
	const target = agent('target', true, true);
	assert.deepEqual(collaborationCandidates(main, [target], true), [target]);
	target.data.platform_config.allow_global_main_call = false;
	assert.deepEqual(collaborationCandidates(main, [target], true), []);
	target.data.platform_config.allow_global_main_call = true;
	assert.deepEqual(collaborationCandidates(main, [target], true), [target]);
});

test('其他主智能体与业务智能体选择协作对象不受总控调用开关影响', () => {
	const caller = agent('initializer');
	assert.deepEqual(
		collaborationCandidates(caller, [
			caller,
			agent('expert', true, false, true),
			agent('disabled', false, false, true),
		]).map((row) => row.id),
		['expert'],
	);
});

for (const allowMain of [false, true]) {
	for (const invitable of [false, true]) {
		test(`总控授权=${allowMain}、其他邀请=${invitable} 独立过滤候选`, () => {
			const target = agent('target', true, allowMain, invitable);
			const caller = agent('caller');
			assert.deepEqual(
				collaborationCandidates(caller, [caller, target], true),
				allowMain ? [target] : [],
			);
			assert.deepEqual(
				collaborationCandidates(caller, [caller, target], false),
				invitable ? [target] : [],
			);
		});
	}
}

test('关闭其他邀请立即移出候选，已有勾选名单也不能使其继续显示', () => {
	const caller = agent('caller');
	caller.data.call_config = { scope: 'selected', allowed_agent_ids: ['target'] };
	const target = agent('target', true, false, true);
	assert.deepEqual(collaborationCandidates(caller, [target]), [target]);
	target.data.invite_config.invitable = false;
	assert.deepEqual(collaborationCandidates(caller, [target]), []);
	assert.deepEqual(collaborationSelection(caller.data.call_config), ['target']);
});

test('只有明确选择的名单生效，未配置时保持独立工作', () => {
	assert.deepEqual(collaborationSelection({ scope: 'selected', allowed_agent_ids: ['a'] }), ['a']);
	assert.deepEqual(collaborationSelection({ scope: 'none', allowed_agent_ids: ['a'] }), []);
	assert.deepEqual(collaborationSelection(), []);
});

test('名单保存去重且只更新调用范围，不覆盖协作说明、模型或平台配置', () => {
	assert.deepEqual(collaborationUpdate(['a', 'a', 'b']), {
		call_config: { scope: 'selected', allowed_agent_ids: ['a', 'b'] },
	});
	assert.deepEqual(collaborationUpdate([]), {
		call_config: { scope: 'none', allowed_agent_ids: [] },
	});
});
