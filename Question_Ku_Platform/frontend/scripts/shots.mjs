/*
 * 页面截图自查脚本（仅开发期使用，不进产物）。
 *
 * 存在的理由：UI 改完只能靠人眼验收，而"好不好看/暗色下面板有没有露白"
 * 这类问题必须有像素级的反馈回路，否则每次都要用户替我当眼睛。
 *
 * 用法：
 *   node scripts/shots.mjs            # 浅色（默认），1440×900
 *   node scripts/shots.mjs dark       # 暗色
 *   $env:W=1280; $env:H=800; node scripts/shots.mjs
 * 输出：frontend/_shots/<theme>/*.png
 * 前置：后端已在 8002 提供页面（脚本直接从它取动态 id 并截图）。
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const BASE = process.env.BASE || 'http://127.0.0.1:8002'
const THEME = process.argv[2] === 'dark' ? 'dark' : 'light'
const W = Number(process.env.W || 1440)
const H = Number(process.env.H || 900)
const OUT = path.resolve('_shots', THEME)
mkdirSync(OUT, { recursive: true })

// 动态路由（练习编辑器 / 暂存复核）要真实 id，从接口现取，不写死
const pick = async (url, getter) => {
  try {
    return getter(await (await fetch(url)).json())
  } catch {
    return undefined
  }
}
const practiceId = await pick(`${BASE}/api/practices`, (d) => d.practices?.[0]?.id)
const sourceId = await pick(`${BASE}/api/sources`, (d) => d.sources?.[0]?.id)

const routes = [
  ['dashboard', '/dashboard'],
  ['upload', '/upload'],
  ['library', '/library'],
  ['basket', '/basket'],
  ['practices', '/practices'],
  ['papers', '/papers'],
  ['tags', '/tags'],
  ['settings', '/settings'],
]
if (practiceId) routes.push(['practice-editor', `/practice/editor?id=${practiceId}`])
if (sourceId) routes.push(['extract-review', `/extract/${sourceId}`])

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: W, height: H } })

// 主题在 main.js 挂载前从 localStorage 读取，所以必须在导航前写入
await page.addInitScript((theme) => {
  if (theme === 'dark') localStorage.setItem('theme', 'dark')
  else localStorage.removeItem('theme')
}, THEME)

// 顺手抓控制台错误：截图只能看"好不好看"，报错得靠这个
const problems = []
page.on('console', (m) => {
  if (m.type() === 'error') problems.push(`[console] ${m.text()}`)
})
page.on('pageerror', (e) => problems.push(`[pageerror] ${e.message}`))

for (const [name, route] of routes) {
  await page.goto(BASE + route, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800) // 等入场动画结束，否则会截到半透明中间帧
  await page.screenshot({ path: path.join(OUT, `${name}.png`) })
  console.log('captured', name)
}

await browser.close()

if (problems.length) {
  console.log('\n控制台错误：')
  for (const p of [...new Set(problems)]) console.log(' -', p)
} else {
  console.log('\n无控制台错误')
}
