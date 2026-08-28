<template>
  <div class="handout-view">
    <div class="handout-header">
      <h2>讲义编辑</h2>
      <p class="subtitle">选择题目，拖拽排序，导出 PDF 讲义</p>
    </div>

    <el-row :gutter="16">
      <!-- Left: Handout List -->
      <el-col :span="7">
        <el-card class="handout-list-card">
          <template #header>
            <div class="card-header">
              <span>我的讲义</span>
              <el-button type="primary" size="small" @click="showCreateDialog = true">
                <el-icon><Plus /></el-icon> 新建
              </el-button>
            </div>
          </template>
          <div
            v-for="h in handouts"
            :key="h.id"
            class="handout-item"
            :class="{ active: currentHandout?.id === h.id }"
            @click="selectHandout(h.id)"
          >
            <div class="h-title">{{ h.title }}</div>
            <div class="h-meta">
              <el-tag size="small" :type="h.status === 'exported' ? 'success' : 'info'">
                {{ h.items?.length || 0 }} 题
              </el-tag>
              <span class="h-status">{{ statusText(h.status) }}</span>
            </div>
          </div>
          <el-empty v-if="handouts.length === 0" description="暂无讲义" :image-size="60" />
        </el-card>
      </el-col>

      <!-- Right: Handout Editor -->
      <el-col :span="17">
        <el-card v-if="currentHandout" class="editor-card">
          <template #header>
            <div class="editor-header">
              <el-input
                v-model="currentHandout.title"
                style="width: 300px;"
                @blur="saveHandoutMeta"
              />
              <div class="editor-actions">
                <el-button @click="showAddDialog = true">
                  <el-icon><Plus /></el-icon> 添加题目
                </el-button>
                <el-button
                  type="primary"
                  @click="exportPdf"
                  :loading="exporting"
                  :disabled="!currentHandout.items?.length"
                >
                  <el-icon><Download /></el-icon> 导出 PDF
                </el-button>
              </div>
            </div>
          </template>

          <!-- Items (drag to reorder) -->
          <draggable
            v-model="currentHandout.items"
            item-key="id"
            handle=".drag-handle"
            @end="onReorder"
            class="items-list"
          >
            <template #item="{ element, index }">
              <div class="editor-item" :class="'type-' + element.item_type">
                <div class="drag-handle">
                  <el-icon><Rank /></el-icon>
                </div>
                <div class="item-content">
                  <div class="item-type-badge">
                    <el-tag size="small" :type="itemTypeTag(element.item_type)">
                      {{ itemTypeText(element.item_type) }}
                    </el-tag>
                    <span v-if="element.item_type === 'question' && element.question_snapshot" class="q-num">
                      第 {{ element.question_snapshot.question_number }} 题
                    </span>
                  </div>
                  <div class="item-preview" v-if="element.item_type === 'question' && element.question_snapshot">
                    {{ truncate(element.question_snapshot.content, 120) }}
                  </div>
                  <div class="item-preview" v-else-if="element.custom_content">
                    {{ truncate(element.custom_content, 120) }}
                  </div>
                </div>
                <div class="item-actions">
                  <el-button
                    v-if="element.item_type === 'question'"
                    text
                    size="small"
                    @click="toggleAnswer(element)"
                  >
                    {{ element.show_answer ? '隐藏答案' : '显示答案' }}
                  </el-button>
                  <el-button
                    text
                    type="danger"
                    size="small"
                    @click="removeItem(element.id)"
                  >
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
            </template>
          </draggable>

          <el-empty
            v-if="!currentHandout.items?.length"
            description="点击「添加题目」开始编辑讲义"
            :image-size="80"
          />
        </el-card>

        <el-card v-else class="no-selection">
          <el-empty description="选择或新建一个讲义开始编辑" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Create Handout Dialog -->
    <el-dialog v-model="showCreateDialog" title="新建讲义" width="400px">
      <el-form @submit.prevent="createHandout">
        <el-form-item label="标题">
          <el-input v-model="newHandoutTitle" placeholder="例：高二物理力学专题" />
        </el-form-item>
        <el-form-item label="学科">
          <el-select v-model="newHandoutSubject" placeholder="选择学科">
            <el-option label="物理" value="physics" />
            <el-option label="数学" value="math" />
            <el-option label="化学" value="chemistry" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createHandout" :disabled="!newHandoutTitle">创建</el-button>
      </template>
    </el-dialog>

    <!-- Add Question Dialog -->
    <el-dialog v-model="showAddDialog" title="添加题目到讲义" width="700px">
      <el-tabs v-model="addTab">
        <el-tab-pane label="从题库选择" name="questions">
          <el-table
            :data="availableQuestions"
            @selection-change="onQuestionSelect"
            height="400"
            size="small"
          >
            <el-table-column type="selection" width="40" />
            <el-table-column prop="question_number" label="#" width="50" />
            <el-table-column prop="question_type" label="题型" width="80" />
            <el-table-column label="内容">
              <template #default="{ row }">
                {{ truncate(row.content, 80) }}
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="添加标题" name="title">
          <el-input v-model="newSectionTitle" placeholder="例：一、力学基础" />
        </el-tab-pane>
        <el-tab-pane label="添加备注" name="note">
          <el-input
            v-model="newNoteContent"
            type="textarea"
            :rows="4"
            placeholder="知识点总结、教学备注..."
          />
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addSelectedItem">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import draggable from 'vuedraggable'

