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
      <el-row style="margin-top: 8px;" :gutter="12" align="middle">
        <el-col :span="8">
          <el-select v-model="filters.tag_ids" multiple placeholder="按标签筛选" clearable filterable @change="loadQuestions" style="width: 100%;">
            <el-option label="⚠ 未打标签" value="none" />
            <el-option v-for="t in allTags" :key="t.id" :label="`${subjectText(t.subject)} / ${categoryText(t.category)} / ${t.name}`" :value="t.id" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-button size="small" @click="showTagMgmt = true"><el-icon><PriceTag /></el-icon> 标签管理</el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- Batch Actions Bar -->
    <div class="batch-bar" v-if="selectedIds.size > 0">
      <span>已选 <b>{{ selectedIds.size }}</b> 题</span>
      <el-button type="success" size="small" @click="batchApprove">批量通过</el-button>
      <el-button type="warning" size="small" @click="batchAICorrect">AI 批量修正</el-button>
      <el-button type="info" size="small" @click="showTagDialog = true">批量打标签</el-button>
      <el-button type="warning" size="small" @click="batchAITag">AI 批量打标</el-button>
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
            <div v-for="opt in q.options.slice(0, 4)" :key="opt.label" class="opt-line"
              v-html="opt.label + '. ' + renderOptionContent(opt.content)">
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
          <!-- Preview mode: rendered LaTeX + images -->
          <template v-if="detailPreviewMode">
            <div v-for="(opt, i) in detailQuestion.options" :key="i" class="option-rendered"
              v-html="opt.label + '. ' + renderOptionContent(opt.content)">
            </div>
          </template>
          <!-- Edit mode: input fields -->
          <template v-else>
            <div v-for="(opt, i) in detailQuestion.options" :key="i" style="margin-bottom: 6px;">
              <el-input v-model="opt.content" size="small">
                <template #prepend>{{ opt.label }}</template>
              </el-input>
            </div>
          </template>
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

        <!-- Tags Section -->
        <div style="margin-top: 16px;">
          <h4 style="margin-bottom: 8px;">标签</h4>
          <div style="display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 8px;">
            <el-tag v-for="t in detailQuestion.tags" :key="t.id" :color="t.color" effect="dark" closable @close="removeTagFromDetail(t.id)" style="margin: 2px;">
              {{ t.name }}
            </el-tag>
            <span v-if="!detailQuestion.tags?.length" style="color: #c0c4cc; font-size: 13px;">暂无标签</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <el-select v-model="detailTagSelect" placeholder="添加标签" filterable size="small" style="width: 200px;">
              <el-option v-for="t in availableTagsForDetail" :key="t.id" :label="`${categoryText(t.category)} / ${t.name}`" :value="t.id" />
            </el-select>
            <el-button size="small" @click="addTagToDetail" :disabled="!detailTagSelect">添加</el-button>
            <el-button size="small" type="warning" @click="aiTagSingle" :loading="aiTagging">AI 打标</el-button>
          </div>
        </div>

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

    <!-- Tag Management Dialog -->
    <el-dialog v-model="showTagMgmt" title="标签管理" width="600px">
      <!-- Subject tabs (primary level) -->
      <el-tabs v-model="mgmtSubject" style="margin-bottom: 12px;">
        <el-tab-pane label="物理" name="physics" />
        <el-tab-pane label="数学" name="math" />
        <el-tab-pane label="化学" name="chemistry" />
        <el-tab-pane label="英语" name="english" />
      </el-tabs>
      <!-- Category sub-tabs (secondary level) -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <el-radio-group v-model="mgmtCategory" size="small">
          <el-radio-button label="knowledge">知识点</el-radio-button>
          <el-radio-button label="skill">技能</el-radio-button>
          <el-radio-button label="error_type">错因</el-radio-button>
          <el-radio-button label="custom">自定义</el-radio-button>
        </el-radio-group>
        <el-button type="primary" size="small" @click="showCreateTag = true">
          <el-icon><Plus /></el-icon> 新增
        </el-button>
      </div>
      <div style="display: flex; flex-wrap: wrap; gap: 8px;">
        <div v-for="t in filteredMgmtTags" :key="t.id" class="mgmt-tag">
          <span>{{ t.name }}</span>
          <span class="mgmt-tag-actions">
            <el-button text size="small" @click="editTagItem(t)">编辑</el-button>
            <el-button text type="danger" size="small" @click="deleteTagItem(t)">删除</el-button>
          </span>
        </div>
      </div>
      <el-empty v-if="filteredMgmtTags.length === 0" description="该分类暂无标签" :image-size="40" />
    </el-dialog>

    <!-- Create/Edit Tag Dialog -->
    <el-dialog v-model="showCreateTag" :title="editingTagItem ? '编辑标签' : '新增标签'" width="400px" append-to-body>
      <el-form @submit.prevent="saveTagItem">
        <el-form-item label="学科">
          <el-select v-model="tagForm.subject" :disabled="!!editingTagItem">
            <el-option label="物理" value="physics" />
            <el-option label="数学" value="math" />
            <el-option label="化学" value="chemistry" />
            <el-option label="英语" value="english" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="tagForm.name" placeholder="标签名称" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="tagForm.category" :disabled="!!editingTagItem">
            <el-option label="知识点" value="knowledge" />
            <el-option label="技能" value="skill" />
            <el-option label="错因" value="error_type" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色（可选）">
          <el-color-picker v-model="tagForm.color" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateTag = false; editingTagItem = null">取消</el-button>
        <el-button type="primary" @click="saveTagItem" :disabled="!tagForm.name">保存</el-button>
      </template>
    </el-dialog>

    <!-- Batch Tag Dialog -->
    <el-dialog v-model="showTagDialog" title="批量打标签" width="450px">
      <el-select v-model="batchTagSubject" placeholder="按学科筛选" clearable @change="() => {}" style="width: 100%; margin-bottom: 8px;">
        <el-option label="物理" value="physics" />
        <el-option label="数学" value="math" />
        <el-option label="化学" value="chemistry" />
        <el-option label="英语" value="english" />
      </el-select>
      <el-select v-model="selectedTagIds" multiple placeholder="选择标签" filterable style="width: 100%;">
        <el-option v-for="t in batchFilteredTags" :key="t.id" :label="`${subjectText(t.subject)} / ${categoryText(t.category)} / ${t.name}`" :value="t.id" />
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
import { renderFullContent, renderPreview, renderOptionContent } from '../utils/render.js'

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
const batchTagSubject = ref('')

