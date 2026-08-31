<template>
  <div class="wb-canvas">
    <!-- 大标题 -->
    <div class="wb-title-row">
      <span class="wb-label">大标题</span>
      <input class="wb-title-input" :value="title"
             @change="onTitleChange" placeholder="点击编辑练习标题" />
    </div>

    <div class="wb-insert">
      <el-dropdown trigger="click" @command="c => insertAt(0, c)">
        <el-button size="small" type="primary" plain>＋ 在开头插入…</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="subtitle">小标题（小节）</el-dropdown-item>
            <el-dropdown-item command="custom_text">说明文字 / 自定义内容</el-dropdown-item>
            <el-dropdown-item command="spacer">空白</el-dropdown-item>
            <el-dropdown-item command="page_break">分页符</el-dropdown-item>
            <el-dropdown-item command="question" divided>题目（从题库添加）</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div class="wb-blocks">
      <template v-for="(blk, bi) in blocks" :key="blk.id">
        <!-- 拖动插入指示线 -->
        <div v-if="dropBefore === bi" class="wb-drop-line"></div>

        <!-- 小节 -->
        <div v-if="blk.type === 'subtitle'" class="wb-block wb-subtitle"
             :class="{ dragging: dragIndex === bi }"
             draggable="true" @dragstart="onDragStart(bi, $event)" @dragend="onDragEnd"
             @dragover.prevent="onDragOver(bi)" @drop.prevent="onDrop(bi)">
          <div class="wb-block-head">
            <span class="drag-handle" title="拖动排序">⠿</span>
            <span class="wb-type-tag sub">小节</span>
            <b class="wb-sub-no">{{ sectionLabel(subIndex(bi)) }}</b>
            <input v-if="editingId === blk.id" class="wb-inline-input"
                   v-model="blk.title" @keyup.enter="editingId = null" @blur="editingId = null" />
            <span v-else class="wb-sub-title" @click="editingId = blk.id">{{ blk.title || '未命名小节' }}</span>
            <span class="flex-gap" />
            <el-tooltip content="显示标题"><el-switch v-model="blk.show_title" size="small" @change="touch(blk, bi)" /></el-tooltip>
            <el-tooltip content="从新页开始"><el-switch v-model="blk.start_on_new_page" size="small" @change="touch(blk, bi)" /></el-tooltip>
            <el-button size="small" text @click="moveBlock(bi, -1)" :disabled="bi === 0">↑</el-button>
            <el-button size="small" text @click="moveBlock(bi, 1)" :disabled="bi === blocks.length - 1">↓</el-button>
            <el-button size="small" text type="danger" @click="removeBlock(bi, blk)">✖</el-button>
          </div>
        </div>

        <!-- 题目引用 -->
        <div v-else-if="blk.type === 'question_ref'" class="wb-block wb-question"
             :class="{ dragging: dragIndex === bi }"
             draggable="true" @dragstart="onDragStart(bi, $event)" @dragend="onDragEnd"
             @dragover.prevent="onDragOver(bi)" @drop.prevent="onDrop(bi)">
          <div class="wb-block-head">
            <span class="drag-handle" title="拖动排序">⠿</span>
            <span class="wb-type-tag q">题目</span>
            <b class="wb-q-no">{{ questionNo(bi) }}</b>
            <span class="wb-q-preview">{{ questionPreview(blk) }}</span>
            <span class="flex-gap" />
            <el-button size="small" type="primary" link @click="emit('open-question', blk.question_id)">编辑</el-button>
            <el-button size="small" text @click="moveBlock(bi, -1)" :disabled="bi === 0">↑</el-button>
            <el-button size="small" text @click="moveBlock(bi, 1)" :disabled="bi === blocks.length - 1">↓</el-button>
            <el-button size="small" text type="danger" @click="removeBlock(bi, blk)">✖</el-button>
          </div>
        </div>

        <!-- 说明文字 / 自定义内容 -->
        <div v-else-if="blk.type === 'custom_text'" class="wb-block wb-custom"
             :class="{ dragging: dragIndex === bi }"
             draggable="true" @dragstart="onDragStart(bi, $event)" @dragend="onDragEnd"
             @dragover.prevent="onDragOver(bi)" @drop.prevent="onDrop(bi)">
          <div class="wb-block-head">
            <span class="drag-handle" title="拖动排序">⠿</span>
            <span class="wb-type-tag c">说明</span>
            <span class="wb-custom-label">说明文字 / 自定义内容</span>
            <span class="flex-gap" />
            <el-button size="small" text @click="moveBlock(bi, -1)" :disabled="bi === 0">↑</el-button>
            <el-button size="small" text @click="moveBlock(bi, 1)" :disabled="bi === blocks.length - 1">↓</el-button>
            <el-button size="small" text type="danger" @click="removeBlock(bi, blk)">✖</el-button>
          </div>
          <div class="wb-custom-body">
            <div class="wb-richtool">
              <el-button size="small" text @mousedown.prevent="exec('bold')"><b>B</b></el-button>
              <el-button size="small" text @mousedown.prevent="exec('italic')"><i>I</i></el-button>
              <el-button size="small" text @mousedown.prevent="exec('underline')"><u>U</u></el-button>
              <el-select size="small" style="width:92px" :model-value="'normal'" @change="v => exec('formatBlock', v)">
                <el-option label="正文" value="normal" />
                <el-option label="标题1" value="h1" />
                <el-option label="标题2" value="h2" />
                <el-option label="标题3" value="h3" />
              </el-select>
              <el-button size="small" text @mousedown.prevent="exec('justifyLeft')">左</el-button>
              <el-button size="small" text @mousedown.prevent="exec('justifyCenter')">中</el-button>
              <el-button size="small" text @mousedown.prevent="exec('justifyRight')">右</el-button>
              <el-button size="small" @mousedown.prevent="pickImage(bi)"><el-icon><Picture /></el-icon> 图片</el-button>
              <el-button size="small" text @mousedown.prevent="exec('removeFormat')">清除格式</el-button>
            </div>
            <div class="wb-editable" contenteditable="true" spellcheck="false"
                 :data-bi="bi" :innerHTML="displayHtml(blk.html)"
                 @input="onCustomInput(bi, $event)"></div>
          </div>
        </div>

        <!-- 空白 -->
        <div v-else-if="blk.type === 'spacer'" class="wb-block wb-spacer"
             :class="{ dragging: dragIndex === bi }"
             draggable="true" @dragstart="onDragStart(bi, $event)" @dragend="onDragEnd"
             @dragover.prevent="onDragOver(bi)" @drop.prevent="onDrop(bi)">
          <div class="wb-block-head">
            <span class="drag-handle" title="拖动排序">⠿</span>
            <span class="wb-type-tag sp">空白</span>
            <span>高度</span>
            <el-input-number v-model="blk.height" size="small" :min="8" :max="200" :step="4"
                             controls-position="right" style="width:110px" @change="touch(blk, bi)" />
            <span class="wb-px">px</span>
            <el-radio-group v-model="blk.height" size="small" @change="touch(blk, bi)">
              <el-radio-button :label="12">小</el-radio-button>
              <el-radio-button :label="24">中</el-radio-button>
              <el-radio-button :label="48">大</el-radio-button>
            </el-radio-group>
            <span class="flex-gap" />
            <el-button size="small" text @click="moveBlock(bi, -1)" :disabled="bi === 0">↑</el-button>
            <el-button size="small" text @click="moveBlock(bi, 1)" :disabled="bi === blocks.length - 1">↓</el-button>
            <el-button size="small" text type="danger" @click="removeBlock(bi, blk)">✖</el-button>
          </div>
          <div class="wb-spacer-preview" :style="{ height: blk.height + 'px' }"></div>
        </div>

        <!-- 分页符 -->
        <div v-else-if="blk.type === 'page_break'" class="wb-block wb-pagebreak"
             :class="{ dragging: dragIndex === bi }"
             draggable="true" @dragstart="onDragStart(bi, $event)" @dragend="onDragEnd"
             @dragover.prevent="onDragOver(bi)" @drop.prevent="onDrop(bi)">
          <div class="wb-block-head">
            <span class="drag-handle" title="拖动排序">⠿</span>
            <span class="wb-type-tag pb">分页符</span>
            <span class="wb-pb-label">此后的内容从新一页开始</span>
            <span class="flex-gap" />
            <el-button size="small" text @click="moveBlock(bi, -1)" :disabled="bi === 0">↑</el-button>
            <el-button size="small" text @click="moveBlock(bi, 1)" :disabled="bi === blocks.length - 1">↓</el-button>
            <el-button size="small" text type="danger" @click="removeBlock(bi, blk)">✖</el-button>
          </div>
          <div class="wb-pb-rule"></div>
        </div>
      </template>
      <div v-if="dropBefore === blocks.length" class="wb-drop-line"></div>
      <el-empty v-if="!blocks.length" description="整册为空：点击上方「在开头插入…」添加小节或内容" :image-size="60" />
    </div>

    <div class="wb-insert">
      <el-dropdown trigger="click" @command="c => insertAt(blocks.length, c)">
        <el-button size="small" type="primary" plain>＋ 在末尾插入…</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="subtitle">小标题（小节）</el-dropdown-item>
            <el-dropdown-item command="custom_text">说明文字 / 自定义内容</el-dropdown-item>
            <el-dropdown-item command="spacer">空白</el-dropdown-item>
            <el-dropdown-item command="page_break">分页符</el-dropdown-item>
            <el-dropdown-item command="question" divided>题目（从题库添加）</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { ElMessageBox } from 'element-plus'

