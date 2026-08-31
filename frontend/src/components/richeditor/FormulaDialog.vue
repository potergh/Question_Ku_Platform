<!-- 公式编辑弹窗（阶段 3）：LaTeX 输入 + KaTeX 实时预览 + 常用符号面板 + 行内/独立切换 -->
<template>
  <el-dialog v-model="visible" :title="isNew ? '插入公式' : '编辑公式'" width="640px"
             @close="emit('update:modelValue', false)">
    <div class="fd-body">
      <!-- 常用符号面板：只插入 LaTeX 模板，不制造另一套格式 -->
      <div class="fd-symbols">
        <template v-for="grp in SYMBOL_GROUPS" :key="grp.name">
          <span class="fd-sym-group">{{ grp.name }}</span>
          <el-tooltip v-for="s in grp.items" :key="s.tex" :content="s.tip || s.tex" placement="top">
            <button class="fd-sym-btn" @click="insertTemplate(s.tex)">{{ s.label }}</button>
          </el-tooltip>
        </template>
      </div>

      <el-input v-model="latex" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }"
                placeholder="输入 LaTeX，如 \frac{m}{V}" @keydown="onKeydown" ref="inputRef" />

      <!-- 实时预览 + 错误提示 -->
      <div class="fd-preview" :class="{ 'fd-preview-display': display, 'fd-preview-error': !!error }">
        <span v-if="error" class="fd-error">{{ error }}</span>
        <span v-else-if="!latex.trim()" class="fd-empty">（输入内容后此处实时预览）</span>
        <span v-else v-html="previewHtml" />
      </div>

      <div class="fd-mode">
        <el-radio-group v-model="display" size="small">
          <el-radio-button :value="false">行内公式</el-radio-button>
          <el-radio-button :value="true">独立公式</el-radio-button>
        </el-radio-group>
        <span class="fd-hint">Ctrl+Enter 确认</span>
      </div>
    </div>

    <template #footer>
      <el-button v-if="!isNew" type="danger" text @click="onDelete">删除公式</el-button>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!latex.trim() || !!error" @click="onConfirm">确认</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import katex from 'katex'
import { ElMessageBox } from 'element-plus'

const props = defineProps({
  modelValue: Boolean,
  latex: String,
  display: Boolean,       // true = 独立公式
  isNew: Boolean,         // true = 插入新公式（无删除按钮）
})
const emit = defineEmits(['update:modelValue', 'update:latex', 'update:display', 'confirm', 'delete'])

const inputRef = ref(null)

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})
const latex = computed({
  get: () => props.latex,
  set: (v) => emit('update:latex', v),
})
const display = computed({
  get: () => props.display,
  set: (v) => emit('update:display', v),
})

// 实时渲染 + 语法错误检测（throwOnError 捕获非法命令）
const preview = computed(() => {
  const tex = (props.latex || '').trim()
  if (!tex) return { html: '', error: '' }
  try {
    const html = katex.renderToString(tex, { throwOnError: true, displayMode: props.display })
    return { html, error: '' }
  } catch (e) {
    return { html: '', error: '语法错误：' + String(e.message).replace(/^KaTeX parse error:\s*/, '') }
  }
})
const previewHtml = computed(() => preview.value.html)
const error = computed(() => preview.value.error)

// 打开时聚焦输入框
watch(() => props.modelValue, (v) => {
  if (v) nextTick(() => inputRef.value?.focus?.())
})

