// 隔离测试：schema 构建与文档解析分别是否正常
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { pretendToBeVisual: true })
for (const k of ['window', 'document', 'Node', 'Element', 'HTMLElement', 'Text',
  'DocumentFragment', 'MutationObserver', 'getComputedStyle']) {
  try { Object.defineProperty(globalThis, k, { value: dom.window[k] ?? dom.window, configurable: true }) } catch (e) {}
}
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })

const core = await import('@tiptap/core')
const StarterKit = (await import('@tiptap/starter-kit')).default

console.log('exports:', Object.keys(core).filter(k => /schema|Document/i.test(k)))

const schema = core.getSchema([StarterKit])
console.log('schema?', !!schema, 'topNode:', schema?.topNodeType?.name)

const content = [{ type: 'paragraph', content: [{ type: 'text', text: '你好' }] }]
try {
  const doc = core.createDocument(content, schema, undefined, { errorOnInvalidContent: true })
  console.log('doc?', !!doc, 'type?', !!doc?.type, 'schema?', !!doc?.type?.schema)
  console.log('ctor:', doc?.constructor?.name, 'keys:', Object.keys(doc || {}))
  console.log('proto methods:', Object.getOwnPropertyNames(Object.getPrototypeOf(doc || {})).slice(0, 12))
  try { console.log('toJSON:', JSON.stringify(doc?.toJSON?.()).slice(0, 120)) } catch (e) { console.log('toJSON fail:', e.message) }
} catch (e) {
  console.log('createDocument FAIL:', e.message)
}
try {
  const doc2 = core.createDocument(content, schema)
  console.log('doc2?', !!doc2, 'type?', !!doc2?.type, 'schema?', !!doc2?.type?.schema)
} catch (e) {
  console.log('createDocument2 FAIL:', e.message)
}
