import assert from 'node:assert/strict'
import { test } from 'node:test'
import { agentImageType, encodeAgentImageAttachments } from '../src/utils/agentImageAttachments.ts'

const file = (name, type, bytes = [1, 2, 3, 4]) => ({ name, type, size: bytes.length, arrayBuffer: async () => Uint8Array.from(bytes).buffer })

test('仅编码本次选择的受支持图片，保留原字节且不把普通文档伪装成图片', async () => {
  const inputs = [file('现场.PNG', ''), file('报告.pdf', 'application/pdf'), file('扫描.tif', 'image/tiff'), file('图.webp', 'image/webp')]
  assert.deepEqual(await encodeAgentImageAttachments(inputs), [
    { name: '现场.PNG', media_type: 'image/png', data: 'AQIDBA==' },
    { name: '图.webp', media_type: 'image/webp', data: 'AQIDBA==' },
  ])
  assert.deepEqual(await encodeAgentImageAttachments([]), [])
  assert.equal(agentImageType({ name: 'image.jpeg', type: 'application/octet-stream' }), 'image/jpeg')
  assert.equal(agentImageType({ name: 'misnamed.jpg', type: 'application/pdf' }), null)
})

test('张数、总大小及空文件限制在读取文件前处理', async () => {
  const unread = { ...file('a.png', 'image/png'), arrayBuffer: () => { throw new Error('must not read') } }
  await assert.rejects(encodeAgentImageAttachments(Array(9).fill(unread)), /最多发送 8 张/)
  await assert.rejects(encodeAgentImageAttachments([{ ...unread, size: 31 * 1024 * 1024 }]), /30 MB/)
  await assert.rejects(encodeAgentImageAttachments([{ ...unread, size: 0 }]), /非空图片/)
  await assert.rejects(encodeAgentImageAttachments([{ ...unread, name: 'a'.repeat(301) }]), /300/)
})

test('停止或切换会话后不再组装图片请求', async () => {
  const controller = new AbortController()
  const selected = { ...file('a.gif', 'image/gif'), arrayBuffer: async () => { controller.abort(); return new ArrayBuffer(4) } }
  await assert.rejects(encodeAgentImageAttachments([selected], controller.signal), { name: 'AbortError' })
})
