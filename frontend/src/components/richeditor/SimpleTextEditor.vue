<!-- 轻量版说明文字/自定义内容编辑器（阶段 5）：复用单题编辑器的 TipTap 内核扩展，
     工具栏仅保留说明文字需要的：B/I/U、标题、对齐、列表、公式、图片（本地上传）、
     字体字号、段落（行距/段前后/缩进）、清除格式。
     数据仍存 HTML：保存时 editor.getHTML() → 公式转 $...$、图片回写 asset://；加载时反向还原。 -->
<template>
  <div class="ste" v-if="editor">
    <div class="ste-toolbar">
      <el-tooltip content="加粗"><el-button size="small" text :class="{ on: editor.isActive('bold') }" @click="editor.chain().focus().toggleBold().run()"><b>B</b></el-button></el-tooltip>
      <el-tooltip content="斜体"><el-button size="small" text :class="{ on: editor.isActive('italic') }" @click="editor.chain().focus().toggleItalic().run()"><i>I</i></el-button></el-tooltip>
      <el-tooltip content="下划线"><el-button size="small" text :class="{ on: editor.isActive('underline') }" @click="editor.chain().focus().toggleUnderline().run()"><u>U</u></el-button></el-tooltip>
      <el-select size="small" class="ste-sel ste-sel-block" :model-value="curBlock" style="width:96px" @change="onBlockChange">
        <el-option label="正文" value="p" />
        <el-option label="标题 1" value="h1" />
        <el-option label="标题 2" value="h2" />
        <el-option label="标题 3" value="h3" />
      </el-select>
      <el-tooltip content="左对齐"><el-button size="small" text :class="{ on: editor.isActive({ textAlign: 'left' }) }" @click="editor.chain().focus().setTextAlign('left').run()">⇤</el-button></el-tooltip>
      <el-tooltip content="居中"><el-button size="small" text :class="{ on: editor.isActive({ textAlign: 'center' }) }" @click="editor.chain().focus().setTextAlign('center').run()">≡</el-button></el-tooltip>
      <el-tooltip content="右对齐"><el-button size="small" text :class="{ on: editor.isActive({ textAlign: 'right' }) }" @click="editor.chain().focus().setTextAlign('right').run()">⇥</el-button></el-tooltip>
      <span class="ste-sep" />
      <el-tooltip content="无序列表"><el-button size="small" text :class="{ on: editor.isActive('bulletList') }" @click="editor.chain().focus().toggleBulletList().run()">•≡</el-button></el-tooltip>
      <el-tooltip content="有序列表"><el-button size="small" text :class="{ on: editor.isActive('orderedList') }" @click="editor.chain().focus().toggleOrderedList().run()">1≡</el-button></el-tooltip>
      <span class="ste-sep" />
      <el-tooltip content="插入行内公式"><el-button size="small" text @click="openFormula(false)">∑行内</el-button></el-tooltip>
      <el-tooltip content="插入独立公式"><el-button size="small" text @click="openFormula(true)">∑独立</el-button></el-tooltip>
      <el-tooltip content="插入本地图片"><el-button size="small" @click="pickFile"><el-icon><Picture /></el-icon> 图片</el-button></el-tooltip>
      <span class="ste-sep" />
      <el-select v-model="curFont" size="small" class="ste-sel" style="width:92px" placeholder="字体"
        @change="v => applyText('fontFamily', v)">
        <el-option v-for="f in FONT_NAMES" :key="f" :label="f" :value="f" />
      </el-select>
      <el-select v-model="curSize" size="small" class="ste-sel" style="width:118px" placeholder="字号"
        @change="v => applyText('fontSize', v)">
        <el-option v-for="s in FONT_SIZES" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-popover trigger="click" :width="240">
        <template #reference><el-button size="small" text>段落▾</el-button></template>
        <div class="ste-para-panel">
          <div class="ste-para-row"><span>段前</span>
            <el-select v-model="curSpaceBefore" size="small"
              @change="v => applyPara('spaceBefore', v === 'default' ? null : v)">
              <el-option value="default" label="默认" />
              <el-option v-for="pt in SPACING_PTS" :key="'b' + pt" :value="pt" :label="`${pt} pt`" />
            </el-select>
          </div>
          <div class="ste-para-row"><span>段后</span>
            <el-select v-model="curSpaceAfter" size="small"
              @change="v => applyPara('spaceAfter', v === 'default' ? null : v)">
              <el-option value="default" label="默认" />
              <el-option v-for="pt in SPACING_PTS" :key="'a' + pt" :value="pt" :label="`${pt} pt`" />
            </el-select>
          </div>
          <div class="ste-para-row"><span>行距</span>
            <el-select v-model="curLineHeight" size="small"
              @change="v => applyPara('lineHeight', v === 'default' ? null : v)">
              <el-option value="default" label="默认" />
              <el-option v-for="lh in LINE_HEIGHTS" :key="lh" :label="`${lh} 倍`" :value="lh" />
            </el-select>
          </div>
          <div class="ste-para-row"><span>首行缩进</span>
            <el-switch v-model="curFirstIndent" size="small" @change="v => applyPara('firstLineIndent', v)" />
          </div>
          <div class="ste-para-row"><span>左缩进</span>
            <el-button size="small" text :disabled="(curIndent || 0) <= 0" @click="applyPara('indent', (curIndent || 0) - 1)">−</el-button>
            <span class="ste-indent-val">{{ curIndent || 0 }}</span>
            <el-button size="small" text :disabled="(curIndent || 0) >= 8" @click="applyPara('indent', (curIndent || 0) + 1)">＋</el-button>
          </div>
          <el-button size="small" class="ste-para-reset" @click="applyPara('reset', true)">恢复本段为默认</el-button>
        </div>
      </el-popover>
      <el-tooltip content="清除格式（回到默认样式）"><el-button size="small" text @click="clearFormat">清除格式</el-button></el-tooltip>
    </div>

    <editor-content :editor="editor" class="ste-canvas" />

    <FormulaDialog v-model="showFormula" v-model:latex="formulaLatex"
      v-model:display="formulaDisplay" :is-new="formulaIsNew"
      @confirm="onFormulaConfirm" @delete="onFormulaDelete" />

    <input ref="fileRef" type="file" accept="image/*" style="display:none" @change="onFileChange" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useEditor, EditorContent, Node } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import TextAlign from '@tiptap/extension-text-align'
