const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
  canonicalGwtUrl,
  canonicalGwtAttachmentUrl,
  clampLimit,
  GWT_WEBVPN_LIST_URL,
  gwtWebVpnArticleUrl,
  gwtWebVpnResourceUrl,
  gwtWebVpnListPageUrl,
  createCampusWebVpnController,
  extractArticle,
  extractListEntriesSince,
  isAllowedCampusUrl,
  isGwtListUrl,
  isGwtTransportUrl,
  normalizeGwtAttachments,
  normalizePublishedDate,
} = require('./campus-webvpn.cjs')

test('campus navigation accepts only SZTU HTTPS hosts', () => {
  assert.equal(isAllowedCampusUrl('https://webvpn.sztu.edu.cn/'), true)
  assert.equal(isAllowedCampusUrl('https://nbw-sztu-edu-cn.webvpn.sztu.edu.cn/info/1029/1.htm'), true)
  assert.equal(isAllowedCampusUrl('http://webvpn.sztu.edu.cn/'), false)
  assert.equal(isAllowedCampusUrl('https://webvpn.sztu.edu.cn.example.com/'), false)
})

test('GWT transport rejects unrelated SZTU subdomains', () => {
  assert.equal(isGwtTransportUrl('https://nbw.sztu.edu.cn/info/1029/1.htm'), true)
  assert.equal(isGwtTransportUrl('https://nbw-sztu-edu-cn.webvpn.sztu.edu.cn/info/1029/1.htm'), true)
  assert.equal(isGwtTransportUrl('https://design.sztu.edu.cn/info/1029/1.htm'), false)
})

test('GWT list recognition survives WebVPN hostname rewriting', () => {
  assert.equal(isGwtListUrl(GWT_WEBVPN_LIST_URL), true)
  assert.equal(
    GWT_WEBVPN_LIST_URL,
    'https://nbw-sztu-edu-cn-s.webvpn.sztu.edu.cn:8118/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029',
  )
  assert.equal(
    isGwtListUrl('https://nbw-sztu-edu-cn.webvpn.sztu.edu.cn/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029'),
    true,
  )
  assert.equal(isGwtListUrl('https://webvpn.sztu.edu.cn/login'), false)
})

test('relative and rewritten GWT links map to the canonical campus URL', () => {
  assert.equal(
    canonicalGwtUrl('/info/1029/4321.htm', 'https://proxy.webvpn.sztu.edu.cn/info/1029/4321.htm'),
    'https://nbw.sztu.edu.cn/info/1029/4321.htm',
  )
  assert.equal(
    canonicalGwtUrl('https://proxy.webvpn.sztu.edu.cn/info/1029/9876.htm'),
    'https://nbw.sztu.edu.cn/info/1029/9876.htm',
  )
  assert.equal(
    canonicalGwtUrl('http://nbw.sztu.edu.cn/info/1020/51877.htm'),
    'https://nbw.sztu.edu.cn/info/1020/51877.htm',
  )
  assert.equal(canonicalGwtUrl('https://example.com/steal'), '')
})

test('GWT article links always stay inside the authenticated WebVPN transport', () => {
  assert.equal(
    gwtWebVpnArticleUrl('info/1020/51877.htm', 'https://nbw.sztu.edu.cn/info/1020/51877.htm'),
    'https://nbw-sztu-edu-cn-s.webvpn.sztu.edu.cn:8118/info/1020/51877.htm',
  )
  assert.equal(gwtWebVpnArticleUrl('https://example.com/steal'), '')
})

test('GWT attachments keep canonical metadata and download through WebVPN', () => {
  const canonical = canonicalGwtAttachmentUrl(
    'https://nbw.sztu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1',
  )
  assert.equal(
    canonical,
    'https://nbw.sztu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1',
  )
  assert.equal(
    gwtWebVpnResourceUrl(canonical),
    'https://nbw-sztu-edu-cn-s.webvpn.sztu.edu.cn:8118/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1',
  )
  assert.equal(canonicalGwtAttachmentUrl('https://example.com/steal.pdf'), '')
})

