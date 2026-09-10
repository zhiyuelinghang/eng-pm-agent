import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	credentialFields,
	credentialFieldValue,
	credentialUpdateData,
} from '../src/lib/credential-fields.ts';

const schema = {
	type: 'object',
	properties: {
		id: { type: 'string' },
		type: { type: 'string', const: 'openai_credential' },
		name: { type: 'string' },
		api_key: { type: 'string', format: 'password', writeOnly: true },
		base_url: { anyOf: [{ type: 'string' }, { type: 'null' }] },
		organization: { anyOf: [{ type: 'string' }, { type: 'null' }] },
		model_catalog: { type: 'object' },
		fixed_setting: { type: 'string', const: 'fixed' },
	},
};

const saved = () => ({
	id: 'fictional-credential',
	type: 'openai_credential',
	name: '测试连接',
	api_key: 'fictional-test-key',
	base_url: 'https://example.invalid/v1',
	organization: 'fictional-organization',
	fixed_setting: 'fixed',
	provider_extra: 'keep-provider-setting',
	model_catalog: { manual_models: [{ name: 'fictional-model' }] },
});

test('行内字段保留schema顺序和密钥元数据，排除身份、目录和固定字段', () => {
	const fields = credentialFields(schema);
	assert.deepEqual(
		fields.map(([key]) => key),
		['name', 'api_key', 'base_url', 'organization'],
	);
	assert.equal(fields[1][1], schema.properties.api_key);
	assert.deepEqual(credentialFields(null), []);
	assert.deepEqual(credentialFields(undefined), []);
});

test('单行字段将空值转为空字符串，不误清空非空值', () => {
	const data = { unset: undefined, empty: null, key: 'fictional-test-key', zero: 0, flag: false };
	for (const key of ['unset', 'empty', 'missing'])
		assert.equal(credentialFieldValue(data, key), '');
	assert.equal(credentialFieldValue(data, 'key'), 'fictional-test-key');
	assert.equal(credentialFieldValue(data, 'zero'), '0');
	assert.equal(credentialFieldValue(data, 'flag'), 'false');
});

test('只改名称保留未改密钥和provider字段，不回写旧模型目录且不修改原基线', () => {
	const data = saved();
	const original = structuredClone(data);
	const changes = { name: '新名称' };
	assert.deepEqual(credentialUpdateData(data, schema, changes), {
		type: 'openai_credential',
		name: '新名称',
		api_key: 'fictional-test-key',
		base_url: 'https://example.invalid/v1',
		organization: 'fictional-organization',
		fixed_setting: 'fixed',
		provider_extra: 'keep-provider-setting',
	});
	assert.deepEqual(data, original);
	assert.deepEqual(changes, { name: '新名称' });
});

test('草稿不能修改类型或固定字段，也不能注入schema以外字段和旧目录', () => {
	const changes = {
		type: 'other_credential',
		id: 'replacement-id',
		model_catalog: 'stale-catalogue',
		fixed_setting: 'changed',
		unknown: 'injected',
		provider_extra: 'not-editable-through-this-schema',
	};
	const result = credentialUpdateData(saved(), schema, changes);
	assert.equal(result.type, 'openai_credential');
	assert.equal(result.fixed_setting, 'fixed');
	assert.equal(result.provider_extra, 'keep-provider-setting');
	for (const key of ['id', 'model_catalog', 'unknown'])
		assert.equal(Object.hasOwn(result, key), false);
});

test('清空nullable字段提交null，其他字符串原样保存且不替换未修改值', () => {
	const result = credentialUpdateData(saved(), schema, {
		base_url: '',
		organization: '',
		name: '',
		api_key: ' fictional-test-key-with-spaces ',
	});
	assert.equal(result.base_url, null);
	assert.equal(result.organization, null);
	assert.equal(result.name, '');
	assert.equal(result.api_key, ' fictional-test-key-with-spaces ');
	const withoutNullableUrl = {
		...schema,
		properties: { ...schema.properties, base_url: { type: 'string' } },
	};
	assert.equal(credentialUpdateData(saved(), withoutNullableUrl, { base_url: '' }).base_url, '');
	assert.equal(credentialUpdateData(saved(), schema, {}).base_url, 'https://example.invalid/v1');
});
