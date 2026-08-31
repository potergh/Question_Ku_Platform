<!-- 单题所见即所得编辑器（阶段 1）：题干/图片/选项/留白在同一个连续画布内编辑。
     编辑器文档（rich_document）为新真源；保存后后端反推旧块/快照（导出兼容）。 -->
<template>
  <div class="qre" v-if="editor">
    <!-- 工具栏 -->
    <div class="qre-toolbar">
      <el-tooltip content="撤销"><el-button size="small" text :disabled="!editor.can().undo()" @click="editor.chain().focus().undo().run()">↶</el-button></el-tooltip>
      <el-tooltip content="重做"><el-button size="small" text :disabled="!editor.can().redo()" @click="editor.chain().focus().redo().run()">↷</el-button></el-tooltip>
      <span class="qre-sep" />
      <el-tooltip content="加粗"><el-button size="small" text :class="{ on: editor.isActive('bold') }" @click="editor.chain().focus().toggleBold().run()"><b>B</b></el-button></el-tooltip>
      <el-tooltip content="斜体"><el-button size="small" text :class="{ on: editor.isActive('italic') }" @click="editor.chain().focus().toggleItalic().run()"><i>I</i></el-button></el-tooltip>
      <el-tooltip content="下划线"><el-button size="small" text :class="{ on: editor.isActive('underline') }" @click="editor.chain().focus().toggleUnderline().run()"><u>U</u></el-button></el-tooltip>
      <el-tooltip content="删除线"><el-button size="small" text :class="{ on: editor.isActive('strike') }" @click="editor.chain().focus().toggleStrike().run()"><s>S</s></el-button></el-tooltip>
      <el-tooltip content="上标"><el-button size="small" text :class="{ on: editor.isActive('superscript') }" @click="editor.chain().focus().toggleSuperscript().run()">x²</el-button></el-tooltip>
      <el-tooltip content="下标"><el-button size="small" text :class="{ on: editor.isActive('subscript') }" @click="editor.chain().focus().toggleSubscript().run()">x₂</el-button></el-tooltip>
      <span class="qre-sep" />
      <el-tooltip content="左对齐"><el-button size="small" text :class="{ on: editor.isActive({ textAlign: 'left' }) }" @click="editor.chain().focus().setTextAlign('left').run()">⇤</el-button></el-tooltip>
      <el-tooltip content="居中"><el-button size="small" text :class="{ on: editor.isActive({ textAlign: 'center' }) }" @click="editor.chain().focus().setTextAlign('center').run()">≡</el-button></el-tooltip>
      <el-tooltip content="右对齐"><el-button size="small" text :class="{ on: editor.isActive({ textAlign: 'right' }) }" @click="editor.chain().focus().setTextAlign('right').run()">⇥</el-button></el-tooltip>
      <el-tooltip content="两端对齐"><el-button size="small" text :class="{ on: editor.isActive({ textAlign: 'justify' }) }" @click="editor.chain().focus().setTextAlign('justify').run()">☰</el-button></el-tooltip>
      <span class="qre-sep" />
      <el-tooltip content="无序列表"><el-button size="small" text :class="{ on: editor.isActive('bulletList') }" @click="editor.chain().focus().toggleBulletList().run()">•≡</el-button></el-tooltip>
      <el-tooltip content="有序列表"><el-button size="small" text :class="{ on: editor.isActive('orderedList') }" @click="editor.chain().focus().toggleOrderedList().run()">1≡</el-button></el-tooltip>
      <el-tooltip content="插入横线（填写线/分隔线）"><el-button size="small" text @click="editor.chain().focus().setHorizontalRule().run()">—</el-button></el-tooltip>
      <el-tooltip content="插入行内公式（选中 LaTeX 文本可直接转换）"><el-button size="small" text @click="openFormulaDialog(false)">∑行内</el-button></el-tooltip>
      <el-tooltip content="插入独立公式（单独成行）"><el-button size="small" text @click="openFormulaDialog(true)">∑独立</el-button></el-tooltip>
      <el-tooltip content="减少缩进"><el-button size="small" text :disabled="!editor.can().liftListItem('listItem')" @click="editor.chain().focus().liftListItem('listItem').run()">⇤•</el-button></el-tooltip>
      <el-tooltip content="增加缩进"><el-button size="small" text :disabled="!editor.can().sinkListItem('listItem')" @click="editor.chain().focus().sinkListItem('listItem').run()">⇥•</el-button></el-tooltip>
      <el-tooltip content="清除格式（回到练习默认样式）"><el-button size="small" text @click="clearFormatting">⌫T</el-button></el-tooltip>
      <span class="qre-sep" />
      <el-select v-model="curFont" size="small" class="qre-sel qre-sel-font" placeholder="字体"
        @change="(v) => applyTextStyle('fontFamily', v)">
        <el-option v-for="f in FONT_NAMES" :key="f" :label="f" :value="f" />
      </el-select>
      <el-select v-model="curSize" size="small" class="qre-sel qre-sel-size" placeholder="字号"
        @change="(v) => applyTextStyle('fontSize', v)">
        <el-option v-for="s in FONT_SIZES" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-tooltip content="文字颜色（可任意选择）">
        <el-color-picker v-model="curColor" size="small" :predefine="QUICK_COLORS"
          @change="(v) => applyTextStyle('color', v)" />
      </el-tooltip>
      <el-select v-model="curLineHeight" size="small" class="qre-sel qre-sel-lh" placeholder="行距"
        @change="(v) => applyPara('lineHeight', v === 'default' ? null : v)">
        <el-option value="default" label="默认" />
        <el-option v-for="lh in LINE_HEIGHTS" :key="lh" :label="`${lh} 倍`" :value="lh" />
      </el-select>
      <el-popover trigger="click" :width="240">
        <template #reference><el-button size="small" text>段落▾</el-button></template>
        <div class="qre-para-panel">
          <div class="qre-para-row"><span>段前</span>
            <el-select v-model="curSpaceBefore" size="small"
              @change="(v) => applyPara('spaceBefore', v === 'default' ? null : v)">
              <el-option value="default" label="默认" />
              <el-option v-for="pt in SPACING_PTS" :key="'b' + pt" :value="pt" :label="`${pt} pt`" />
            </el-select>
          </div>
          <div class="qre-para-row"><span>段后</span>
            <el-select v-model="curSpaceAfter" size="small"
              @change="(v) => applyPara('spaceAfter', v === 'default' ? null : v)">
              <el-option value="default" label="默认" />
              <el-option v-for="pt in SPACING_PTS" :key="'a' + pt" :value="pt" :label="`${pt} pt`" />
            </el-select>
          </div>
          <div class="qre-para-row"><span>首行缩进</span>
            <el-switch v-model="curFirstIndent" size="small" @change="(v) => applyPara('firstLineIndent', v)" />
          </div>
          <div class="qre-para-row"><span>左缩进</span>
            <el-button size="small" text :disabled="!canIndent(-1)" @click="applyPara('indent', (curIndent || 0) - 1)">−</el-button>
            <span class="qre-indent-val">{{ curIndent || 0 }}</span>
            <el-button size="small" text :disabled="(curIndent || 0) >= 8" @click="applyPara('indent', (curIndent || 0) + 1)">＋</el-button>
          </div>
          <el-button size="small" class="qre-para-reset" @click="resetParaToGlobal">恢复本段为全局样式</el-button>
        </div>
      </el-popover>
      <span class="qre-sep" />
      <el-tooltip content="添加选项（或在选项内按 Ctrl+Enter）"><el-button size="small" text @click="editor.chain().focus().addOption().run()">+选项</el-button></el-tooltip>
      <el-tooltip content="删除光标所在选项"><el-button size="small" text type="danger" :disabled="!inOption" @click="removeCurrentOption">−选项</el-button></el-tooltip>
      <el-tooltip content="选项上移"><el-button size="small" text :disabled="!inOption" @click="editor.chain().focus().moveOption(-1).run()">选项↑</el-button></el-tooltip>
      <el-tooltip content="选项下移"><el-button size="small" text :disabled="!inOption" @click="editor.chain().focus().moveOption(1).run()">选项↓</el-button></el-tooltip>
      <span class="flex-gap" />
      <span class="qre-status" :class="'st-' + status">{{ STATUS_TEXT[status] }}</span>
      <el-button v-if="status === 'failed'" size="small" type="danger" text @click="doSave">重试</el-button>
      <el-button size="small" type="primary" :loading="status === 'saving'" @click="doSave">保存</el-button>
    </div>

    <!-- 连续编辑画布（未局部覆盖的内容跟随练习默认样式） -->
    <editor-content :editor="editor" class="qre-canvas" :style="canvasStyle" />

    <!-- 公式编辑弹窗（阶段 3） -->
    <FormulaDialog v-model="showFormulaDialog" v-model:latex="formulaLatex"
      v-model:display="formulaDisplay" :is-new="formulaIsNew"
      @confirm="onFormulaConfirm" @delete="onFormulaDelete" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useEditor, EditorContent, Extension } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Superscript from '@tiptap/extension-superscript'
