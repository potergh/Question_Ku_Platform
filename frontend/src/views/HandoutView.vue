<template>
  <div class="handout-view">
    <div class="handout-header">
      <h2>讲义编辑</h2>
      <p class="subtitle">选择题目，编辑知识备注，拖拽排序，导出 PDF</p>
    </div>

    <el-row :gutter="16">
      <!-- Left: Handout List -->
      <el-col :span="6">
        <el-card class="handout-list-card">
          <template #header>
            <div class="card-header">
              <span>我的讲义</span>
              <el-button type="primary" size="small" @click="showCreateDialog = true">
                <el-icon><Plus /></el-icon>
              </el-button>
            </div>
          </template>
          <div
            v-for="h in handouts"
            :key="h.id"
            class="handout-list-item"
            :class="{ active: currentHandout?.id === h.id }"
            @click="selectHandout(h.id)"
          >
            <div class="h-title">{{ h.title }}</div>
            <div class="h-meta">
              <el-tag size="small" :type="h.status === 'exported' ? 'success' : 'info'">
                {{ h.items?.length || 0 }} 项
              </el-tag>
              <span class="h-status">{{ statusText(h.status) }}</span>
            </div>
          </div>
          <el-empty v-if="handouts.length === 0" description="暂无讲义" :image-size="50" />
        </el-card>
      </el-col>

      <!-- Right: Handout Editor -->
      <el-col :span="18">
        <el-card v-if="currentHandout" class="editor-card">
          <template #header>
            <div class="editor-header">
              <el-input v-model="currentHandout.title" style="width: 260px;" @blur="saveHandoutMeta" />
              <div class="editor-actions">
                <el-dropdown @command="addItem" trigger="click">
                  <el-button size="small">
                    <el-icon><Plus /></el-icon> 添加 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="question">从题库选题</el-dropdown-item>
                      <el-dropdown-item command="section_title">章节标题</el-dropdown-item>
                      <el-dropdown-item command="knowledge_note">知识备注 (Markdown)</el-dropdown-item>
                      <el-dropdown-item command="example" divided>例题 (选题+标记)</el-dropdown-item>
                      <el-dropdown-item command="exercise">练习 (选题+标记)</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-dropdown @command="exportFile" :disabled="!currentHandout.items?.length">
                  <el-button type="primary" size="small" :loading="exporting">
                    <el-icon><Download /></el-icon> 导出 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="pdf">导出 PDF</el-dropdown-item>
                      <el-dropdown-item command="docx_teacher">导出 Word (教师版)</el-dropdown-item>
                      <el-dropdown-item command="docx_student">导出 Word (学生版)</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button size="small" @click="showAIDrawer = true" type="success">
                  <el-icon><MagicStick /></el-icon> AI 助手
                </el-button>
              </div>
            </div>
          </template>

          <!-- Config bar -->
          <div class="config-bar">
            <el-checkbox v-model="handoutConfig.has_answer_section" @change="saveConfig">答案区独立展示</el-checkbox>
            <el-checkbox v-model="handoutConfig.has_knowledge_summary" @change="saveConfig">包含知识总结</el-checkbox>
          </div>

          <!-- Items (drag to reorder) -->
          <draggable v-model="currentHandout.items" item-key="id" handle=".drag-handle" @end="onReorder" class="items-list">
            <template #item="{ element, index }">
              <div class="editor-item" :class="'type-' + element.item_type">
                <div class="drag-handle"><el-icon><Rank /></el-icon></div>
                <div class="item-body">
                  <!-- Section Title -->
                  <div v-if="element.item_type === 'section_title'" class="inline-edit">
                    <el-icon style="color: #e6a23c;"><Menu /></el-icon>
                    <el-input v-model="element.custom_content" size="small" placeholder="章节标题" @blur="saveItemContent(element)" style="font-weight: bold;" />
                  </div>

                  <!-- Knowledge Note (Markdown) -->
                  <div v-else-if="element.item_type === 'knowledge_note'" class="note-edit">
                    <div class="item-type-label">
                      <el-tag size="small" type="info">知识备注</el-tag>
                      <el-switch v-model="element._editing" active-text="编辑" inactive-text="预览" size="small" />
                    </div>
                    <MdEditor
                      v-if="element._editing"
                      v-model="element.custom_content"
                      :toolbars="mdToolbars"
                      style="height: 200px;"
                      @onSave="saveItemContent(element)"
                    />
                    <div v-else class="md-preview" v-html="renderMarkdown(element.custom_content)" @dblclick="element._editing = true"></div>
                  </div>

                  <!-- Question (example/exercise/plain question) -->
                  <div v-else-if="element.item_type === 'question' || element.item_type === 'example' || element.item_type === 'exercise'" class="question-item">
                    <div class="item-type-label">
                      <el-tag size="small" :type="itemTypeTag(element.item_type)">{{ itemTypeText(element.item_type) }}</el-tag>
                      <span v-if="element.question_snapshot" class="q-num">
                        第 {{ element.question_snapshot.question_number }} 题
                        <span v-if="element.question_snapshot.score">({{ element.question_snapshot.score }}分)</span>
                      </span>
                    </div>
                    <div class="q-snapshot-content" v-if="element.question_snapshot">
                      <div v-html="renderSnapshotContent(element.question_snapshot)"></div>
                    </div>
                    <div class="q-answer-toggle">
                      <el-switch v-model="element.show_answer" active-text="显示答案" inactive-text="隐藏答案" size="small" @change="toggleAnswer(element)" />
                    </div>
                    <div class="q-answer-content" v-if="element.show_answer && element.question_snapshot">
                      <div v-if="element.question_snapshot.answer"><b>答案：</b>{{ element.question_snapshot.answer }}</div>
                      <div v-if="element.question_snapshot.explanation"><b>解析：</b>{{ element.question_snapshot.explanation }}</div>
                    </div>
                  </div>
                </div>
                <div class="item-actions">
                  <el-button text type="danger" size="small" @click="removeItem(element.id)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
            </template>
          </draggable>

          <el-empty v-if="!currentHandout.items?.length" description="点击上方「添加」开始编辑讲义" :image-size="80" />
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
          <el-select v-model="newHandoutSubject">
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
    <el-dialog v-model="showAddDialog" :title="addDialogTitle" width="700px">
      <el-table :data="availableQuestions" @selection-change="onQuestionSelect" height="400" size="small">
        <el-table-column type="selection" width="40" />
        <el-table-column prop="question_number" label="#" width="50" />
        <el-table-column prop="question_type" label="题型" width="80" />
        <el-table-column label="内容">
          <template #default="{ row }">{{ truncate(row.content, 80) }}</template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addSelectedQuestions">添加</el-button>
      </template>
    </el-dialog>

    <!-- Add Section Title Dialog -->
    <el-dialog v-model="showSectionDialog" title="添加章节标题" width="400px">
      <el-input v-model="newSectionTitle" placeholder="例：一、力学基础" />
      <template #footer>
        <el-button @click="showSectionDialog = false">取消</el-button>
        <el-button type="primary" @click="addSectionTitle" :disabled="!newSectionTitle">添加</el-button>
      </template>
    </el-dialog>

    <!-- Add Knowledge Note Dialog -->
    <el-dialog v-model="showNoteDialog" title="添加知识备注" width="600px">
      <MdEditor v-model="newNoteContent" :toolbars="mdToolbars" style="height: 250px;" />
      <template #footer>
        <el-button @click="showNoteDialog = false">取消</el-button>
        <el-button type="primary" @click="addKnowledgeNote" :disabled="!newNoteContent">添加</el-button>
      </template>
    </el-dialog>

    <!-- AI Assistant Drawer -->
    <el-drawer v-model="showAIDrawer" title="AI 助手" size="480px" direction="rtl">
      <div class="ai-panel">
        <!-- Student Profile -->
        <div class="ai-section">
          <label class="ai-label">学生特点</label>
          <el-input
            v-model="aiStudentProfile"
            type="textarea"
            :rows="2"
            placeholder="例：高二学生，力学基础薄弱，计算能力一般"
          />
        </div>

        <!-- Action Buttons -->
        <div class="ai-actions">
          <el-button @click="aiAction('suggest_structure')" :loading="aiLoading" :disabled="!aiStudentProfile">
            📝 建议结构
          </el-button>
          <el-button @click="aiAction('recommend_questions')" :loading="aiLoading" :disabled="!aiStudentProfile">
            🎯 推荐题目
          </el-button>
          <el-button @click="showNoteGenDialog = true" :disabled="!aiStudentProfile">
            ✍️ 生成备注
          </el-button>
        </div>

        <!-- Results -->
        <div class="ai-results" v-if="aiResults.length">
          <div v-for="(r, i) in aiResults" :key="i" class="ai-result-item">
            <el-card size="small">
              <div class="result-header">
                <el-tag size="small" :type="r.confidence > 0.7 ? 'success' : 'warning'">
                  {{ r.confidence ? `${Math.round(r.confidence * 100)}%` : r.title ? '章节' : '备注' }}
                </el-tag>
                <span class="result-title">{{ r.title || r.content?.slice(0, 50) || '...' }}</span>
              </div>
              <div class="result-reason" v-if="r.reason">{{ r.reason }}</div>
              <div class="result-desc" v-if="r.description">{{ r.description }}</div>
              <div class="result-md" v-if="r.markdown" v-html="renderMarkdown(r.markdown)"></div>
              <div class="result-actions">
                <el-button size="small" type="primary" @click="adoptAIResult(r)">
                  采纳
                </el-button>
              </div>
            </el-card>
          </div>
        </div>

        <el-empty v-if="!aiResults.length && !aiLoading" description="输入学生特点，选择 AI 操作" :image-size="60" />
        <div v-if="aiLoading" class="ai-loading">
          <el-icon class="is-loading"><Loading /></el-icon> AI 思考中...
        </div>

        <el-alert v-if="aiError" :title="aiError" type="error" :closable="true" style="margin-top: 12px;" />
      </div>
    </el-drawer>

    <!-- Generate Note Dialog -->
    <el-dialog v-model="showNoteGenDialog" title="AI 生成教学备注" width="500px">
      <el-form>
        <el-form-item label="主题">
          <el-input v-model="aiNoteTopic" placeholder="例：牛顿第二定律" />
        </el-form-item>
        <el-form-item label="补充说明">
          <el-input v-model="aiNoteContext" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <div v-if="aiGeneratedNote" class="generated-note-preview" v-html="renderMarkdown(aiGeneratedNote)"></div>
      <template #footer>
        <el-button @click="showNoteGenDialog = false">取消</el-button>
        <el-button @click="generateNote" :loading="aiLoading" :disabled="!aiNoteTopic">生成</el-button>
        <el-button type="primary" @click="adoptGeneratedNote" :disabled="!aiGeneratedNote">采纳并添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import draggable from 'vuedraggable'
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import { renderFullContent } from '../utils/render.js'