// Tag management state
const showTagMgmt = ref(false)
const showCreateTag = ref(false)
const editingTagItem = ref(null)
const mgmtSubject = ref('physics')
const mgmtCategory = ref('knowledge')
const tagForm = reactive({ name: '', subject: 'physics', category: 'knowledge', color: null })
const detailTagSelect = ref('')
const aiTagging = ref(false)

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
  tag_ids: [],
})

// Dynamic subjects from API
const availableSubjects = computed(() => {
  const subjects = [
    { value: 'physics', label: '物理' },
    { value: 'math', label: '数学' },
    { value: 'chemistry', label: '化学' },
    { value: 'english', label: '英语' },
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
    if (filters.tag_ids?.length) params.tag_ids = filters.tag_ids.join(',')

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
  q.content = d.content
  if (d.options && d.options.length > 0) q.options = d.options
  if (d.answer) q.answer = d.answer
  if (d.explanation) q.explanation = d.explanation
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
const subjectText = (s) => ({ physics: '物理', math: '数学', chemistry: '化学', english: '英语' })[s] || s || '未分类'

// ── Tag Management ──

const filteredMgmtTags = computed(() => allTags.value.filter(t => t.subject === mgmtSubject.value && t.category === mgmtCategory.value))

const batchFilteredTags = computed(() => {
  if (!batchTagSubject.value) return allTags.value
  return allTags.value.filter(t => t.subject === batchTagSubject.value)
})

const availableTagsForDetail = computed(() => {
  if (!detailQuestion.value) return allTags.value
  const currentIds = new Set(detailQuestion.value.tags?.map(t => t.id) || [])
  const subject = detailQuestion.value.subject
  return allTags.value.filter(t => !currentIds.has(t.id) && (!subject || !t.subject || t.subject === subject))
})

const addTagToDetail = async () => {
  if (!detailTagSelect.value || !detailQuestion.value) return
  try {
    await axios.post('/api/questions/batch-tag', {
      question_ids: [detailQuestion.value.id],
      tag_ids: [detailTagSelect.value],
    })
    const tag = allTags.value.find(t => t.id === detailTagSelect.value)
    if (tag && !detailQuestion.value.tags) detailQuestion.value.tags = []
    if (tag) detailQuestion.value.tags.push({ id: tag.id, name: tag.name, category: tag.category, color: tag.color })
    detailTagSelect.value = ''
    loadQuestions()
  } catch (e) {
    ElMessage.error('添加标签失败')
  }
}

const removeTagFromDetail = async (tagId) => {
  if (!detailQuestion.value) return
  try {
    await axios.post('/api/questions/batch-untag', {
      question_ids: [detailQuestion.value.id],
      tag_ids: [tagId],
    })
    detailQuestion.value.tags = detailQuestion.value.tags?.filter(t => t.id !== tagId) || []
    loadQuestions()
  } catch (e) {
    ElMessage.error('移除标签失败')
  }
}

const aiTagSingle = async () => {
  if (!detailQuestion.value) return
  aiTagging.value = true
  try {
    const res = await axios.post('/api/questions/batch-ai-tag', {
      question_ids: [detailQuestion.value.id],
    })
    if (res.data.tagged > 0) {
      ElMessage.success('AI 打标完成')
      // Reload question to get updated tags
      const qRes = await axios.get(`/api/questions/${detailQuestion.value.id}`)
      detailQuestion.value.tags = qRes.data.tags || []
      loadQuestions()
    } else {
      ElMessage.info('AI 未找到合适标签')
    }
  } catch (e) {
    ElMessage.error('AI 打标失败')
  } finally {
    aiTagging.value = false
  }
}

const batchAITag = async () => {
  if (selectedIds.size === 0) return
  try {
    await ElMessageBox.confirm(
      `将对 ${selectedIds.size} 道题执行 AI 自动打标，每道题会调用一次 AI。继续？`,
      'AI 批量打标', { type: 'info' }
    )
  } catch { return }
  try {
    const res = await axios.post('/api/questions/batch-ai-tag', {
      question_ids: [...selectedIds],
    })
    ElMessage.success(`AI 打标完成：${res.data.tagged} 道题`)
    loadQuestions()
  } catch (e) {
    ElMessage.error('AI 批量打标失败')
  }
}

// Tag CRUD
const editTagItem = (tag) => {
  editingTagItem.value = tag
  tagForm.name = tag.name
  tagForm.subject = tag.subject || 'physics'
  tagForm.category = tag.category
  tagForm.color = tag.color
  showCreateTag.value = true
}

const saveTagItem = async () => {
  try {
    if (editingTagItem.value) {
      await axios.put(`/api/tags/${editingTagItem.value.id}`, { ...tagForm })
      ElMessage.success('标签已更新')
    } else {
      await axios.post('/api/tags', { name: tagForm.name, subject: mgmtSubject.value, category: mgmtCategory.value, color: tagForm.color })
      ElMessage.success('标签已创建')
    }
    showCreateTag.value = false
    editingTagItem.value = null
    tagForm.name = ''
    tagForm.color = null
    loadTags()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const deleteTagItem = async (tag) => {
  try {
    await ElMessageBox.confirm(`确定删除标签“${tag.name}”？`, '警告', { type: 'warning' })
    await axios.delete(`/api/tags/${tag.id}`)
    ElMessage.success('已删除')
    loadTags()
    loadQuestions()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

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
.opt-line { font-size: 12px; color: #909399; line-height: 1.5; }
.opt-line :deep(img) { max-height: 24px; vertical-align: middle; margin: 0 2px; border-radius: 2px; }
.opt-line :deep(.katex) { font-size: 0.95em; }

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
  max-width: min(100%, 400px);
  max-height: 300px;
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

/* Rendered options in detail drawer */
.option-rendered {
  padding: 6px 10px;
  margin-bottom: 4px;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
  color: #303133;
}
.option-rendered :deep(img) {
  max-height: 40px;
  vertical-align: middle;
  margin: 0 4px;
  border-radius: 3px;
}
.option-rendered :deep(.katex) {
  font-size: 1.0em;
}

/* Tag management */
.mgmt-tag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  font-size: 13px;
  min-width: 120px;
}
.mgmt-tag-actions {
  opacity: 0;
  transition: opacity 0.2s;
  margin-left: 8px;
}
.mgmt-tag:hover .mgmt-tag-actions {
  opacity: 1;
}
</style>
