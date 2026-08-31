// 选项组/选项节点：视觉连续画布内的语义节点
// 行为约定（阶段 1 决策）：
//   Enter      → 当前选项内换行（hardBreak），不把选项拆成两个
//   Ctrl+Enter → 在当前选项后创建下一个选项
//   标签 A、B、C… 由系统自动编号，任何增删移动后统一重排
import { Node } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import OptionView from './OptionView.vue'

const LABELS = 'ABCDEFGHIJKLMN'

// 选区所在的 option 节点（位置 + 节点），不在选项内返回 null
export function findOptionAt(state) {
  const { $from } = state.selection
  for (let d = $from.depth; d > 0; d--) {
    if ($from.node(d).type.name === 'option') {
      return { depth: d, start: $from.before(d), node: $from.node(d) }
    }
  }
  return null
}

// 按文档顺序统一重排所有选项标签（位置仅属性变化，不需要映射）
function renumberLabels(tr) {
  const items = []
  tr.doc.descendants((node, pos) => {
    if (node.type.name === 'option') items.push([pos, node])
    return node.type.name === 'optionGroup'
  })
  items.forEach(([pos, node], i) => {
    const label = LABELS[i] || '?'
    if (node.attrs.label !== label) {
      tr.setNodeMarkup(pos, null, { ...node.attrs, label })
    }
  })
}

// 找到唯一的选项组（位置 + 节点）；没有返回 null
function findGroup(doc) {
  let found = null
  doc.descendants((node, pos) => {
    if (node.type.name === 'optionGroup') { found = { pos, node }; return false }
    return true
  })
  return found
}

function selectInside(tr, pos) {
  tr.setSelection(TextSelection.create(tr.doc, pos))
}

export const OptionGroup = Node.create({
  name: 'optionGroup',
  group: 'block',
  content: 'option+',
  isolating: true,   // 光标/编辑不越界，防止误删整组结构
  renderHTML({ HTMLAttributes }) {
    return ['div', HTMLAttributes, 0]
  },
})

export const Option = Node.create({
  name: 'option',
  content: 'inline*',
  defining: true,
  addAttributes() {
    return { label: { default: '?' } }
  },
  // 即使有 NodeView 也必须有 toDOM（ProseMirror 建 DOM 时要求）
  renderHTML({ HTMLAttributes }) {
    return ['div', HTMLAttributes, 0]
  },
  addNodeView() {
    return VueNodeViewRenderer(OptionView)
  },
  addCommands() {
    return {
      addOption: () => ({ state, tr, dispatch }) => {
        const optType = state.schema.nodes.option
        const grpType = state.schema.nodes.optionGroup
        const group = findGroup(tr.doc)
        if (!group) {
          const opt = optType.create({ label: 'A' })
          tr.insert(tr.doc.content.size, grpType.create(null, [opt]))
          renumberLabels(tr)
          if (dispatch) selectInside(tr, tr.doc.content.size - 1)
        } else {
          const kids = []
          group.node.forEach(c => kids.push(c))
          kids.push(optType.create({ label: '?' }))
          tr.replaceWith(group.pos + 1, group.pos + group.node.nodeSize - 1, kids)
          renumberLabels(tr)
          if (dispatch) {
            const g = findGroup(tr.doc)
            selectInside(tr, g.pos + g.node.nodeSize - 2)  // 最后一个选项的正文内
          }
        }
        if (dispatch) dispatch(tr)
        return true
      },
      removeOption: () => ({ state, tr, dispatch }) => {
        const found = findOptionAt(state)
        if (!found) return false
        tr.delete(found.start, found.start + found.node.nodeSize)
        renumberLabels(tr)
        if (dispatch) dispatch(tr)   // 选区由 ProseMirror 自动映射到删除后的位置
        return true
      },
      moveOption: (delta) => ({ state, tr, dispatch }) => {
        const found = findOptionAt(state)
        if (!found) return false
        const $pos = tr.doc.resolve(found.start)
        const groupDepth = found.depth - 1
        const parent = $pos.node(groupDepth)
        const idx = $pos.index(groupDepth)
        const swap = idx + delta
        if (swap < 0 || swap >= parent.childCount) return false
        const kids = []
        parent.forEach(c => kids.push(c))
        ;[kids[idx], kids[swap]] = [kids[swap], kids[idx]]
        const groupStart = $pos.before(groupDepth)
        tr.replaceWith(groupStart + 1, groupStart + parent.nodeSize - 1, kids)
        renumberLabels(tr)
        if (dispatch) dispatch(tr)
        return true
      },
      splitOptionNext: () => ({ state, tr, dispatch }) => {
        // Ctrl+Enter：当前选项后新建下一个选项
        const found = findOptionAt(state)
        if (!found) return false
        const optType = state.schema.nodes.option
        const insertPos = found.start + found.node.nodeSize
        tr.insert(insertPos, optType.create({ label: '?' }))
        renumberLabels(tr)
        if (dispatch) {
          selectInside(tr, insertPos + 1)
          dispatch(tr)
        }
        return true
      },
    }
  },
  addKeyboardShortcuts() {
    return {
      Enter: ({ editor }) => {
        if (!findOptionAt(editor.state)) return false
        return editor.chain().focus().insertContent({ type: 'hardBreak' }).run()
      },
      'Mod-Enter': ({ editor }) => {
        if (!findOptionAt(editor.state)) return false
        return editor.commands.splitOptionNext()
      },
    }
  },
})