const mdToolbars = ['bold', 'italic', '|', 'title', 'unordered-list', 'ordered-list', '|', 'link', 'code', '=', 'preview']

const handouts = ref([])
const currentHandout = ref(null)
const handoutConfig = reactive({ has_answer_section: false, has_knowledge_summary: false })
const showCreateDialog = ref(false)
const showAddDialog = ref(false)
const showSectionDialog = ref(false)
const showNoteDialog = ref(false)
const newHandoutTitle = ref('')
const newHandoutSubject = ref('physics')
const newSectionTitle = ref('')
const newNoteContent = ref('')
const exporting = ref(false)
const availableQuestions = ref([])
const selectedQuestions = ref([])
const pendingItemType = ref('question')

// AI panel state
const showAIDrawer = ref(false)
const aiStudentProfile = ref('')
const aiLoading = ref(false)
const aiResults = ref([])
const aiError = ref('')
const showNoteGenDialog = ref(false)
const aiNoteTopic = ref('')
const aiNoteContext = ref('')
const aiGeneratedNote = ref('')

const addDialogTitle = computed(() => {
  const map = { question: '从题库选题', example: '添加例题', exercise: '添加练习' }
  return map[pendingItemType.value] || '选题'
})

// ── Handout CRUD ──
const loadHandouts = async () => {
  try {
    const res = await axios.get('/api/handouts')
    handouts.value = res.data.handouts
  } catch (e) { console.error(e) }
}

