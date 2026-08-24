import fs from 'node:fs'
import path from 'node:path'
import readline from 'node:readline'
import { fileURLToPath, pathToFileURL } from 'node:url'


const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const playwrightModuleUrl = pathToFileURL(
  path.join(__dirname, '..', 'frontend', 'node_modules', 'playwright', 'index.mjs'),
).href
const { chromium } = await import(playwrightModuleUrl)

const BASE_URL = process.env.EVENT_RADAR_TRUTH_SOCIAL_BASE_URL || 'https://truthsocial.com'
const COOKIE_FILE = process.env.EVENT_RADAR_TRUTH_SOCIAL_COOKIE_FILE || ''
const COOKIE_HEADER = process.env.EVENT_RADAR_TRUTH_SOCIAL_COOKIE || ''
const USER_AGENT =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
const BOOTSTRAP_TIMEOUT_MS = 45_000

let browser = null
let context = null
let page = null
let isBootstrapped = false

function respond(payload) {
  process.stdout.write(JSON.stringify(payload) + '\n')
}

function log(message, error) {
  if (error) {
    console.error(`${message}: ${error.stack || error.message || String(error)}`)
    return
  }
  console.error(message)
}

function normalizeHandle(handle) {
  return String(handle || '').trim().replace(/^@+/, '').toLowerCase()
}

function parseCookieHeader(headerValue) {
  if (!headerValue) {
    return []
  }
  const cookies = []
  for (const segment of String(headerValue).split(';')) {
    const trimmed = segment.trim()
    if (!trimmed) {
      continue
    }
    const separatorIndex = trimmed.indexOf('=')
    if (separatorIndex <= 0) {
      continue
    }
    const name = trimmed.slice(0, separatorIndex).trim()
    const value = trimmed.slice(separatorIndex + 1).trim()
    cookies.push({
      name,
      value,
      url: BASE_URL,
      path: '/',
      secure: BASE_URL.startsWith('https://'),
      sameSite: 'Lax',
    })
  }
  return cookies
}

function normalizeCookieObject(name, value) {
  return {
    name: String(name),
    value: String(value),
    url: BASE_URL,
    path: '/',
    secure: BASE_URL.startsWith('https://'),
    sameSite: 'Lax',
  }
}

function normalizeCookieEntry(entry) {
  if (!entry || typeof entry !== 'object' || !entry.name || entry.value === undefined) {
    return null
  }
  const normalized = {
    name: String(entry.name),
    value: String(entry.value),
    path: String(entry.path || '/'),
    secure: typeof entry.secure === 'boolean' ? entry.secure : BASE_URL.startsWith('https://'),
    httpOnly: Boolean(entry.httpOnly),
  }
  const sameSite = String(entry.sameSite || 'Lax')
  if (['Lax', 'Strict', 'None'].includes(sameSite)) {
    normalized.sameSite = sameSite
  } else {
    normalized.sameSite = 'Lax'
  }
  if (entry.domain) {
    normalized.domain = String(entry.domain).replace(/^#HttpOnly_/, '')
  } else if (entry.url) {
    normalized.url = String(entry.url)
  } else {
    normalized.url = BASE_URL
  }
  const expires = Number(entry.expires)
  if (Number.isFinite(expires) && expires > 0) {
    normalized.expires = expires
  }
  return normalized
}

function parseCookieJar(text) {
  const cookies = []
  for (const rawLine of String(text).split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#') || !rawLine.includes('\t')) {
      continue
    }
    const parts = rawLine.split('\t')
    if (parts.length < 7) {
      continue
    }
    const [domain, _includeSubdomains, cookiePath, secureFlag, expiresRaw, name, value] = parts
    const cookie = {
      name,
      value,
      domain: domain.replace(/^#HttpOnly_/, ''),
      path: cookiePath || '/',
      secure: String(secureFlag).toUpperCase() === 'TRUE',
      httpOnly: String(domain).startsWith('#HttpOnly_'),
      sameSite: 'Lax',
    }
    const expires = Number(expiresRaw)
    if (Number.isFinite(expires) && expires > 0) {
      cookie.expires = expires
    }
    cookies.push(cookie)
  }
  return cookies
}

function readCookiesFromFile(filePath) {
  if (!filePath) {
    return []
  }
  const raw = fs.readFileSync(filePath, 'utf8')
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      return parsed.map((entry) => normalizeCookieEntry(entry)).filter(Boolean)
    }
    if (parsed && typeof parsed === 'object') {
      return Object.entries(parsed).map(([name, value]) => normalizeCookieObject(name, value))
    }
  } catch {
    // Fall through to Netscape cookie jar parsing.
  }
  return parseCookieJar(raw)
}

function collectCookies() {
  const cookies = [
    ...readCookiesFromFile(COOKIE_FILE),
    ...parseCookieHeader(COOKIE_HEADER),
  ]
  const deduped = new Map()
  for (const cookie of cookies) {
    const normalized = normalizeCookieEntry(cookie)
    if (!normalized) {
      continue
    }
    const scope = normalized.domain || normalized.url || BASE_URL
    const key = `${normalized.name}|${scope}|${normalized.path}`
    deduped.set(key, normalized)
  }
  return [...deduped.values()]
}