const handouts = ref([])
const currentHandout = ref(null)
const showCreateDialog = ref(false)
const showAddDialog = ref(false)
const newHandoutTitle = ref('')
const newHandoutSubject = ref('physics')
const exporting = ref(false)
const addTab = ref('questions')
const availableQuestions = ref([])
const selectedQuestions = ref([])
const newSectionTitle = ref('')
const newNoteContent = ref('')

const loadHandouts = async () => {
  try {
    const res = await axios.get('/api/handouts')
    handouts.value = res.data.handouts
  } catch (e) {
    console.error('Failed to load handouts:', e)
  }
}

const selectHandout = async (id) => {
  try {
    const res = await axios.get(`/api/handouts/${id}`)
    currentHandout.value = res.data
  } catch (e) {
    ElMessage.error('加载讲义失败')
  }
}

const createHandout = async () => {
  try {
    const res = await axios.post('/api/handouts', {
      title: newHandoutTitle.value,
      subject: newHandoutSubject.value,
    })
    handouts.value.unshift(res.data)
    currentHandout.value = res.data
    showCreateDialog.value = false
    newHandoutTitle.value = ''
    ElMessage.success('讲义已创建')
  } catch (e) {
    ElMessage.error('创建失败')
  }
}

const saveHandoutMeta = async () => {
  if (!currentHandout.value) return
  try {
    await axios.put(`/api/handouts/${currentHandout.value.id}`, {
      title: currentHandout.value.title,
    })
  } catch (e) { /* silent */ }
}

const loadQuestions = async () => {
  try {
    const res = await axios.get('/api/questions', { params: { review_status: 'approved', page_size: 200 } })
    availableQuestions.value = res.data.questions
  } catch (e) {
    // Also load pending questions
    const res = await axios.get('/api/questions', { params: { page_size: 200 } })
    availableQuestions.value = res.data.questions
  }
}

const onQuestionSelect = (rows) => {
  selectedQuestions.value = rows
}

const addSelectedItem = async () => {
  if (!currentHandout.value) return

  if (addTab.value === 'questions') {
    for (const q of selectedQuestions.value) {
      await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
        item_type: 'question',
        question_id: q.id,
      })
    }
    if (selectedQuestions.value.length) {
      ElMessage.success(`已添加 ${selectedQuestions.value.length} 题`)
    }
  } else if (addTab.value === 'title') {
    if (newSectionTitle.value) {
      await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
        item_type: 'section_title',
        custom_content: newSectionTitle.value,
      })
      newSectionTitle.value = ''
    }
  } else if (addTab.value === 'note') {
    if (newNoteContent.value) {
      await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
        item_type: 'knowledge_note',
        custom_content: newNoteContent.value,
      })
      newNoteContent.value = ''
    }
  }

  showAddDialog.value = false
  selectedQuestions.value = []
  await selectHandout(currentHandout.value.id)
}

