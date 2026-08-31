<!-- 块级图片节点视图：渲染 + 工具条 + 拖拽缩放控制点 + 排版切换（阶段 4） -->
<!-- 工具条使用 position:fixed 并钳制在视口内，避免并排窄节点下被裁剪/遮挡（阶段 4 修复） -->
<template>
  <node-view-wrapper as="div" class="qre-img" :class="alignCls" :style="nodeViewStyle"
    :data-layout="node.attrs.layout || 'row'"
    :data-selected="selected || undefined">
    <div class="qre-img-wrap">
      <img v-if="!loadError" ref="imgEl" :src="imgSrc" :style="imgStyle" @error="loadError = true" />
      <div v-else class="qre-img-missing">⚠ 图片缺失</div>
      <!-- 选中时显示右下角缩放手柄：并排时调整行整体高度，单图/独占时调宽度 -->
      <div v-if="selected && !loadError" class="qre-img-handle" @mousedown.stop.prevent="startResize"></div>
    </div>
    <div ref="toolEl" v-show="selected" class="qre-img-tools" contenteditable="false" :style="toolPos">
      <!-- 排版切换：并排 / 独占（阶段 4） -->
      <el-button size="small" text @click="toggleLayout">
        {{ (node.attrs.layout || 'row') === 'row' ? '⇋独占' : '⇆并排' }}
      </el-button>
      <el-select v-if="!inRow" :model-value="node.attrs.align || 'center'" size="small" style="width:76px" :teleported="false"
                 @change="v => updateAttributes({ align: v })">
        <el-option label="左对齐" value="left" /><el-option label="居中" value="center" /><el-option label="右对齐" value="right" />
      </el-select>
      <!-- 宽度（独占/单图）：适应内容 或任意百分比（拖拽缩放后出现的非预设值动态补一项） -->
      <el-select v-if="!inRow" :model-value="widthDisplay" size="small" style="width:88px" :teleported="false"
                 @change="v => onWidthChange(v)">
        <el-option label="适应内容" value="fit" />
        <el-option v-if="customWidthOption" :label="`${customWidthOption}%`" :value="customWidthOption" />
        <el-option v-for="p in WIDTH_PRESETS" :key="p" :label="`${p}%`" :value="p" />
      </el-select>
      <!-- 并排整体缩放（阶段 4）：整行等比例缩放（首图左偏移居中），拖拽/预设均可 -->
      <el-select v-if="inRow" :model-value="scaleDisplay" size="small" style="width:88px" :teleported="false"
                 @change="v => onScaleChange(v)">
        <el-option v-if="customScaleOption" :label="`${customScaleOption}%`" :value="customScaleOption" />
        <el-option v-for="p in SCALE_PRESETS" :key="p" :label="`${p}%`" :value="p" />
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
const SCALE_PRESETS = [25, 40, 50, 60, 75, 80, 100]

const props = defineProps({ node: Object, editor: Object, selected: Boolean,
  updateAttributes: Function, deleteNode: Function })

const imgEl = ref(null)
const fileInput = ref(null)
const loadError = ref(false)
const toolEl = ref(null)
const toolPos = ref({})

// src 变化时重置加载错误状态
watch(() => props.node.attrs.src, () => { loadError.value = false })