async function requestJson(relativePath, allowRetry = true) {
  await ensureBootstrapped(false)
  const result = await page.evaluate(async ({ relativePath }) => {
    const response = await fetch(relativePath, {
      credentials: 'include',
      headers: {
        Accept: 'application/json, text/plain, */*',
      },
    })
    const text = await response.text()
    return {
      status: response.status,
      text,
      retryAfter: response.headers.get('retry-after'),
    }
  }, { relativePath })
  if (result.status === 403 && allowRetry) {
    await ensureBootstrapped(true)
    return requestJson(relativePath, false)
  }
  let json = null
  try {
    json = result.text ? JSON.parse(result.text) : null
  } catch {
    json = null
  }
  return {
    status: result.status,
    text: result.text,
    json,
    retryAfter: result.retryAfter,
  }
}

async function ensureBootstrapped(forceRefresh) {
  if (!forceRefresh && isBootstrapped) {
    return
  }
  await page.goto(BASE_URL, {
    waitUntil: 'domcontentloaded',
    timeout: BOOTSTRAP_TIMEOUT_MS,
  })
  await page.waitForTimeout(350)
  isBootstrapped = true
}

async function fetchStatuses(request) {
  const handle = normalizeHandle(request.handle)
  if (!handle) {
    throw new Error('truth_social_handle_missing')
  }
  let account = null
  let sourceAccountId = request.sourceAccountId ? String(request.sourceAccountId) : null
  if (!sourceAccountId) {
    const lookup = await requestJson(`/api/v1/accounts/lookup?acct=${encodeURIComponent(handle)}`)
    if (lookup.status === 429) {
      const error = new Error('truth_social_rate_limited')
      error.retryAfter = lookup.retryAfter || null
      throw error
    }
    if (lookup.status === 403) {
      throw new Error('truth_social_lookup_forbidden')
    }
    if (lookup.status >= 400 || !lookup.json || !lookup.json.id) {
      throw new Error(`truth_social_lookup_failed:${lookup.status}`)
    }
    account = lookup.json
    sourceAccountId = String(lookup.json.id)
  }
  const params = new URLSearchParams({
    limit: String(request.limit || 5),
    exclude_replies: request.excludeReplies ? 'true' : 'false',
    only_replies: 'false',
    with_muted: 'true',
  })
  const statuses = await requestJson(
    `/api/v1/accounts/${encodeURIComponent(sourceAccountId)}/statuses?${params.toString()}`,
  )
  if (statuses.status === 403) {
    throw new Error('truth_social_auth_forbidden')
  }
  if (statuses.status === 429) {
    const error = new Error('truth_social_rate_limited')
    error.retryAfter = statuses.retryAfter || null
    throw error
  }
  if (statuses.status >= 400 || !Array.isArray(statuses.json)) {
    throw new Error(`truth_social_statuses_failed:${statuses.status}`)
  }
  return {
    account: {
      id: sourceAccountId,
      url: account?.url || null,
    },
    statuses: statuses.json,
  }
}

async function startWorker() {
  browser = await chromium.launch({ headless: true })
  context = await browser.newContext({
    userAgent: USER_AGENT,
    viewport: { width: 1280, height: 800 },
  })
  const cookies = collectCookies()
  if (cookies.length > 0) {
    await context.addCookies(cookies)
  }
  page = await context.newPage()
  await page.route('**/*', async (route) => {
    const request = route.request()
    const resourceType = request.resourceType()
    const url = request.url()
    if (
      resourceType === 'image' ||
      resourceType === 'media' ||
      resourceType === 'font' ||
      resourceType === 'stylesheet' ||
      resourceType === 'script'
    ) {
      await route.abort()
      return
    }
    if (url.includes('/api/v5/truth/ads') || url.includes('/api/v1/truth/ads/')) {
      await route.abort()
      return
    }
    await route.continue()
  })
  respond({ type: 'ready' })
}

async function shutdownWorker() {
  try {
    await page?.close()
  } catch {
    // Ignore close failures during shutdown.
  }
  try {
    await context?.close()
  } catch {
    // Ignore close failures during shutdown.
  }
  try {
    await browser?.close()
  } catch {
    // Ignore close failures during shutdown.
  }
}

try {
  await startWorker()
} catch (error) {
  log('Failed to start Truth Social browser worker', error)
  respond({
    type: 'error',
    error: `truth_social_browser_worker_failed:${error.message || String(error)}`,
  })
  process.exit(1)
}

const input = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
})

for await (const rawLine of input) {
  const line = rawLine.trim()
  if (!line) {
    continue
  }
  let request
  try {
    request = JSON.parse(line)
  } catch (error) {
    log('Invalid worker request', error)
    respond({ ok: false, error: 'truth_social_browser_invalid_request' })
    continue
  }
  if (request.type === 'shutdown') {
    break
  }
  if (request.type !== 'fetch_statuses') {
    respond({ ok: false, error: 'truth_social_browser_unknown_request' })
    continue
  }
  try {
    const result = await fetchStatuses(request)
    respond({ ok: true, result })
  } catch (error) {
    log('Truth Social browser request failed', error)
    respond({
      ok: false,
      error: error.message || String(error),
      retryAfter: error.retryAfter || null,
    })
  }
}

await shutdownWorker()