const props = defineProps({
  practiceId: { type: String, required: true },
  sections: { type: Array, default: () => [] },
  layout: { type: Array, default: () => [] },
  title: { type: String, default: '' },
})
const emit = defineEmits(['update:title', 'open-question', 'insert-question', 'change', 'remove-question', 'pick-image'])

// 本地块列表：与父级 layout 同步
const blocks = ref(JSON.parse(JSON.stringify(props.layout || [])))
watch(() => props.layout, val => {
  blocks.value = JSON.parse(JSON.stringify(val || []))
}, { deep: true })

const editingId = ref(null)
const dragIndex = ref(null)
const dropBefore = ref(null)

const uid = () => 'wb_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7)

// 计算小节序号 / 题目整册序号
const sectionLabel = (n) => ['一','二','三','四','五','六','七','八','九','十','十一','十二'][n - 1] || String(n)
const subIndex = (bi) => blocks.value.slice(0, bi + 1).filter(b => b.type === 'subtitle').length
const questionNo = (bi) => blocks.value.slice(0, bi + 1).filter(b => b.type === 'question_ref').length

// 题目预览（从 sections 里找）
const questionMap = computed(() => {
  const m = {}
  for (const s of props.sections || []) for (const q of s.questions || []) m[q.id] = q
  return m
})
const questionPreview = (blk) => {
  const q = questionMap.value[blk.question_id]
  if (!q) return '(题目已被删除)'
  return (q.content || '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '[图]').replace(/\$\$[^$]*\$\$|\$[^$\n]*\$/g, '[公式]').slice(0, 40)
}

// ---- 块操作 ----
const commit = () => emit('change', JSON.parse(JSON.stringify(blocks.value)))

const insertAt = (index, type) => {
  if (type === 'question') { emit('insert-question', index); return }
  const blk = { type, id: uid() }
  if (type === 'subtitle') {
    blk.title = '新小节'; blk.show_title = true; blk.start_on_new_page = false
  } else if (type === 'custom_text') {
    blk.html = '<p></p>'; blk.align = 'left'
  } else if (type === 'spacer') {
    blk.height = 24
  }
  blocks.value.splice(index, 0, blk)
  commit()
}
const touch = (blk, bi) => { blk._t = Date.now(); commit() }
const moveBlock = (bi, dir) => {
  const to = bi + dir
  if (to < 0 || to >= blocks.value.length) return
  const arr = blocks.value
  ;[arr[bi], arr[to]] = [arr[to], arr[bi]]
  commit()
}
const removeBlock = async (bi, blk) => {
  if (blk.type === 'subtitle') {
    // 统计其下直到下一小节前的题目/内容
    let under = 0, untilNext = false
    for (let i = bi + 1; i < blocks.value.length; i++) {
      if (blocks.value[i].type === 'subtitle') break
      if (blocks.value[i].type === 'question_ref') under++
    }
    const hint = under ? `（含其下 ${under} 题，将并入前一小节）` : ''
    await ElMessageBox.confirm(`删除小节“${blk.title || ''}”${hint}？`, '提示', { type: 'warning' })
  } else if (blk.type === 'question_ref') {
    const q = questionMap.value[blk.question_id]
    await ElMessageBox.confirm(`从整册中删除第 ${questionNo(bi)} 题？${q ? '该题将同时从练习中删除。' : ''}`, '提示', { type: 'warning' })
    // 题目删除走父级（调用后端删除接口，保证题库快照一并清理）
    emit('remove-question', blk.question_id)
    return
  } else {
    await ElMessageBox.confirm('删除该块？', '提示', { type: 'warning' })
  }
  blocks.value.splice(bi, 1)
  commit()
}

// ---- 拖动排序 ----
const onDragStart = (bi, e) => {
  dragIndex.value = bi
  e.dataTransfer.effectAllowed = 'move'
  try { e.dataTransfer.setData('text/plain', String(bi)) } catch {}
}
const onDragEnd = () => { dragIndex.value = null; dropBefore.value = null }
const onDragOver = (bi) => { if (dragIndex.value !== null) dropBefore.value = bi }
const onDrop = (bi) => {
  const from = dragIndex.value
  let to = dropBefore.value
  if (from === null) return
  if (from < to) to--
  const arr = JSON.parse(JSON.stringify(blocks.value))
  const [item] = arr.splice(from, 1)
  arr.splice(to, 0, item)
  blocks.value = arr
  dragIndex.value = null; dropBefore.value = null
  commit()
}

// ---- 说明文字富文本 ----
const toDisplay = (html) => (html || '').replace(/asset:\/\/practice\//g,
  `/api/practices/${props.practiceId}/assets/`)
const toStore = (html) => (html || '').replace(new RegExp(`/api/practices/${props.practiceId}/assets/`, 'g'),
  'asset://practice/')
const displayHtml = (html) => toDisplay(html)
const onCustomInput = (bi, e) => {
  const el = e.target
  blocks.value[bi].html = toStore(el.innerHTML)
  commit()
}
const exec = (cmd, val) => {
  document.execCommand(cmd, false, val || null)
  // 触发一次 input 以同步内容
  const el = document.activeElement
  if (el && el.classList.contains('wb-editable')) el.dispatchEvent(new Event('input', { bubbles: true }))
}
const pickImage = (bi) => {
  // 用父级图片选择器（复用资产列表）
  emit('pick-image', bi)
}
const titleChanged = (e) => { emit('update:title', e.target.value.trim()) }
const onTitleChange = (e) => titleChanged(e)

defineExpose({ toDisplay, toStore, insertImageAt })
function insertImageAt(bi, resolvedSrc) {
  const el = document.querySelector(`.wb-editable[data-bi="${bi}"]`)
  if (!el) return
  el.focus()
  document.execCommand('insertHTML', false, `<img src="${resolvedSrc}" style="max-width:100%">`)
  blocks.value[bi].html = toStore(el.innerHTML)
  commit()
}
</script>

<style scoped>
.wb-canvas { max-width: 780px; margin: 0 auto; }
.wb-title-row { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #fff;
  border: 1px solid #ebeef5; border-radius: 6px; margin-bottom: 10px; }
.wb-label { font-weight: bold; font-size: 13px; color: #303133; flex-shrink: 0; }
.wb-title-input { flex: 1; border: none; outline: none; font-size: 16px; font-weight: bold;
  background: transparent; color: #303133; }
.wb-title-input:focus { border-bottom: 1px dashed #409eff; }
.wb-insert { margin: 8px 0; text-align: center; }
.wb-blocks { display: flex; flex-direction: column; gap: 8px; }
.wb-block { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; }
.wb-block.dragging { opacity: .5; }
.wb-drop-line { height: 3px; background: #409eff; border-radius: 2px; margin: -1px 4px; }
.wb-block-head { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-bottom: 1px solid #f0f2f5; }
.drag-handle { cursor: grab; color: #c0c4cc; font-size: 14px; user-select: none; }
.wb-type-tag { font-size: 11px; padding: 1px 6px; border-radius: 3px; color: #fff; flex-shrink: 0; }
.wb-type-tag.sub { background: #67c23a; }
.wb-type-tag.q { background: #409eff; }
.wb-type-tag.c { background: #e6a23c; }
.wb-type-tag.sp { background: #909399; }
.wb-type-tag.pb { background: #f56c6c; }
.flex-gap { flex: 1; }
.wb-sub-no { color: #67c23a; flex-shrink: 0; }
.wb-sub-title { cursor: pointer; font-weight: bold; font-size: 14px; }
.wb-sub-title:hover { color: #409eff; }
.wb-inline-input { border: 1px solid #409eff; border-radius: 4px; padding: 2px 6px; font-size: 14px; outline: none; }
.wb-q-no { color: #409eff; flex-shrink: 0; }
.wb-q-preview { color: #606266; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
.wb-custom-body { padding: 8px; }
.wb-richtool { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px dashed #ebeef5; }
.wb-richtool .el-button { padding: 0 6px; }
.wb-editable { min-height: 48px; padding: 8px; border: 1px solid #ebeef5; border-radius: 4px;
  outline: none; line-height: 1.7; }
.wb-editable:focus { border-color: #409eff; }
.wb-editable img { max-width: 100%; }
.wb-custom-label { color: #909399; font-size: 12px; }
.wb-spacer-preview { background: repeating-linear-gradient(45deg, #f5f7fa, #f5f7fa 6px, #e4e7ed 6px, #e4e7ed 12px);
  border: 1px dashed #dcdfe6; border-radius: 4px; margin: 6px 8px; }
.wb-px { color: #909399; font-size: 12px; }
.wb-pb-label { color: #f56c6c; font-size: 12px; }
.wb-pb-rule { border-top: 2px dashed #f56c6c; margin: 6px 8px; position: relative; }
.wb-pb-rule::after { content: '分页'; position: absolute; right: 8px; top: -8px; background: #fff;
  color: #f56c6c; font-size: 11px; padding: 0 4px; }
</style>
