<template>
  <div class="library-view">
    <div class="library-header">
      <h2>题库管理</h2>
      <p class="subtitle">浏览、搜索、筛选、批量操作所有题目</p>
    </div>

    <!-- Search & Filters -->
    <el-card class="filter-card">
      <el-row :gutter="12" align="middle">
        <el-col :span="6">
          <el-input
            v-model="filters.search"
            placeholder="搜索题目内容..."
            clearable
            @keyup.enter="loadQuestions"
            @clear="loadQuestions"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </el-col>
        <el-col :span="3">
          <el-select v-model="filters.subject" placeholder="学科" clearable @change="loadQuestions">
            <el-option v-for="s in availableSubjects" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-col>
        <el-col :span="3">
          <el-select v-model="filters.question_type" placeholder="题型" clearable @change="loadQuestions">
            <el-option label="选择题" value="选择题" />
            <el-option label="填空题" value="填空题" />
            <el-option label="解答题" value="解答题" />
            <el-option label="实验题" value="实验题" />
          </el-select>
        </el-col>
        <el-col :span="3">
          <el-select v-model="filters.review_status" placeholder="状态" clearable @change="loadQuestions">
            <el-option label="待审核" value="pending" />
            <el-option label="已通过" value="approved" />
            <el-option label="已驳回" value="rejected" />
          </el-select>
        </el-col>
        <el-col :span="3">
          <el-select v-model="filters.difficulty" placeholder="难度" clearable @change="loadQuestions">
            <el-option v-for="d in 5" :key="d" :label="`${d} 星`" :value="d" />
          </el-select>
        </el-col>
        <el-col :span="3">
          <el-select v-model="filters.source_id" placeholder="试卷" clearable @change="loadQuestions">
            <el-option v-for="s in doneSources" :key="s.id" :label="s.filename" :value="s.id" />
          </el-select>
        </el-col>
        <el-col :span="3" style="text-align: right;">
          <el-button @click="loadQuestions"><el-icon><Refresh /></el-icon></el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- Batch Actions Bar -->
    <div class="batch-bar" v-if="selectedIds.size > 0">
      <span>已选 <b>{{ selectedIds.size }}</b> 题</span>
      <el-button type="success" size="small" @click="batchApprove">批量通过</el-button>
      <el-button type="warning" size="small" @click="batchAICorrect">AI 批量修正</el-button>
      <el-button type="info" size="small" @click="showTagDialog = true">批量打标签</el-button>
      <el-button type="primary" size="small" @click="addToHandout">加入讲义</el-button>
      <el-button type="danger" size="small" @click="batchDelete">批量删除</el-button>
      <el-button text size="small" @click="selectedIds.clear()">取消选择</el-button>
    </div>
    
    <!-- Select All Bar -->
    <div class="select-all-bar" v-if="questions.length > 0">
      <el-checkbox 
        :model-value="allSelected" 
        @change="toggleSelectAll"
        :indeterminate="someSelected"
      >
        全选当前页 ({{ questions.length }} 题)
      </el-checkbox>
      <span class="total-count">共 {{ total }} 题</span>
    </div>

    <!-- Question Cards Grid -->
    <div class="question-grid" v-if="questions.length > 0">
      <div
        v-for="q in questions"
        :key="q.id"
        class="q-card"
        :class="{ selected: selectedIds.has(q.id), 'needs-review': q.review_status === 'pending' }"
        @click="toggleSelect(q.id)"
      >
        <div class="q-card-header">
          <el-checkbox
            :model-value="selectedIds.has(q.id)"
            @click.stop="toggleSelect(q.id)"
          />
          <span class="q-num">#{{ q.question_number }}</span>
          <el-tag v-if="q.question_type" size="small" type="info">{{ q.question_type_zh || q.question_type }}</el-tag>
          <el-tag
            :type="reviewTagType(q.review_status)"
            size="small"
          >{{ reviewText(q.review_status) }}</el-tag>
          <el-tag v-if="q.ai_suggestions" size="small" type="warning" effect="plain" style="margin-left: 2px;">
            AI
          </el-tag>
        </div>

        <div class="q-card-body" @click.stop="openDetail(q)">
          <div class="q-content-preview" v-html="renderPreview(q.content, 150)"></div>
          <div class="q-options-preview" v-if="q.options?.length">
            <div v-for="opt in q.options.slice(0, 4)" :key="opt.label" class="opt-line">
              {{ opt.label }}. {{ truncate(opt.content, 40) }}
            </div>
          </div>
        </div>

        <div class="q-card-footer">
          <div class="q-tags">
            <el-tag v-for="t in q.tags" :key="t.id" size="small" :color="t.color" effect="dark" style="margin-right: 4px;">
              {{ t.name }}
            </el-tag>
          </div>
          <div class="q-meta">
            <span v-if="q.score">{{ q.score }}分</span>
            <span v-if="q.ocr_confidence" class="confidence">{{ (q.ocr_confidence * 100).toFixed(0) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <el-empty v-else description="暂无题目" />

    <!-- Pagination -->
    <div class="pagination" v-if="total > pageSize">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="loadQuestions"
      />
    </div>

    <!-- Detail Drawer -->
    <el-drawer v-model="showDetail" title="题目详情" size="500px">
      <template v-if="detailQuestion">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="题号">{{ detailQuestion.question_number }}</el-descriptions-item>
          <el-descriptions-item label="题型">{{ detailQuestion.question_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="学科">{{ detailQuestion.subject || '-' }}</el-descriptions-item>
          <el-descriptions-item label="难度">
            <el-rate v-model="detailQuestion.difficulty" :max="5" disabled size="small" />
          </el-descriptions-item>
          <el-descriptions-item label="分值">{{ detailQuestion.score || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="reviewTagType(detailQuestion.review_status)">{{ reviewText(detailQuestion.review_status) }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <h4 style="margin: 16px 0 8px;">
          题目内容
          <el-switch v-model="detailPreviewMode" active-text="预览" inactive-text="编辑" size="small" style="margin-left: 12px;" />
        </h4>
        <!-- Rendered preview (with LaTeX + images) -->
        <div v-if="detailPreviewMode" class="rendered-preview" v-html="renderFullContent(detailQuestion.content)"></div>
        <!-- Raw editor -->
        <el-input v-else v-model="detailQuestion.content" type="textarea" :autosize="{ minRows: 3, maxRows: 12 }" />

        <div v-if="detailQuestion.options?.length" style="margin-top: 12px;">
          <h4>选项</h4>
          <div v-for="(opt, i) in detailQuestion.options" :key="i" style="margin-bottom: 6px;">
            <el-input v-model="opt.content" size="small">
              <template #prepend>{{ opt.label }}</template>
            </el-input>
          </div>
        </div>

        <el-row :gutter="12" style="margin-top: 12px;">
          <el-col :span="12">
            <el-input v-model="detailQuestion.answer" placeholder="答案">
              <template #prepend>答案</template>
            </el-input>
          </el-col>
          <el-col :span="12">
            <el-input v-model="detailQuestion.explanation" placeholder="解析">
              <template #prepend>解析</template>
            </el-input>
          </el-col>
        </el-row>

        <div style="margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap;">
          <el-button type="primary" @click="saveDetail">保存</el-button>
          <el-button type="warning" @click="aiCorrectSingle" :loading="aiCorrecting">
            <el-icon v-if="!aiCorrecting"><MagicStick /></el-icon>
            AI 修正
          </el-button>
          <el-button v-if="detailQuestion.review_status === 'pending'" type="success" @click="quickReview('approve')">通过</el-button>
          <el-button v-if="detailQuestion.review_status === 'pending'" type="danger" @click="quickReview('reject')">驳回</el-button>
        </div>

        <!-- AI Suggestions -->
        <div v-if="detailQuestion.ai_suggestions" class="ai-suggest-box">
          <div class="ai-suggest-header">
            <el-icon style="color: #e6a23c;"><MagicStick /></el-icon>
            <span>AI 建议</span>
            <el-tag size="small" type="warning">{{ Math.round((detailQuestion.ai_suggestions.confidence || 0) * 100) }}% 置信</el-tag>
          </div>
          <div class="ai-suggest-body">
            <span v-if="detailQuestion.ai_suggestions.question_type">题型: {{ detailQuestion.ai_suggestions.question_type }}</span>
            <span v-if="detailQuestion.ai_suggestions.difficulty">难度: {{ detailQuestion.ai_suggestions.difficulty }}星</span>
          </div>
          <el-button size="small" type="warning" @click="acceptAI" :disabled="aiAccepted">采纳 AI 建议</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- Batch Tag Dialog -->
    <el-dialog v-model="showTagDialog" title="批量打标签" width="400px">
      <el-select v-model="selectedTagIds" multiple placeholder="选择标签" filterable style="width: 100%;">
        <el-option v-for="t in allTags" :key="t.id" :label="`${categoryText(t.category)} / ${t.name}`" :value="t.id" />
      </el-select>
      <template #footer>
        <el-button @click="showTagDialog = false">取消</el-button>
        <el-button type="primary" @click="doBatchTag">确认</el-button>
      </template>
    </el-dialog>

    <!-- AI Correction Preview Dialog -->
    <el-dialog v-model="showAIPreview" title="AI 修正预览" width="700px" top="5vh">
      <div v-if="aiPreviewData" class="ai-preview">
        <el-alert type="info" :closable="false" style="margin-bottom: 12px;">
          <span v-if="aiPreviewData.needs_llm">AI 已修正以下内容，请检查后确认应用</span>
          <span v-else>内容质量良好，无需 AI 修正</span>
        </el-alert>
        <div v-if="aiPreviewData.analysis?.problems?.length" class="ai-problems">
          <b>检测到的问题：</b>
          <ul><li v-for="p in aiPreviewData.analysis.problems" :key="p">{{ p }}</li></ul>
        </div>
        <!-- Content comparison -->
        <el-row :gutter="16">
          <el-col :span="12">
            <h4>原始内容</h4>
            <div class="preview-box original">{{ aiPreviewData.original_content }}</div>
          </el-col>
          <el-col :span="12">
            <h4>AI 修正后</h4>
            <div class="preview-box corrected" v-html="renderFullContent(aiPreviewData.content)"></div>
          </el-col>
        </el-row>
        <!-- Options comparison -->
        <div v-if="aiPreviewData.options?.length" style="margin-top: 12px;">
          <h4>选项对比</h4>
          <el-row :gutter="16">
            <el-col :span="12">
              <div v-for="opt in aiPreviewData.original_options" :key="opt.label" class="opt-compare">
                {{ opt.label }}. {{ opt.content || '(空)' }}
              </div>
            </el-col>
            <el-col :span="12">
              <div v-for="opt in aiPreviewData.options" :key="opt.label" class="opt-compare">
                {{ opt.label }}. {{ opt.content || '(空)' }}
              </div>
            </el-col>
          </el-row>
        </div>
      </div>
      <template #footer>
        <el-button @click="showAIPreview = false">取消</el-button>
        <el-button type="primary" @click="acceptAICorrection" :disabled="!aiPreviewData?.needs_llm">
          应用修正
        </el-button>
      </template>
    </el-dialog>

    <!-- Batch AI Progress Dialog -->
    <el-dialog v-model="showBatchAIProgress" title="AI 批量修正" width="500px">
      <div v-if="batchAIState === 'running'">
        <el-progress :percentage="batchAIProgress" :status="batchAIProgress === 100 ? 'success' : ''" />
        <p style="margin-top: 8px; color: #909399;">正在修正第 {{ batchAICurrent }} / {{ batchAITotal }} 题...</p>
      </div>
      <div v-if="batchAIState === 'done'">
        <el-result icon="success" title="批量修正完成">
          <template #sub-title>
            成功 {{ batchAIResults.filter(r => !r.error).length }} 题，
            失败 {{ batchAIResults.filter(r => r.error).length }} 题
          </template>
        </el-result>
      </div>
      <template #footer>
        <el-button v-if="batchAIState === 'done'" type="primary" @click="showBatchAIProgress = false; loadQuestions()">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { renderFullContent, renderPreview } from '../utils/render.js'

const questions = ref([])
const sources = ref([])
const allTags = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const selectedIds = reactive(new Set())
const showDetail = ref(false)
const detailQuestion = ref(null)
const detailPreviewMode = ref(true) // true = preview, false = edit
const aiAccepted = ref(false)
const showTagDialog = ref(false)
const selectedTagIds = ref([])

// AI correction state
const aiCorrecting = ref(false)
const showAIPreview = ref(false)
const aiPreviewData = ref(null)
const showBatchAIProgress = ref(false)
const batchAIState = ref('idle') // idle / running / done
const batchAIProgress = ref(0)
const batchAICurrent = ref(0)
const batchAITotal = ref(0)
const batchAIResults = ref([])

const filters = reactive({
  search: '',
  subject: '',
  question_type: '',
  review_status: '',
  difficulty: null,
  source_id: '',
})

// Dynamic subjects from API
const availableSubjects = computed(() => {
  const subjects = [
    { value: 'physics', label: '物理' },
    { value: 'math', label: '数学' },
    { value: 'chemistry', label: '化学' },
    { value: 'english', label: '英语' },
    { value: 'chinese', label: '语文' },
  ]
  // Add any additional subjects from sources
  const sourceSubjects = new Set(sources.value.filter(s => s.ocr_status === 'done' && s.subject).map(s => s.subject))
  for (const subj of sourceSubjects) {
    if (!subjects.find(s => s.value === subj)) {
      subjects.push({ value: subj, label: subj })
    }
  }
  return subjects
})

// Only show sources with OCR done
const doneSources = computed(() => {
  return sources.value.filter(s => s.ocr_status === 'done')
})

// Select all functionality
const allSelected = computed(() => {
  return questions.value.length > 0 && questions.value.every(q => selectedIds.has(q.id))
})

const someSelected = computed(() => {
  const selectedCount = questions.value.filter(q => selectedIds.has(q.id)).length
  return selectedCount > 0 && selectedCount < questions.value.length
})

const toggleSelectAll = (checked) => {
  if (checked) {
    questions.value.forEach(q => selectedIds.add(q.id))
  } else {
    questions.value.forEach(q => selectedIds.delete(q.id))
  }
}

const loadSources = async () => {
  try {
    const res = await axios.get('/api/sources')
    sources.value = res.data.sources
  } catch (e) { /* silent */ }
}

const loadTags = async () => {
  try {
    const res = await axios.get('/api/tags')
    allTags.value = res.data
  } catch (e) { /* silent */ }
}

const loadQuestions = async () => {
  try {
    const params = { page: page.value, page_size: pageSize }
    if (filters.search) params.search = filters.search
    if (filters.subject) params.subject = filters.subject
    if (filters.question_type) params.question_type = filters.question_type
    if (filters.review_status) params.review_status = filters.review_status
    if (filters.difficulty) params.difficulty = filters.difficulty
    if (filters.source_id) params.source_id = filters.source_id

    const res = await axios.get('/api/questions', { params })
    questions.value = res.data.questions
    total.value = res.data.total
  } catch (e) {
    ElMessage.error('加载失败')
  }
}

const toggleSelect = (id) => {
  if (selectedIds.has(id)) selectedIds.delete(id)
  else selectedIds.add(id)
}

const openDetail = (q) => {
  detailQuestion.value = JSON.parse(JSON.stringify(q))
  detailPreviewMode.value = true
  aiAccepted.value = false
  showDetail.value = true
}

const saveDetail = async () => {
  try {
    const q = detailQuestion.value
    await axios.put(`/api/questions/${q.id}`, {
      content: q.content,
      options: q.options,
      answer: q.answer,
      explanation: q.explanation,
      difficulty: q.difficulty,
    })
    ElMessage.success('已保存')
    loadQuestions()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const quickReview = async (action) => {
  try {
    await axios.post(`/api/questions/${detailQuestion.value.id}/review?action=${action}`)
    ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
    showDetail.value = false
    loadQuestions()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

const acceptAI = async () => {
  try {
    await axios.post(`/api/questions/${detailQuestion.value.id}/accept-ai`)
    ElMessage.success('已采纳 AI 建议')
    aiAccepted.value = true
    loadQuestions()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

const batchApprove = async () => {
  try {
    await ElMessageBox.confirm(`确定通过 ${selectedIds.size} 道题？`)
    await axios.post('/api/questions/batch-approve', { question_ids: [...selectedIds] })
    ElMessage.success('批量通过成功')
    selectedIds.clear()
    loadQuestions()
  } catch (e) { if (e !== 'cancel') ElMessage.error('操作失败') }
}

const batchDelete = async () => {
  try {
    await ElMessageBox.confirm(`确定删除 ${selectedIds.size} 道题？`, '警告', { type: 'warning' })
    await axios.post('/api/questions/batch-delete', { question_ids: [...selectedIds] })
    ElMessage.success('批量删除成功')
    selectedIds.clear()
    loadQuestions()
  } catch (e) { if (e !== 'cancel') ElMessage.error('操作失败') }
}

const doBatchTag = async () => {
  try {
    await axios.post('/api/questions/batch-tag', {
      question_ids: [...selectedIds],
      tag_ids: selectedTagIds.value,
    })
    ElMessage.success('标签已添加')
    showTagDialog.value = false
    selectedTagIds.value = []
    loadQuestions()
  } catch (e) {
    ElMessage.error('打标签失败')
  }
}

const addToHandout = () => {
  ElMessage.info(`已选 ${selectedIds.size} 题，讲义选择功能开发中`)
}

// ── AI Correction ──

const aiCorrectSingle = async () => {
  if (!detailQuestion.value) return
  aiCorrecting.value = true
  try {
    const res = await axios.post(`/api/questions/${detailQuestion.value.id}/ai-correct`)
    aiPreviewData.value = {
      ...res.data,
      original_content: detailQuestion.value.content || '',
      original_options: detailQuestion.value.options ? JSON.parse(JSON.stringify(detailQuestion.value.options)) : [],
    }
    showAIPreview.value = true
  } catch (e) {
    ElMessage.error('AI 修正失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    aiCorrecting.value = false
  }
}

const acceptAICorrection = async () => {
  if (!aiPreviewData.value || !detailQuestion.value) return
  const d = aiPreviewData.value
  const q = detailQuestion.value
  // Apply corrected content to the detail question
  q.content = d.content
  if (d.options && d.options.length > 0) q.options = d.options
  if (d.answer) q.answer = d.answer
  if (d.explanation) q.explanation = d.explanation
  // Save to backend
  try {
    await axios.put(`/api/questions/${q.id}`, {
      content: q.content,
      options: q.options,
      answer: q.answer,
      explanation: q.explanation,
    })
    ElMessage.success('已应用 AI 修正')
    showAIPreview.value = false
    loadQuestions()
    // Refresh detail view
    const res2 = await axios.get(`/api/questions/${q.id}`)
    detailQuestion.value = res2.data
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const batchAICorrect = async () => {
  if (selectedIds.size === 0) return
  try {
    await ElMessageBox.confirm(
      `将对 ${selectedIds.size} 道题执行 AI 修正，每道题会消耗一次 AI 调用。继续？`,
      'AI 批量修正', { type: 'info' }
    )
  } catch { return }

  showBatchAIProgress.value = true
  batchAIState.value = 'running'
  batchAITotal.value = selectedIds.size
  batchAICurrent.value = 0
  batchAIProgress.value = 0
  batchAIResults.value = []

  const ids = [...selectedIds]
  const results = []

  for (let i = 0; i < ids.length; i++) {
    batchAICurrent.value = i + 1
    batchAIProgress.value = Math.round(((i + 1) / ids.length) * 100)
    try {
      const res = await axios.post(`/api/questions/${ids[i]}/ai-correct`)
      results.push({ question_id: ids[i], ...res.data })
      // Auto-apply if AI made corrections
      if (res.data.needs_llm && res.data.content) {
        await axios.put(`/api/questions/${ids[i]}`, {
          content: res.data.content,
          options: res.data.options,
          answer: res.data.answer,
          explanation: res.data.explanation,
        })
      }
    } catch (e) {
      results.push({ question_id: ids[i], error: e.response?.data?.detail || e.message })
    }
  }

  batchAIResults.value = results
  batchAIState.value = 'done'
  selectedIds.clear()
}

const truncate = (text, len) => {
  if (!text) return ''
  return text.length > len ? text.slice(0, len) + '...' : text
}

const reviewTagType = (s) => ({ pending: 'warning', approved: 'success', rejected: 'danger' })[s] || 'info'
const reviewText = (s) => ({ pending: '待审核', approved: '已通过', rejected: '已驳回' })[s] || s
const categoryText = (c) => ({ knowledge: '知识点', skill: '技能', error_type: '错因', custom: '自定义' })[c] || c

onMounted(() => {
  loadSources()
  loadTags()
  loadQuestions()
})
</script>

<style scoped>
.library-view { max-width: 1200px; margin: 0 auto; }
.library-header { margin-bottom: 16px; }
.subtitle { color: #909399; margin-top: 4px; }
.filter-card { margin-bottom: 12px; }

.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: #ecf5ff;
  border: 1px solid #b3d8ff;
  border-radius: 6px;
  margin-bottom: 12px;
}

.select-all-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
}

.total-count {
  color: #909399;
}

.question-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}

.q-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s;
}
.q-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
.q-card.selected { border-color: #409eff; background: #ecf5ff; }
.q-card.needs-review { border-left: 3px solid #e6a23c; }

.q-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.q-num { font-weight: bold; color: #303133; }

.q-card-body { margin-bottom: 8px; }
.q-content-preview {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  max-height: 80px;
  overflow: hidden;
}
.q-options-preview { margin-top: 6px; }
.opt-line { font-size: 12px; color: #909399; }

.q-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.q-tags { flex: 1; }
.q-meta { font-size: 12px; color: #909399; display: flex; gap: 8px; }
.confidence { color: #67c23a; }

.pagination { margin-top: 16px; text-align: center; }

/* AI Suggestions */
.ai-suggest-box {
  margin-top: 16px; padding: 12px; background: #fdf6ec;
  border: 1px solid #f5dab1; border-radius: 6px;
}
.ai-suggest-header {
  display: flex; align-items: center; gap: 6px;
  font-weight: 500; margin-bottom: 8px;
}
.ai-suggest-body {
  display: flex; gap: 16px; font-size: 13px; color: #606266;
  margin-bottom: 8px;
}

/* Rendered preview in detail drawer */
.rendered-preview {
  padding: 12px 16px;
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  line-height: 1.8;
  font-size: 14px;
  color: #303133;
  word-break: break-word;
  overflow-wrap: break-word;
}
.rendered-preview :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 4px;
  margin: 6px 0;
  display: block;
}
.rendered-preview :deep(.katex) {
  font-size: 1.05em;
}
.rendered-preview :deep(.katex-display) {
  margin: 12px 0;
  overflow-x: auto;
}

/* AI Correction Preview */
.ai-preview .ai-problems {
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 4px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.ai-preview .ai-problems ul {
  margin: 4px 0 0 16px;
  padding: 0;
}
.preview-box {
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  max-height: 300px;
  overflow-y: auto;
  min-height: 80px;
}
.preview-box.original {
  background: #f5f5f5;
  border: 1px solid #e4e7ed;
  white-space: pre-wrap;
  word-break: break-all;
  color: #606266;
}
.preview-box.corrected {
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  color: #303133;
}
.opt-compare {
  font-size: 13px;
  padding: 2px 0;
  color: #606266;
}
</style>
