/**
 * Shared content renderer — handles LaTeX, images, Markdown tables, and basic Markdown.
 * Used by LibraryView (detail preview) and ExtractReviewView (staging review).
 */
import katex from 'katex'
import 'katex/dist/katex.min.css'

/**
 * Render LaTeX expression to HTML string.
 * Returns raw text wrapped in error span if parsing fails.
 */
function renderLatex(tex, displayMode = false) {
  try {
    return katex.renderToString(tex, {
      throwOnError: false,
      displayMode,
      output: 'html',
    })
  } catch {
    return `<span class="latex-error">${tex}</span>`
  }
}

/**
 * Process LaTeX in text: replace $...$ and $$...$$ with rendered KaTeX HTML.
 * Must be called BEFORE markdown image/bold/italic processing
 * so that LaTeX content is not mangled by other regexes.
 */
function processLatex(text) {
  if (!text) return text

  // Block math: $$...$$ (must come before inline $)
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => {
    return renderLatex(tex.trim(), true)
  })

  // Block math: \[...\]
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => {
    return renderLatex(tex.trim(), true)
  })

  // Inline math: $...$  (but not \$ escaped)
  text = text.replace(/(?<!\\)\$(?!\$)([^\$\n]+?)\$/g, (_, tex) => {
    return renderLatex(tex.trim(), false)
  })

  // Inline math: \(...\)
  text = text.replace(/\\\(([\s\S]+?)\\\)/g, (_, tex) => {
    return renderLatex(tex.trim(), false)
  })

  return text
}

/**
 * Inline pipeline：LaTeX + 图片 + 基础 Markdown → HTML 片段（不含表格）。
 *
 * Processing order:
 * 1. LaTeX ($...$ and $$...$$) → KaTeX HTML
 * 2. Images ![alt](url) → <img>
 * 3. Bold **text** → <b>
 * 4. Italic *text* → <i>
 * 5. Headers ### → <h4>, ## → <h3>
 * 6. Lists - item → <li>
 * 7. Newlines → <br>
 */
function renderInline(text, ctx) {
  // 1. LaTeX
  let html = processLatex(text)

  // 2. Images
  if (ctx.showImages) {
    let imgCount = 0
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
      imgCount++
      if (imgCount > ctx.maxImages) return ''
      return `<img src="${url}" alt="${alt}" style="max-width:min(100%, 400px);max-height:300px;height:auto;margin:4px 0;border-radius:4px;" loading="lazy" />`
    })
  } else {
    // Strip images entirely
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '')
  }

  // 3-6. Basic Markdown
  html = html
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<i>$1</i>')
    .replace(/^#### (.+)$/gm, '<h5>$1</h5>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')

  // 7. Newlines (but not inside block elements)
  return html.replace(/\n/g, '<br>')
}

// ── Markdown 表格 ────────────────────────────────────────────────────
// 表格必须在 LaTeX 之前解析：单元格分隔符就是 ASCII `|`，而 KaTeX 渲染绝对值
// （$|x|$ / \left|...\right|）的产物里也带 ASCII `|`，先渲染公式会把单元格切错。
//
// 换行按行扫描，遇到「表头行 + |---| 分隔行」就整段交给 renderTable，
// 表格之外的文本仍走原来的 renderInline。

const UNESCAPED_PIPE = /(?<!\\)\|/

// 数学公式整体（块级/行内）。公式内部的 `|` 不可能是单元格边界。
const MATH_SPAN = /\$\$[\s\S]*?\$\$|\$[^$\n]*?\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)/g
// 掩码用的占位符：正文里不会出现的控制字符。
const MATH_PIPE = '\u0001'

const TABLE_WRAP_STYLE = 'overflow-x:auto;margin:6px 0;max-width:100%;'
const TABLE_STYLE = 'border-collapse:collapse;font-size:0.95em;'
const CELL_STYLE =
  'border:1px solid var(--color-line);padding:4px 10px;text-align:left;' +
  'vertical-align:top;line-height:1.5;'
const HEAD_CELL_STYLE =
  CELL_STYLE + 'background:var(--color-sunken);font-weight:600;white-space:nowrap;'

/** 按未转义的 `|` 切单元格，去掉首尾装饰性的竖线。
 *
 * 切之前先把**公式内部的** `|` 换成占位符：模型写 `$|x|$` 时不会按 GFM 要求
 * 转义成 `\|`，而 GFM 里未转义的 `|` 就是分隔符 —— 直接切会把一个单元格拆成
 * 三个，凭空多出两列，整张表从此错位。公式里不可能有单元格边界，先保护起来。
 */
function splitRow(line) {
  let text = String(line).trim()
  if (text.startsWith('|')) text = text.slice(1)
  if (text.endsWith('|')) text = text.slice(0, -1)
  text = text.replace(MATH_SPAN, (span) => span.replace(/\|/g, MATH_PIPE))
  return text
    .split(UNESCAPED_PIPE)
    .map((cell) => cell.split(MATH_PIPE).join('|').replace(/\\\|/g, '|').trim())
}

/** `| --- | :--: |` 这类分隔行：每个单元格只由 - 和 : 组成。 */
function isSeparatorRow(line) {
  const text = String(line || '').trim()
  if (!text.includes('|')) return false
  const cells = splitRow(text)
  return cells.length > 1 && cells.every((cell) => /^:?-+:?$/.test(cell))
}

