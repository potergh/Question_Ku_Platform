<template>
  <div class="tags-view">
    <div class="tags-header">
      <h2>标签管理</h2>
      <p class="subtitle">管理知识点、技能、错因等标签体系</p>
    </div>

    <el-row :gutter="16">
      <!-- Left: Tag Tree by Category -->
      <el-col :span="10">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>标签体系</span>
              <el-button type="primary" size="small" @click="showCreateDialog = true">
                <el-icon><Plus /></el-icon> 新增
              </el-button>
            </div>
          </template>

          <el-tabs v-model="activeCategory">
            <el-tab-pane label="知识点" name="knowledge" />
            <el-tab-pane label="技能" name="skill" />
            <el-tab-pane label="错因" name="error_type" />
            <el-tab-pane label="自定义" name="custom" />
          </el-tabs>

          <el-tree
            :data="filteredTree"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            highlight-current
            @node-click="onTagSelect"
            default-expand-all
          >
            <template #default="{ node, data }">
              <div class="tree-node">
                <span>{{ data.name }}</span>
                <span class="tree-actions">
                  <el-button text size="small" @click.stop="editTag(data)">编辑</el-button>
                  <el-button text type="danger" size="small" @click.stop="deleteTag(data)">删除</el-button>
                </span>
              </div>
            </template>
          </el-tree>

          <el-empty v-if="filteredTree.length === 0" description="该分类暂无标签" :image-size="50" />
        </el-card>
      </el-col>

      <!-- Right: Tag Details -->
      <el-col :span="14">
        <el-card v-if="selectedTag">
          <template #header>
            <span>{{ selectedTag.name }}</span>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="名称">{{ selectedTag.name }}</el-descriptions-item>
            <el-descriptions-item label="分类">{{ categoryText(selectedTag.category) }}</el-descriptions-item>
            <el-descriptions-item label="颜色">
              <el-tag v-if="selectedTag.color" :color="selectedTag.color" effect="dark" size="small">示例</el-tag>
              <span v-else style="color: #909399;">默认</span>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
        <el-card v-else>
          <el-empty description="选择左侧标签查看详情" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="showCreateDialog" :title="editingTag ? '编辑标签' : '新增标签'" width="400px">
      <el-form @submit.prevent="saveTag">
        <el-form-item label="名称">
          <el-input v-model="tagForm.name" placeholder="标签名称" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="tagForm.category" :disabled="!!editingTag">
            <el-option label="知识点" value="knowledge" />
            <el-option label="技能" value="skill" />
            <el-option label="错因" value="error_type" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="父标签（可选）">
          <el-select v-model="tagForm.parent_id" clearable placeholder="无父级">
            <el-option
              v-for="t in tags.filter(t => t.category === tagForm.category && t.id !== editingTag?.id)"
              :key="t.id"
              :label="t.name"
              :value="t.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色（可选）">
          <el-color-picker v-model="tagForm.color" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false; editingTag = null">取消</el-button>
        <el-button type="primary" @click="saveTag" :disabled="!tagForm.name">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const tags = ref([])
const tagTree = ref([])
const activeCategory = ref('knowledge')
const selectedTag = ref(null)
const showCreateDialog = ref(false)
const editingTag = ref(null)
const tagForm = reactive({ name: '', category: 'knowledge', parent_id: null, color: null })

const loadTags = async () => {
  try {
    const [listRes, treeRes] = await Promise.all([
      axios.get('/api/tags'),
      axios.get('/api/tags/tree'),
    ])
    tags.value = listRes.data
    tagTree.value = treeRes.data
  } catch (e) {
    console.error('Failed to load tags:', e)
  }
}

const filteredTree = computed(() => {
  return tagTree.value.filter(t => t.category === activeCategory.value)
})

const onTagSelect = (data) => {
  selectedTag.value = data
}

const editTag = (tag) => {
  editingTag.value = tag
  tagForm.name = tag.name
  tagForm.category = tag.category
  tagForm.parent_id = tag.parent_id
  tagForm.color = tag.color
  showCreateDialog.value = true
}

const saveTag = async () => {
  try {
    if (editingTag.value) {
      await axios.put(`/api/tags/${editingTag.value.id}`, { ...tagForm })
      ElMessage.success('标签已更新')
    } else {
      await axios.post('/api/tags', { ...tagForm })
      ElMessage.success('标签已创建')
    }
    showCreateDialog.value = false
    editingTag.value = null
    tagForm.name = ''
    tagForm.category = activeCategory.value
    tagForm.parent_id = null
    tagForm.color = null
    loadTags()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const deleteTag = async (tag) => {
  try {
    await ElMessageBox.confirm(`确定删除标签"${tag.name}"？子标签也会一并删除。`, '警告', { type: 'warning' })
    await axios.delete(`/api/tags/${tag.id}`)
    ElMessage.success('已删除')
    if (selectedTag.value?.id === tag.id) selectedTag.value = null
    loadTags()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

const categoryText = (c) => ({ knowledge: '知识点', skill: '技能', error_type: '错因', custom: '自定义' })[c] || c

onMounted(() => {
  loadTags()
})
</script>

<style scoped>
.tags-view { max-width: 1000px; margin: 0 auto; }
.tags-header { margin-bottom: 16px; }
.subtitle { color: #909399; margin-top: 4px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }

.tree-node {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding-right: 8px;
}

.tree-actions {
  opacity: 0;
  transition: opacity 0.2s;
}

.tree-node:hover .tree-actions {
  opacity: 1;
}
</style>