import Subscript from '@tiptap/extension-subscript'
import TextAlign from '@tiptap/extension-text-align'
import { InlineFormula, DisplayFormula } from './formulaNodes'
import { BlockImage, InlineImage } from './imageNodes'
import { AnswerSpace } from './answerSpaceNode'
import { OptionGroup, Option, findOptionAt } from './optionNodes'
import { TextStyleExt, RichParagraph } from './typographyNodes'
import FormulaDialog from './FormulaDialog.vue'
import {
  FONT_NAMES, FONT_SIZES, LINE_HEIGHTS, SPACING_PTS, QUICK_COLORS,
  DEFAULT_STYLE, cssFontFamily,
} from './typography'

const props = defineProps({
  doc: Object,               // rich_document（schema v1）
  practiceId: String,
  questionId: String,
  defaultStyle: Object,      // 练习默认样式（未局部覆盖时跟随）
})
const emit = defineEmits(['saved', 'requestReplaceImage'])

const STATUS_TEXT = { unsaved: '未保存', saving: '保存中…', saved: '已保存', failed: '保存失败' }

// 组件级元数据（图片/公式节点渲染时需要 practiceId 解析资产）
const Meta = Extension.create({ name: 'qre', addStorage: () => ({ practiceId: '' }) })

// 安全粘贴：外部图片忽略、脚本/事件属性/内联样式清理（schema 之外的标签由编辑器自动丢弃）
function sanitizePastedHTML(html) {
  const div = document.createElement('div')
  div.innerHTML = html
  div.querySelectorAll('script,style,link,meta,iframe,object,embed,form').forEach(el => el.remove())
  div.querySelectorAll('img').forEach(img => {
    const src = img.getAttribute('src') || ''
    const safe = src.startsWith('/api/practices/') || src.startsWith('asset://practice/')
    if (!safe) img.remove()
  })
  div.querySelectorAll('*').forEach(el => {
    el.removeAttribute('style')
    for (const attr of [...el.attributes]) {
      if (attr.name.startsWith('on')) el.removeAttribute(attr.name)
      if (attr.name === 'href' && /^\s*javascript:/i.test(attr.value)) el.removeAttribute(attr.name)
    }
  })
  return div.innerHTML
}

