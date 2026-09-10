import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	MEMORY_SETTINGS_KEYS,
	isAvailableMemoryModel,
	memorySettingsChanges,
	memorySettingsRequest,
	mergeMemorySettings,
	pickMemorySettings,
	sameMemoryValue,
	validateMemorySettings,
} from '../src/lib/memory-settings.ts';

const model = {
	type: 'custom_openai_credential',
	credential_id: 'one',
	model: 'learning',
	parameters: {},
};
const otherModel = { ...model, credential_id: 'two', model: 'compression' };
const thirdModel = { ...model, credential_id: 'three', model: 'alternate' };
const base = () => ({
	learning_enabled: true,
	learning_model_config: structuredClone(model),
	learning_interactions_enabled: true,
	learning_business_events_enabled: true,
	group_learning_enabled: true,
	compression_model_config: null,
});

test('保存只提交六项公开配置和明确版本，不回写内部字段', () => {
	const draft = { ...base(), recall_top_k: 7, memory_model_config: thirdModel };
	const request = memorySettingsRequest(draft, 12);
	assert.deepEqual(Object.keys(request), ['settings', 'expected_revision']);
	assert.deepEqual(Object.keys(request.settings), [...MEMORY_SETTINGS_KEYS]);
	assert.equal(request.expected_revision, 12);
	assert.deepEqual(request.settings, base());
	assert.equal(draft.recall_top_k, 7);
});

test('缺失设置和无效版本不能产生不完整更新', () => {
	for (const key of MEMORY_SETTINGS_KEYS) {
		const incomplete = base();
		delete incomplete[key];
		assert.throws(() => memorySettingsRequest(incomplete, 1), /incomplete/);
	}
	for (const revision of [undefined, null, -1, 0.5, Number.NaN, '1']) {
		assert.throws(() => memorySettingsRequest(base(), revision), /revision/);
	}
	assert.equal(memorySettingsRequest(base(), 0).expected_revision, 0);
});

test('暂停时允许清空学习模型和全部来源，同时采用会话模型压缩', () => {
	const paused = {
		...base(),
		learning_enabled: false,
		learning_model_config: null,
		learning_interactions_enabled: false,
		learning_business_events_enabled: false,
		group_learning_enabled: false,
	};
	assert.deepEqual(validateMemorySettings(paused, []), []);
	assert.deepEqual(memorySettingsRequest(paused, 1).settings, paused);
});

test('启用学习时必须有模型与至少一个来源', () => {
	const draft = {
		...base(),
		learning_model_config: null,
		learning_interactions_enabled: false,
		learning_business_events_enabled: false,
		group_learning_enabled: false,
	};
	assert.deepEqual(validateMemorySettings(draft, []), [
		{ field: 'learning_model_config', code: 'model_required' },
		{ field: 'learning_sources', code: 'source_required' },
	]);
});

for (const source of [
	'learning_interactions_enabled',
	'learning_business_events_enabled',
	'group_learning_enabled',
]) {
	test(`单独启用来源 ${source} 可以保存`, () => {
		const draft = {
			...base(),
			learning_interactions_enabled: false,
			learning_business_events_enabled: false,
			group_learning_enabled: false,
			[source]: true,
		};
		assert.deepEqual(validateMemorySettings(draft, [model]), []);
	});
}

test('模型有效性同时核对提供方、凭证和模型名', () => {
	assert.equal(isAvailableMemoryModel(model, [model]), true);
	for (const changed of [
		{ ...model, type: 'other' },
		{ ...model, credential_id: 'other' },
		{ ...model, model: 'other' },
	]) {
		assert.equal(isAvailableMemoryModel(model, [changed]), false);
	}
	assert.deepEqual(validateMemorySettings(base(), [otherModel]), [
		{ field: 'learning_model_config', code: 'model_unavailable' },
	]);
});

test('压缩与学习分别选择和校验，暂停学习仍可以配置压缩模型', () => {
	const draft = {
		...base(),
		learning_enabled: false,
		learning_model_config: null,
		compression_model_config: otherModel,
	};
	assert.deepEqual(validateMemorySettings(draft, [otherModel]), []);
	assert.deepEqual(validateMemorySettings(draft, [model]), [
		{ field: 'compression_model_config', code: 'model_unavailable' },
	]);
});

test('字段顺序变化不产生假修改，实际模型变化仍能识别', () => {
	const reordered = {
		...base(),
		learning_model_config: {
			parameters: {},
			model: model.model,
			credential_id: model.credential_id,
			type: model.type,
		},
	};
	assert.equal(sameMemoryValue(base(), reordered), true);
	assert.equal(sameMemoryValue(base(), { ...base(), learning_model_config: otherModel }), false);
});

test('并发修改不同字段时保留双方修改，且不改变原草稿', () => {
	const original = base();
	const local = { ...base(), group_learning_enabled: false };
	const remote = { ...base(), compression_model_config: otherModel };
	const merged = mergeMemorySettings(original, local, remote, {});
	assert.deepEqual(merged, { ...remote, group_learning_enabled: false });
	assert.equal(local.compression_model_config, null);
	assert.equal(remote.group_learning_enabled, true);
	assert.equal(original.group_learning_enabled, true);
	assert.equal(
		memorySettingsChanges(original, local, remote).some((change) => change.conflict),
		false,
	);
	assert.equal(memorySettingsRequest(merged, 23).expected_revision, 23);
});

test('同一模型被双方修改时必须明确选择，不能静默覆盖', () => {
	const original = base();
	const local = { ...base(), learning_model_config: otherModel };
	const remote = { ...base(), learning_model_config: thirdModel };
	assert.deepEqual(memorySettingsChanges(original, local, remote), [
		{ key: 'learning_model_config', localChanged: true, remoteChanged: true, conflict: true },
	]);
	assert.throws(() => mergeMemorySettings(original, local, remote, {}), /Choose/);
	assert.deepEqual(
		mergeMemorySettings(original, local, remote, { learning_model_config: 'local' }),
		local,
	);
	assert.deepEqual(
		mergeMemorySettings(original, local, remote, { learning_model_config: 'remote' }),
		remote,
	);
});

test('双方作出相同修改时不要求多余冲突选择', () => {
	const changed = { ...base(), group_learning_enabled: false };
	assert.equal(
		memorySettingsChanges(base(), changed, structuredClone(changed))[0].conflict,
		false,
	);
	assert.deepEqual(mergeMemorySettings(base(), changed, structuredClone(changed), {}), changed);
	assert.deepEqual(pickMemorySettings({ ...changed, hidden_policy: true }), changed);
});
