/**
 * Shared content renderer — handles LaTeX, images, and basic Markdown.
 * Used by LibraryView (detail preview) and HandoutView (item preview).
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
 * Full content renderer — LaTeX + images + basic Markdown → HTML string.
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
export function renderFullContent(text, options = {}) {
  if (!text) return options.emptyText || ''

  const { showImages = true, maxImages = 20 } = options

  // 1. LaTeX
  let html = processLatex(text)

  // 2. Images
  if (showImages) {
    let imgCount = 0
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
      imgCount++
      if (imgCount > maxImages) return ''
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
  html = html.replace(/\n/g, '<br>')

  return html
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

  // Strip LaTeX — render as plain text for preview
  cleanText = cleanText.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => `[${tex.trim()}]`)
  cleanText = cleanText.replace(/(?<!\\)\$(?!\$)([^\$\n]+?)\$/g, (_, tex) => tex.trim())

  // Strip remaining markdown
  cleanText = cleanText
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '$1')
    .replace(/^#{1,4}\s+/gm, '')

  // Truncate
  if (cleanText.length > maxLen) {
    cleanText = cleanText.slice(0, maxLen) + '...'
  }

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