// 注：tiptap 2.27 起 content 必须传完整 {type:'doc'} 对象，裸节点数组会被当成 Fragment 导致崩溃
const emptyDoc = () => ({ type: 'doc', content: [{ type: 'paragraph' }] })
// 旧迁移数据兼容：段内的 displayFormula 提升为块级（前端它是 block 节点，放段内会被 ProseMirror 丢弃）
const normalizeDoc = (d) => {
  const out = []
  for (const n of (d?.content || [])) {
    if (n?.type === 'paragraph' && (n.content || []).some(c => c?.type === 'displayFormula')) {
      let buf = []
      const flush = () => { if (buf.length) { out.push({ ...n, content: buf }); buf = [] } }
      for (const c of n.content) {
        if (c?.type === 'displayFormula') { flush(); out.push(c) } else buf.push(c)
      }
      flush()
    } else if (n) out.push(n)
  }
  return out.length ? { type: 'doc', content: out } : emptyDoc()
}
const asDoc = (d) => (d?.content?.length ? normalizeDoc(d) : emptyDoc())

const editor = useEditor({
  content: asDoc(props.doc),
  extensions: [
    StarterKit.configure({
      heading: false, blockquote: false, codeBlock: false, code: false,
      paragraph: false,   // paragraph 换用带排版属性的 RichParagraph（horizontalRule 启用供插入横线）
    }),
    RichParagraph,
    Underline, Superscript, Subscript,
    TextAlign.configure({ types: ['paragraph'] }),
    TextStyleExt,
    BlockImage, InlineImage, InlineFormula, DisplayFormula,
    AnswerSpace, OptionGroup, Option,
    Meta,
  ],
  editorProps: {
    attributes: { class: 'qre-prosemirror', spellcheck: 'false' },
    transformPastedHTML: sanitizePastedHTML,
  },
  onBeforeCreate({ editor: ed }) {
    ed.storage.qre.practiceId = props.practiceId
    // 图片替换请求：存储待替换图片的 src，触发父组件开启替换模式资产选择器
    ed.storage.qre.onRequestReplaceImage = (src) => {
      ed.storage.qre.replacingImageSrc = src
      emit('requestReplaceImage')
    }
    // 公式点击编辑（行内单击/独立双击，由 formulaNodes NodeView 上抛）
    ed.storage.qre.onEditFormula = ({ pos, latex, display }) => {
      formulaIsNew.value = false
      formulaEditPos.value = pos
      formulaInsertRange.value = null
      formulaLatex.value = latex
      formulaDisplay.value = display
      showFormulaDialog.value = true
    }
    ed.on('transaction', () => { rev.value++ })   // 工具栏选区状态刷新
  },
  onUpdate({ editor: ed }) {
    if (ed.view.composing) return   // 中文输入法组词期间不触发保存
    markDirty()
  },
})