const selectHandout = async (id) => {
  try {
    const res = await axios.get(`/api/handouts/${id}`)
    currentHandout.value = res.data
    // Add _editing flag to items
    currentHandout.value.items.forEach(i => { i._editing = false })
    // Load config
    const cfg = currentHandout.value.config || {}
    handoutConfig.has_answer_section = cfg.has_answer_section || false
    handoutConfig.has_knowledge_summary = cfg.has_knowledge_summary || false
  } catch (e) { ElMessage.error('加载失败') }
}

const createHandout = async () => {
  try {
    const res = await axios.post('/api/handouts', { title: newHandoutTitle.value, subject: newHandoutSubject.value })
    handouts.value.unshift(res.data)
    currentHandout.value = res.data
    showCreateDialog.value = false
    newHandoutTitle.value = ''
    ElMessage.success('已创建')
  } catch (e) { ElMessage.error('创建失败') }
}

const saveHandoutMeta = async () => {
  if (!currentHandout.value) return
  try { await axios.put(`/api/handouts/${currentHandout.value.id}`, { title: currentHandout.value.title }) } catch (e) {}
}

const saveConfig = async () => {
  if (!currentHandout.value) return
  try {
    await axios.put(`/api/handouts/${currentHandout.value.id}`, {
      config: { has_answer_section: handoutConfig.has_answer_section, has_knowledge_summary: handoutConfig.has_knowledge_summary }
    })
  } catch (e) {}
}

