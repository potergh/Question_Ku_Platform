<!-- 答题留白节点视图：纯空白行（无横线，用户决策 2026-08-30）+ 悬停行数控制 -->
<template>
  <node-view-wrapper as="div" class="qre-space">
    <div v-for="i in rows" :key="i" class="qre-space-line"></div>
    <div v-if="!rows" class="qre-space-zero">（无留白）</div>
    <div class="qre-space-tools" contenteditable="false">
      <el-select :model-value="rows" size="small" style="width:112px" :teleported="false"
                 @change="v => updateAttributes({ rows: Number(v) })">
        <el-option label="无留白" :value="0" /><el-option label="小（2 行）" :value="2" />
        <el-option label="中（4 行）" :value="4" /><el-option label="大（8 行）" :value="8" />
        <el-option label="超大（12 行）" :value="12" />
      </el-select>
    </div>
  </node-view-wrapper>
</template>

<script setup>
import { computed } from 'vue'
import { NodeViewWrapper } from '@tiptap/vue-3'

const props = defineProps({ node: Object, updateAttributes: Function })
const rows = computed(() => props.node.attrs.rows ?? 4)
</script>
