// 阶段 2 排版扩展：textStyle 标记（字体/字号/颜色）+ 段落排版属性（行距/间距/缩进）。
// 序列化出的 marks / attrs 与后端 rich_document 白名单一一对应（validate_doc）。
import { Mark } from '@tiptap/core'
import Paragraph from '@tiptap/extension-paragraph'
import { cssFontFamily } from './typography'

// CSS 字体名 → 白名单显示名（粘贴解析用）
const FAMILY_TO_NAME = {
  SimSun: '宋体', SimHei: '黑体', KaiTi: '楷体', FangSong: '仿宋',
  'Microsoft YaHei': '微软雅黑', Arial: 'Arial', 'Times New Roman': 'Times New Roman',
}

export const TextStyleExt = Mark.create({
  name: 'textStyle',

  addAttributes() {
    return {
      fontFamily: {
        default: null,
        parseHTML: (el) => {
          const first = (el.style?.fontFamily || '').split(',')[0].replace(/["']/g, '').trim()
          return FAMILY_TO_NAME[first] || null
        },
        renderHTML: (attrs) => (attrs.fontFamily
          ? { style: `font-family: ${cssFontFamily(attrs.fontFamily)}` } : {}),
      },
      fontSize: {
        default: null,
        parseHTML: (el) => parseFloat(el.style?.fontSize) || null,
        renderHTML: (attrs) => (attrs.fontSize ? { style: `font-size: ${attrs.fontSize}pt` } : {}),
      },
      color: {
        default: null,
        parseHTML: (el) => el.style?.color || null,
        renderHTML: (attrs) => (attrs.color ? { style: `color: ${attrs.color}` } : {}),
      },
    }
  },

  parseHTML() {
    return [{
      tag: 'span',
      getAttrs: (el) => (el.hasAttribute('style') && el.getAttribute('style')?.trim() ? null : false),
    }]
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', HTMLAttributes, 0]
  },

  addCommands() {
    return {
      // 设置单个样式属性（传 null/空 = 清除该属性）。
      // 注：updateAttributes 只更新已有 mark 的文本；改用 getAttributes + setMark，
      // 对纯文本也能新建 textStyle 标记，并保留已有其他属性。
      setTextStyleAttr: (key, value) => ({ chain, editor }) => {
        // 注：Editor 实例只暴露 getAttributes（getMarkAttributes 仅为内部函数）
        const attrs = { ...editor.getAttributes('textStyle'), [key]: value || null }
        const c = chain().setMark('textStyle', attrs)
        return (value ? c : c.pruneTextStyle()).run()   // 清空属性时顺手移除空标记
      },
      // 清除格式后调用：把不含任何属性的空 textStyle 标记整体移除，避免残留空 span
      pruneTextStyle: () => ({ state, dispatch }) => {
        if (state.selection.empty) return true
        let tr = state.tr
        const { from, to } = state.selection
        state.doc.nodesBetween(from, to, (node, pos) => {
          if (!node.isText) return
          node.marks.forEach((mark) => {
            if (mark.type.name !== 'textStyle') return
            const a = mark.attrs
            if (!a.fontFamily && !a.fontSize && !a.color) {
              tr = tr.removeMark(pos, pos + node.nodeSize, mark)
            }
          })
        })
        if (dispatch) dispatch(tr)
        return true
      },
    }
  },
})

// 段落排版属性：无属性 = 跟随练习默认样式（全局改即生效，局部覆盖保持不变）
export const RichParagraph = Paragraph.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      lineHeight: {
        default: null,
        parseHTML: (el) => {
          const v = parseFloat(el.style?.lineHeight)
          return Number.isFinite(v) && v > 0 ? v : null
        },
        renderHTML: (attrs) => (attrs.lineHeight ? { style: `line-height: ${attrs.lineHeight}` } : {}),
      },
      spaceBefore: {
        default: null,
        renderHTML: (attrs) => (attrs.spaceBefore
          ? { style: `margin-top: ${(attrs.spaceBefore * 4) / 3}px` } : {}),
      },
      spaceAfter: {
        default: null,
        renderHTML: (attrs) => (attrs.spaceAfter
          ? { style: `margin-bottom: ${(attrs.spaceAfter * 4) / 3}px` } : {}),
      },
      firstLineIndent: {
        default: false,
        renderHTML: (attrs) => (attrs.firstLineIndent ? { style: 'text-indent: 2em' } : {}),
      },
      indent: {
        default: 0,
        renderHTML: (attrs) => (attrs.indent ? { style: `margin-left: ${attrs.indent * 2}em` } : {}),
      },
    }
  },

  addCommands() {
    return {
      ...this.parent?.(),
      setParagraphAttr: (key, value) => ({ commands }) => commands.updateAttributes(
        this.name, { [key]: value === undefined ? null : value }),
      // 恢复本段为全局样式（阶段 2 计划项）：清掉所有局部段落属性
      resetParagraph: () => ({ commands }) => commands.updateAttributes(this.name, {
        lineHeight: null, spaceBefore: null, spaceAfter: null,
        firstLineIndent: false, indent: 0, textAlign: null,
      }),
    }
  },
})