import { InlineFormula, DisplayFormula } from './formulaNodes'
import { TextStyleExt, RichParagraph } from './typographyNodes'
import { FONT_NAMES, FONT_SIZES, LINE_HEIGHTS, SPACING_PTS } from './typography'
import { resolveAssetSrc } from './assets'
import FormulaDialog from './FormulaDialog.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  practiceId: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

/* 简单图片节点：可解析 <img> 加载存量 HTML；保存仍回写 asset:// 存储形式 */
const SimpleImage = Node.create({
  name: 'image',
  group: 'block',
  atom: true,
  selectable: true,
  addAttributes() { return { src: { default: '' } } },
  parseHTML() {
    return [{ tag: 'img[src]', getAttrs: el => ({ src: el.getAttribute('src') || '' }) }]
  },
  renderHTML({ node }) {
    const pid = this.editor?.storage?.qre?.practiceId
    return ['img', { src: resolveAssetSrc(node.attrs.src, pid), class: 'ste-img' }]
  },
})

/* ---- 存储/显示双向转换：公式 $..$ ↔ data-formula 节点；图片 asset:// ↔ 真实 URL ---- */
const dec = (s) => (s || '').replace(/&quot;/g, '"').replace(/&#39;/g, "'")
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
const enc = (s) => (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;')

const toDisplay = (html) => (html || '')
  .replace(/\$\$([\s\S]*?)\$\$/g, (_, l) => `<div data-formula-display latex="${enc(l.trim())}"></div>`)
  .replace(/\$([^$\n]+)\$/g, (_, l) => `<span data-formula-inline latex="${enc(l.trim())}"></span>`)
  .replace(/asset:\/\/practice\//g, `/api/practices/${props.practiceId}/assets/`)

const toStore = (html) => (html || '')
  .replace(/<span data-formula-inline[^>]*latex="([^"]*)"[^>]*>[\s\S]*?<\/span>/g, (_, l) => `$${dec(l)}$`)
  .replace(/<div data-formula-display[^>]*latex="([^"]*)"[^>]*>[\s\S]*?<\/div>/g, (_, l) => `\n$$${dec(l)}$$\n`)
  .replace(new RegExp(`/api/practices/${props.practiceId}/assets/`, 'g'), 'asset://practice/')

/* ---- 编辑器 ---- */
const editor = useEditor({
  content: toDisplay(props.modelValue),
  extensions: [
    StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
    Underline,
    TextAlign.configure({ types: ['heading', 'paragraph'] }),
    TextStyleExt,
    RichParagraph,
    InlineFormula,
    DisplayFormula,
    SimpleImage,
  ],
  editorProps: {
    attributes: { class: 'ste-prosemirror', spellcheck: 'false' },
  },
  onBeforeCreate({ editor: ed }) {
    ed.storage.qre = { practiceId: props.practiceId }
    ed.storage.qre.onEditFormula = ({ pos, latex, display }) => {
      formulaIsNew.value = false
      formulaEditPos.value = pos
      formulaLatex.value = latex
      formulaDisplay.value = display
      showFormula.value = true
    }
    ed.on('transaction', () => { rev.value++ })
  },
  onUpdate({ editor: ed }) {
    if (ed.view.composing) return
    updating = true
    lastHtml = ed.getHTML()
    const st = toStore(lastHtml)
    emit('update:modelValue', st)
    updating = false
  },
})

let updating = false
let lastHtml = props.modelValue || ''
const rev = ref(0)
const fileRef = ref(null)

watch(() => props.modelValue, (html) => {
  if (updating || !editor.value) return
  const next = toStore(editor.value.getHTML())
  if ((html || '') === next) return
  lastHtml = html || ''
  editor.value.commands.setContent(toDisplay(html || ''), { emitUpdate: false })
})

onBeforeUnmount(() => editor.value?.destroy())

/* ---- 工具栏选区状态 ---- */
const curBlock = computed(() => {
  rev.value
  const e = editor.value
  if (!e) return 'p'
  if (e.isActive('heading', { level: 1 })) return 'h1'
  if (e.isActive('heading', { level: 2 })) return 'h2'
  if (e.isActive('heading', { level: 3 })) return 'h3'
  return 'p'
})
const curFont = computed(() => { rev.value; return editor.value?.getAttributes('textStyle').fontFamily || '' })
const curSize = computed(() => { rev.value; return editor.value?.getAttributes('textStyle').fontSize || null })
const curSpaceBefore = computed(() => { rev.value; return editor.value?.getAttributes('paragraph').spaceBefore ?? 'default' })
const curSpaceAfter = computed(() => { rev.value; return editor.value?.getAttributes('paragraph').spaceAfter ?? 'default' })
const curLineHeight = computed(() => { rev.value; return editor.value?.getAttributes('paragraph').lineHeight ?? 'default' })
const curFirstIndent = computed(() => { rev.value; return !!editor.value?.getAttributes('paragraph').firstLineIndent })
const curIndent = computed(() => { rev.value; return editor.value?.getAttributes('paragraph').indent || 0 })

const onBlockChange = (v) => {
  const e = editor.value
  if (!e) return
  if (v === 'p') e.chain().focus().setParagraph().run()
  else e.chain().focus().toggleHeading({ level: Number(v[1]) }).run()
}
const applyText = (key, value) => {
  if (!value) return
  editor.value?.chain().focus().setTextStyleAttr(key, value).run()
}
const applyPara = (key, value) => {
  const e = editor.value
  if (!e) return
  if (key === 'reset') { e.chain().focus().resetParagraph().run(); return }
  e.chain().focus().setParagraphAttr(key, value).run()
}
const clearFormat = () => {
  const e = editor.value
  if (!e) return
  e.chain().focus().setTextStyleAttr('fontFamily', null).setTextStyleAttr('fontSize', null)
    .setParagraphAttr('lineHeight', null).setParagraphAttr('spaceBefore', null)
    .setParagraphAttr('spaceAfter', null).setParagraphAttr('firstLineIndent', false)
    .setParagraphAttr('indent', 0).setParagraphAttr('textAlign', null)
    .unsetAllMarks().run()
}

/* ---- 公式 ---- */
const showFormula = ref(false)
const formulaLatex = ref('')
const formulaDisplay = ref(false)
const formulaIsNew = ref(true)
const formulaEditPos = ref(null)
const openFormula = (display) => {
  formulaIsNew.value = true
  formulaEditPos.value = null
  formulaLatex.value = ''
  formulaDisplay.value = display
  showFormula.value = true
}
const onFormulaConfirm = (latex, display) => {
  const e = editor.value
  if (!e) return
  if (formulaEditPos.value !== null) {
    const type = display ? 'displayFormula' : 'inlineFormula'
    e.commands.command(({ tr, dispatch }) => {
      tr.setNodeMarkup(formulaEditPos.value, null, { latex })
      if (dispatch) dispatch(tr)
      return true
    })
    formulaEditPos.value = null
  } else {
    const type = display ? 'displayFormula' : 'inlineFormula'
    e.chain().focus().insertContent({ type, attrs: { latex } }).run()
  }
}
const onFormulaDelete = () => {
  const e = editor.value
  if (!e || formulaEditPos.value === null) return
  e.commands.command(({ tr, dispatch }) => {
    tr.delete(formulaEditPos.value, formulaEditPos.value + 1)
    if (dispatch) dispatch(tr)
    return true
  })
  formulaEditPos.value = null
}

/* ---- 本地图片上传 ---- */
const pickFile = () => fileRef.value?.click()
const onFileChange = async (e) => {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  if (!/^image\//.test(file.type)) { ElMessage.warning('请选择图片文件'); return }
  if (file.size > 10 * 1024 * 1024) { ElMessage.warning('图片不能超过 10MB'); return }
  const fd = new FormData()
  fd.append('file', file)
  try {
    const res = await axios.post(`/api/practices/${props.practiceId}/assets/upload`, fd)
    const name = res.data?.name
    if (!name) throw new Error('no name')
    editor.value?.chain().focus().insertContent({ type: 'image', attrs: { src: `asset://practice/${name}` } }).run()
    ElMessage.success('图片已插入')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '图片上传失败')
  }
}
</script>

<style scoped>
.ste { border: 1px solid #dcdfe6; border-radius: 6px; }
.ste-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 2px; padding: 4px 6px;
  border-bottom: 1px solid #ebeef5; background: #fafafa; }
.ste-sep { width: 1px; height: 16px; background: #dcdfe6; margin: 0 4px; }
.ste-sel { margin: 0 2px; }
.ste-canvas { padding: 8px 10px; min-height: 56px; max-height: 320px; overflow: auto; }
.ste-canvas :deep(.ste-prosemirror) { outline: none; min-height: 40px; }
.ste-canvas :deep(h1) { font-size: 1.5em; margin: .4em 0; }
.ste-canvas :deep(h2) { font-size: 1.25em; margin: .4em 0; }
.ste-canvas :deep(h3) { font-size: 1.1em; margin: .4em 0; }
.ste-canvas :deep(ol), .ste-canvas :deep(ul) { padding-left: 1.4em; }
.ste-canvas :deep(img.ste-img) { max-width: 100%; height: auto; border: 1px dashed #c0c4cc; }
.ste-para-panel { display: flex; flex-direction: column; gap: 8px; }
.ste-para-row { display: flex; align-items: center; gap: 8px; justify-content: space-between; }
.ste-para-row > span:first-child { width: 60px; color: #606266; font-size: 12px; }
.ste-indent-val { width: 22px; text-align: center; color: #606266; font-size: 12px; }
.ste-para-reset { width: 100%; }
:deep(.katex-display) { margin: .5em 0; }
</style>
