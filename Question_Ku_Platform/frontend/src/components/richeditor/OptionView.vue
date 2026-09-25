<!-- 选项节点视图：标签（系统管理、自动编号）+ 连续正文 -->
<template>
  <node-view-wrapper as="div" class="qre-option" :data-selected="selected || undefined">
    <span class="qre-option-label" contenteditable="false">{{ node.attrs.label }}.</span>
    <node-view-content as="span" class="qre-option-content" />
  </node-view-wrapper>
</template>

<script setup>
import { NodeViewWrapper, NodeViewContent } from '@tiptap/vue-3'

defineProps({ node: Object, selected: Boolean })
</script>