const removeItem = async (itemId) => {
  try {
    await axios.delete(`/api/handouts/${currentHandout.value.id}/items/${itemId}`)
    currentHandout.value.items = currentHandout.value.items.filter(i => i.id !== itemId)
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

const toggleAnswer = async (item) => {
  try {
    const res = await axios.post(`/api/handouts/${currentHandout.value.id}/items/${item.id}/toggle-answer`)
    item.show_answer = res.data.show_answer
  } catch (e) { /* silent */ }
}

const onReorder = async () => {
  if (!currentHandout.value) return
  const itemIds = currentHandout.value.items.map(i => i.id)
  try {
    await axios.post(`/api/handouts/${currentHandout.value.id}/reorder`, { item_ids: itemIds })
  } catch (e) {
    ElMessage.error('排序失败')
  }
}

const exportPdf = async () => {
  exporting.value = true
  try {
    const res = await axios.post(`/api/handouts/${currentHandout.value.id}/export`, null, {
      responseType: 'blob',
    })
    // Download the blob
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `${currentHandout.value.title}.pdf`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
    currentHandout.value.status = 'exported'
    ElMessage.success('PDF 已导出')
  } catch (e) {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

const truncate = (text, len) => {
  if (!text) return ''
  return text.length > len ? text.slice(0, len) + '...' : text
}

const statusText = (s) => {
  const map = { draft: '草稿', ready: '待导出', exported: '已导出' }
  return map[s] || s
}

const itemTypeText = (t) => {
  const map = { question: '题目', section_title: '标题', knowledge_note: '备注', example: '例题', exercise: '练习' }
  return map[t] || t
}

const itemTypeTag = (t) => {
  const map = { question: '', section_title: 'warning', knowledge_note: 'info' }
  return map[t] || ''
}

watch(showAddDialog, (val) => {
  if (val) loadQuestions()
})

onMounted(() => {
  loadHandouts()
})
</script>

<style scoped>
.handout-view {
  max-width: 1200px;
  margin: 0 auto;
}

.handout-header {
  margin-bottom: 16px;
}

.subtitle {
  color: #909399;
  margin-top: 4px;
}

.handout-list-card {
  height: calc(100vh - 180px);
  overflow-y: auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.handout-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 6px;
  border: 1px solid transparent;
  transition: all 0.2s;
}

.handout-item:hover {
  background: #f5f7fa;
}

.handout-item.active {
  background: #ecf5ff;
  border-color: #409eff;
}

.h-title {
  font-weight: 500;
  margin-bottom: 4px;
}

.h-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #909399;
}

.editor-card {
  min-height: calc(100vh - 180px);
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.editor-actions {
  display: flex;
  gap: 8px;
}

.items-list {
  min-height: 200px;
}

.editor-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  margin-bottom: 8px;
  background: #fff;
  transition: box-shadow 0.2s;
}

.editor-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.editor-item.type-section_title {
  background: #fdf6ec;
  border-color: #f5dab1;
}

.editor-item.type-knowledge_note {
  background: #ecf5ff;
  border-color: #b3d8ff;
}

.drag-handle {
  cursor: grab;
  color: #c0c4cc;
  font-size: 18px;
  padding: 4px;
}

.drag-handle:active {
  cursor: grabbing;
}

.item-content {
  flex: 1;
  min-width: 0;
}

.item-type-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.q-num {
  font-size: 12px;
  color: #606266;
}

.item-preview {
  font-size: 13px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.no-selection {
  min-height: calc(100vh - 180px);
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
