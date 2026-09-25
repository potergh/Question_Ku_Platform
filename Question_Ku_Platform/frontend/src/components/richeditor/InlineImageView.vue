<!-- 行内图片节点视图：选项/段落内的小图。
     与块级图 BlockImageView 对齐的工具栏（宽度/替换/上传/删除）+ 右下角拖拽缩放手柄；
     区别：行内图只调宽度、保持行内流式，不参与并排/整行缩放与对齐。 -->
<template>
  <node-view-wrapper as="span" class="qre-inline-img-wrap" :data-selected="selected || undefined">
    <img
      v-if="!loadError"
      ref="imgEl"
      :src="imgSrc"
      :style="imgStyle"
      class="qre-inline-img"
      @error="loadError = true"
    />
    <span v-else class="qre-inline-img-missing">⚠图缺</span>
    <!-- 选中时显示右下角缩放手柄：水平拖拽改宽度（百分比） -->
    <span v-if="selected && !loadError" class="qre-inline-img-handle" @mousedown.stop.prevent="startResize"></span>
    <!-- 选中时工具条：fixed 定位钳制在视口内，与块级图一致 -->
    <div ref="toolEl" v-show="selected && !loadError" class="qre-inline-img-tools" contenteditable="false" :style="toolPos">
      <el-select :model-value="widthDisplay" size="small" style="width:88px" :teleported="false"
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
import { computed, nextTick, ref, watch } from 'vue'
import { NodeViewWrapper } from '@tiptap/vue-3'
import axios from 'axios'
import { resolveAssetSrc } from './assets'

const WIDTH_PRESETS = [25, 40, 50, 60, 75, 80, 90, 100]

const props = defineProps({
  node: Object, editor: Object, selected: Boolean,
  updateAttributes: Function, deleteNode: Function,
})

const imgEl = ref(null)
const fileInput = ref(null)
const toolEl = ref(null)
const toolPos = ref({})
const loadError = ref(false)
watch(() => props.node.attrs.src, () => { loadError.value = false })

const imgSrc = computed(() =>
  resolveAssetSrc(props.node.attrs.src, props.editor.storage.qre?.practiceId))

// 有 width（百分比）按宽度铺、高度自适应且解除高度钳制（与 PDF 一致）；无 width 走 CSS 默认小图
const imgStyle = computed(() => {
  const w = props.node.attrs.width
  if (!w) return {}
  const pct = typeof w === 'string' && w.endsWith('%') ? w : `${w}%`
  return { width: pct, maxWidth: '100%', maxHeight: 'none', height: 'auto', verticalAlign: 'middle' }
})

// ---------- 工具条定位：fixed + 视口钳制（同块级图，避免窄列里被裁剪） ----------
const positionTool = () => {
  const host = imgEl.value?.closest('.qre-inline-img-wrap')
  const t = toolEl.value
  if (!host || !t) return
  const r = host.getBoundingClientRect()
  const tw = t.offsetWidth || 240
  const th = t.offsetHeight || 32
  const vw = window.innerWidth || 1200
  const left = Math.min(Math.max(r.left, 6), vw - tw - 6)
  let top = r.top - th - 6
  if (top < 6) top = r.bottom + 6
  toolPos.value = { left: left + 'px', top: top + 'px' }
}
watch(() => props.selected, (v) => {
  if (v) {
    nextTick(positionTool)
    window.addEventListener('scroll', positionTool, true)
    window.addEventListener('resize', positionTool)
  } else {
    window.removeEventListener('scroll', positionTool, true)
    window.removeEventListener('resize', positionTool)
  }
})

// ---------- 宽度下拉（与块级图一致） ----------
const widthDisplay = computed(() => {
  const w = props.node.attrs.width
  if (!w || w === 'fit') return 'fit'
  if (typeof w === 'number') return w
  if (typeof w === 'string' && w.endsWith('%')) return parseFloat(w)
  return 'fit'
})
const customWidthOption = computed(() => {
  const w = widthDisplay.value
  return (typeof w === 'number' && !WIDTH_PRESETS.includes(w)) ? w : null
})
const onWidthChange = (v) => {
  props.updateAttributes({ width: v === 'fit' ? null : v })
}

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

// ---------- 拖拽缩放：水平拖动量折算为「占行宽百分比」，范围 5~100 ----------
const startResize = (e) => {
  e.preventDefault()
  const startX = e.clientX
  const startW = imgEl.value?.offsetWidth || 60
  const containerW = props.editor.view.dom.closest('.qre-prosemirror')?.offsetWidth || 600
  const onMove = (ev) => {
    const delta = ev.clientX - startX
    const pct = Math.round(Math.max(5, startW + delta) / containerW * 100)
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