// 画布默认样式：跟随练习设置（局部 marks/段落属性覆盖之）
const ds = computed(() => ({ ...DEFAULT_STYLE, ...(props.defaultStyle || {}) }))
const canvasStyle = computed(() => ({
  '--qre-font-family': cssFontFamily(ds.value.font_family),
  '--qre-font-size': `${ds.value.font_size}pt`,
  '--qre-line-height': ds.value.line_height,
}))

/* ---- 工具栏排版状态（随选区刷新） ---- */
const rev = ref(0)
const textStyleAttrs = computed(() => {
  rev.value   // 依赖触发
  return editor.value?.getAttributes('textStyle') || {}
})
const paraAttrs = computed(() => {
  rev.value
  return editor.value?.getAttributes('paragraph') || {}
})
const curFont = ref(null)
const curSize = ref(null)
const curColor = ref(null)
const curLineHeight = ref(null)
const curSpaceBefore = ref(null)
const curSpaceAfter = ref(null)
const curFirstIndent = ref(false)
const curIndent = ref(0)
watch(rev, () => {
  if (!editor.value) return
  const ts = textStyleAttrs.value
  // 未局部覆盖时回显练习默认样式（与画布实际显示一致）；颜色无默认值，留空即可
  curFont.value = ts.fontFamily || ds.value.font_family
  curSize.value = ts.fontSize || ds.value.font_size
  curColor.value = ts.color || null
  const pa = paraAttrs.value
  // Element Plus 把 '' 视为无值（显示占位符），故用非空哨兵 'default' 表示跟随全局
  curLineHeight.value = pa.lineHeight || 'default'
  curSpaceBefore.value = pa.spaceBefore ?? 'default'
  curSpaceAfter.value = pa.spaceAfter ?? 'default'
  curFirstIndent.value = !!pa.firstLineIndent
  curIndent.value = pa.indent || 0
}, { immediate: true })

