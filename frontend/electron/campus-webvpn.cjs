const fs = require('fs')
const path = require('path')

const WEBVPN_HOME = 'https://webvpn.sztu.edu.cn/'
const GWT_DIRECT_BASE = 'https://nbw.sztu.edu.cn/'
const GWT_LIST_PATH = 'list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029'
// The SZTU Sangfor portal advertises the HTTPS resource through its `-s`
// proxy host on port 8118. The superficially similar host without `-s`/8118
// redirects back to unified authentication even when the portal session is
// valid, which made a healthy login look expired during synchronization.
const GWT_WEBVPN_BASE = 'https://nbw-sztu-edu-cn-s.webvpn.sztu.edu.cn:8118/'
const GWT_WEBVPN_LIST_URL = new URL(GWT_LIST_PATH, GWT_WEBVPN_BASE).toString()
const CAMPUS_PARTITION = 'persist:knowledgehub-sztu-webvpn'
const MAX_SYNC_ITEMS = 300
const MAX_LIST_PAGES = 50
const MAX_ARTICLE_ATTACHMENTS = 100

function isAllowedCampusUrl(value) {
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase()
    return url.protocol === 'https:' && (host === 'sztu.edu.cn' || host.endsWith('.sztu.edu.cn'))
  } catch {
    return false
  }
}

function isGwtTransportUrl(value) {
  try {
    const host = new URL(value).hostname.toLowerCase()
    return isAllowedCampusUrl(value) && (
      host === 'nbw.sztu.edu.cn'
      || host === 'webvpn.sztu.edu.cn'
      || host.endsWith('.webvpn.sztu.edu.cn')
    )
  } catch {
    return false
  }
}

function isGwtListUrl(value) {
  try {
    const url = new URL(value)
    const expected = new URL(GWT_LIST_PATH, GWT_DIRECT_BASE)
    return isGwtTransportUrl(value)
      && url.pathname.endsWith(expected.pathname)
      && url.searchParams.get('wbtreeid') === expected.searchParams.get('wbtreeid')
  } catch {
    return false
  }
}

