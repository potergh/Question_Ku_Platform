// 公式节点（阶段 3：可点击编辑）
// 用原生 DOM NodeView + KaTeX 渲染，原子节点不可编辑、可选中、可整体删除。
// 行内公式单击、独立公式双击打开编辑弹窗（经 editor.storage.qre.onEditFormula 上抛）。
import { Node, mergeAttributes } from '@tiptap/core'
import katex from 'katex'
// KaTeX 样式必须随节点引入：否则 .katex-mathml 隐藏层不被裁剪，
// 与 katex-html 可视层同时显示，一个公式看起来是两个（练习编辑器不经过题库的 render.js）
import 'katex/dist/katex.min.css'

function renderLatex(latex, displayMode) {
  try {
    return katex.renderToString(latex || '', { throwOnError: false, displayMode })
  } catch (e) {
    return `<span class="formula-error">${latex || ''}</span>`
  }
}

function formulaNodeView(displayMode) {
  return ({ node, editor, getPos }) => {
    const dom = document.createElement(displayMode ? 'div' : 'span')
    dom.className = displayMode ? 'qre-formula-display' : 'qre-formula-inline'
    dom.setAttribute('data-latex', node.attrs.latex || '')
    dom.innerHTML = renderLatex(node.attrs.latex, displayMode)
    const open = () => editor.storage.qre?.onEditFormula?.({
      pos: getPos(), latex: node.attrs.latex || '', display: displayMode,
    })
    const onClick = () => { if (!displayMode) open() }
    const onDblClick = () => { if (displayMode) open() }
    dom.addEventListener('click', onClick)
    dom.addEventListener('dblclick', onDblClick)
    return {
      dom,
      ignoreMutation: () => true,
      update: (updated) => {
        if (updated.type.name !== node.type.name) return false
        node = updated   // 保持 attrs 同步，避免编辑后上抛旧内容
        dom.setAttribute('data-latex', updated.attrs.latex || '')
        dom.innerHTML = renderLatex(updated.attrs.latex, displayMode)
        return true
      },
      destroy: () => {
        dom.removeEventListener('click', onClick)
        dom.removeEventListener('dblclick', onDblClick)
      },
    }
  }
}

export const InlineFormula = Node.create({
  name: 'inlineFormula',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return { latex: { default: '' } }
  },
  parseHTML() {
    return [{ tag: 'span[data-formula-inline]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes({ 'data-formula-inline': '' }, HTMLAttributes)]
  },
  addNodeView() {
    return formulaNodeView(false)
  },
})

export const DisplayFormula = Node.create({
  name: 'displayFormula',
  group: 'block',
  atom: true,
  selectable: true,
  addAttributes() {
    return { latex: { default: '' } }
  },
  parseHTML() {
    return [{ tag: 'div[data-formula-display]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes({ 'data-formula-display': '' }, HTMLAttributes)]
  },
  addNodeView() {
    return formulaNodeView(true)
  },
})