// ---------- 工具条：仅选中图片显示（点击选中后出现，其他图片不显示），fixed + 视口钳制 ----------
const positionTool = () => {
  const host = imgEl.value?.closest('.qre-img')
  const t = toolEl.value
  if (!host || !t) return
  const r = host.getBoundingClientRect()
  const tw = t.offsetWidth || 280
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

// 计算当前图片所在的连续 row 组（数量 + 节点位置），用于等宽分配与整行缩放
const rowGroup = computed(() => {
  const doc = props.editor.state.doc
  let myPos = -1
  let myNode = null
  doc.descendants((node, pos) => {
    if (myPos >= 0) return false
    if (node.type.name === 'image' && node.attrs.src === props.node.attrs.src) {
      if (!myNode) { myNode = node; myPos = pos }
    }
  })
  const empty = { count: 1, positions: [] }
  if (myPos < 0 || (props.node.attrs.layout || 'row') !== 'row') return empty
  const positions = []
  // 向前收集连续 row 图片
  let pos = myPos
  while (pos > 0) {
    const resolved = doc.resolve(pos)
    const parent = resolved.parent
    const idx = resolved.index()
    if (idx === 0) break
    const prev = parent.child(idx - 1)
    if (prev.type.name === 'image' && (prev.attrs.layout || 'row') === 'row') {
      positions.unshift(pos - prev.nodeSize)
      pos -= prev.nodeSize
    } else break
  }
  positions.push(myPos)
  // 向后收集连续 row 图片（用累计 nodeSize 求后续兄弟节点位置）
  const resolved = doc.resolve(myPos)
  const parent = resolved.parent
  const startIdx = resolved.index()
  let nextPos = myPos
  for (let i = startIdx + 1; i < parent.childCount; i++) {
    nextPos += parent.child(i - 1).nodeSize
    const child = parent.child(i)
    if (child.type.name === 'image' && (child.attrs.layout || 'row') === 'row') positions.push(nextPos)
    else break
  }
  return { count: positions.length, positions, index: positions.indexOf(myPos) }
})
const rowImageCount = computed(() => rowGroup.value.count)
// 是否处于并排组中（多图 row）：此时隐藏宽度/对齐，改由整行缩放控制
const inRow = computed(() => (props.node.attrs.layout || 'row') === 'row' && rowImageCount.value > 1)

// 整行缩放（并排）：数字 = 占行宽百分比，null = 100 铺满整行
const scaleDisplay = computed(() => props.node.attrs.scale || 100)
const customScaleOption = computed(() => {
  const s = scaleDisplay.value
  return (typeof s === 'number' && !SCALE_PRESETS.includes(s)) ? s : null
})
const onScaleChange = (v) => {
  const val = v >= 100 ? null : v
  if (inRow.value) patchRowImages({ scale: val })   // 并排：整行一起缩放
  else props.updateAttributes({ scale: val })
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

const imgSrc = computed(() => resolveAssetSrc(props.node.attrs.src, props.editor.storage.qre?.practiceId))
const alignCls = computed(() => ({
  'is-left': (props.node.attrs.align || 'center') === 'left',
  'is-center': (props.node.attrs.align || 'center') === 'center',
  'is-right': props.node.attrs.align === 'right',
}))
const nodeViewStyle = computed(() => {
  // 并排(row)时：节点视图占容器宽度的 scale/N %（整行总宽 = scale%，方案 A 整行等比缩放）；
  // 首图加左偏移 (100-scale)/2 %，使缩放后的整行在容器内居中
  const layout = props.node.attrs.layout || 'row'
  const inRow = layout === 'row' && rowImageCount.value > 1
  if (!inRow) return {}
  const scale = props.node.attrs.scale || 100
  const style = { width: ((scale / 100) * 100 / rowImageCount.value).toFixed(2) + '%' }
  if (rowGroup.value.index === 0) {
    style.marginLeft = ((100 - scale) / 2).toFixed(2) + '%'
  }
  return style
})

const imgStyle = computed(() => {
  const layout = props.node.attrs.layout || 'row'
  const inRow = layout === 'row' && rowImageCount.value > 1
  const w = props.node.attrs.width
  if (inRow) {
    // 并排：图片填满等宽 wrapper（整行缩放由节点宽度 scale/N% 控制，图片随节点等比缩放）
    return { width: '100%', height: 'auto', maxWidth: 'none', maxHeight: 'none' }
  }
  if (layout === 'block') {
    // 独占纵向：默认铺满整行居中（在空白处拖动后期望"在中间铺满全部区域"）
    if (!w || w === 'fit') return { width: '100%', maxWidth: 'none', maxHeight: '8cm' }
    if (typeof w === 'number') return { width: w + '%', maxWidth: 'none', maxHeight: 'none' }
    if (typeof w === 'string' && w.endsWith('%')) return { width: w, maxWidth: 'none', maxHeight: 'none' }
  }
  if (!w || w === 'fit') return { width: 'auto', maxWidth: '50%', maxHeight: '8cm' }
  if (typeof w === 'number') return { width: w + '%', maxWidth: 'none', maxHeight: 'none' }
  if (typeof w === 'string' && w.endsWith('%')) return { width: w, maxWidth: 'none', maxHeight: 'none' }
  return { width: 'auto', maxWidth: '50%', maxHeight: '8cm' }
})

// 把补丁应用到当前图片所在的整行所有图片节点（等宽并排保持一致）
const patchRowImages = (patch) => {
  const { state, dispatch } = props.editor.view
  const doc = state.doc
  const positions = rowGroup.value.positions
  if (!positions.length) { props.updateAttributes(patch); return }
  let tr = state.tr
  for (const pos of positions) {
    const node = doc.nodeAt(pos)
    if (node && node.type.name === 'image') {
      tr = tr.setNodeMarkup(pos, null, { ...node.attrs, ...patch })
    }
  }
  dispatch(tr)
}

// 拖拽缩放：
// - 并排(row)时：水平拖拽整行等比例缩放（写 scale 百分比 20~100）
// - 单图/独占(block)时：按内容宽度百分比更新 width 属性
const startResize = (e) => {
  e.preventDefault()
  const inRow = (props.node.attrs.layout || 'row') === 'row' && rowImageCount.value > 1
  const startX = e.clientX
  const startY = e.clientY
  const startW = imgEl.value?.offsetWidth || 100
  const startH = imgEl.value?.offsetHeight || 100
  const containerW = props.editor.view.dom.closest('.qre-prosemirror')?.offsetWidth || 600

  const onMove = (ev) => {
    if (inRow) {
      const startScale = props.node.attrs.scale || 100
      const delta = ev.clientX - startX
      const newScale = Math.max(20, Math.min(100, Math.round(startScale + delta / containerW * 100)))
      patchRowImages({ scale: newScale >= 100 ? null : newScale })
    } else {
      const delta = ev.clientX - startX
      const pct = Math.round(Math.max(20, startW + delta) / containerW * 100)
      props.updateAttributes({ width: Math.max(5, Math.min(100, pct)) })
    }
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
</script>
