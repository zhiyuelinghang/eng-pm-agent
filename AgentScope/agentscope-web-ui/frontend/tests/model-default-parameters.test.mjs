import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	modelParameterFields,
	modelParameterOverrides,
	modelParameterValues,
	validateModelParameterValues,
} from '../src/lib/model-default-parameters.ts';
import { CUSTOM_REQUEST_BODY_KEY } from '../src/lib/model-parameters.ts';

const schema = {
	properties: {
		temperature: { type: 'number', default: 0.7 },
		reasoning_effort: { type: 'string', default: 'medium' },
		max_tokens: { type: 'integer', default: 4096 },
		thinking_enable: { type: 'boolean', default: false },
		thinking_budget: { type: 'integer', default: 0 },
		top_p: { type: 'number', default: 1 },
		top_k: { type: 'integer', default: 40 },
		parallel_tool_calls: { type: 'boolean', default: true },
	},
};

test('仅提供模型声明的思考模式和强度，不展示自动运行参数或补造能力', () => {
	assert.deepEqual(
		modelParameterFields(schema).map(([key]) => key),
		['reasoning_effort', 'thinking_enable'],
	);
	assert.deepEqual(
		modelParameterFields({ properties: { temperature: schema.properties.temperature } }),
		[],
	);
	assert.deepEqual(modelParameterFields(null), []);
});

test('没有覆盖时保持空对象，显式false、零和与schema默认相同的值仍独立保存', () => {
	assert.deepEqual(modelParameterValues({}), {});
	assert.deepEqual(modelParameterOverrides({}, {}), {});
	const explicit = Object.fromEntries(
		Object.entries(schema.properties).map(([key, property]) => [key, property.default]),
	);
	assert.deepEqual(modelParameterOverrides(explicit, {}), {
		temperature: 0.7,
		reasoning_effort: 'medium',
		max_tokens: 4096,
		thinking_enable: false,
		thinking_budget: 0,
		top_p: 1,
		top_k: 40,
		parallel_tool_calls: true,
	});
});

test('使用默认值仅移除顶层空覆盖，保留false、零、空容器和其他显式值', () => {
	assert.deepEqual(
		modelParameterOverrides(
			{
				temperature: undefined,
				reasoning_effort: null,
				max_tokens: '',
				thinking_enable: false,
				thinking_budget: 0,
				supported_empty_list: [],
				supported_empty_object: {},
				whitespace_value: ' ',
			},
			{},
		),
		{
			thinking_enable: false,
			thinking_budget: 0,
			supported_empty_list: [],
			supported_empty_object: {},
			whitespace_value: ' ',
		},
	);
});

test('只改常用选项保留隐藏高级参数和嵌套请求JSON，草稿与已存数据彼此隔离', () => {
	const saved = {
		thinking_enable: true,
		max_tokens: 8192,
		response_format: { type: 'json_object', details: { strict: false } },
		[CUSTOM_REQUEST_BODY_KEY]: {
			vendor: { thinking: { budget: 0, enabled: false }, tags: ['fictional'] },
		},
	};
	const values = modelParameterValues(saved);
	assert.equal(Object.hasOwn(values, CUSTOM_REQUEST_BODY_KEY), false);
	values.thinking_enable = false;
	const result = modelParameterOverrides(values, saved[CUSTOM_REQUEST_BODY_KEY]);
	assert.deepEqual(result, { ...saved, thinking_enable: false });
	result.response_format.details.strict = true;
	result[CUSTOM_REQUEST_BODY_KEY].vendor.tags.push('new');
	assert.equal(values.response_format.details.strict, false);
	assert.equal(saved.response_format.details.strict, false);
	assert.deepEqual(saved[CUSTOM_REQUEST_BODY_KEY].vendor.tags, ['fictional']);
	assert.equal(saved.thinking_enable, true);
});

test('清空自定义请求体不恢复旧JSON，重置全部覆盖能保存空对象', () => {
	const values = { thinking_enable: false, [CUSTOM_REQUEST_BODY_KEY]: { old_vendor_flag: true } };
	assert.deepEqual(modelParameterOverrides(values, {}), { thinking_enable: false });
	assert.deepEqual(modelParameterOverrides({}, {}), {});
	assert.deepEqual(values[CUSTOM_REQUEST_BODY_KEY], { old_vendor_flag: true });
});

test('新的自定义请求体完全替换旧键，嵌套null、空字符串及数组内容不被清理', () => {
	const newBody = { vendor: { unset: null, text: '', modes: [{ enabled: false, budget: 0 }] } };
	const result = modelParameterOverrides(
		{
			temperature: 0,
			[CUSTOM_REQUEST_BODY_KEY]: { removed_vendor_flag: true },
		},
		newBody,
	);
	assert.deepEqual(result, { temperature: 0, [CUSTOM_REQUEST_BODY_KEY]: newBody });
	newBody.vendor.modes[0].budget = 99;
	assert.equal(result[CUSTOM_REQUEST_BODY_KEY].vendor.modes[0].budget, 0);
});

test('隐藏的旧数值覆盖不阻塞思考设置保存，仍原样保留供后端处理', () => {
	const saved = {
		thinking_enable: false,
		reasoning_effort: 'high',
		temperature: -0.1,
		max_tokens: 65536,
		top_p: 0,
		parallel_tool_calls: false,
		thinking_budget: 0,
	};
	const currentSchema = {
		properties: {
			...schema.properties,
			max_tokens: { type: 'integer', minimum: 1, maximum: 8192 },
			top_p: { type: 'number', exclusiveMinimum: 0, maximum: 1 },
		},
	};
	const values = modelParameterValues(saved);
	assert.equal(validateModelParameterValues(currentSchema, values), null);
	assert.deepEqual(modelParameterOverrides(values, {}), saved);
	assert.equal(
		validateModelParameterValues(currentSchema, { ...values, thinking_enable: 'false' }),
		'thinking_enable',
	);
});
test('枚举与布尔严格区分显式值，选择使用默认值可消除原来的无效覆盖', () => {
	const selectionSchema = {
		properties: {
			thinking_enable: { type: 'boolean' },
			reasoning_effort: {
				anyOf: [{ type: 'string', enum: ['low', 'high'] }, { type: 'null' }],
			},
		},
	};
	assert.equal(
		validateModelParameterValues(selectionSchema, {
			thinking_enable: false,
			reasoning_effort: 'low',
		}),
		null,
	);
	assert.equal(
		validateModelParameterValues(selectionSchema, { thinking_enable: 'false' }),
		'thinking_enable',
	);
	assert.equal(
		validateModelParameterValues(selectionSchema, { reasoning_effort: 'retired-option' }),
		'reasoning_effort',
	);
	for (const resetValue of [undefined, null, '']) {
		const values = { thinking_enable: false, reasoning_effort: resetValue };
		assert.equal(validateModelParameterValues(selectionSchema, values), null);
		assert.deepEqual(modelParameterOverrides(values, {}), { thinking_enable: false });
	}
});

test('校验跳过schema外的已有值，不修改或清理未知高级参数', () => {
	const values = {
		thinking_enable: false,
		previous_provider_option: { limit: -1, flags: [false] },
	};
	const before = structuredClone(values);
	assert.equal(validateModelParameterValues(schema, values), null);
	assert.deepEqual(values, before);
	assert.deepEqual(modelParameterOverrides(values, {}), before);
	assert.equal(validateModelParameterValues(null, values), null);
});
