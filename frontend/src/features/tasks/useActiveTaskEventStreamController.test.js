import assert from 'node:assert/strict'
import test from 'node:test'

import { useActiveTaskEventStreamController } from './useActiveTaskEventStreamController.js'

class FakeEventSource {
  constructor(url) {
    this.url = url
    this.listeners = new Map()
    this.closed = false
  }

  addEventListener(type, callback) {
    this.listeners.set(type, callback)
  }

  close() {
    this.closed = true
  }

  emit(type, data) {
    this.listeners.get(type)?.({ data })
  }
}

function createController() {
  const sources = []
  const merges = []
  const applied = []
  const hydrated = []
  const snapshots = new Map([['task/1', { stage: 'download' }]])
  const controller = useActiveTaskEventStreamController({
    apiBase: 'http://127.0.0.1:8000/api',
    eventSourceFactory: (url) => {
      const source = new FakeEventSource(url)
      sources.push(source)
      return source
    },
    mergeBatchTasks: (tasks) => merges.push(tasks),
    applyTaskData: (task) => applied.push(task),
    hydrateProgressiveTask: (...args) => hydrated.push(args),
    progressiveTaskSnapshots: snapshots,
    terminalStatuses: new Set(['completed', 'failed']),
    isActiveTask: (task) => task.status === 'running',
  })
  return { controller, sources, merges, applied, hydrated }
}

test('streams only the active content task, ignores malformed events, and closes on a terminal update', async () => {
  const { controller, sources, merges, applied, hydrated } = createController()
  controller.syncTaskEventStream({
    activeContentItemId: 'content-1',
    batchTasks: [{ task_id: 'task/1', content_item_id: 'content-1', status: 'running' }],
  })
  assert.equal(sources.length, 1)
  assert.equal(sources[0].url, 'http://127.0.0.1:8000/api/tasks/task%2F1/events')

  sources[0].emit('task', 'not-json')
  sources[0].emit('task', JSON.stringify({ task_id: 'other', status: 'running' }))
  assert.deepEqual(merges, [])

  const completed = { task_id: 'task/1', content_item_id: 'content-1', status: 'completed' }
  sources[0].emit('task', JSON.stringify(completed))
  await Promise.resolve()
  assert.deepEqual(merges, [[completed]])
  assert.deepEqual(applied, [completed])
  assert.deepEqual(hydrated, [[completed, { stage: 'download' }]])
  assert.equal(sources[0].closed, true)
})

test('reuses a matching stream and closes it when the active content changes or disappears', () => {
  const { controller, sources } = createController()
  const task = { task_id: 'task-1', content_item_id: 'content-1', status: 'running' }
  controller.syncTaskEventStream({ activeContentItemId: 'content-1', batchTasks: [task] })
  controller.syncTaskEventStream({ activeContentItemId: 'content-1', batchTasks: [task] })
  assert.equal(sources.length, 1)

  controller.syncTaskEventStream({ activeContentItemId: 'content-2', batchTasks: [task] })
  assert.equal(sources[0].closed, true)
  controller.syncTaskEventStream({ activeContentItemId: 'content-1', batchTasks: [task] })
  assert.equal(sources.length, 2)
  controller.stopTaskEventStream()
  assert.equal(sources[1].closed, true)
})

test('does not create a stream when EventSource is unavailable', () => {
  const controller = useActiveTaskEventStreamController({
    apiBase: '/api',
    mergeBatchTasks: () => assert.fail('should not merge'),
    applyTaskData: () => assert.fail('should not apply'),
    hydrateProgressiveTask: () => assert.fail('should not hydrate'),
    progressiveTaskSnapshots: new Map(),
    terminalStatuses: new Set(),
    isActiveTask: () => true,
  })
  controller.syncTaskEventStream({
    activeContentItemId: 'content-1',
    batchTasks: [{ task_id: 'task-1', content_item_id: 'content-1' }],
  })
})
