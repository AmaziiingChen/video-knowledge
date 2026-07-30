import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MAX_AUDIO_WAVEFORM_CACHE_ENTRIES,
  readAudioWaveformCache,
  writeAudioWaveformCache,
} from './audioWaveformCache.js'

function makeStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, String(value)),
  }
}

test('persists compact waveform samples for reopening an imported audio file', () => {
  const storage = makeStorage()
  writeAudioWaveformCache('audio:summer', [[-1, 1], [-0.25, 0.5], [0, 0]], storage)

  const restored = readAudioWaveformCache('audio:summer', storage)
  assert.equal(restored.length, 3)
  assert.deepEqual(restored[0], [-1, 1])
  assert.ok(Math.abs(restored[1][0] + 0.247) < 0.02)
  assert.ok(Math.abs(restored[1][1] - 0.498) < 0.02)
})

test('keeps the waveform cache bounded by recent entries', () => {
  const storage = makeStorage()
  for (let index = 0; index <= MAX_AUDIO_WAVEFORM_CACHE_ENTRIES; index += 1) {
    writeAudioWaveformCache(`audio:${index}`, [[-0.2, 0.2]], storage)
  }

  assert.equal(readAudioWaveformCache('audio:0', storage), null)
  const latest = readAudioWaveformCache(`audio:${MAX_AUDIO_WAVEFORM_CACHE_ENTRIES}`, storage)
  assert.ok(Math.abs(latest[0][0] + 0.2) < 0.01)
  assert.ok(Math.abs(latest[0][1] - 0.2) < 0.01)
})
