import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick } from 'vue'

import { searchResultCountBucket, useLibrarySearchController } from './useLibrarySearchController.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function createController({ request = {}, recordTelemetry = () => {} } = {}) {
  const notices = []
  const timers = []
  const cancelled = []
  const controller = useLibrarySearchController({
    request: {
      get: async () => ({ data: [] }),
      post: async () => ({ data: [] }),
      ...request,
    },
    notify: { error: (message) => notices.push(message) },
    recordTelemetry,
    schedule: (callback, delay) => {
      const timer = { callback, delay }
      timers.push(timer)
      return timer
    },
    cancelSchedule: (timer) => cancelled.push(timer),
  })
  return { controller, notices, timers, cancelled }
}

test('search telemetry uses the fixed result-count buckets at every boundary', () => {
  assert.deepEqual(
    [0, 1, 5, 6, 20, 21, 100, 101, 200].map(searchResultCountBucket),
    ['0', '1_5', '1_5', '6_20', '6_20', '21_100', '21_100', '101_plus', '101_plus'],
  )
})

test('empty and one-character queries clear immediately without scheduling a request', async () => {
  const { controller, timers, cancelled } = createController()
  controller.searchResultContentItems.value = [{ id: 'old' }]
  controller.searchQuery.value = 'a'
  await nextTick()

  assert.deepEqual(controller.searchResultContentItems.value, [])
  assert.equal(timers.length, 0)

  controller.searchQuery.value = 'query'
  await nextTick()
  controller.searchQuery.value = ''
  await nextTick()
  assert.equal(cancelled.length, 1)
  controller.disposeLibrarySearchController()
})

test('debounced search resolves global matches in backend result order', async () => {
  const requests = []
  const telemetry = []
  const { controller, timers, cancelled } = createController({
    request: {
      get: async (...args) => {
        requests.push(args)
        return { data: [{ content_key: 'b' }, { content_key: 'a' }, { content_key: 'missing' }] }
      },
      post: async (...args) => {
        requests.push(args)
        return { data: [{ id: 'a', title: 'A' }, { id: 'b', title: 'B' }] }
      },
    },
    recordTelemetry: (...args) => telemetry.push(args),
  })
  controller.searchQuery.value = '  查询 '
  controller.librarySearchScope.value = 'video'
  await nextTick()

  assert.equal(timers.length, 2)
  assert.deepEqual(cancelled, [timers[0]])
  assert.equal(timers[1].delay, 350)
  await timers[1].callback()
  assert.deepEqual(requests, [
    ['http://127.0.0.1:8000/api/search', { params: { q: '查询', scope: 'video', limit: 200 }, timeout: 10000 }],
    ['http://127.0.0.1:8000/api/content/items/resolve', { content_item_ids: ['b', 'a', 'missing'] }, { timeout: 10000 }],
  ])
  assert.deepEqual(controller.searchResultContentItems.value, [{ id: 'b', title: 'B' }, { id: 'a', title: 'A' }])
  assert.deepEqual(telemetry, [['search_completed', { result_count_bucket: '1_5' }]])
  controller.disposeLibrarySearchController()
})

test('a stale search response cannot replace a newer query', async () => {
  const firstSearch = deferred()
  const { controller, timers } = createController({
    request: {
      get: async (url, options) => {
        if (options.params.q === 'first') return firstSearch.promise
        return { data: [{ content_key: 'new' }] }
      },
      post: async () => ({ data: [{ id: 'new', title: 'New' }] }),
    },
  })
  controller.searchQuery.value = 'first'
  await nextTick()
  const firstRun = timers[0].callback()
  controller.searchQuery.value = 'second'
  await nextTick()
  firstSearch.resolve({ data: [{ content_key: 'old' }] })
  await firstRun
  await timers[1].callback()

  assert.deepEqual(controller.searchResultContentItems.value, [{ id: 'new', title: 'New' }])
  controller.disposeLibrarySearchController()
})

test('a current search error clears resolved rows and reports one usable error', async () => {
  const { controller, notices } = createController({
    request: { get: async () => { throw new Error('网络不可用') } },
  })
  controller.searchResultContentItems.value = [{ id: 'previous' }]
  controller.searchQuery.value = 'query'

  await controller.searchContent()
  assert.deepEqual(controller.searchResultContentItems.value, [])
  assert.equal(controller.searchingContent.value, false)
  assert.deepEqual(notices, ['网络不可用'])
  controller.disposeLibrarySearchController()
})

test('disposing cancels a pending debounce timer', async () => {
  const { controller, timers, cancelled } = createController()
  controller.searchQuery.value = 'query'
  await nextTick()
  controller.disposeLibrarySearchController()

  assert.equal(timers.length, 1)
  assert.deepEqual(cancelled, [timers[0]])
})
