const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const { directChildEnvironment } = require('./network-env.cjs')

test('desktop backend never inherits proxy variables from Electron', () => {
  const result = directChildEnvironment({
    PATH: '/usr/bin',
    HTTP_PROXY: 'http://127.0.0.1:7897',
    HTTPS_PROXY: 'http://127.0.0.1:7897',
    ALL_PROXY: 'socks5://127.0.0.1:7897',
    no_proxy: 'localhost',
  })

  assert.deepEqual(result, { PATH: '/usr/bin' })
})

test('public Electron requests may follow system networking without relaxing renderer navigation', () => {
  const mainSource = fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8')

  assert.doesNotMatch(mainSource, /appendSwitch\('no-proxy-server'\)/)
  assert.match(mainSource, /mainWindow\.webContents\.on\('will-navigate'/)
  assert.match(mainSource, /mainWindow\.webContents\.setWindowOpenHandler/)
})
