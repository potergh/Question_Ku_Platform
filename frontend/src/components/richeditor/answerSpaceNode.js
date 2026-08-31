// 答题留白节点：纯空白占位（渲染端 .space-line 无横线，用户决策 2026-08-30）
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import AnswerSpaceView from './AnswerSpaceView.vue'

export const AnswerSpace = Node.create({
  name: 'answerSpace',
  group: 'block',
  atom: true,
  selectable: true,
  addAttributes() {
    return { rows: { default: 4 } }
  },
  renderHTML({ HTMLAttributes }) {
    return ['div', HTMLAttributes]
  },
  addNodeView() {
    return VueNodeViewRenderer(AnswerSpaceView, {
      // 行数下拉内的事件交给 Vue 组件，不让 ProseMirror 抢焦点导致重渲染
      stopEvent: ({ event }) =>
        !!(event && event.target && event.target.closest && event.target.closest('.qre-space-tools')),
    })
  },
})