// 排版命令：应用后由 transaction 触发 onUpdate → 自动进入待保存
const applyTextStyle = (key, value) => {
  editor.value?.chain().focus().setTextStyleAttr(key, value).run()
}
const applyPara = (key, value) => {
  editor.value?.chain().focus().setParagraphAttr(key, value).run()
}
const canIndent = (delta) => {
  const next = (curIndent.value || 0) + delta
  return next >= 0 && next <= 8
}
const resetParaToGlobal = () => {
  editor.value?.chain().focus().resetParagraph().run()
}
const clearFormatting = () => {
  editor.value?.chain().focus()
    .clearNodes().unsetAllMarks().resetParagraph().pruneTextStyle().run()
}

const inOption = computed(() => editor.value && !!findOptionAt(editor.value.state))

/* ---- 保存：未保存 → 1 秒防抖自动保存；手动保存立即执行；序号防止旧响应覆盖 ---- */
const status = ref('saved')
const dirty = ref(false)
let saveSeq = 0
let saveTimer = null

const toDoc = (json) => ({ type: 'doc', schema_version: 1, content: json.content || [] })

const doSave = async () => {
  clearTimeout(saveTimer)
  if (!editor.value) return
  const seq = ++saveSeq
  status.value = 'saving'
  try {
    const res = await axios.put(
      `/api/practices/${props.practiceId}/questions/${props.questionId}/document`,
      { document: toDoc(editor.value.getJSON()) })
    if (seq !== saveSeq) return   // 已有更新的保存，丢弃过期响应
    status.value = 'saved'
    dirty.value = false
    emit('saved', res.data)
  } catch (e) {
    if (seq !== saveSeq) return
    status.value = 'failed'
    ElMessage.error(e.response?.data?.detail || '保存失败，请重试')
  }
}
const markDirty = () => {
  dirty.value = true
  if (status.value !== 'failed') status.value = 'unsaved'
  clearTimeout(saveTimer)
  saveTimer = setTimeout(doSave, 1000)
}

// 切题/离开前强制落盘；外部重建文档（如恢复题库版本）时重置画布内容
const flush = async () => {
  clearTimeout(saveTimer)
  if (dirty.value && editor.value) await doSave()
}
watch(() => props.doc, (d) => {
  if (!editor.value) return
  const next = JSON.stringify(d?.content || [])
  const cur = JSON.stringify(editor.value.getJSON().content || [])
  if (next === cur) return
  saveSeq++   // 作废进行中的旧保存响应（重建后以新文档为准）
  dirty.value = false
  status.value = 'saved'
  clearTimeout(saveTimer)
  editor.value.commands.setContent(asDoc(d), false)
})

// 从练习资产插入块级图片（图片选择器入口）
const insertImageBlock = (src) => {
  editor.value?.chain().focus()
    .insertContent({ type: 'image', attrs: { src, align: 'center', width: null, layout: 'row' } }).run()
  markDirty()
}

/* ---- 公式（阶段 3）：插入/编辑/删除，未输入内容不创建空节点 ---- */
const showFormulaDialog = ref(false)
const formulaLatex = ref('')
const formulaDisplay = ref(false)
const formulaIsNew = ref(true)
const formulaEditPos = ref(null)        // 编辑模式：节点位置（切换行内/独立时需重建节点）
const formulaInsertRange = ref(null)    // 插入模式：选中文本范围（转为公式）

// 工具栏入口：有选中文本时预填（支持选中 LaTeX 直接转换）
const openFormulaDialog = (display) => {
  const { state } = editor.value
  const { from, to, empty } = state.selection
  formulaIsNew.value = true
  formulaEditPos.value = null
  formulaInsertRange.value = empty ? null : { from, to }
  formulaLatex.value = empty ? '' : state.doc.textBetween(from, to)
  formulaDisplay.value = display
  showFormulaDialog.value = true
}

