// 图片节点：块级图（Vue NodeView 带样式控制）+ 行内小图（选项/段落内）
// 均不定义 parseHTML：粘贴进来的外部 <img> 直接丢弃（安全粘贴策略：外部图片忽略）
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import BlockImageView from './BlockImageView.vue'
import { resolveAssetSrc } from './assets'

export const BlockImage = Node.create({
  name: 'image',
  group: 'block',
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      src: { default: '' },
      align: { default: 'center' },
      width: { default: null },   // null/'fit' = 适应；数字 = 百分比；字符串 '50%' 向后兼容
      layout: { default: 'row' }, // 'row' = 与相邻图片并排 | 'block' = 独占一行纵向
    }
  },
  // 序列化/粘贴输出用解析后的真实地址，避免 asset:// 进 DOM 产生请求报错（存储仍用 asset://，见 getJSON 不变）
  renderHTML({ node }) {
    const pid = this.editor?.storage?.qre?.practiceId
    return ['img', { src: resolveAssetSrc(node.attrs.src, pid) }]
  },
  addNodeView() {
    return VueNodeViewRenderer(BlockImageView, {
      // 工具条（对齐/宽度下拉、删除）和缩放手柄内的事件交给 Vue 组件，不让 ProseMirror 抢焦点导致重渲染
      stopEvent: ({ event }) =>
        !!(event && event.target && event.target.closest &&
           (event.target.closest('.qre-img-tools') || event.target.closest('.qre-img-handle'))),
    })
  },
})

export const InlineImage = Node.create({
  name: 'inlineImage',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return { src: { default: '' } }
  },
  renderHTML({ node }) {
    const pid = this.editor?.storage?.qre?.practiceId
    return ['img', { src: resolveAssetSrc(node.attrs.src, pid), class: 'qre-inline-img' }]
  },
})