test('GWT attachment normalization deduplicates proxy URLs and rejects other hosts', () => {
  const attachments = normalizeGwtAttachments([
    {
      name: '  附件 1：实施方案  ',
      raw_href: '/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1',
      resolved_href: 'https://nbw-sztu-edu-cn-s.webvpn.sztu.edu.cn:8118/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1',
    },
    {
      name: '重复链接',
      url: 'https://nbw.sztu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1',
    },
    { name: '恶意附件', url: 'https://example.com/steal.pdf' },
    { name: '普通导航', url: 'https://nbw.sztu.edu.cn/info/1019/51866.htm' },
  ])

  assert.deepEqual(attachments, [{
    name: '附件 1：实施方案',
    url: 'https://nbw.sztu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1',
    download_type: 'direct',
  }])
})

test('GWT attachment normalization keeps imported metadata bounded', () => {
  const candidates = Array.from({ length: 120 }, (_, index) => ({
    name: `附件 ${index + 1}`,
    url: `https://nbw.sztu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&wbfileid=${index + 1}`,
  }))
  assert.equal(normalizeGwtAttachments(candidates).length, 100)
})

test('WebVPN article extraction scans the full page for sibling attachment blocks', async () => {
  let injectedScript = ''
  await extractArticle({
    webContents: {
      executeJavaScript: async (script) => {
        injectedScript = script
        return null
      },
    },
  })

  assert.match(injectedScript, /document\.querySelectorAll\('a\[href\]'\)/)
  assert.match(injectedScript, /raw_href/)
  assert.match(injectedScript, /publicationCandidates/)
  assert.match(injectedScript, /published_at: publishedAt/)
  assert.doesNotMatch(injectedScript, /attachments:\s*originalLinks\.map/)
})

test('GWT attachment download reuses the WebVPN session and saves asynchronously', async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'knowledgehub-webvpn-download-'))
  const destination = path.join(userData, '通知附件.pdf')
  let fetchedUrl = ''
  const campusSession = {
    setPermissionRequestHandler() {},
    fetch: async (url) => {
      fetchedUrl = url
      return {
        ok: true,
        status: 200,
        url,
        headers: { get: (name) => name === 'content-type' ? 'application/pdf' : '8' },
        arrayBuffer: async () => Uint8Array.from([37, 80, 68, 70]).buffer,
      }
    },
  }
  const controller = createCampusWebVpnController({
    app: { getPath: () => userData },
    BrowserWindow: class {},
    session: { fromPartition: () => campusSession },
    safeStorage: { isEncryptionAvailable: () => false },
    dialog: { showSaveDialog: async () => ({ canceled: false, filePath: destination }) },
  })

  const result = await controller.downloadAttachment(
    'https://nbw.sztu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1',
    '通知附件.pdf',
  )

  assert.equal(fetchedUrl, 'https://nbw-sztu-edu-cn-s.webvpn.sztu.edu.cn:8118/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1')
  assert.deepEqual(fs.readFileSync(destination), Buffer.from([37, 80, 68, 70]))
  assert.deepEqual(result, { canceled: false, path: destination })
})

test('sync limit remains bounded', () => {
  assert.equal(clampLimit('bad'), 20)
  assert.equal(clampLimit(0), 1)
  assert.equal(clampLimit(500), 300)
})

test('GWT backfill page URLs and dates are normalized deterministically', () => {
  assert.equal(normalizePublishedDate('2026年7月2日'), '2026-07-02')
  assert.equal(normalizePublishedDate('2026/07/02 9:05'), '2026-07-02 09:05')
  assert.equal(normalizePublishedDate('2026-07-02 09:05:07'), '2026-07-02 09:05:07')
  assert.equal(normalizePublishedDate('未知日期'), '')
  const page = new URL(gwtWebVpnListPageUrl(3))
  assert.equal(page.searchParams.get('PAGENUM'), '3')
  assert.equal(page.searchParams.get('wbtreeid'), '1029')
})