function canonicalGwtUrl(rawHref, resolvedHref = '') {
  const raw = String(rawHref || '').trim()
  if (!raw || /^(?:javascript:|mailto:|#)/i.test(raw)) return ''

  try {
    const direct = new URL(raw, GWT_DIRECT_BASE)
    if (direct.hostname.toLowerCase() === 'nbw.sztu.edu.cn') {
      return new URL(`${direct.pathname}${direct.search}`, GWT_DIRECT_BASE).toString()
    }
  } catch {
    // WebVPN may expose only the rewritten absolute URL. Its normal article
    // paths can still be mapped to the canonical public campus hostname.
  }

  try {
    const proxied = new URL(resolvedHref || raw)
    if (!isGwtTransportUrl(proxied.toString()) || !/^\/info\//.test(proxied.pathname)) return ''
    return new URL(`${proxied.pathname}${proxied.search}`, GWT_DIRECT_BASE).toString()
  } catch {
    return ''
  }
}

function gwtWebVpnArticleUrl(rawHref, resolvedHref = '') {
  const canonical = canonicalGwtUrl(rawHref, resolvedHref)
  if (!canonical) return ''
  const direct = new URL(canonical)
  return new URL(`${direct.pathname}${direct.search}`, GWT_WEBVPN_BASE).toString()
}

function canonicalGwtAttachmentUrl(rawHref, resolvedHref = '') {
  for (const value of [rawHref, resolvedHref]) {
    try {
      const url = new URL(String(value || ''), GWT_DIRECT_BASE)
      const canonical = url.hostname.toLowerCase() === 'nbw.sztu.edu.cn'
        ? new URL(`${url.pathname}${url.search}`, GWT_DIRECT_BASE)
        : (isGwtTransportUrl(url.toString())
            ? new URL(`${url.pathname}${url.search}`, GWT_DIRECT_BASE)
            : null)
      if (!canonical || !/(?:download\.jsp|downloadattachurl|clickdown|\.(?:pdf|docx?|xlsx?|pptx?|zip|rar)(?:$|[?#]))/i.test(canonical.toString())) continue
      return canonical.toString()
    } catch {
      // Try the alternate form supplied by the page.
    }
  }
  return ''
}

function gwtWebVpnResourceUrl(canonicalUrl) {
  try {
    const direct = new URL(canonicalUrl)
    if (direct.hostname.toLowerCase() !== 'nbw.sztu.edu.cn') return ''
    return new URL(`${direct.pathname}${direct.search}`, GWT_WEBVPN_BASE).toString()
  } catch {
    return ''
  }
}

function normalizeGwtAttachments(candidates = []) {
  if (!Array.isArray(candidates)) return []
  const attachments = []
  const seen = new Set()
  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== 'object') continue
    const rawHref = String(candidate.raw_href || candidate.url || '').trim()
    const resolvedHref = String(candidate.resolved_href || candidate.url || '').trim()
    const url = canonicalGwtAttachmentUrl(rawHref, resolvedHref)
    if (!url || seen.has(url)) continue
    seen.add(url)
    attachments.push({
      name: String(candidate.name || '未命名附件').replace(/\s+/g, ' ').trim().slice(0, 300) || '未命名附件',
      url,
      download_type: 'direct',
    })
    if (attachments.length >= MAX_ARTICLE_ATTACHMENTS) break
  }
  return attachments
}

function clampLimit(value) {
  const parsed = Number.parseInt(value, 10)
  if (!Number.isFinite(parsed)) return 20
  return Math.max(1, Math.min(MAX_SYNC_ITEMS, parsed))
}

function normalizePublishedDate(value) {
  const match = String(value || '').match(
    /(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?(?:\s*T?\s*([01]?\d|2[0-3])\s*[:：时]\s*([0-5]?\d)(?:\s*[:：分]\s*([0-5]?\d)\s*秒?)?\s*分?)?/,
  )
  if (!match) return ''
  let normalized = `${match[1]}-${match[2].padStart(2, '0')}-${match[3].padStart(2, '0')}`
  if (match[4] !== undefined && match[5] !== undefined) {
    normalized += ` ${match[4].padStart(2, '0')}:${match[5].padStart(2, '0')}`
    if (match[6] !== undefined) normalized += `:${match[6].padStart(2, '0')}`
  }
  return normalized
}

function gwtWebVpnListPageUrl(page) {
  const url = new URL(GWT_WEBVPN_LIST_URL)
  url.searchParams.set('PAGENUM', String(Math.max(1, Number.parseInt(page, 10) || 1)))
  return url.toString()
}

function createCampusWebVpnController({ app, BrowserWindow, session, safeStorage, dialog }) {
  let loginWindow = null

  function campusSession() {
    const value = session.fromPartition(CAMPUS_PARTITION, { cache: true })
    value.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
    return value
  }

  function metadataPath() {
    return path.join(app.getPath('userData'), 'campus-webvpn-session.bin')
  }

  function readMetadata() {
    const file = metadataPath()
    if (!fs.existsSync(file)) return {}
    try {
      const payload = fs.readFileSync(file)
      const text = safeStorage.isEncryptionAvailable()
        ? safeStorage.decryptString(payload)
        : payload.toString('utf8')
      const data = JSON.parse(text)
      return data && typeof data === 'object' ? data : {}
    } catch {
      return {}
    }
  }

  function writeMetadata(updates) {
    const next = { ...readMetadata(), ...updates, updatedAt: new Date().toISOString() }
    const text = JSON.stringify(next)
    const payload = safeStorage.isEncryptionAvailable()
      ? safeStorage.encryptString(text)
      : Buffer.from(text, 'utf8')
    fs.mkdirSync(path.dirname(metadataPath()), { recursive: true })
    fs.writeFileSync(metadataPath(), payload, { mode: 0o600 })
  }

  async function status() {
    const metadata = readMetadata()
    const cookies = await campusSession().cookies.get({})
    const hasWebVpnCookie = cookies.some((cookie) => (
      String(cookie.domain || '').replace(/^\./, '').endsWith('sztu.edu.cn')
    ))
    const hasListUrl = isGwtListUrl(metadata.listUrl || '')
    let state = 'disconnected'
    let label = '尚未连接'
    let detail = '校内网络可直接同步；校外请先登录学校 WebVPN。'
    if (hasWebVpnCookie && hasListUrl) {
      state = 'connected'
      label = '会话已保存'
      detail = '已记录公文通的 WebVPN 入口；同步时会自动验证会话。'
    } else if (hasWebVpnCookie) {
      state = 'needs_gwt'
      label = '还差一步'
      detail = '已检测到 WebVPN 会话，请在登录窗口中从服务大厅打开公文通列表。'
    }
    return {
      available: true,
      state,
      label,
      detail,
      connected: state === 'connected',
      has_list_url: hasListUrl,
    }
  }

  function rememberGwtUrl(value) {
    if (!isGwtListUrl(value)) return false
    writeMetadata({ listUrl: value })
    return true
  }

  function openLoginWindow(parentWindow) {
    if (loginWindow && !loginWindow.isDestroyed()) {
      loginWindow.show()
      loginWindow.focus()
      return loginWindow
    }

    loginWindow = new BrowserWindow({
      width: 1080,
      height: 760,
      minWidth: 820,
      minHeight: 620,
      title: '连接深圳技术大学 WebVPN',
      parent: parentWindow || undefined,
      modal: false,
      backgroundColor: '#f7f8f5',
      webPreferences: {
        partition: CAMPUS_PARTITION,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    })
    const activeWindow = loginWindow

    let redirectingFromPortal = false
    let completingLogin = false
    const captureNavigation = (_event, value) => rememberGwtUrl(value)
    activeWindow.webContents.on('did-navigate', captureNavigation)
    activeWindow.webContents.on('did-navigate-in-page', captureNavigation)
    activeWindow.webContents.on('did-frame-navigate', captureNavigation)
    activeWindow.webContents.on('did-finish-load', () => {
      if (activeWindow.isDestroyed()) return
      const currentUrl = activeWindow.webContents.getURL()
      if (rememberGwtUrl(currentUrl)) {
        if (completingLogin) return
        completingLogin = true
        setTimeout(() => {
          if (!activeWindow.isDestroyed()) activeWindow.close()
        }, 250)
        return
      }

      // Some SSO deployments return to the WebVPN portal instead of honoring
      // the original service URL. Continue to the notice list automatically.
      try {
        const current = new URL(currentUrl)
        const home = new URL(WEBVPN_HOME)
        if (!redirectingFromPortal && current.origin === home.origin && current.pathname === home.pathname) {
          redirectingFromPortal = true
          activeWindow.loadURL(GWT_WEBVPN_LIST_URL).catch(() => {})
        }
      } catch {
        // Navigation guards below keep malformed and external URLs blocked.
      }
    })
    activeWindow.webContents.on('will-navigate', (event, value) => {
      if (!isAllowedCampusUrl(value)) event.preventDefault()
    })
    activeWindow.webContents.on('will-redirect', (event, value) => {
      if (!isAllowedCampusUrl(value)) event.preventDefault()
    })
    activeWindow.webContents.setWindowOpenHandler(({ url }) => {
      if (isAllowedCampusUrl(url)) activeWindow.loadURL(url).catch(() => {})
      return { action: 'deny' }
    })
    activeWindow.on('closed', () => {
      if (loginWindow === activeWindow) loginWindow = null
    })

    activeWindow.loadURL(GWT_WEBVPN_LIST_URL).catch(() => {})
    return activeWindow
  }

  async function connect(parentWindow) {
    const window = openLoginWindow(parentWindow)
    return new Promise((resolve) => {
      window.once('closed', async () => resolve(await status()))
    })
  }

  async function disconnect() {
    if (loginWindow && !loginWindow.isDestroyed()) loginWindow.close()
    await campusSession().clearStorageData()
    try {
      fs.unlinkSync(metadataPath())
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
    return status()
  }

  async function sync(request = 20) {
    const options = request && typeof request === 'object' ? request : { limit: request }
    const maximum = clampLimit(options.limit)
    const publishedAfter = normalizePublishedDate(options.publishedAfter)
    const metadata = readMetadata()
    if (!isGwtListUrl(metadata.listUrl || '')) {
      return {
        ok: false,
        error: 'authorization_required',
        message: '请先连接 WebVPN，并在服务大厅中打开一次公文通列表。',
      }
    }

    const worker = new BrowserWindow({
      show: false,
      width: 1000,
      height: 760,
      webPreferences: {
        partition: CAMPUS_PARTITION,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
        images: false,
      },
    })
    worker.webContents.on('will-navigate', (event, value) => {
      if (!isAllowedCampusUrl(value)) event.preventDefault()
    })
    worker.webContents.on('will-redirect', (event, value) => {
      if (!isAllowedCampusUrl(value)) event.preventDefault()
    })
    worker.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))

    try {
      // Always use the current portal-advertised proxy address. Older builds
      // may have persisted a recognizable but unusable no-port URL.
      await loadWindowUrl(worker, GWT_WEBVPN_LIST_URL, 30000)
      const finalListUrl = worker.webContents.getURL()
      rememberGwtUrl(finalListUrl)
      if (!isGwtListUrl(finalListUrl)) {
        return {
          ok: false,
          error: 'authorization_required',
          message: '公文通请求被 WebVPN 重定向回认证页面，请重新连接。',
        }
      }
      const entries = await extractListEntriesSince(worker, maximum, publishedAfter)
      if (!entries.length) {
        return {
          ok: false,
          error: 'list_parse_failed',
          message: '已进入公文通列表，但没有识别到文章；页面结构可能已经变化。',
        }
      }

      const articles = []
      let failed = 0
      for (const entry of entries) {
        const canonicalUrl = canonicalGwtUrl(entry.raw_href, entry.fetch_url)
        const transportUrl = gwtWebVpnArticleUrl(entry.raw_href, entry.fetch_url)
        if (!canonicalUrl || !transportUrl) {
          failed += 1
          continue
        }
        try {
          await loadWindowUrl(worker, transportUrl, 25000)
          const finalArticleUrl = worker.webContents.getURL()
          if (!isGwtTransportUrl(finalArticleUrl)) {
            if (/\/portal\/shortcut\.html|\/controller\/v1\/public\/verify/i.test(finalArticleUrl)) {
              return {
                ok: false,
                error: 'article_transport_failed',
                message: '公文通详情页离开了 WebVPN 通道，请更新应用后重新同步。',
              }
            }
            failed += 1
            continue
          }
          const article = await extractArticle(worker)
          if (article?.authorization_required) {
            return {
              ok: false,
              error: 'authorization_required',
              message: 'WebVPN 登录态已过期，请重新连接后再同步。',
            }
          }
          if (!article?.body_text || article.body_text.length < 20) {
            failed += 1
            continue
          }
          articles.push({
            title: article.title || entry.title,
            canonical_url: canonicalUrl,
            body_text: article.body_text,
            body_html: article.body_html,
            author: entry.department || '深圳技术大学',
            published_at: article.published_at || entry.published_at,
            images: article.images,
            attachments: normalizeGwtAttachments(article.attachments),
          })
        } catch {
          failed += 1
        }
      }

      if (!articles.length) {
        return {
          ok: false,
          error: 'capture_failed',
          message: '已进入公文通列表，但详情页正文未能识别；请稍后重试或反馈页面变化。',
        }
      }
      return { ok: true, articles, failed, discovered: entries.length }
    } catch {
      return {
        ok: false,
        error: 'authorization_required',
        message: '无法通过已保存的 WebVPN 会话访问公文通，请重新连接。',
      }
    } finally {
      if (!worker.isDestroyed()) worker.destroy()
    }
  }

  async function downloadAttachment(rawUrl, suggestedName = '校园附件') {
    const canonicalUrl = canonicalGwtAttachmentUrl(rawUrl, rawUrl)
    const transportUrl = gwtWebVpnResourceUrl(canonicalUrl)
    if (!transportUrl) throw new Error('附件地址不属于公文通')
    const safeName = String(suggestedName || '校园附件')
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
      .replace(/[. ]+$/g, '')
      .slice(0, 180) || '校园附件'
    if (!dialog?.showSaveDialog) throw new Error('当前环境不支持保存附件')
    const destination = await dialog.showSaveDialog({ defaultPath: safeName })
    if (destination.canceled || !destination.filePath) return { canceled: true, path: '' }

    const response = await campusSession().fetch(transportUrl, { redirect: 'follow' })
    if (!response.ok) throw new Error(`附件下载失败（HTTP ${response.status}）`)
    if (response.url && !isGwtTransportUrl(response.url)) {
      throw new Error('WebVPN 登录态已过期，请重新连接后下载')
    }
    const contentType = String(response.headers.get('content-type') || '').toLowerCase()
    if (contentType.includes('text/html')) {
      throw new Error('WebVPN 返回了登录页面，请重新连接后下载')
    }
    const expectedBytes = Number(response.headers.get('content-length') || 0)
    if (expectedBytes > 100 * 1024 * 1024) throw new Error('附件超过 100 MB，请在公文通中下载')
    const payload = Buffer.from(await response.arrayBuffer())
    if (payload.length > 100 * 1024 * 1024) throw new Error('附件超过 100 MB，请在公文通中下载')
    await fs.promises.writeFile(destination.filePath, payload)
    return { canceled: false, path: destination.filePath }
  }

  return { status, connect, disconnect, sync, downloadAttachment }
}

async function loadWindowUrl(window, url, timeoutMs) {
  let timeout
  try {
    await Promise.race([
      window.loadURL(url),
      new Promise((_, reject) => {
        timeout = setTimeout(() => {
          if (!window.isDestroyed()) window.webContents.stop()
          reject(new Error('campus page load timed out'))
        }, timeoutMs)
      }),
    ])
  } finally {
    if (timeout) clearTimeout(timeout)
  }
}

async function extractListEntries(window, limit) {
  return window.webContents.executeJavaScript(`(() => {
    const nodes = Array.from(document.querySelectorAll('ul.news-ul li.clearfix')).slice(0, ${limit});
    return nodes.map((node) => {
      const anchor = node.querySelector('.width04 a[href]') || node.querySelector('a[href]');
      if (!anchor) return null;
      const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
      const date = text.match(/20\\d{2}[-/.年]\\d{1,2}[-/.月]\\d{1,2}日?/);
      return {
        title: (anchor.getAttribute('title') || anchor.textContent || '').replace(/\\s+/g, ' ').trim(),
        raw_href: anchor.getAttribute('href') || '',
        fetch_url: anchor.href || '',
        department: (node.querySelector('.width03 a')?.textContent || '').replace(/\\s+/g, ' ').trim(),
        published_at: date ? date[0].replace(/[年/.]/g, '-').replace(/月/g, '-').replace(/日/g, '') : '',
      };
    }).filter((item) => item && item.title.length >= 4 && item.fetch_url);
  })()`, true)
}

async function extractListEntriesSince(window, limit, publishedAfter = '') {
  const maximum = clampLimit(limit)
  const cutoff = normalizePublishedDate(publishedAfter)
  const entries = []
  const seen = new Set()
  for (let page = 1; page <= MAX_LIST_PAGES && entries.length < maximum; page += 1) {
    if (page > 1) {
      await loadWindowUrl(window, gwtWebVpnListPageUrl(page), 30000)
      if (!isGwtListUrl(window.webContents.getURL())) break
    }
    const pageEntries = await extractListEntries(window, maximum)
    if (!pageEntries.length) break
    const pageDates = []
    let unseen = 0
    for (const rawEntry of pageEntries) {
      const publishedAt = normalizePublishedDate(rawEntry.published_at)
      if (publishedAt) pageDates.push(publishedAt)
      const canonicalUrl = canonicalGwtUrl(rawEntry.raw_href, rawEntry.fetch_url)
      const identity = canonicalUrl || rawEntry.fetch_url
      if (!identity || seen.has(identity)) continue
      seen.add(identity)
      unseen += 1
      if (cutoff && publishedAt && publishedAt < cutoff) continue
      entries.push({ ...rawEntry, published_at: publishedAt })
      if (entries.length >= maximum) break
    }
    if (!unseen) break
    if (cutoff && pageDates.length && pageDates.every((value) => value < cutoff)) break
    if (!cutoff && entries.length >= maximum) break
  }
  return entries.slice(0, maximum)
}

async function extractArticle(window) {
  return window.webContents.executeJavaScript(`(() => {
    if (document.querySelector('input[type="password"]')) return { authorization_required: true };
    const selectors = ['div.v_news_content', '#vsb_content', '#js_content', '.article-content', '.news-content', '.content_detail', '.show_content', 'article', 'main'];
    const source = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
    if (!source) return null;
    const content = source.cloneNode(true);
    content.querySelectorAll('script, style, noscript, iframe, form, input, button, object, embed').forEach((node) => node.remove());
    const originalImages = Array.from(source.querySelectorAll('img'));
    Array.from(content.querySelectorAll('img')).forEach((image, index) => {
      const original = originalImages[index];
      const absolute = original?.src || original?.getAttribute('data-src') || original?.getAttribute('src') || '';
      if (absolute && /^https?:/i.test(absolute)) image.setAttribute('src', absolute);
      else image.remove();
      image.removeAttribute('data-src');
    });
    const originalLinks = Array.from(source.querySelectorAll('a[href]'));
    Array.from(content.querySelectorAll('a[href]')).forEach((anchor, index) => {
      const absolute = originalLinks[index]?.href || '';
      if (absolute && /^https?:/i.test(absolute)) anchor.setAttribute('href', absolute);
      else anchor.removeAttribute('href');
    });
    // MicroFlow intentionally extracts the body from v_news_content but scans
    // the complete page for attachments. VSB templates commonly render their
    // real download anchors in a sibling block below the visible body text.
    const pageLinks = Array.from(document.querySelectorAll('a[href]'));
    const pageText = (document.body?.innerText || '').replace(/\\u00a0/g, ' ');
    const normalizeDate = (value) => {
      const match = String(value || '').match(/(20\\d{2})\\s*[-/.年]\\s*(\\d{1,2})\\s*[-/.月]\\s*(\\d{1,2})\\s*日?(?:\\s*T?\\s*([01]?\\d|2[0-3])\\s*[:：时]\\s*([0-5]?\\d)(?:\\s*[:：分]\\s*([0-5]?\\d)\\s*秒?)?\\s*分?)?/);
      if (!match) return '';
      let result = match[1] + '-' + match[2].padStart(2, '0') + '-' + match[3].padStart(2, '0');
      if (match[4] !== undefined && match[5] !== undefined) {
        result += ' ' + match[4].padStart(2, '0') + ':' + match[5].padStart(2, '0');
        if (match[6] !== undefined) result += ':' + match[6].padStart(2, '0');
      }
      return result;
    };
    const publicationSelectors = [
      'time[datetime]', '.detail_message .message_right', '.page_content_head',
      '.news_conent_two_js', '.parameter > .date', '.ar_title', '.con_title .info',
      '.newsd-left', '.show-time', '.article_box .sub_box', '.v_news_info',
      '.content_t', '.cnt_note', '.article-meta', '.news_info', '.article-time',
      '.detail_message', '.message_right'
    ];
    const publicationCandidates = publicationSelectors.map((selector) => {
      const node = document.querySelector(selector);
      return node?.getAttribute?.('datetime') || node?.textContent || '';
    });
    const publicationMeta = document.querySelector('meta[name="PubDate" i], meta[name="publishdate" i]');
    publicationCandidates.push(publicationMeta?.getAttribute('content') || '', pageText);
    const publishedAt = publicationCandidates.map(normalizeDate).find(Boolean) || '';
    return {
      title: (document.querySelector('h1, .article-title, .content-title, .tit')?.textContent || document.title || '').replace(/\\s+/g, ' ').trim(),
      body_text: (source.innerText || source.textContent || '').split(/\\n+/).map((line) => line.replace(/\\s+/g, ' ').trim()).filter(Boolean).join('\\n'),
      body_html: content.outerHTML,
      published_at: publishedAt,
      images: originalImages.map((image) => image.src || '').filter((value) => /^https?:/i.test(value)),
      attachments: pageLinks.map((anchor) => ({
        name: (anchor.textContent || anchor.getAttribute('title') || anchor.getAttribute('download') || '').replace(/\s+/g, ' ').trim() || '未命名附件',
        raw_href: anchor.getAttribute('href') || '',
        resolved_href: anchor.href || '',
      })).filter((attachment) => /(?:download\.jsp|downloadattachurl|clickdown|\.(?:pdf|docx?|xlsx?|pptx?|zip|rar)(?:$|[?#]))/i.test(attachment.raw_href + ' ' + attachment.resolved_href)).slice(0, 200),
    };
  })()`, true)
}

module.exports = {
  WEBVPN_HOME,
  GWT_DIRECT_BASE,
  GWT_LIST_PATH,
  GWT_WEBVPN_LIST_URL,
  isAllowedCampusUrl,
  isGwtTransportUrl,
  isGwtListUrl,
  canonicalGwtUrl,
  gwtWebVpnArticleUrl,
  canonicalGwtAttachmentUrl,
  gwtWebVpnResourceUrl,
  normalizeGwtAttachments,
  normalizePublishedDate,
  gwtWebVpnListPageUrl,
  clampLimit,
  createCampusWebVpnController,
  extractArticle,
  extractListEntriesSince,
}
