import assert from 'node:assert/strict'
import test from 'node:test'
import { libraryContentIcon } from './contentIcons.js'

test('file-tree content types keep their reviewed SF Symbol mappings', () => {
  assert.equal(libraryContentIcon({ content_type: 'article' }), 'text.document')
  assert.equal(libraryContentIcon({ content_type: 'audio' }), 'waveform')
  assert.equal(libraryContentIcon({ content_type: 'video' }), 'film')
  assert.equal(libraryContentIcon({ source_provider: 'bilibili' }), 'film')
})
