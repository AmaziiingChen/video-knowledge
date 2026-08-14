const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const {
  TELEMETRY_PROXY_ENVIRONMENT_NAME,
  directChildEnvironment,
  telemetryProxyFromElectronRules,
  telemetryProxyFromEnvironment,
  validatedTelemetryProxyUrl,
} = require('./network-env.cjs')

test('desktop backend inherits only a sanitized telemetry proxy', () => {
  const result = directChildEnvironment({
    PATH: '/usr/bin',
    HTTP_PROXY: 'http://127.0.0.1:7897',
    HTTPS_PROXY: 'http://127.0.0.1:7897',
    ALL_PROXY: 'socks5://127.0.0.1:7897',
    no_proxy: 'localhost',
  })

  assert.deepEqual(result, {
    PATH: '/usr/bin',
    [TELEMETRY_PROXY_ENVIRONMENT_NAME]: 'http://127.0.0.1:7897',
  })
})

test('telemetry proxy validation rejects credentials, paths, unsupported schemes and invalid ports', () => {
  for (const value of [
    '',
    'socks5://127.0.0.1:7897',
    'http://user:secret@127.0.0.1:7897',
    'http://127.0.0.1:7897/private',
    'http://127.0.0.1:7897/?target=private',
    'http://127.0.0.1:99999',
    'not-a-url',
  ]) assert.equal(validatedTelemetryProxyUrl(value), '')

  assert.equal(validatedTelemetryProxyUrl('https://proxy.example.test:443/'), 'https://proxy.example.test')
})

test('invalid higher-priority proxy values cannot hide a valid HTTP proxy', () => {
  assert.equal(telemetryProxyFromEnvironment({
    HTTPS_PROXY: 'socks5://127.0.0.1:7897',
    HTTP_PROXY: 'http://localhost:7897',
  }), 'http://localhost:7897')
})

test('Electron system proxy rules take priority when Finder has no proxy environment', () => {
  assert.equal(
    telemetryProxyFromElectronRules('PROXY 127.0.0.1:7897; DIRECT'),
    'http://127.0.0.1:7897',
  )
  assert.equal(
    telemetryProxyFromElectronRules('HTTPS proxy.example.test:8443; DIRECT'),
    'https://proxy.example.test:8443',
  )
  assert.equal(telemetryProxyFromElectronRules('SOCKS5 127.0.0.1:7897; DIRECT'), '')
  assert.deepEqual(directChildEnvironment({ PATH: '/usr/bin' }, 'http://127.0.0.1:7897'), {
    PATH: '/usr/bin',
    [TELEMETRY_PROXY_ENVIRONMENT_NAME]: 'http://127.0.0.1:7897',
  })
})

test('an injected telemetry-only proxy is discarded unless standard proxy settings validate it', () => {
  assert.deepEqual(directChildEnvironment({
    PATH: '/usr/bin',
    [TELEMETRY_PROXY_ENVIRONMENT_NAME]: 'http://attacker.example:8080',
    HTTPS_PROXY: 'http://user:secret@127.0.0.1:7897',
  }), { PATH: '/usr/bin' })
})

test('public Electron requests may follow system networking without relaxing renderer navigation', () => {
  const mainSource = fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8')

  assert.doesNotMatch(mainSource, /appendSwitch\('no-proxy-server'\)/)
  assert.match(mainSource, /mainWindow\.webContents\.on\('will-navigate'/)
  assert.match(mainSource, /mainWindow\.webContents\.setWindowOpenHandler/)
})
