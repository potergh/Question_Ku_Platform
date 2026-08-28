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
        :multiple="true"
      >
        <el-icon class="upload-icon"><Upload /></el-icon>
        <div class="upload-text">
          拖拽文件到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="upload-tip">
            支持 PDF / DOCX / PPTX / TXT 格式，可多文件批量上传
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
            </el-select>
          </div>
        </template>
      </el-upload>
    </el-card>

    <!-- Pending Uploads (confirmation queue) -->
    <el-card class="queue-card" v-if="pendingFiles.length > 0">
      <template #header>
        <div class="card-header">
          <span>待上传文件 ({{ pendingFiles.length }})</span>
          <div>
            <el-button text type="danger" size="small" @click="pendingFiles = []">
              <el-icon><Delete /></el-icon> 清空
            </el-button>
            <el-button type="primary" size="small" @click="uploadPending" :loading="uploading">
              <el-icon><Upload /></el-icon> 开始上传
            </el-button>
          </div>
        </div>
      </template>
      <div v-for="(file, idx) in pendingFiles" :key="idx" class="pending-item">
        <el-icon style="color: #409eff;"><Document /></el-icon>
        <span class="pending-name">{{ file.name }}</span>
        <span class="pending-size">{{ formatSize(file.size) }}</span>
        <el-button text type="danger" size="small" @click="pendingFiles.splice(idx, 1)">
          <el-icon><Close /></el-icon>
        </el-button>
      </div>
    </el-card>

    <!-- Processing Queue -->
    <el-card class="queue-card" v-if="activeJobs.length > 0">
      <template #header>
        <div class="card-header">
          <span>处理队列</span>
          <div>
            <el-button text @click="refreshJobs">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
            <el-button text type="danger" @click="clearCompletedJobs" :loading="clearingJobs">
              <el-icon><Delete /></el-icon> 清除已完成
            </el-button>
          </div>
        </div>
      </template>
      <div v-for="job in activeJobs" :key="job.id" class="job-item">
        <div class="job-header">
          <span class="job-filename">{{ job.filename || '未知文件' }}</span>
          <div class="job-header-actions">
            <el-tag :type="jobStatusType(job)" size="small">
              {{ jobStatusText(job) }}
            </el-tag>
            <el-button
              v-if="job.status === 'queued' || job.status === 'running'"
              text
              type="danger"
              size="small"
              @click="cancelJob(job)"
              :loading="job.cancelling"
            >
              取消
            </el-button>
          </div>
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
            v-if="job.source_id && job.error_message !== '用户取消'"
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
          <div>
            <el-button 
              v-if="selectedSourceIds.size > 0" 
              text 
              type="danger" 
              size="small" 
              @click="batchDeleteSources"
            >
              <el-icon><Delete /></el-icon> 批量删除 ({{ selectedSourceIds.size }})
            </el-button>
          </div>
        </div>
      </template>
      <el-table :data="sources" stripe @selection-change="onSourceSelectionChange">
        <el-table-column type="selection" width="40" />
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
        <el-table-column label="操作" width="180">
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
            <el-button 
              v-if="row.ocr_status === 'done'"
              text 
              type="primary" 
              size="small" 
              @click="goToLibrary(row.id)"
            >
              查看
            </el-button>
            <el-button text type="danger" size="small" @click="deleteSource(row.id)">
              删除
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
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const router = useRouter()
const selectedSubject = ref('physics')
const uploading = ref(false)
const sources = ref([])
const jobs = ref([])
const pendingFiles = ref([])
const selectedSourceIds = ref(new Set())
const clearingJobs = ref(false)

const beforeUpload = (file) => {
  // Add to pending list instead of immediate upload
  pendingFiles.value.push(file)
  return false // Prevent auto-upload
}

const uploadPending = async () => {
  if (pendingFiles.value.length === 0) return
  
  uploading.value = true
  const files = [...pendingFiles.value]
  pendingFiles.value = []
  
  let successCount = 0
  let failCount = 0
  
  for (const file of files) {
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('subject', selectedSubject.value)
      
      await axios.post('/api/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      successCount++
    } catch (e) {
      failCount++
      console.error(`Failed to upload ${file.name}:`, e)
    }
  }
  
  uploading.value = false
  
  if (successCount > 0) {
    ElMessage.success(`成功上传 ${successCount} 个文件，开始 OCR 处理`)
  }
  if (failCount > 0) {
    ElMessage.error(`${failCount} 个文件上传失败`)
  }
  
  loadSources()
  startPolling()
}

const onUploadSuccess = (response) => {
  // Legacy handler for single file upload
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

const clearCompletedJobs = async () => {
  try {
    await ElMessageBox.confirm('确定清除所有已完成和失败的任务记录？', '提示')
    clearingJobs.value = true
    await axios.post('/api/jobs/clear-failed')
    ElMessage.success('已清除')
    loadJobs()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('操作失败')
  } finally {
    clearingJobs.value = false
  }
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

const cancelJob = async (job) => {
  try {
    await ElMessageBox.confirm('确定取消此任务？OCR处理将停止。', '提示', { type: 'warning' })
    job.cancelling = true
    await axios.post(`/api/jobs/${job.id}/cancel`)
    ElMessage.success('任务已取消')
    loadJobs()
    loadSources()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('取消失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    job.cancelling = false
  }
}

const deleteSource = async (sourceId) => {
  try {
    await ElMessageBox.confirm('确定删除此试卷？相关题目和文件将被永久删除。', '警告', { type: 'warning' })
    await axios.delete(`/api/sources/${sourceId}`)
    ElMessage.success('已删除')
    loadSources()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

const onSourceSelectionChange = (selection) => {
  selectedSourceIds.value = new Set(selection.map(s => s.id))
}

const batchDeleteSources = async () => {
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selectedSourceIds.value.size} 个试卷？`, '警告', { type: 'warning' })
    await axios.post('/api/sources/batch-delete', { source_ids: [...selectedSourceIds.value] })
    ElMessage.success('批量删除成功')
    selectedSourceIds.value.clear()
    loadSources()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('操作失败')
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
  const map = { physics: '物理', math: '数学', chemistry: '化学', english: '英语' }
  return map[subject] || subject || '-'
}

const formatTime = (dt) => {
  if (!dt) return '-'
  return new Date(dt).toLocaleString('zh-CN')
}

const formatSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
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
  max-width: 900px;
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

.pending-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.pending-item:last-child {
  border-bottom: none;
}

.pending-name {
  flex: 1;
  font-weight: 500;
  color: #303133;
}

.pending-size {
  color: #909399;
  font-size: 13px;
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

.job-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
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
