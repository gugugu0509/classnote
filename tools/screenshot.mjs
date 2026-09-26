// 用 Edge 无头模式 + CDP 给 PWA 截图（三个标签页各一张）。
// 用法: node shot.mjs <baseUrl> <outDir>
import { spawn } from 'node:child_process'
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8000/app/'
const OUT = process.argv[3] || '.'
const PORT = 9333
const profile = mkdtempSync(join(tmpdir(), 'edge-shot-'))

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
  '--disable-extensions', '--mute-audio',
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`,
  'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function wsUrl() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
      const page = list.find((t) => t.type === 'page')
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl
    } catch {}
    await sleep(250)
  }
  throw new Error('CDP 未就绪')
}

class Cdp {
  constructor(ws) {
    this.ws = ws
    this.id = 0
    this.pending = new Map()
    this.events = new Map()
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
      } else if (msg.method) {
        const waiters = this.events.get(msg.method) || []
        this.events.set(msg.method, [])
        waiters.forEach((w) => w(msg.params))
      }
    })
  }
  send(method, params = {}) {
    const id = ++this.id
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }))
  }
  once(method, timeout = 15000) {
    return new Promise((resolve, reject) => {
      const list = this.events.get(method) || []
      list.push(resolve)
      this.events.set(method, list)
      setTimeout(() => reject(new Error(method + ' 超时')), timeout)
    })
  }
}

const shots = [
  { tab: 'record', file: 'pwa-1-record.png' },
  { tab: 'photo', file: 'pwa-2-photo.png' },
  { tab: 'mindmap', file: 'pwa-3-mindmap.png' },
]

try {
  const ws = new WebSocket(await wsUrl())
  await new Promise((r) => ws.addEventListener('open', r, { once: true }))
  const cdp = new Cdp(ws)

  await cdp.send('Page.enable')
  await cdp.send('Runtime.enable')
  // 手机尺寸 ×2 缩放，截出来更清晰
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 430, height: 932, deviceScaleFactor: 2, mobile: true,
  })

  const loaded = cdp.once('Page.loadEventFired').catch(() => {})
  await cdp.send('Page.navigate', { url: BASE })
  await loaded
  await sleep(1200)

  for (const s of shots) {
    await cdp.send('Runtime.evaluate', { expression: `switchTab('${s.tab}')` })
    await sleep(900)
    const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' })
    const path = join(OUT, s.file)
    writeFileSync(path, Buffer.from(data, 'base64'))
    console.log(`✓ ${s.file}  (tab=${s.tab})`)
  }
} finally {
  edge.kill()
  await sleep(400)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}
