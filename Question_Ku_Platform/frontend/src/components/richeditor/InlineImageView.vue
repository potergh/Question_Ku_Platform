<!-- 行内图片节点视图：选项/段落内的小图，选中后右下角出现拖拽缩放手柄。
     与块级图 BlockImageView 的区别：只调宽度、保持行内流式（不参与并排/整行缩放）。 -->
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
  </node-view-wrapper>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { NodeViewWrapper } from '@tiptap/vue-3'
import { resolveAssetSrc } from './assets'

const props = defineProps({
  node: Object, editor: Object, selected: Boolean,
  updateAttributes: Function, deleteNode: Function,
})

const imgEl = ref(null)
const loadError = ref(false)
watch(() => props.node.attrs.src, () => { loadError.value = false })

const imgSrc = computed(() =>
  resolveAssetSrc(props.node.attrs.src, props.editor.storage.qre?.practiceId))

// 有 width（百分比）按宽度铺、高度自适应；无 width 走 CSS 默认小图（height:1.5em）
const imgStyle = computed(() => {
  const w = props.node.attrs.width
  if (!w) return {}
  const pct = typeof w === 'string' && w.endsWith('%') ? w : `${w}%`
  return { width: pct, maxWidth: '100%', height: 'auto', verticalAlign: 'middle' }
})

// 拖拽缩放：水平拖动量折算为「占行宽百分比」，范围 5~100（与块图单图缩放一致）
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