// ── Add Items ──
const addItem = (type) => {
  if (type === 'section_title') { showSectionDialog.value = true; return }
  if (type === 'knowledge_note') { showNoteDialog.value = true; return }
  pendingItemType.value = type
  loadQuestions()
  showAddDialog.value = true
}

const loadQuestions = async () => {
  try {
    const res = await axios.get('/api/questions', { params: { page_size: 200 } })
    availableQuestions.value = res.data.questions
  } catch (e) { availableQuestions.value = [] }
}

const onQuestionSelect = (rows) => { selectedQuestions.value = rows }

const addSelectedQuestions = async () => {
  if (!currentHandout.value) return
  for (const q of selectedQuestions.value) {
    await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
      item_type: pendingItemType.value === 'question' ? 'question' : pendingItemType.value,
      question_id: q.id,
    })
  }
  if (selectedQuestions.value.length) ElMessage.success(`已添加 ${selectedQuestions.value.length} 题`)
  showAddDialog.value = false
  selectedQuestions.value = []
  await selectHandout(currentHandout.value.id)
}

const addSectionTitle = async () => {
  if (!currentHandout.value || !newSectionTitle.value) return
  await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
    item_type: 'section_title', custom_content: newSectionTitle.value,
  })
  newSectionTitle.value = ''
  showSectionDialog.value = false
  await selectHandout(currentHandout.value.id)
}

const addKnowledgeNote = async () => {
  if (!currentHandout.value || !newNoteContent.value) return
  await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
    item_type: 'knowledge_note', custom_content: newNoteContent.value,
  })
  newNoteContent.value = ''
  showNoteDialog.value = false
  await selectHandout(currentHandout.value.id)
}

// ── Item Ops ──
const removeItem = async (itemId) => {
  try {
    await axios.delete(`/api/handouts/${currentHandout.value.id}/items/${itemId}`)
    currentHandout.value.items = currentHandout.value.items.filter(i => i.id !== itemId)
  } catch (e) { ElMessage.error('删除失败') }
}

const toggleAnswer = async (item) => {
  try { await axios.post(`/api/handouts/${currentHandout.value.id}/items/${item.id}/toggle-answer`) } catch (e) {}
}

const saveItemContent = async (item) => {
  try {
    await axios.put(`/api/handouts/${currentHandout.value.id}/items/${item.id}`, {
      custom_content: item.custom_content,
    })
  } catch (e) {}
}

const onReorder = async () => {
  if (!currentHandout.value) return
  const ids = currentHandout.value.items.map(i => i.id)
  try { await axios.post(`/api/handouts/${currentHandout.value.id}/reorder`, { item_ids: ids }) } catch (e) {}
}

const exportFile = async (command) => {
  exporting.value = true
  try {
    let url = `/api/handouts/${currentHandout.value.id}/export?format=${command === 'pdf' ? 'pdf' : 'docx'}`
    if (command === 'docx_student') url += '&version=student'
    else if (command === 'docx_teacher') url += '&version=teacher'
    
    const res = await axios.post(url, null, { responseType: 'blob' })
    const blob = new Blob([res.data])
    const downloadUrl = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = downloadUrl
    
    // Determine filename
    let ext = command === 'pdf' ? 'pdf' : 'docx'
    let suffix = command === 'docx_student' ? '_学生版' : command === 'docx_teacher' ? '_教师版' : ''
    a.download = `${currentHandout.value.title}${suffix}.${ext}`
    
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(downloadUrl)
    
    currentHandout.value.status = 'exported'
    const formatText = command === 'pdf' ? 'PDF' : command === 'docx_teacher' ? 'Word (教师版)' : 'Word (学生版)'
    ElMessage.success(`${formatText} 已导出`)
  } catch (e) { 
    ElMessage.error('导出失败') 
  } finally { 
    exporting.value = false 
  }
}

