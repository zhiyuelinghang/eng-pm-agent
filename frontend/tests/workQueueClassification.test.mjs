import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { workQueueStatus, workQueueLabel, isUserWorkQueueTask } = await server.ssrLoadModule('/src/views/workspace/ai-work-platform/presentation.ts')
const task = overrides => ({ status: 'pending', responsibleId: 'u1', confirmatorId: 'reviewer', workflowSteps: [], ...overrides })

test('执行中、待补资料和待确认统一进入未完成，逾期仅改变右侧标签', () => {
  for (const status of ['pending', 'processing', 'need_more_info', 'waiting_confirm', 'overdue']) {
    const item = task({ status })
    assert.equal(workQueueStatus(item), 'unfinished')
    assert.equal(workQueueLabel(item), status === 'overdue' ? '已逾期' : '待处理')
  }
})

test('完成后的任务仍属于责任人与实际经办人，可从未完成移入已完成', () => {
  const item = task({ responsibleId: 'lead', workflowSteps: [{ owner_user_id: 'u1', status: 'processing' }] })
  assert.equal(isUserWorkQueueTask(item, 'u1'), true)
  assert.equal(workQueueStatus(item), 'unfinished')
  item.status = 'done'; item.workflowSteps[0].status = 'completed'
  for (const user of ['u1', 'lead', 'reviewer']) assert.equal(isUserWorkQueueTask(item, user), true)
  assert.equal(workQueueStatus(item), 'done')
  assert.equal(workQueueLabel(item), '已完成')
  assert.equal(isUserWorkQueueTask(item, 'unrelated'), false)
})

test('已取消任务不混入两个任务分类，未登录时不显示个人任务', () => {
  assert.equal(isUserWorkQueueTask(task({ status: 'cancelled' }), 'u1'), false)
  assert.equal(workQueueLabel(task({ status: 'cancelled' })), '已取消')
  assert.equal(isUserWorkQueueTask(task({}), ''), false)
})

test('未完成任务仍按当前责任节点分派，验收任务只在待确认时交给验收人', () => {
  const item = task({ responsibleId: 'lead', workflowSteps: [
    { owner_user_id: 'previous', status: 'completed' }, { owner_user_id: 'current', status: 'processing' },
  ] })
  assert.equal(isUserWorkQueueTask(item, 'previous'), false)
  assert.equal(isUserWorkQueueTask(item, 'current'), true)
  assert.equal(isUserWorkQueueTask(item, 'reviewer'), false)
  item.status = 'waiting_confirm'
  assert.equal(isUserWorkQueueTask(item, 'reviewer'), true)
})