test('GWT WebVPN backfill paginates through the requested date boundary', async () => {
  const pages = {
    '1': [
      { title: '近期通知一', raw_href: '/info/1029/1.htm', fetch_url: 'https://nbw.sztu.edu.cn/info/1029/1.htm', published_at: '2026-07-15' },
      { title: '近期通知二', raw_href: '/info/1029/2.htm', fetch_url: 'https://nbw.sztu.edu.cn/info/1029/2.htm', published_at: '2026-07-10' },
    ],
    '2': [
      { title: '边界通知', raw_href: '/info/1029/3.htm', fetch_url: 'https://nbw.sztu.edu.cn/info/1029/3.htm', published_at: '2026-07-02' },
      { title: '更早通知', raw_href: '/info/1029/4.htm', fetch_url: 'https://nbw.sztu.edu.cn/info/1029/4.htm', published_at: '2026-07-01' },
    ],
    '3': [
      { title: '历史通知', raw_href: '/info/1029/5.htm', fetch_url: 'https://nbw.sztu.edu.cn/info/1029/5.htm', published_at: '2026-06-30' },
    ],
  }
  const loaded = []
  const fakeWindow = {
    destroyed: false,
    isDestroyed() { return this.destroyed },
    loadURL(url) {
      this.webContents.url = url
      loaded.push(new URL(url).searchParams.get('PAGENUM') || '1')
      return Promise.resolve()
    },
    webContents: {
      url: GWT_WEBVPN_LIST_URL,
      getURL() { return this.url },
      executeJavaScript() {
        const page = new URL(this.url).searchParams.get('PAGENUM') || '1'
        return Promise.resolve(pages[page] || [])
      },
      stop() {},
    },
  }

  const entries = await extractListEntriesSince(fakeWindow, 300, '2026-07-02')

  assert.deepEqual(entries.map((entry) => entry.title), ['近期通知一', '近期通知二', '边界通知'])
  assert.deepEqual(loaded, ['2', '3'])
})

test('connection finishes automatically after the authenticated notice list loads', async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'knowledgehub-webvpn-'))
  const windows = []

  class FakeWebContents extends EventEmitter {
    constructor() {
      super()
      this.url = ''
    }

    getURL() { return this.url }
    setWindowOpenHandler() {}
  }

  class FakeBrowserWindow extends EventEmitter {
    constructor() {
      super()
      this.destroyed = false
      this.webContents = new FakeWebContents()
      windows.push(this)
    }

    isDestroyed() { return this.destroyed }
    show() {}
    focus() {}
    loadURL(url) {
      this.webContents.url = url
      return Promise.resolve()
    }
    close() {
      this.destroyed = true
      this.emit('closed')
    }
  }

  const campusSession = {
    setPermissionRequestHandler() {},
    cookies: { get: async () => [{ domain: '.sztu.edu.cn' }] },
    clearStorageData: async () => {},
  }
  const controller = createCampusWebVpnController({
    app: { getPath: () => userData },
    BrowserWindow: FakeBrowserWindow,
    session: { fromPartition: () => campusSession },
    safeStorage: { isEncryptionAvailable: () => false },
  })

  const connection = controller.connect()
  assert.equal(windows[0].webContents.getURL(), GWT_WEBVPN_LIST_URL)
  windows[0].webContents.url = GWT_WEBVPN_LIST_URL
  windows[0].webContents.emit('did-finish-load')

  const result = await connection
  assert.equal(result.connected, true)
  assert.equal(result.has_list_url, true)
  assert.equal(windows[0].isDestroyed(), true)
})

test('sync migrates a saved legacy proxy URL and distinguishes an empty list', async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'knowledgehub-webvpn-sync-'))
  fs.writeFileSync(
    path.join(userData, 'campus-webvpn-session.bin'),
    JSON.stringify({
      listUrl: 'https://nbw-sztu-edu-cn.webvpn.sztu.edu.cn/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029',
    }),
  )
  const loadedUrls = []

  class FakeSyncWebContents extends EventEmitter {
    constructor() {
      super()
      this.url = ''
    }

    getURL() { return this.url }
    setWindowOpenHandler() {}
    executeJavaScript() { return Promise.resolve([]) }
  }

  class FakeSyncWindow extends EventEmitter {
    constructor() {
      super()
      this.destroyed = false
      this.webContents = new FakeSyncWebContents()
    }

    isDestroyed() { return this.destroyed }
    loadURL(url) {
      loadedUrls.push(url)
      this.webContents.url = url
      return Promise.resolve()
    }
    destroy() { this.destroyed = true }
  }

  const campusSession = {
    setPermissionRequestHandler() {},
    cookies: { get: async () => [{ domain: '.sztu.edu.cn' }] },
    clearStorageData: async () => {},
  }
  const controller = createCampusWebVpnController({
    app: { getPath: () => userData },
    BrowserWindow: FakeSyncWindow,
    session: { fromPartition: () => campusSession },
    safeStorage: { isEncryptionAvailable: () => false },
  })

  const result = await controller.sync(20)
  assert.deepEqual(loadedUrls, [GWT_WEBVPN_LIST_URL])
  assert.equal(result.error, 'list_parse_failed')
  assert.match(result.message, /页面结构可能已经变化/)
})
