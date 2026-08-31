<!-- 块级图片节点视图：渲染 + 工具条 + 拖拽缩放控制点 + 排版切换（阶段 4） -->
<template>
  <node-view-wrapper as="div" class="qre-img" :class="alignCls"
    :data-layout="node.attrs.layout || 'row'"
    :data-selected="selected || undefined">
    <div class="qre-img-wrap">
      <img v-if="!loadError" ref="imgEl" :src="imgSrc" :style="imgStyle" @error="loadError = true" />
      <div v-else class="qre-img-missing">⚠ 图片缺失</div>
      <!-- 选中时显示右下角缩放手柄 -->
      <div v-if="selected && !loadError" class="qre-img-handle" @mousedown.stop.prevent="startResize"></div>
    </div>
    <div class="qre-img-tools" contenteditable="false">
      <!-- 排版切换：并排 / 独占（阶段 4） -->
      <el-button size="small" text @click="toggleLayout">
        {{ (node.attrs.layout || 'row') === 'row' ? '⇋独占' : '⇆并排' }}
      </el-button>
      <el-select :model-value="node.attrs.align || 'center'" size="small" style="width:92px" :teleported="false"
                 @change="v => updateAttributes({ align: v })">
        <el-option label="左对齐" value="left" /><el-option label="居中" value="center" /><el-option label="右对齐" value="right" />
      </el-select>
      <!-- 宽度：适应内容 或任意百分比（拖拽缩放后出现的非预设值动态补一项） -->
      <el-select :model-value="widthDisplay" size="small" style="width:112px" :teleported="false"
                 @change="v => onWidthChange(v)">
        <el-option label="适应内容" value="fit" />
        <el-option v-if="customWidthOption" :label="`${customWidthOption}%`" :value="customWidthOption" />
        <el-option v-for="p in WIDTH_PRESETS" :key="p" :label="`${p}%`" :value="p" />
      </el-select>
      <el-button size="small" text @click="requestReplace">替换</el-button>
      <el-button size="small" text @click="fileInput?.click()">上传</el-button>
      <el-button size="small" text type="danger" @click="deleteNode">删除</el-button>
      <input ref="fileInput" type="file" accept="image/*" style="display:none" @change="onUpload" />
    </div>
  </node-view-wrapper>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { NodeViewWrapper } from '@tiptap/vue-3'
import axios from 'axios'
import { resolveAssetSrc } from './assets'

const WIDTH_PRESETS = [25, 40, 50, 60, 75, 80, 90, 100]

const props = defineProps({ node: Object, editor: Object, selected: Boolean,
  updateAttributes: Function, deleteNode: Function })

const imgEl = ref(null)
const fileInput = ref(null)
const loadError = ref(false)

// src 变化时重置加载错误状态
watch(() => props.node.attrs.src, () => { loadError.value = false })

// 宽度展示：数字 = 百分比，'fit' = 适应内容
const widthDisplay = computed(() => {
  const w = props.node.attrs.width
  if (!w || w === 'fit') return 'fit'
  if (typeof w === 'number') return w
  if (typeof w === 'string' && w.endsWith('%')) return parseFloat(w)
  return 'fit'
})

// 当前宽度不在预设列表时，动态补一个选项（拖拽缩放产生的任意值）
const customWidthOption = computed(() => {
  const w = widthDisplay.value
  return (typeof w === 'number' && !WIDTH_PRESETS.includes(w)) ? w : null
})

const onWidthChange = (v) => {
  props.updateAttributes({ width: v === 'fit' ? null : v })
}

// 排版切换：row ↔ block（阶段 4）
const toggleLayout = () => {
  const cur = props.node.attrs.layout || 'row'
  props.updateAttributes({ layout: cur === 'row' ? 'block' : 'row' })
}

// 计算当前图片所在的连续 row 组大小（用于并排等宽分配）
const rowImageCount = computed(() => {
  const doc = props.editor.state.doc
  let myPos = -1
  let myNode = null
  doc.descendants((node, pos) => {
    if (myPos >= 0) return false
    if (node.type.name === 'image' && node.attrs.src === props.node.attrs.src) {
      // 用对象引用确认是同一个节点（避免同名 src 误匹配）
      if (!myNode) { myNode = node; myPos = pos }
    }
  })
  if (myPos < 0 || (props.node.attrs.layout || 'row') !== 'row') return 1

  let count = 1
  // 向前数连续 row 图片
  let pos = myPos
  while (pos > 0) {
    const resolved = doc.resolve(pos)
    const parent = resolved.parent
    const idx = resolved.index()
    if (idx === 0) break
    const prev = parent.child(idx - 1)
    if (prev.type.name === 'image' && (prev.attrs.layout || 'row') === 'row') {
      count++
      pos -= prev.nodeSize
    } else break
  }
  // 向后数连续 row 图片
  const resolved = doc.resolve(myPos)
  const parent = resolved.parent
  const startIdx = resolved.index()
  for (let i = startIdx + 1; i < parent.childCount; i++) {
    const child = parent.child(i)
    if (child.type.name === 'image' && (child.attrs.layout || 'row') === 'row') count++
    else break
  }
  return count
})

const requestReplace = () => {
  props.editor.storage.qre.onRequestReplaceImage?.(props.node.attrs.src)
}

const onUpload = async (e) => {
  const file = e.target.files?.[0]
  if (!file) return
  const pid = props.editor.storage.qre?.practiceId
  if (!pid) return
  const form = new FormData()
  form.append('file', file)
  try {
    const res = await axios.post(`/api/practices/${pid}/assets/upload`, form)
    props.updateAttributes({ src: `asset://practice/${res.data.name}` })
    loadError.value = false
  } catch (err) {
    console.error('upload failed', err)
  } finally {
    e.target.value = ''
  }
}

const imgSrc = computed(() => resolveAssetSrc(props.node.attrs.src, props.editor.storage.qre?.practiceId))
const alignCls = computed(() => ({
  'is-left': (props.node.attrs.align || 'center') === 'left',
  'is-center': (props.node.attrs.align || 'center') === 'center',
  'is-right': props.node.attrs.align === 'right',
}))
const imgStyle = computed(() => {
  const layout = props.node.attrs.layout || 'row'
  const inRow = layout === 'row' && rowImageCount.value > 1
  const w = props.node.attrs.width
  if (inRow) {
    // 并排：等宽分配容器，图片填满自身 wrapper
    const pct = (100 / rowImageCount.value).toFixed(2)
    return { width: pct + '%', maxWidth: 'none', maxHeight: 'none' }
  }
  if (!w || w === 'fit') return { width: 'auto', maxWidth: '50%', maxHeight: '8cm' }
  if (typeof w === 'number') return { width: w + '%', maxWidth: 'none', maxHeight: 'none' }
  if (typeof w === 'string' && w.endsWith('%')) return { width: w, maxWidth: 'none', maxHeight: 'none' }
  return { width: 'auto', maxWidth: '50%', maxHeight: '8cm' }
})

// 拖拽缩放：以编辑区内容宽度为基准，按比例更新 width 属性
const startResize = (e) => {
  e.preventDefault()
  const startX = e.clientX
  const startW = imgEl.value?.offsetWidth || 100
  const containerW = props.editor.view.dom.closest('.qre-prosemirror')?.offsetWidth || 600

  const onMove = (ev) => {
    const delta = ev.clientX - startX
    const pct = Math.round(Math.max(20, startW + delta) / containerW * 100)
    props.updateAttributes({ width: Math.max(5, Math.min(100, pct)) })
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
</script>