/** 从表头行起收集连续的表行，直到**空行**才结束。
 *
 * 为什么不按"整行含 `|`"结束：单元格内容里可以有换行（模型常这么写，实测第 24 题
 * 的「实验步骤」格就是三行），按前者会从中间截断 —— 那一题 7 行的表实测只渲染出 4
 * 行，剩下半边带着 `|` 漏进正文，界面上就是"一半表格 + 一串乱码"。
 *
 * 判据是**上一行结没结束**：GFM 的行尾是 `|`，行尾缺 `|` 说明单元格没闭合、下一行
 * 是它的延续（接回上一行末尾；renderInline 会把 \n 渲染成 <br>，单元格里就是两行）。
 * 上一行已闭合时，下一行必须自带 `|` 才算新行 —— 否则表格到此为止，免得把紧跟其后
 * 的正文一并吞进表格。
 */
function collectTable(lines, start) {
  const rows = [lines[start]]
  let index = start + 1
  while (index < lines.length) {
    const text = lines[index].trim()
    if (!text) break
    const last = String(rows[rows.length - 1]).trimEnd()
    if (last.endsWith('|')) {
      if (!text.includes('|')) break
      rows.push(lines[index])
    } else {
      rows[rows.length - 1] = `${last}\n${text}`
    }
    index++
  }
  return { rows, next: index }
}

function renderTable(rows, ctx) {
  const parsed = rows.map(splitRow)
  // 列数取所有行的最大值，而不是表头声明的数量。
  // 实测模型给的表头常比数据行少声明一列（`| ****牌电烤箱** | |` 声明 2 列，
  // 数据行却有 3 列），按 GFM 严格解析会把 1100W / 440W 整列丢掉 ——
  // 漏数据的代价高于与规范不一致。
  const width = parsed.reduce((max, row) => Math.max(max, row.length), 0)
  if (width < 2) return ''

  const pad = (row) => row.concat(new Array(Math.max(0, width - row.length)).fill(''))
  const head = pad(parsed[0])
    .map((cell) => `<th style="${HEAD_CELL_STYLE}">${renderInline(cell, ctx)}</th>`)
    .join('')
  // parsed[1] 是分隔行，不渲染
  const body = parsed
    .slice(2)
    .map(
      (row) =>
        `<tr>${pad(row)
          .map((cell) => `<td style="${CELL_STYLE}">${renderInline(cell, ctx)}</td>`)
          .join('')}</tr>`,
    )
    .join('')

  return (
    `<div style="${TABLE_WRAP_STYLE}"><table style="${TABLE_STYLE}">` +
    `<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
  )
}

/**
 * Full content renderer — LaTeX + 表格 + images + basic Markdown → HTML string.
 *
 * 表格识别是外层循环（先于 renderInline），其余全文交给 renderInline。
 */
export function renderFullContent(text, options = {}) {
  if (!text) return options.emptyText || ''

  const ctx = {
    showImages: options.showImages !== false,
    maxImages: options.maxImages ?? 20,
  }

  const lines = String(text).split('\n')
  const out = []
  let buffer = []
  const flush = () => {
    if (buffer.length) {
      out.push(renderInline(buffer.join('\n'), ctx))
      buffer = []
    }
  }

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes('|') && isSeparatorRow(lines[i + 1])) {
      const table = collectTable(lines, i)
      const html = renderTable(table.rows, ctx)
      if (html) {
        flush()
        out.push(html)
        i = table.next - 1
        continue
      }
    }
    buffer.push(lines[i])
  }
  flush()

  return out.join('')
}

/**
 * Render a preview with text truncated + images shown as thumbnails.
 * Used for card previews in LibraryView.
 */
export function renderPreview(text, maxLen = 150) {
  if (!text) return ''

  // Extract images first
  const images = []
  let cleanText = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
    images.push(`<img src="${url}" alt="${alt}" style="max-width:100px;max-height:70px;margin:2px;border-radius:3px;vertical-align:middle;" loading="lazy" />`)
    return ''
  })

  // Strip remaining markdown
  cleanText = cleanText
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)/g, '$1')
    .replace(/^#{1,4}\s+/gm, '')

  // Truncate - must run BEFORE KaTeX: slicing HTML breaks tags
  if (cleanText.length > maxLen) {
    cleanText = cleanText.slice(0, maxLen) + '...'
  }

  // LaTeX: render with KaTeX, same as full view. Previously stripped to
  // plain text, so cards showed raw \mathrm{mg} tokens.
  cleanText = cleanText
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => renderLatex(tex.trim(), true))
    .replace(/(?<!\\)\$(?!\$)([^\$\n]+?)\$/g, (_, tex) => renderLatex(tex.trim(), false))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, tex) => renderLatex(tex.trim(), false))
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => renderLatex(tex.trim(), true))

  // Combine
  return cleanText + (images.length ? '<div style="margin-top:4px;">' + images.join('') + '</div>' : '')
}

/**
 * Render option content — LaTeX + inline images.
 * Used for displaying options in card preview and detail drawer.
 */
export function renderOptionContent(text) {
  if (!text) return ''

  // 1. LaTeX (same as processLatex in renderFullContent)
  let html = text

  // Block math: $$...$$
  html = html.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => {
    return renderLatex(tex.trim(), true)
  })
  // Block math: \[...\]
  html = html.replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => {
    return renderLatex(tex.trim(), true)
  })
  // Inline math: $...$
  html = html.replace(/(?<!\\)\$(?!\$)([^\$\n]+?)\$/g, (_, tex) => {
    return renderLatex(tex.trim(), false)
  })
  // Inline math: \(...\)
  html = html.replace(/\\\(([\s\S]+?)\\\)/g, (_, tex) => {
    return renderLatex(tex.trim(), false)
  })

  // 2. Images as small inline thumbnails
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
    return `<img src="${url}" alt="${alt}" style="max-height:40px;vertical-align:middle;margin:0 4px;border-radius:3px;" loading="lazy" />`
  })

  return html
}