const onFormulaConfirm = (latex, display) => {
  if (!latex.trim()) return   // 空内容不创建公式节点
  const typeName = display ? 'displayFormula' : 'inlineFormula'
  const ed = editor.value
  if (!formulaIsNew.value && formulaEditPos.value != null) {
    // 编辑已有公式：同类型只改属性；行内/独立切换则重建节点（类型不同不可 setNodeMarkup）
    const pos = formulaEditPos.value
    ed.chain().focus().command(({ tr, state }) => {
      const node = state.doc.nodeAt(pos)
      if (!node || (node.type.name !== 'inlineFormula' && node.type.name !== 'displayFormula')) return false
      if (node.type.name === typeName) tr.setNodeMarkup(pos, null, { ...node.attrs, latex })
      else tr.replaceWith(pos, pos + node.nodeSize, state.schema.nodes[typeName].create({ latex }))
      return true
    }).run()
  } else if (formulaInsertRange.value) {
    // 选中 LaTeX 文本 → 替换为公式节点（限幅防文档已变化）
    const { from, to } = formulaInsertRange.value
    ed.chain().focus().command(({ tr, state }) => {
      if (from >= state.doc.content.size) return false
      tr.replaceWith(from, Math.min(to, state.doc.content.size), state.schema.nodes[typeName].create({ latex }))
      return true
    }).run()
  } else {
    ed.chain().focus().insertContent({ type: typeName, attrs: { latex } }).run()
  }
  markDirty()
  showFormulaDialog.value = false
}

const onFormulaDelete = () => {
  const pos = formulaEditPos.value
  editor.value?.chain().focus().command(({ tr, state }) => {
    const node = pos != null && state.doc.nodeAt(pos)
    if (!node) return false
    tr.delete(pos, pos + node.nodeSize)
    return true
  }).run()
  markDirty()
  showFormulaDialog.value = false
}
// 替换当前待替换图片的 src（保留宽高/对齐）
const replaceImageBlock = (newSrc) => {
  const targetSrc = editor.value?.storage.qre.replacingImageSrc
  if (!targetSrc) return
  editor.value.storage.qre.replacingImageSrc = null
  editor.value.chain().focus().command(({ tr, state }) => {
    let found = false
    state.doc.descendants((node, pos) => {
      if (!found && node.type.name === 'image' && node.attrs.src === targetSrc) {
        tr.setNodeMarkup(pos, null, { ...node.attrs, src: newSrc })
        found = true
        return false
      }
    })
    return found
  }).run()
  markDirty()
}
defineExpose({ flush, isDirty: () => dirty.value, insertImageBlock, replaceImageBlock })

// 页面关闭/刷新时保护未保存内容
const onUnload = (e) => { if (dirty.value) { e.preventDefault(); e.returnValue = '' } }
window.addEventListener('beforeunload', onUnload)
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onUnload)
  clearTimeout(saveTimer)
})

const removeCurrentOption = async () => {
  await ElMessageBox.confirm('删除光标所在的这个选项？后续选项将自动重新编号。', '提示', { type: 'warning' })
  editor.value.chain().focus().removeOption().run()
  markDirty()
}
</script>

<style scoped>
.qre { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; }
.qre-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 2px;
  padding: 6px 8px; border-bottom: 1px solid #ebeef5; position: sticky; top: 0;
  background: #fff; z-index: 2; border-radius: 6px 6px 0 0; }
