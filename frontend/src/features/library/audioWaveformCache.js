const STORAGE_KEY = 'knowledgehub.audio-waveform-cache.v1'
export const MAX_AUDIO_WAVEFORM_CACHE_ENTRIES = 60
export const MAX_AUDIO_WAVEFORM_CACHE_BYTES = 2 * 1024 * 1024

function safeStorage(storage) {
  return storage || globalThis.localStorage
}

function loadEntries(storage) {
  try {
    const entries = JSON.parse(safeStorage(storage).getItem(STORAGE_KEY) || '[]')
    return Array.isArray(entries)
      ? entries.filter((entry) => entry && typeof entry.key === 'string' && typeof entry.samples === 'string')
      : []
  } catch {
    return []
  }
}

function saveEntries(entries, storage) {
  try {
    safeStorage(storage).setItem(STORAGE_KEY, JSON.stringify(entries))
  } catch {
    // Waveforms are a disposable convenience cache. Playback stays available
    // when local storage is unavailable or full.
  }
}

function entrySize(entry) {
  return entry.key.length + entry.samples.length + 96
}

function encodeBytes(bytes) {
  let binary = ''
  const chunkSize = 0x8000
  for (let start = 0; start < bytes.length; start += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(start, start + chunkSize))
  }
  return globalThis.btoa(binary)
}

function decodeBytes(value) {
  const binary = globalThis.atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes
}

function toByte(value) {
  return Math.round((Math.max(-1, Math.min(1, Number(value) || 0)) + 1) * 127.5)
}

function fromByte(value) {
  return (Number(value) / 127.5) - 1
}

export function readAudioWaveformCache(key, storage) {
  if (!key) return null
  const entry = loadEntries(storage).find((candidate) => candidate.key === key)
  if (!entry) return null
  try {
    const bytes = decodeBytes(entry.samples)
    if (bytes.length < 2 || bytes.length % 2 !== 0) return null
    const points = Array.from({ length: bytes.length / 2 }, (_, index) => [
      fromByte(bytes[index * 2]),
      fromByte(bytes[index * 2 + 1]),
    ])
    return points
  } catch {
    return null
  }
}

export function writeAudioWaveformCache(key, points, storage) {
  if (!key || !Array.isArray(points) || !points.length) return
  try {
    const bytes = new Uint8Array(points.length * 2)
    points.forEach((point, index) => {
      bytes[index * 2] = toByte(point?.[0])
      bytes[index * 2 + 1] = toByte(point?.[1])
    })
    const entry = { key, samples: encodeBytes(bytes), savedAt: Date.now() }
    const candidates = [entry, ...loadEntries(storage).filter((candidate) => candidate.key !== key)]
    let retained = candidates.slice(0, MAX_AUDIO_WAVEFORM_CACHE_ENTRIES)
    while (retained.length > 1 && retained.reduce((total, candidate) => total + entrySize(candidate), 0) > MAX_AUDIO_WAVEFORM_CACHE_BYTES) {
      retained = retained.slice(0, -1)
    }
    saveEntries(retained, storage)
  } catch {
    // Encoding failure must not block the first-time waveform or playback.
  }
}
