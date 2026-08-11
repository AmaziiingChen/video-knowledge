const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const electronDir = __dirname
const mainSource = fs.readFileSync(path.join(electronDir, 'main.cjs'), 'utf8')

function pngSize(fileName) {
  const data = fs.readFileSync(path.join(electronDir, 'assets', fileName))
  assert.equal(data.subarray(1, 4).toString('ascii'), 'PNG')
  return {
    width: data.readUInt32BE(16),
    height: data.readUInt32BE(20),
  }
}

test('macOS tray uses a dedicated template K with standard and Retina assets', () => {
  assert.deepEqual(pngSize('trayTemplate.png'), { width: 18, height: 18 })
  assert.deepEqual(pngSize('trayTemplate@2x.png'), { width: 36, height: 36 })
  assert.match(mainSource, /createFromPath\(path\.join\(__dirname, 'assets', 'trayTemplate\.png'\)\)/)
  assert.match(mainSource, /image\.setTemplateImage\(true\)/)
  assert.doesNotMatch(mainSource, /setPressedImage\(/)
})
