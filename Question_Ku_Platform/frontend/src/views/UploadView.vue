<template>
  <div class="page-shell page-enter">
    <!-- 去掉渐变图标章：图标方块 + 渐变几乎是最容易被认出的模板指纹。
         改成印刷式页头——标题 + 一条流程走向，扫一眼就知道会经过哪几步。 -->
    <header class="page-head" style="--i: 0">
      <span class="icon-chip icon-chip--sm bg-tint-brand text-on-tint-brand">
        <el-icon :size="17"><Upload /></el-icon>
      </span>
      <h1 class="page-title">导入试卷</h1>
      <p class="page-subtitle">切题 → 暂存区复核 → 确认后入库</p>
    </header>

    <!-- 导入卡片：参数行 + 拖拽区 -->
    <section class="panel">
      <div class="flex flex-wrap items-center gap-x-8 gap-y-3 border-b border-line px-6 py-4">
        <div class="flex items-center gap-2.5">
          <span class="text-sm text-ink-soft">识别通道</span>
          <el-radio-group v-model="selectedChannel" size="small">
            <el-radio-button v-for="key in CHANNEL_ORDER" :key="key" :value="key">
              {{ CHANNEL_META[key].label }}
            </el-radio-button>
          </el-radio-group>
        </div>
        <div class="flex items-center gap-2.5">
          <span class="text-sm text-ink-soft">文档形态</span>
          <el-select v-model="selectedDocKind" size="small" style="width: 120px">
            <el-option label="自动判定" value="auto" />
            <el-option label="试卷" value="paper" />
            <el-option label="讲义" value="handout" />
          </el-select>
        </div>
        <div class="flex items-center gap-2.5">
          <span class="text-sm text-ink-soft">学科</span>
          <el-select
            v-model="selectedSubject"
            placeholder="可选"
            size="small"
            style="width: 120px"
          >
            <el-option label="物理" value="physics" />
            <el-option label="数学" value="math" />
            <el-option label="化学" value="chemistry" />
            <el-option label="英语" value="english" />
          </el-select>
        </div>
        <!--
          通道选择建议放在**行尾**，而不是紧跟通道：basis-full 在 flex-wrap 容器里
          强制换行，插在通道与文档形态之间会把后两项挤到第二行。
          格式/流程那类说明留给拖拽区的 CHANNEL_META.hint，这里只回答"该选哪个" ——
          选错通道要等识别跑完（额度已经扣了）才暴露，所以这行必须在选的时候就看得见。
        -->
        <p class="basis-full text-xs leading-relaxed text-ink-muted">
          {{ CHANNEL_META[selectedChannel].pick }}
        </p>
      </div>

      <div class="p-6">
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
          class="upload-drop"
        >
          <div class="grid place-items-center py-2">
            <!-- 底已经是 sunken 了，芯片再用 tint-brand 会几乎看不见（95% vs 94.4%）：
                 有色底上用白底芯片反而更清楚。 -->
            <span
              class="icon-chip icon-chip--lg bg-surface text-primary-500 shadow-[var(--shadow-xs)] mb-3.5"
            >
              <el-icon :size="22"><Upload /></el-icon>
            </span>
            <p class="text-base text-ink">
              拖拽文件到此处，或 <span class="font-medium text-primary-500">点击选择</span>
            </p>
            <p class="mt-2 text-sm text-ink-muted">
              {{ channelMeta(selectedChannel).hint }}
            </p>
          </div>
        </el-upload>
      </div>
    </section>

    <!-- 待上传队列：先挑角色、可配对答案文档，点「开始上传」才真正发请求 -->
    <section v-if="pendingFiles.length > 0" class="mt-5 rounded-card border border-line bg-surface">
      <header class="flex items-center justify-between px-6 pb-3 pt-5">
        <h2 class="text-base font-semibold text-ink">
          待上传
          <span class="ml-1.5 text-sm font-normal text-ink-muted">
            {{ pendingFiles.length }} 个文件
          </span>
        </h2>
        <div class="flex items-center gap-2">
          <el-button text size="small" @click="pendingFiles = []">清空</el-button>
          <el-button type="primary" size="small" :loading="uploading" @click="uploadPending">
            开始上传
          </el-button>
        </div>
      </header>

      <div
        v-if="channelMeta(selectedChannel).companion"
        class="flex flex-wrap items-center gap-2.5 border-t border-line bg-primary-50/50 px-6 py-3"
      >
        <span class="text-sm text-ink-soft">配对答案文档</span>
        <el-select
          v-model="companionFilename"
          clearable
          size="small"
          placeholder="可选：需先上传答案文档"
          style="width: 280px"
        >
          <el-option
            v-for="doc in answerDocOptions"
            :key="doc.id"
            :label="doc.filename"
            :value="doc.filename"
          />
        </el-select>
        <span class="text-xs text-ink-muted">答案文档不单独产题，只作为第三答案来源按题号配对</span>
      </div>

      <ul class="divide-y divide-line border-t border-line">
        <li
          v-for="(item, idx) in pendingFiles"
          :key="idx"
          class="flex items-center gap-3 px-6 py-3"
        >
          <el-icon class="shrink-0 text-primary-500"><Document /></el-icon>
          <span class="min-w-0 flex-1 truncate text-sm font-medium text-ink">
            {{ item.raw.name }}
          </span>
          <span class="tabular-nums shrink-0 text-sm text-ink-muted">
            {{ formatSize(item.raw.size) }}
          </span>
          <el-select v-model="item.role" size="small" style="width: 128px">
            <el-option label="试卷 / 讲义" value="paper" />
            <el-option label="答案文档" value="answer_doc" />
          </el-select>
          <el-button text size="small" @click="pendingFiles.splice(idx, 1)">
            <el-icon><Close /></el-icon>
          </el-button>
        </li>
      </ul>
    </section>

    <!-- 处理队列：只显示进行中与失败的任务 -->
    <section v-if="activeJobs.length > 0" class="mt-5 rounded-card border border-line bg-surface">
      <header class="flex items-center justify-between px-6 pb-3 pt-5">
        <h2 class="text-base font-semibold text-ink">处理中</h2>
        <div class="flex items-center gap-2">
          <el-button text size="small" @click="refreshJobs">
            <el-icon><Refresh /></el-icon>&nbsp;刷新
          </el-button>
          <el-button text size="small" type="danger" :loading="clearingJobs" @click="clearCompletedJobs">
            清除记录
          </el-button>
        </div>
      </header>

      <ul class="divide-y divide-line border-t border-line">
        <li v-for="job in activeJobs" :key="job.id" class="px-6 py-4">
          <div class="flex items-center justify-between gap-3">
            <span class="min-w-0 flex-1 truncate text-sm font-medium text-ink">
              {{ job.filename || '未知文件' }}
            </span>
            <div class="flex shrink-0 items-center gap-2">
              <el-tag :type="jobStatusType(job)" size="small">{{ jobStatusText(job) }}</el-tag>
              <el-button
                v-if="job.status === 'queued' || job.status === 'running'"
                text
                type="danger"
                size="small"
                :loading="job.cancelling"
                @click="cancelJob(job)"
              >
                取消
              </el-button>
              <el-button
                text
                type="danger"
                size="small"
                :loading="job.deleting"
                @click="deleteJob(job)"
              >
                删除
              </el-button>
            </div>
          </div>
          <el-progress
            class="mt-2.5"
            :percentage="Math.round(job.progress || 0)"
            :status="job.status === 'failed' ? 'exception' : job.status === 'success' ? 'success' : ''"
            :stroke-width="14"
            :text-inside="true"
          />
          <div
            v-if="job.error_message"
            class="mt-2.5 flex flex-wrap items-center gap-x-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600"
          >
            <el-icon><WarningFilled /></el-icon>
            <span class="min-w-0 flex-1">{{ job.error_message }}</span>
            <el-button
              v-if="job.source_id && job.error_message !== '用户取消'"
              link
              type="primary"
              size="small"
              @click="retrySource(job.source_id)"
            >
              重试
            </el-button>
          </div>
        </li>
      </ul>
    </section>

    <!-- 已导入列表：staging = 待确认（要点「预览确认」才入库） -->
    <section v-if="sources.length > 0" class="mt-5 overflow-hidden rounded-card border border-line bg-surface">
      <header class="flex items-center justify-between px-6 pb-3 pt-5">
        <h2 class="text-base font-semibold text-ink">
          已导入
          <span class="ml-1.5 text-sm font-normal text-ink-muted">
            {{ sources.length }} 份
          </span>
        </h2>
        <el-button
          v-if="selectedSourceIds.size > 0"
          text
          type="danger"
          size="small"
          @click="batchDeleteSources"
        >
          删除选中 ({{ selectedSourceIds.size }})
        </el-button>
      </header>

      <el-table
        :data="sources"
        stripe
        class="border-t border-line"
        @selection-change="onSourceSelectionChange"
      >
        <el-table-column type="selection" width="42" />
        <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column prop="subject" label="学科" width="80">
          <template #default="{ row }">{{ subjectText(row.subject) }}</template>
        </el-table-column>
        <!-- 通道名统一成「本地OCR识别 / 大模型识别 / MinerU识别」后变长了，列宽跟着放宽 -->
        <el-table-column prop="extract_channel" label="通道" width="132">
          <template #default="{ row }">
            <el-tag :type="channelMeta(row.extract_channel).tagType" size="small" effect="plain">
              {{ channelMeta(row.extract_channel).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ocr_status" label="状态" width="150">
          <template #default="{ row }">
            <el-tag :type="statusType(row.ocr_status)" size="small" effect="plain">
              {{ statusText(row.ocr_status) }}
            </el-tag>
            <el-tag
              v-if="row.ocr_status === 'staging'"
              type="warning"
              size="small"
              class="ml-1.5"
              effect="light"
            >
              待确认
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question_count" label="题数" width="70" align="center" />
        <el-table-column prop="created_at" label="上传时间" width="165">
          <template #default="{ row }">
            <span class="tabular-nums text-sm">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <!--
          操作列只留一个「查看」。
          以前 done 状态下「预览确认」与「查看」会**同时出现**（同一行两个入口指同一件事），
          用户得猜哪个才是看题目。现在合成一个，去处由通道决定（见 viewSource）。
        -->
        <el-table-column label="操作" width="170" align="right">
          <template #default="{ row }">
            <el-button
              v-if="isStaged(row) || row.ocr_status === 'done'"
              text
              type="primary"
              size="small"
              @click="viewSource(row)"
            >
              查看
            </el-button>
            <el-button
              v-if="row.ocr_status === 'error'"
              text
              type="warning"
              size="small"
              @click="retrySource(row.id)"
            >
              重试
            </el-button>
            <el-button text type="danger" size="small" @click="deleteSource(row.id)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 空状态：教用户这条流程怎么走，而不是只说"没有数据" -->
    <section
      v-if="sources.length === 0 && activeJobs.length === 0"
      class="mt-5 rounded-card border border-dashed border-line bg-surface px-6 py-14 text-center"
    >
      <span class="icon-chip icon-chip--lg bg-tint-brand text-on-tint-brand mx-auto mb-4">
        <el-icon :size="22"><Files /></el-icon>
      </span>
      <p class="text-base font-medium text-ink">题库还是空的</p>
      <p class="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-muted">
        拖入第一份试卷开始建库：识别完成的题目会先进入暂存区，逐题核对答案与切题边界，确认无误才进入题库。
      </p>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { CHANNEL_META, CHANNEL_ORDER, channelMeta } from '../utils/channels'

const router = useRouter()
const selectedSubject = ref('physics')
// 识别通道：local_ocr 已从 CHANNEL_ORDER 下线（导入页不再提供该选项，但历史数据
// 仍要显示，见 channels.js）。默认落在 api_extract。
// 通道只在导入页选一次；设置页不再有"识别模式"总开关，避免两处表达同一件事打架。
const selectedChannel = ref('api_extract')
// 文档形态提示：auto 时不传 doc_kind，由模型按版面判定。
const selectedDocKind = ref('auto')
// 配对的答案文档文件名（需先上传该答案文档），仅 api_extract 通道使用。
const companionFilename = ref(null)
const uploading = ref(false)
const allSources = ref([])
const jobs = ref([])
const pendingFiles = ref([])
const selectedSourceIds = ref(new Set())
const clearingJobs = ref(false)

// 答案文档不产题，不进主列表，只在下拉里作为配对候选。
const sources = computed(() => allSources.value.filter(s => s.role !== 'answer_doc'))
const answerDocOptions = computed(() => allSources.value.filter(s => s.role === 'answer_doc'))

const beforeUpload = (file) => {
  // 先进待上传队列（可逐份标记为答案文档），确认后再上传。
  pendingFiles.value.push({ raw: file, role: 'paper' })
  return false // Prevent auto-upload
}

// 选了需要 AI 的通道，凭据却没配 —— 这种失败要等识别跑完（额度已扣）才暴露，很浪费。
// 这里在上传前先算一次，只在不匹配时返回一句话，匹配就返回 null。
//
// 判据必须和后端同口径：后端已改为「只看有没有 Key / Base URL」，不再看 ai_mode
// （见 get_vision_config 与 ai_service._get_ai_config）。若这里还查 ai_mode，
// 会拿一个已经失效的条件去判断 —— 要么误挡上传，要么漏掉真正会失败的情况。
const detectConfigMismatch = async () => {
  try {
    const res = await axios.get('/api/settings')
    const s = res.data
    const channel = selectedChannel.value
    const needsAI = channel === 'api_extract' || channel === 'mineru'
    if (needsAI && !s.ai_api_key_masked) {
      return `「${channelMeta(channel).label}」要调用大模型，但还没填 API Key，识别会直接失败。`
        + '请先到「系统设置 → 大模型参数」填写 API Key。'
    }
    if (channel === 'mineru' && !s.mineru_api_token_masked) {
      return '还没填 MinerU Token，MinerU 识别会失败。'
        + '请到「系统设置 → MinerU 识别通道」填写后再上传。'
    }
  } catch {
    // 取不到配置就不猜：宁可少一句提示，也不拿错误结论挡住上传。
  }
  return null
}

/*
 * 上传前把"现在选的是哪个模式"摆出来。
 *
 * 模式是页面最上面那排单选项决定的，选中态不明显，很容易点错又因为看不出来
 * 一直错下去 —— 识别是要花额度/时间的，所以在这里给一次反悔的机会。
 * 内容用 h() 构造而**不用 dangerouslyUseHTMLString**：文件名是用户可控的，
 * 塞进 HTML 字符串就是一处注入。
 */
const confirmBeforeUpload = async () => {
  const meta = channelMeta(selectedChannel.value)
  const files = pendingFiles.value
  const warning = await detectConfigMismatch()

  const rows = [
    h('div', { class: 'uc-mode' }, [
      h('span', { class: 'uc-label' }, '识别模式'),
      h('strong', { class: 'uc-value' }, meta.label),
    ]),
    h('div', { class: 'uc-hint' }, meta.hint),
    h(
      'div',
      { class: 'uc-files' },
      files.length === 1 ? `文件：${files[0].raw.name}` : `文件：共 ${files.length} 个`,
    ),
  ]
  if (warning) rows.push(h('div', { class: 'uc-warn' }, warning))

  try {
    await ElMessageBox.confirm(h('div', { class: 'uc' }, rows), '确认开始上传', {
      // 按钮上再写一遍模式名：确认动作自己承认一遍，比只看正文可靠。
      confirmButtonText: `用「${meta.label}」上传`,
      cancelButtonText: '改一下模式',
      ...(warning ? { type: 'warning' } : {}),
    })
    return true
  } catch {
    return false // 用户取消
  }
}

const uploadPending = async () => {
  if (pendingFiles.value.length === 0) return
  if (!(await confirmBeforeUpload())) return

  uploading.value = true
  // 答案文档先传：试卷要靠文件名查到它才能挂上配对关系。
  const items = [...pendingFiles.value].sort(
    (a, b) => (a.role === 'answer_doc' ? 0 : 1) - (b.role === 'answer_doc' ? 0 : 1)
  )
  // 同批上传的答案文档此刻还没进 allSources，下拉里选不到；这里直接按同批文件自动配对。
  const batchAnswerDoc = items.find(f => f.role === 'answer_doc')
  const effectiveCompanion = companionFilename.value || (batchAnswerDoc ? batchAnswerDoc.raw.name : null)
  pendingFiles.value = []

  let successCount = 0
  let failCount = 0

  for (const item of items) {
    try {
      const formData = new FormData()
      formData.append('file', item.raw)
      formData.append('subject', selectedSubject.value)
      formData.append('channel', selectedChannel.value)
      formData.append('role', item.role)
      if (selectedDocKind.value !== 'auto') {
        formData.append('doc_kind', selectedDocKind.value)
      }
      // 配对只对试卷生效；答案文档自己不需要配对。
      // 只有支持配对的通道才发这个字段：后端对不支持的通道会直接拒收答案文档角色。
      if (item.role === 'paper' && channelMeta(selectedChannel.value).companion && effectiveCompanion) {
        formData.append('companion_filename', effectiveCompanion)
      }

      await axios.post('/api/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      successCount++
    } catch (e) {
      failCount++
      // 必须把服务端的 400 原因（同名/文件类型/通道校验等）显示出来：
      // 只报"N 个文件上传失败"，用户无法判断是自己选错文件还是要先删旧来源。
      const reason = e.response?.data?.detail || e.message || '未知错误'
      ElMessage.error(`${item.raw.name}：${reason}`)
      console.error(`Failed to upload ${item.raw.name}:`, e)
    }
  }

  uploading.value = false

  if (successCount > 0) {
    const meta = channelMeta(selectedChannel.value)
    let tip = meta.staged ? `${meta.label}完成后进入暂存区待确认` : '开始 OCR 处理'
    const hasPaper = items.some(i => i.role === 'paper')
    if (meta.companion && hasPaper && !effectiveCompanion) {
      tip = '未关联答案文档：只产题不产答案，文档内若有【答案】/答案区仍会提取'
    }
    ElMessage.success(`成功上传 ${successCount} 个文件，${tip}`)
  }
  if (failCount > 1) {
    // 单个失败上面已逐条给出原因，只有多文件时才再补一条汇总，避免连续两个弹窗
    ElMessage.error(`共 ${failCount} 个文件上传失败`)
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
    // 带上答案文档：主列表过滤掉，但配对下拉需要它们。
    const res = await axios.get('/api/sources', { params: { include_answer_docs: true } })
    allSources.value = res.data.sources
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

// 单条任务删除。任务在跑时等价于「取消并删除」：后端删掉任务行后，
// is_cancelled 把「行不存在」当成取消，任务会在下一个检查点停下。
const deleteJob = async (job) => {
  const active = job.status === 'queued' || job.status === 'running'
  // 说明白差别：取消只是停下、记录还在；删除会把这条队列记录抹掉。
  const tip = active
    ? '该任务正在进行，删除会同时中断它。确定删除？'
    : '确定删除这条任务记录？'
  try {
    await ElMessageBox.confirm(tip, '删除任务', { type: 'warning' })
  } catch {
    return // 用户放弃
  }
  job.deleting = true
  try {
    await axios.delete(`/api/jobs/${job.id}`)
    ElMessage.success('已删除')
    loadJobs()
    loadSources()
  } catch (e) {
    // 404/405 的原文（Job not found / Method Not Allowed）对用户没有可操作性，
    // 而这两种恰恰是最常撞上的：
    //   404 —— 这条任务已经被别处清掉了（「清除记录」、连点两次删除），不是失败；
    //   405 —— DELETE 落到了同路径的 GET 路由上，说明**后端进程里还没有这个接口**
    //         （服务是在改动落地之前启动的，start.bat 不带 --reload，改代码不会自动生效）。
    // 这两种都指不到「再点一次就好」，所以在这里换成能照着做的说法。
    const status = e.response?.status
    if (status === 404) {
      ElMessage.info('该任务记录已不存在，列表已刷新')
      loadJobs()
      loadSources()
    } else if (status === 405) {
      ElMessage.error('后端服务未加载删除接口，请重启后端服务后重试')
    } else {
      ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  } finally {
    job.deleting = false
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

const goToExtract = (sourceId) => {
  router.push(`/extract/${sourceId}`)
}

const statusType = (status) => {
  const map = { pending: 'warning', processing: 'warning', staging: 'warning', done: 'success', error: 'danger' }
  return map[status] || 'info'
}

const statusText = (status) => {
  const map = { pending: '等待中', processing: '处理中', staging: '待确认', done: '已完成', error: '失败' }
  return map[status] || status
}

// 暂存区可预览：走暂存区的通道在 staging（待确认）或 done（已入库可回看）时。
// 判断依据来自通道元信息，不能再写死某个通道 —— 写死时新通道的来源会
// 在列表里既显示错标签、又失去「预览确认」按钮，而界面不会报任何错。
const isStaged = (row) => {
  return channelMeta(row.extract_channel).staged
    && (row.ocr_status === 'staging' || row.ocr_status === 'done')
}

// 「查看」按通道决定去哪（取代原来并列的「预览确认」+「查看」两个按钮）：
//   走暂存区的通道（大模型 / MinerU）→ 复核页：既能看，也要在那里确认入库
//                                       （这就是原来「预览确认」的动作）
//   本地 OCR → 题目识别完已直接入库，去题库按这个来源筛
const viewSource = (row) => {
  if (isStaged(row)) goToExtract(row.id)
  else goToLibrary(row.id)
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
/* 拖拽区：EP 默认的灰虚线框换成令牌化的浅底 + 悬停主色，其余交给组件自身 */
.upload-drop :deep(.el-upload-dragger) {
  border: 1.5px dashed color-mix(in oklab, var(--color-primary-500) 40%, var(--color-line));
  border-radius: var(--radius-card);
  background: var(--color-sunken);
  padding: 30px 24px;
  transition:
    border-color 150ms cubic-bezier(0.25, 1, 0.5, 1),
    background-color 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

.upload-drop :deep(.el-upload-dragger:hover),
.upload-drop :deep(.el-upload-dragger.is-dragover) {
  border-color: var(--color-primary-500);
  border-style: solid;
  background: var(--color-primary-50);
  box-shadow: 0 0 0 4px color-mix(in oklab, var(--color-primary-500) 10%, transparent);
}
</style>