// ── AI Actions ──
const aiAction = async (action) => {
  if (!currentHandout.value) return
  aiLoading.value = true
  aiError.value = ''
  aiResults.value = []
  try {
    const res = await axios.post(`/api/handouts/${currentHandout.value.id}/ai-generate?action=${action}`, {
      student_profile: aiStudentProfile.value,
    })
    aiResults.value = res.data.data || []
    if (!aiResults.value.length) {
      ElMessage.info('AI 没有找到合适的结果')
    }
  } catch (e) {
    aiError.value = e.response?.data?.detail || 'AI 请求失败'
  } finally {
    aiLoading.value = false
  }
}

const generateNote = async () => {
  if (!currentHandout.value || !aiNoteTopic.value) return
  aiLoading.value = true
  aiError.value = ''
  aiGeneratedNote.value = ''
  try {
    const res = await axios.post(`/api/handouts/${currentHandout.value.id}/ai-generate?action=generate_notes`, {
      student_profile: aiStudentProfile.value,
      topic: aiNoteTopic.value,
      context: aiNoteContext.value,
    })
    aiGeneratedNote.value = res.data.data?.markdown || ''
  } catch (e) {
    aiError.value = e.response?.data?.detail || 'AI 请求失败'
  } finally {
    aiLoading.value = false
  }
}

const adoptAIResult = async (result) => {
  if (!currentHandout.value) return
  try {
    if (result.question_id) {
      // It's a question recommendation
      await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
        item_type: 'question',
        question_id: result.question_id,
      })
      ElMessage.success('已添加到讲义')
      await selectHandout(currentHandout.value.id)
    } else if (result.title) {
      // It's a structure suggestion - add as section title
      await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
        item_type: 'section_title',
        custom_content: result.title,
      })
      ElMessage.success('已添加章节标题')
      await selectHandout(currentHandout.value.id)
    }
  } catch (e) {
    ElMessage.error('添加失败')
  }
}

const adoptGeneratedNote = async () => {
  if (!aiGeneratedNote.value || !currentHandout.value) return
  try {
    await axios.post(`/api/handouts/${currentHandout.value.id}/items`, {
      item_type: 'knowledge_note',
      custom_content: aiGeneratedNote.value,
    })
    ElMessage.success('已添加教学备注')
    showNoteGenDialog.value = false
    aiNoteTopic.value = ''
    aiNoteContext.value = ''
    aiGeneratedNote.value = ''
    await selectHandout(currentHandout.value.id)
  } catch (e) {
    ElMessage.error('添加失败')
  }
}

// ── Helpers ──
const truncate = (t, n) => t ? (t.length > n ? t.slice(0, n) + '...' : t) : ''
const statusText = (s) => ({ draft: '草稿', ready: '待导出', exported: '已导出' })[s] || s
const itemTypeText = (t) => ({ question: '题目', section_title: '标题', knowledge_note: '备注', example: '例题', exercise: '练习' })[t] || t
const itemTypeTag = (t) => ({ question: '', section_title: 'warning', knowledge_note: 'info', example: 'success', exercise: 'danger' })[t] || ''

const renderMarkdown = (text) => {
  if (!text) return '<span style="color:#909399">双击编辑...</span>'
  return renderFullContent(text, { emptyText: '<span style="color:#909399">双击编辑...</span>' })
}