.qre-toolbar :deep(.el-button) { padding: 2px 6px; }
.qre-toolbar :deep(.el-button.on) { color: #409eff; background: #ecf5ff; }
.qre-toolbar .qre-sel { margin: 0 2px; }
.qre-toolbar :deep(.qre-sel .el-input__wrapper) { padding-left: 8px; padding-right: 24px; }
.qre-sel-font { width: 100px; }
.qre-sel-size { width: 118px; }
.qre-sel-lh { width: 82px; }
.qre-toolbar :deep(.el-color-picker) { margin: 0 2px; }
.qre-para-panel { display: flex; flex-direction: column; gap: 8px; }
.qre-para-row { display: flex; align-items: center; justify-content: space-between; font-size: 13px; }
.qre-para-row .el-select { width: 120px; }
.qre-indent-val { min-width: 16px; text-align: center; font-size: 13px; }
.qre-para-reset { align-self: flex-end; }
.qre-sep { width: 1px; height: 18px; background: #dcdfe6; margin: 0 6px; }
.flex-gap { flex: 1; }
.qre-status { font-size: 12px; margin-right: 8px; color: #909399; }
.qre-status.st-unsaved { color: #e6a23c; }
.qre-status.st-saving { color: #409eff; }
.qre-status.st-saved { color: #67c23a; }
.qre-status.st-failed { color: #f56c6c; }
.qre-canvas { padding: 14px 18px; }
.qre-canvas :deep(.qre-prosemirror) { min-height: 220px; outline: none;
  font-family: var(--qre-font-family); font-size: var(--qre-font-size); line-height: var(--qre-line-height); }
.qre-canvas :deep(.qre-prosemirror p) { margin: 0 0 6px; }
.qre-canvas :deep(.qre-prosemirror ul),
.qre-canvas :deep(.qre-prosemirror ol) { margin: 2px 0 2px 1.5em; padding: 0; }
.qre-canvas :deep(.qre-prosemirror hr) { border: none; border-top: 1px solid #333; margin: 8px 0; }
.qre-canvas :deep(.qre-option) { display: flex; gap: 6px; padding: 1px 4px; border-radius: 4px; }
.qre-canvas :deep(.qre-option[data-selected]) { background: #ecf5ff; }
.qre-canvas :deep(.qre-option-label) { color: #303133; font-weight: 600; flex-shrink: 0; }
.qre-canvas :deep(.qre-img) { position: relative; padding: 4px; margin: 6px 0; }
.qre-canvas :deep(.qre-img[data-layout="row"]) { display: inline-block; vertical-align: top; margin: 4px 0; padding: 0 3px; box-sizing: border-box; }
.qre-canvas :deep(.qre-img[data-layout="row"] .qre-img-wrap) { width: 100%; }
.qre-canvas :deep(.qre-img[data-layout="row"] img) { width: 100%; }
.qre-canvas :deep(.qre-img.is-center) { text-align: center; }
.qre-canvas :deep(.qre-img.is-left) { text-align: left; }
.qre-canvas :deep(.qre-img.is-right) { text-align: right; }
.qre-canvas :deep(.qre-img-wrap) { position: relative; display: inline-block; }
.qre-canvas :deep(.qre-img img) { max-width: 100%; }
.qre-canvas :deep(.qre-img[data-selected]) { outline: 2px solid #409eff; border-radius: 4px; }
.qre-canvas :deep(.qre-img) { z-index: 1; }
.qre-canvas :deep(.qre-img-handle) {
  position: absolute; bottom: -5px; right: -5px;
  width: 12px; height: 12px;
  background: #409eff; border: 2px solid white; border-radius: 2px;
  cursor: nwse-resize; z-index: 10;
}
.qre-canvas :deep(.qre-img-missing) {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 100px; min-height: 60px;
  background: #f5f7fa; border: 1px dashed #c0c4cc;
  color: #909399; font-size: 12px; border-radius: 4px;
}
.qre-canvas :deep(.qre-img-tools) { position: fixed; display: flex; z-index: 3000;
  gap: 4px; background: rgba(255,255,255,.96); padding: 3px 6px; border-radius: 4px;
  box-shadow: 0 2px 10px rgba(0,0,0,.2); align-items: center; white-space: nowrap; }
.qre-canvas :deep(.qre-space) { position: relative; }
.qre-canvas :deep(.qre-space-line) { height: 1.9em; }
.qre-canvas :deep(.qre-space-zero) { color: #c0c4cc; font-size: 12px; }
.qre-canvas :deep(.qre-space-tools) { position: absolute; right: 0; top: 0; display: none; }
.qre-canvas :deep(.qre-space:hover .qre-space-tools) { display: block; }
.qre-canvas :deep(.qre-inline-img) { height: 1.5em; vertical-align: text-bottom; }
.qre-canvas :deep(.qre-formula-display) { text-align: center; margin: 6px 0; }
.qre-canvas :deep(.qre-formula-inline),
.qre-canvas :deep(.qre-formula-display) { cursor: pointer; border-radius: 4px; }
.qre-canvas :deep(.qre-formula-inline:hover),
.qre-canvas :deep(.qre-formula-display:hover) { outline: 1px dashed #a0cfff; }
.qre-canvas :deep(.formula-error) { color: #f56c6c; font-family: monospace; }
</style>
