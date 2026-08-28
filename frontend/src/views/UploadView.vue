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

    <!-- Processing Queue — active jobs with progress -->
    <el-card class="queue-card" v-if="activeJobs.length > 0">
      <template #header>
        <div class="card-header">
          <span>处理队列</span>
          <el-button text @click="refreshJobs">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </template>
      <div v-for="job in activeJobs" :key="job.id" class="job-item">
        <div class="job-header">
          <span class="job-filename">{{ job.filename || '未知文件' }}</span>
          <el-tag :type="jobStatusType(job)" size="small">
            {{ jobStatusText(job) }}
          </el-tag>
        </div>
        <el-progress
          :percentage="Math.round(job.progress || 0)"
          :status="job.status === 'failed' ? 'exception' : job.status === 'success' ? 'success' : ''"
          :stroke-width="16"
          :text-inside="true"
          style="margin-top: 8px;"
        />
        <div v-if="job.error_message" class="job-error">
          <el-icon style="color: #f56c6c; margin-right: 4px;"><WarningFilled /></el-icon>
          {{ job.error_message }}
          <el-button
            v-if="job.source_id"
            type="primary"
            size="small"
            link
            @click="retrySource(job.source_id)"
            style="margin-left: 8px;"
          >
            重试
          </el-button>
        </div>
      </div>
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
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button
              v-if="row.ocr_status === 'error'"
              text
              type="warning"
              size="small"
              @click="retrySource(row.id)"
            >
              重试
            </el-button>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
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
    jobs.value = res.data
  } catch (e) {
    console.error('Failed to load jobs:', e)
  }
}

// Active jobs: not yet completed (running, queued) or recently failed
const activeJobs = computed(() => {
  return jobs.value.filter(j =>
    j.status === 'queued' || j.status === 'running' || j.status === 'failed'
  )
})

const jobStatusType = (job) => {
  const map = { queued: 'info', running: 'warning', success: 'success', failed: 'danger' }
  return map[job.status] || 'info'
}

const jobStatusText = (job) => {
  if (job.status === 'queued') return '排队中'
  if (job.status === 'running') return '处理中'
  if (job.status === 'success') return '已完成'
  if (job.status === 'failed') return '失败'
  return job.status
}

let pollTimer = null
const startPolling = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    await loadSources()
    await loadJobs()
    // Stop polling if no active jobs
    if (activeJobs.value.length === 0) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }, 2000)
}

const refreshJobs = () => {
  loadSources()
  loadJobs()
}

const retrySource = async (sourceId) => {
  try {
    await axios.post(`/api/sources/${sourceId}/retry`)
    ElMessage.success('重新开始处理')
    loadSources()
    startPolling()
  } catch (e) {
    ElMessage.error('重试失败: ' + (e.response?.data?.detail || e.message))
  }
}

const goToLibrary = (sourceId) => {
  router.push(`/library?source=${sourceId}`)
}

const statusType = (status) => {
  const map = { pending: 'warning', processing: 'warning', done: 'success', error: 'danger' }
  return map[status] || 'info'
}

const statusText = (status) => {
  const map = { pending: '等待中', processing: '处理中', done: '已完成', error: '失败' }
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
  // Start polling if there are active jobs
  if (activeJobs.value.length > 0) {
    startPolling()
  }
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
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

.job-item {
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
}

.job-item:last-child {
  border-bottom: none;
}

.job-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.job-filename {
  font-weight: 500;
  color: #303133;
}

.job-error {
  margin-top: 8px;
  padding: 8px 12px;
  background: #fef0f0;
  border-radius: 4px;
  color: #f56c6c;
  font-size: 13px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
</style>