// Resolve asset:// URLs in question snapshot content
const resolveAssetUrls = (content, sourceId) => {
  if (!content) return content
  return content
    .replace(/asset:\/\/figures\/figures\//g, `/api/ocr-assets/${sourceId}/figures/`)
    .replace(/asset:\/\//g, `/api/ocr-assets/${sourceId}/`)
}

const renderSnapshotContent = (snapshot) => {
  if (!snapshot || !snapshot.content) return ''
  const sourceId = snapshot.source_id || ''
  const resolved = resolveAssetUrls(snapshot.content, sourceId)
  return renderFullContent(resolved)
}

onMounted(() => { loadHandouts() })
</script>

<style scoped>
.handout-view { max-width: 1200px; margin: 0 auto; }
.handout-header { margin-bottom: 16px; }
.subtitle { color: #909399; margin-top: 4px; }

.handout-list-card { height: calc(100vh - 180px); overflow-y: auto; }
.card-header { display: flex; justify-content: space-between; align-items: center; }

.handout-list-item {
  padding: 10px; border-radius: 6px; cursor: pointer; margin-bottom: 4px;
  border: 1px solid transparent; transition: all 0.2s;
}
.handout-list-item:hover { background: #f5f7fa; }
.handout-list-item.active { background: #ecf5ff; border-color: #409eff; }
.h-title { font-weight: 500; margin-bottom: 4px; font-size: 14px; }
.h-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #909399; }

.editor-card { min-height: calc(100vh - 180px); }
.editor-header { display: flex; justify-content: space-between; align-items: center; }
.editor-actions { display: flex; gap: 8px; }

.config-bar {
  display: flex; gap: 16px; padding: 8px 12px; background: #fafafa;
  border: 1px solid #ebeef5; border-radius: 6px; margin-bottom: 12px;
}

.items-list { min-height: 200px; }

.editor-item {
  display: flex; gap: 8px; padding: 10px; border: 1px solid #e4e7ed;
  border-radius: 6px; margin-bottom: 8px; background: #fff; transition: box-shadow 0.2s;
}
.editor-item:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.editor-item.type-section_title { background: #fdf6ec; border-color: #f5dab1; }
.editor-item.type-knowledge_note { background: #f0f9ff; border-color: #b3d8ff; }
.editor-item.type-example { border-left: 3px solid #67c23a; }
.editor-item.type-exercise { border-left: 3px solid #f56c6c; }

.drag-handle { cursor: grab; color: #c0c4cc; font-size: 18px; padding: 4px; flex-shrink: 0; }
.drag-handle:active { cursor: grabbing; }

.item-body { flex: 1; min-width: 0; }
.item-actions { flex-shrink: 0; }

.inline-edit { display: flex; align-items: center; gap: 8px; }
.item-type-label { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.q-num { font-size: 12px; color: #606266; }

.q-snapshot-content { font-size: 13px; color: #606266; margin-bottom: 6px; }
.q-answer-toggle { margin-bottom: 4px; }
.q-answer-content {
  padding: 6px 10px; background: #f0f9eb; border-radius: 4px;
  font-size: 13px; color: #606266;
}

.md-preview {
  min-height: 60px; padding: 8px; border: 1px dashed #dcdfe6;
  border-radius: 4px; cursor: pointer; font-size: 14px; line-height: 1.6;
}
.md-preview:hover { border-color: #409eff; }

.note-edit { }

.no-selection { min-height: calc(100vh - 180px); display: flex; align-items: center; justify-content: center; }

/* AI Panel */
.ai-panel { padding: 0 4px; }
.ai-section { margin-bottom: 16px; }
.ai-label { display: block; font-weight: 500; margin-bottom: 6px; font-size: 13px; color: #606266; }
.ai-actions { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.ai-results { display: flex; flex-direction: column; gap: 10px; }
.ai-result-item :deep(.el-card__body) { padding: 10px; }
.result-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.result-title { font-weight: 500; font-size: 14px; }
.result-reason { font-size: 12px; color: #909399; margin-bottom: 4px; }
.result-desc { font-size: 13px; color: #606266; margin-bottom: 4px; }
.result-md { font-size: 13px; line-height: 1.6; color: #606266; margin-bottom: 6px; }
.result-actions { margin-top: 6px; }
.ai-loading { text-align: center; padding: 20px; color: #409eff; font-size: 14px; }
.ai-loading .el-icon { font-size: 20px; margin-right: 6px; }

.generated-note-preview {
  max-height: 200px; overflow-y: auto; padding: 10px;
  border: 1px solid #e4e7ed; border-radius: 4px; margin-top: 12px;
  font-size: 13px; line-height: 1.6;
}

/* Rendered content: images + KaTeX */
.md-preview :deep(img),
.q-snapshot-content :deep(img),
.generated-note-preview :deep(img),
.result-md :deep(img) {
  max-width: 100%; height: auto; border-radius: 4px; margin: 6px 0; display: block;
}
.md-preview :deep(.katex),
.q-snapshot-content :deep(.katex),
.generated-note-preview :deep(.katex),
.result-md :deep(.katex) {
  font-size: 1.05em;
}
.md-preview :deep(.katex-display),
.q-snapshot-content :deep(.katex-display),
.generated-note-preview :deep(.katex-display),
.result-md :deep(.katex-display) {
  margin: 10px 0; overflow-x: auto;
}
</style>
