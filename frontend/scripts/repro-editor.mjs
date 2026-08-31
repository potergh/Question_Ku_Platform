// 阶段 1 无头复现脚本：逐步加扩展定位 schema undefined 根因
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body><div id="editor"></div></body></html>',
  { pretendToBeVisual: true, url: 'http://localhost/' })
for (const k of ['window', 'document', 'Node', 'Element', 'HTMLElement', 'Text',
  'DocumentFragment', 'MutationObserver', 'getComputedStyle', 'CustomEvent', 'MouseEvent',
  'KeyboardEvent', 'InputEvent', 'ClipboardEvent', 'DragEvent', 'Range', 'DOMParser']) {
  try { Object.defineProperty(globalThis, k, { value: dom.window[k] ?? dom.window, configurable: true }) } catch (e) {}
}
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })

const { Editor } = await import('@tiptap/core')
const StarterKit = (await import('@tiptap/starter-kit')).default
const Underline = (await import('@tiptap/extension-underline')).default
const Superscript = (await import('@tiptap/extension-superscript')).default
const Subscript = (await import('@tiptap/extension-subscript')).default
const TextAlign = (await import('@tiptap/extension-text-align')).default
const { Node, Extension } = await import('@tiptap/core')

const element = dom.window.document.getElementById('editor')

function tryStep(name, extensions, content) {
  try {
    const editor = new Editor({ element, extensions, content })
    console.log(`[OK] ${name}  schema=${!!editor.schema}`)
    editor.destroy()
    return true
  } catch (e) {
    console.log(`[FAIL] ${name}: ${e.message}`)
    console.log((e.stack || '').split('\n').slice(0, 8).join('\n'))
    return false
  }
}

const content = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '你好' }] }] }

tryStep('仅 StarterKit', [StarterKit], content)
tryStep('StarterKit 关闭部分', [StarterKit.configure({ heading: false, blockquote: false, codeBlock: false, code: false, horizontalRule: false })], content)
tryStep('+ Underline/Sup/Sub/TextAlign',
  [StarterKit.configure({ heading: false, blockquote: false, codeBlock: false, code: false, horizontalRule: false }),
    Underline, Superscript, Subscript, TextAlign.configure({ types: ['paragraph'] })], content)

// 自定义节点（不用 VueNodeView 的纯定义版）
const FormulaInline = Node.create({ name: 'inlineFormula', group: 'inline', inline: true, atom: true,
  addAttributes: () => ({ latex: { default: '' } }),
  renderHTML: () => ['span', { 'data-formula-inline': '' }] })
const FormulaBlock = Node.create({ name: 'displayFormula', group: 'block', atom: true,
  addAttributes: () => ({ latex: { default: '' } }),
  renderHTML: () => ['div', { 'data-formula-display': '' }] })
const BlockImage = Node.create({ name: 'image', group: 'block', atom: true,
  addAttributes: () => ({ src: { default: '' }, align: { default: 'center' }, width: { default: 'fit' } }),
  renderHTML: ({ HTMLAttributes }) => ['img', HTMLAttributes] })
const InlineImage = Node.create({ name: 'inlineImage', group: 'inline', inline: true, atom: true,
  addAttributes: () => ({ src: { default: '' } }),
  renderHTML: () => ['img', {}] })
const AnswerSpace = Node.create({ name: 'answerSpace', group: 'block', atom: true,
  addAttributes: () => ({ rows: { default: 4 } }),
  renderHTML: () => ['div', {}] })
const OptionGroup = Node.create({ name: 'optionGroup', group: 'block', content: 'option+', isolating: true,
  renderHTML: ({ HTMLAttributes }) => ['div', HTMLAttributes, 0] })
const Option = Node.create({ name: 'option', content: 'inline*', defining: true,
  addAttributes: () => ({ label: { default: '?' } }),
  renderHTML: ({ HTMLAttributes }) => ['div', HTMLAttributes, 0] })
const Meta = Extension.create({ name: 'qre', addStorage: () => ({ practiceId: '' }) })

tryStep('+ 全部自定义节点（纯定义）',
  [StarterKit, Underline, Superscript, Subscript, TextAlign.configure({ types: ['paragraph'] }),
    FormulaInline, FormulaBlock, BlockImage, InlineImage, AnswerSpace, OptionGroup, Option, Meta],
  content)

// 带选项组的完整内容
const fullContent = { type: 'doc', content: [
  { type: 'paragraph', content: [{ type: 'text', text: '题干' }] },
  { type: 'optionGroup', content: [
    { type: 'option', attrs: { label: 'A' }, content: [{ type: 'text', text: '甲' }] },
    { type: 'option', attrs: { label: 'B' }, content: [{ type: 'text', text: '乙' }] },
  ] },
  { type: 'answerSpace', attrs: { rows: 2 } },
] }
tryStep('+ 完整文档内容',
  [StarterKit, Underline, Superscript, Subscript, TextAlign.configure({ types: ['paragraph'] }),
    FormulaInline, FormulaBlock, BlockImage, InlineImage, AnswerSpace, OptionGroup, Option, Meta],
  fullContent)

console.log('done')
