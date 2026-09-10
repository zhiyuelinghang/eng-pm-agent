import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	availableChatModel,
	firstAvailableChatModel,
	resolveSessionChatModel,
	chatAttachmentBlock,
} from '../src/lib/chat-input.ts';

const model = { name: 'example-vision', input_types: ['text/plain', 'image/png', 'image/jpeg'] };
const groups = {
	empty_provider: [{ credential: { id: 'empty' }, models: [] }],
	custom_openai_credential: [
		{ credential: { id: 'also-empty' }, models: [] },
		{ credential: { id: 'current' }, models: [model] },
	],
};
const config = {
	type: 'custom_openai_credential',
	credential_id: 'current',
	model: model.name,
	parameters: {},
};

test('首个服务商和凭证为空时继续查找真正可用模型', () => {
	assert.deepEqual(firstAvailableChatModel(groups), config);
	assert.equal(firstAvailableChatModel({ empty: groups.empty_provider }), null);
});

test('旧模型或旧凭证不再可用时回落，旧模型专属参数不带到新模型', () => {
	assert.deepEqual(
		resolveSessionChatModel(groups, {
			...config,
			model: 'retired',
			parameters: { temperature: 0 },
		}),
		config,
	);
	assert.deepEqual(
		resolveSessionChatModel(groups, { ...config, credential_id: 'removed' }),
		config,
	);
	assert.equal(resolveSessionChatModel({}, config), null);
});

test('仍可用的会话模型保留原配置，不猜测或扩展图像能力', () => {
	const saved = { ...config, parameters: { thinking_enable: false, temperature: 0 } };
	assert.equal(resolveSessionChatModel(groups, saved), saved);
	assert.equal(availableChatModel(groups, saved), model);
	assert.deepEqual(model.input_types, ['text/plain', 'image/png', 'image/jpeg']);
	assert.equal(availableChatModel(groups, { ...saved, credential_id: 'other' }), null);
});

test('浏览器未提供图片MIME时恢复准确类型，图片原字节通过DataBlock发送', () => {
	assert.deepEqual(
		chatAttachmentBlock({ name: '现场.PNG', type: '' }, 'data:;base64,AQIDBA==', 'image-1'),
		{
			id: 'image-1',
			type: 'data',
			name: '现场.PNG',
			source: { type: 'base64', media_type: 'image/png', data: 'AQIDBA==' },
		},
	);
	assert.equal(
		chatAttachmentBlock(
			{ name: '现场.JPEG', type: 'application/octet-stream' },
			'data:;base64,AQ==',
			'image-2',
		).source.media_type,
		'image/jpeg',
	);
});

test('文档保持明确MIME，未知附件不冒充受支持的原生图片', () => {
	assert.equal(
		chatAttachmentBlock(
			{ name: 'report.jpg', type: 'application/pdf' },
			'data:application/pdf;base64,AQ==',
			'doc',
		).source.media_type,
		'application/pdf',
	);
	assert.equal(
		chatAttachmentBlock({ name: 'other.bin', type: '' }, 'data:;base64,AQ==', 'other').source
			.media_type,
		'application/octet-stream',
	);
});
