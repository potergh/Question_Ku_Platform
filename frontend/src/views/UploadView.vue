<template>
  <div class="upload-view">
    <h2>上传试卷</h2>
    <p class="subtitle">上传 PDF/Word/PPT 文件，系统自动 OCR 切题</p>

    <!-- Upload Area -->
    <el-card class="upload-card">
      <el-upload
        drag
        action="/api/upload"
        :data="{ subject: selectedSubject }"
        :before-upload="beforeUpload"
        :on-success="onUploadSuccess"
        :on-error="onUploadError"
        :show-file-list="false"
        :disabled="uploading"
      >
        <el-icon class="upload-icon"><Upload /></el-icon>
        <div class="upload-text">
          拖拽文件到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="upload-tip">
            支持 PDF / DOCX / PPTX / TXT 格式
            <el-select
              v-model="selectedSubject"
              placeholder="选择学科（可选）"
              size="small"
              style="width: 140px; margin-left: 12px;"
            >
              <el-option label="物理" value="physics" />
              <el-option label="数学" value="math" />
              <el-option label="化学" value="chemistry" />
              <el-option label="英语" value="english" />
              <el-option label="语文" value="chinese" />
            </el-select>
          </div>
        </template>
      </el-upload>
    </el-card>

    <!-- Processing Queue -->
    <el-card class="queue-card" v-if="jobs.length > 0">
      <template #header>
        <div class="card-header">
          <span>处理队列</span>
          <el-button text @click="refreshJobs">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </template>
      <el-table :data="jobs" stripe>
        <el-table-column prop="filename" label="文件名" />
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.ocr_status)">
              {{ statusText(row.ocr_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question_count" label="题目数" width="80" />
        <el-table-column prop="created_at" label="上传时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="goToLibrary(row.id)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Recent Uploads -->
    <el-card class="queue-card" v-if="sources.length > 0">
      <template #header>
        <div class="card-header">
          <span>已上传试卷</span>
        </div>
      </template>
      <el-table :data="sources" stripe>
        <el-table-column prop="filename" label="文件名" />
        <el-table-column prop="subject" label="学科" width="100">
          <template #default="{ row }">
            {{ subjectText(row.subject) }}
          </template>
        </el-table-column>
        <el-table-column prop="ocr_status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.ocr_status)">
              {{ statusText(row.ocr_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question_count" label="题目数" width="80" />
        <el-table-column prop="created_at" label="上传时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="goToLibrary(row.id)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const router = useRouter()
const selectedSubject = ref('physics')
const uploading = ref(false)
const sources = ref([])
const jobs = ref([])

const beforeUpload = (file) => {
  uploading.value = true
  return true
}

const onUploadSuccess = (response) => {
  uploading.value = false
  ElMessage.success(`上传成功，开始 OCR 处理`)
  loadSources()
  // Start polling for job status
  startPolling()
}

const onUploadError = (error) => {
  uploading.value = false
  ElMessage.error('上传失败: ' + (error.message || '未知错误'))
}

const loadSources = async () => {
  try {
    const res = await axios.get('/api/sources')
    sources.value = res.data.sources
  } catch (e) {
    console.error('Failed to load sources:', e)
  }
}

const loadJobs = async () => {
  try {
    const res = await axios.get('/api/jobs')
    jobs.value = res.data.filter(j => j.status !== 'success' && j.status !== 'failed')
  } catch (e) {
    console.error('Failed to load jobs:', e)
  }
}

let pollTimer = null
const startPolling = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    await loadSources()
    await loadJobs()
    // Stop polling if no pending jobs
    const hasPending = jobs.value.some(j => j.status === 'queued' || j.status === 'running')
    if (!hasPending) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }, 3000)
}

const refreshJobs = () => {
  loadSources()
  loadJobs()
}

const goToLibrary = (sourceId) => {
  router.push(`/library?source=${sourceId}`)
}

const statusType = (status) => {
  const map = { pending: 'warning', done: 'success', error: 'danger' }
  return map[status] || 'info'
}

const statusText = (status) => {
  const map = { pending: '处理中', done: '已完成', error: '失败' }
  return map[status] || status
}

const subjectText = (subject) => {
  const map = { physics: '物理', math: '数学', chemistry: '化学', english: '英语', chinese: '语文' }
  return map[subject] || subject || '-'
}

const formatTime = (dt) => {
  if (!dt) return '-'
  return new Date(dt).toLocaleString('zh-CN')
}

onMounted(() => {
  loadSources()
  loadJobs()
})
</script>

<style scoped>
.upload-view {
  max-width: 800px;
  margin: 0 auto;
}

.subtitle {
  color: #909399;
  margin-bottom: 20px;
}

.upload-card {
  margin-bottom: 20px;
}

.upload-icon {
  font-size: 67px;
  color: #909399;
  margin-bottom: 16px;
}

.upload-text {
  color: #606266;
  font-size: 16px;
}

.upload-text em {
  color: #409eff;
  font-style: normal;
}

.upload-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 8px;
  color: #909399;
  font-size: 13px;
}

.queue-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