// 符号面板：分数/根号/上下标/括号/希腊字母/运算符/物理常用
const SYMBOL_GROUPS = [
  { name: '结构', items: [
    { label: 'a/b', tex: '\\frac{}{}', tip: '分数' },
    { label: '√', tex: '\\sqrt{}', tip: '根号' },
    { label: 'ⁿ√', tex: '\\sqrt[]{}', tip: 'n 次根号' },
    { label: 'x²', tex: '^{}', tip: '上标' },
    { label: 'x₂', tex: '_{}', tip: '下标' },
    { label: '∑', tex: '\\sum_{}^{}', tip: '求和' },
    { label: '∫', tex: '\\int_{}^{}', tip: '积分' },
    { label: '()', tex: '\\left(\\right)', tip: '自适应括号' },
    { label: '|x|', tex: '\\left|\\right|', tip: '绝对值' },
    { label: '{…', tex: '\\begin{cases}\\\\\\\\\\end{cases}', tip: '分段函数' },
    { label: '—', tex: '\\overline{}', tip: '上划线（平均值等）' },
  ]},
  { name: '希腊', items: [
    { label: 'α', tex: '\\alpha' }, { label: 'β', tex: '\\beta' }, { label: 'γ', tex: '\\gamma' },
    { label: 'Δ', tex: '\\Delta' }, { label: 'δ', tex: '\\delta' }, { label: 'θ', tex: '\\theta' },
    { label: 'λ', tex: '\\lambda' }, { label: 'μ', tex: '\\mu' }, { label: 'ρ', tex: '\\rho' },
    { label: 'σ', tex: '\\sigma' }, { label: 'φ', tex: '\\varphi' }, { label: 'ω', tex: '\\omega' },
    { label: 'Ω', tex: '\\Omega' }, { label: 'π', tex: '\\pi' },
  ]},
  { name: '运算', items: [
    { label: '×', tex: '\\times' }, { label: '÷', tex: '\\div' }, { label: '±', tex: '\\pm' },
    { label: '≈', tex: '\\approx' }, { label: '≠', tex: '\\neq' }, { label: '≤', tex: '\\leq' },
    { label: '≥', tex: '\\geq' }, { label: '∞', tex: '\\infty' }, { label: '°', tex: '^{\\circ}' },
    { label: '∴', tex: '\\therefore' }, { label: '∵', tex: '\\because' },
  ]},
  { name: '物理', items: [
    { label: 'v⃗', tex: '\\vec{}', tip: '向量' },
    { label: 'm/s', tex: '\\mathrm{m/s}', tip: '单位（正体）' },
    { label: 'kg', tex: '\\mathrm{kg}' }, { label: 'N', tex: '\\mathrm{N}' },
    { label: 'J', tex: '\\mathrm{J}' }, { label: 'W', tex: '\\mathrm{W}' },
    { label: 'Ω', tex: '\\Omega', tip: '欧姆' }, { label: '℃', tex: '^{\\circ}\\mathrm{C}' },
    { label: '⇌', tex: '\\rightleftharpoons', tip: '化学可逆' },
  ]},
]

// 在光标处插入模板，光标停在第一个 {} 内
const insertTemplate = (tex) => {
  const el = inputRef.value?.textarea
  const cur = latex.value || ''
  if (!el) { latex.value = cur + tex; return }
  const start = el.selectionStart ?? cur.length
  const end = el.selectionEnd ?? cur.length
  latex.value = cur.slice(0, start) + tex + cur.slice(end)
  const target = start + tex.indexOf('{}') + 1
  nextTick(() => {
    el.focus()
    const pos = tex.includes('{}') ? target : start + tex.length
    el.setSelectionRange(pos, pos)
  })
}

const onKeydown = (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    if (latex.value.trim() && !error.value) onConfirm()
  }
}

const onConfirm = () => emit('confirm', latex.value.trim(), display.value)

const onDelete = async () => {
  await ElMessageBox.confirm('删除这个公式？', '提示', { type: 'warning' })
  emit('delete')
}
</script>

<style scoped>
.fd-body { display: flex; flex-direction: column; gap: 10px; }
.fd-symbols { display: flex; flex-wrap: wrap; gap: 3px; align-items: center;
  max-height: 118px; overflow-y: auto; padding: 6px; background: #f7f8fa; border-radius: 6px; }
.fd-sym-group { font-size: 12px; color: #909399; margin: 0 4px 0 6px; }
.fd-sym-btn { min-width: 30px; height: 24px; padding: 0 5px; border: 1px solid #dcdfe6;
  border-radius: 4px; background: #fff; cursor: pointer; font-size: 13px; line-height: 1; }
.fd-sym-btn:hover { border-color: #409eff; color: #409eff; }
.fd-preview { min-height: 56px; padding: 8px 10px; border: 1px solid #ebeef5; border-radius: 6px;
  overflow-x: auto; }
.fd-preview-display { text-align: center; }
.fd-preview-error { border-color: #f56c6c; }
.fd-error { color: #f56c6c; font-size: 12px; }
.fd-empty { color: #c0c4cc; font-size: 12px; }
.fd-mode { display: flex; align-items: center; justify-content: space-between; }
.fd-hint { font-size: 12px; color: #909399; }
</style>
