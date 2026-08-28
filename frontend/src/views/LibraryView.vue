<template>
  <div class="review-view">
    <div class="review-header">
      <h2>题目复核</h2>
      <p class="subtitle">审核 OCR 识别结果，编辑修正后通过</p>
    </div>

    <!-- Filters -->
    <el-card class="filter-card">
      <el-row :gutter="16" align="middle">
        <el-col :span="6">
          <el-select v-model="filters.source_id" placeholder="按试卷筛选" clearable @change="loadQuestions">
            <el-option
              v-for="s in sources"
              :key="s.id"
              :label="s.filename"
              :value="s.id"
            />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-select v-model="filters.review_status" placeholder="审核状态" clearable @change="loadQuestions">
            <el-option label="待审核" value="pending" />
            <el-option label="已通过" value="approved" />
            <el-option label="已驳回" value="rejected" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-select v-model="filters.question_type" placeholder="题型" clearable @change="loadQuestions">
            <el-option label="选择题" value="选择题" />
            <el-option label="填空题" value="填空题" />
            <el-option label="解答题" value="解答题" />
            <el-option label="实验题" value="实验题" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-tag type="info">共 {{ total }} 题</el-tag>
        </el-col>
        <el-col :span="6" style="text-align: right;">
          <el-button @click="loadQuestions">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- Question Cards -->
    <div class="question-list" v-if="questions.length > 0">
      <el-card
        v-for="q in questions"
        :key="q.id"
        class="question-card"
        :class="{ 'needs-review': q.needs_review && q.review_status === 'pending' }"
      >
        <div class="q-header">
          <div class="q-meta">
            <span class="q-number">第 {{ q.question_number }} 题</span>
            <el-tag v-if="q.question_type" size="small" type="info">{{ q.question_type }}</el-tag>
            <el-tag v-if="q.difficulty" size="small">难度 {{ q.difficulty }}</el-tag>
            <el-tag v-if="q.score" size="small">{{ q.score }}分</el-tag>
            <el-tag
              :type="reviewTagType(q.review_status)"
              size="small"
            >{{ reviewText(q.review_status) }}</el-tag>
          </div>
          <div class="q-actions">
            <el-button
              v-if="q.review_status === 'pending'"
              type="success"
              size="small"
              @click="reviewQuestion(q.id, 'approve')"
            >通过</el-button>
            <el-button
              v-if="q.review_status === 'pending'"
              type="danger"
              size="small"
              @click="reviewQuestion(q.id, 'reject')"
            >驳回</el-button>
            <el-button
              v-if="q.review_status !== 'pending'"
              text
              size="small"
              @click="reviewQuestion(q.id, q.review_status === 'approved' ? 'reject' : 'approve')"
            >切换状态</el-button>
            <el-button
              type="danger"
              text
              size="small"
              @click="deleteQuestion(q.id)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>

        <!-- Content (editable) -->
        <div class="q-content">
          <el-input
            v-model="q.content"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 10 }"
            placeholder="题目内容 (Markdown)"
          />
        </div>

        <!-- Options (for multiple choice) -->
        <div class="q-options" v-if="q.options && q.options.length > 0">
          <div v-for="(opt, idx) in q.options" :key="idx" class="option-row">
            <span class="option-label">{{ opt.label || String.fromCharCode(65 + idx) }}.</span>
            <el-input
              v-model="opt.content"
              size="small"
              style="flex: 1;"
            />
          </div>
        </div>

        <!-- Answer & Explanation -->
        <el-row :gutter="12" class="q-answer-row">
          <el-col :span="12">
            <el-input
              v-model="q.answer"
              placeholder="答案"
              size="small"
            >
              <template #prepend>答案</template>
            </el-input>
          </el-col>
          <el-col :span="12">
            <el-input
              v-model="q.explanation"
              placeholder="解析"
              size="small"
            >
              <template #prepend>解析</template>
            </el-input>
          </el-col>
        </el-row>

        <!-- Save button -->
        <div class="q-footer">
          <el-button
            type="primary"
            size="small"
            @click="saveQuestion(q)"
            :loading="saving === q.id"
          >保存修改</el-button>
          <span v-if="q.ocr_confidence" class="confidence">
            OCR 置信度: {{ (q.ocr_confidence * 100).toFixed(1) }}%
          </span>
        </div>
      </el-card>
    </div>

    <!-- Empty state -->
    <el-card v-else class="empty-card">
      <el-empty description="暂无题目，请先上传试卷">
        <el-button type="primary" @click="$router.push('/upload')">去上传</el-button>
      </el-empty>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const route = useRoute()
const router = useRouter()

const sources = ref([])
const questions = ref([])
const total = ref(0)
const saving = ref(null)

const filters = ref({
  source_id: route.query.source || '',
  review_status: '',
  question_type: '',
})

const loadSources = async () => {
  try {
    const res = await axios.get('/api/sources')
    sources.value = res.data.sources
  } catch (e) {
    console.error('Failed to load sources:', e)
  }
}

const loadQuestions = async () => {
  try {
    const params = {}
    if (filters.value.source_id) params.source_id = filters.value.source_id
    if (filters.value.review_status) params.review_status = filters.value.review_status
    if (filters.value.question_type) params.question_type = filters.value.question_type

    const res = await axios.get('/api/questions', { params })
    questions.value = res.data.questions
    total.value = res.data.total
  } catch (e) {
    console.error('Failed to load questions:', e)
    ElMessage.error('加载题目失败')
  }
}

const saveQuestion = async (q) => {
  saving.value = q.id
  try {
    await axios.put(`/api/questions/${q.id}`, {
      content: q.content,
      options: q.options,
      answer: q.answer,
      explanation: q.explanation,
    })
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = null
  }
}

const reviewQuestion = async (id, action) => {
  try {
    await axios.post(`/api/questions/${id}/review?action=${action}`)
    ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
    loadQuestions()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

const deleteQuestion = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除此题目？', '确认', { type: 'warning' })
    await axios.delete(`/api/questions/${id}`)
    ElMessage.success('已删除')
    loadQuestions()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

const reviewTagType = (status) => {
  const map = { pending: 'warning', approved: 'success', rejected: 'danger' }
  return map[status] || 'info'
}

const reviewText = (status) => {
  const map = { pending: '待审核', approved: '已通过', rejected: '已驳回' }
  return map[status] || status
}

onMounted(() => {
  loadSources()
  loadQuestions()
})
</script>

<style scoped>
.review-view {
  max-width: 1000px;
  margin: 0 auto;
}

.review-header {
  margin-bottom: 16px;
}

.subtitle {
  color: #909399;
  margin-top: 4px;
}

.filter-card {
  margin-bottom: 16px;
}

.question-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.question-card {
  transition: border-color 0.2s;
}

.question-card.needs-review {
  border-left: 3px solid #e6a23c;
}

.q-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.q-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.q-number {
  font-weight: bold;
  font-size: 15px;
  color: #303133;
}

.q-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.q-content {
  margin-bottom: 12px;
}

.q-options {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.option-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.option-row:last-child {
  margin-bottom: 0;
}

.option-label {
  font-weight: bold;
  color: #606266;
  min-width: 20px;
}

.q-answer-row {
  margin-bottom: 12px;
}

.q-footer {
  display: flex;
  align-items: center;
  gap: 12px;
}

.confidence {
  font-size: 12px;
  color: #909399;
}

.empty-card {
  margin-top: 40px;
}
</style>
