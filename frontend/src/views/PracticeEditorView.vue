<template>
  <div class="editor-page">
    <div class="editor-header">
      <div class="header-left">
        <el-button text @click="goBack">&larr; 返回列表</el-button>
        <b>{{ practice?.title || '加载中…' }}</b>
        <el-tag v-if="practice?.grade" size="small">{{ practice.grade }}</el-tag>
        <span class="qcount">{{ practice?.question_count || 0 }} 题</span>
      </div>
      <div>
        <el-button @click="openSettings"><el-icon><Setting /></el-icon> 练习设置</el-button>
        <el-button @click="previewRegroup"><el-icon><Sort /></el-icon> 整理结构</el-button>
        <el-button @click="unifyLayout"><el-icon><MagicStick /></el-icon> 统一排版</el-button>
        <el-button @click="exportFile('pdf')"><el-icon><Document /></el-icon> 导出 PDF</el-button>
        <el-button @click="exportFile('docx')"><el-icon><Tickets /></el-icon> 导出 Word</el-button>
      </div>
    </div>

    <div class="editor-body">
      <!-- 左：结构树 -->
      <div class="tree-panel">
        <div class="panel-head">
          <span>练习结构</span>
          <span>
            <el-button size="small" text type="primary" @click="openAddQuestions">+ 添加题目</el-button>
            <el-button size="small" text type="primary" @click="addSection">+ 小节</el-button>
          </span>
        </div>
        <div v-for="s in practice?.sections || []" :key="s.id" class="tree-section">
          <div class="section-row">
            <b>{{ s.title }}</b>
            <el-tag v-if="s.section_type === 'custom'" size="small">自定义</el-tag>
            <span class="row-ops">
              <el-tooltip content="显示/隐藏标题"><el-switch v-model="s.show_title" size="small" @change="patchSection(s, { show_title: $event })" /></el-tooltip>
              <el-tooltip content="从新页开始"><el-switch v-model="s.start_on_new_page" size="small" @change="patchSection(s, { start_on_new_page: $event })" /></el-tooltip>
              <el-button size="small" text @click="renameSection(s)">✏</el-button>
              <el-button size="small" text type="danger" @click="removeSection(s)">✖</el-button>
            </span>
          </div>
          <div v-for="q in s.questions" :key="q.id"
               class="tree-question" :class="{ active: selected?.id === q.id }"
               @click="selectQuestion(s, q)">
            <span class="q-label">{{ q.question_number }}.
              <el-tag v-if="q.is_modified" size="small" type="warning">改</el-tag>
            </span>
            <span class="q-preview">{{ treePreview(q.content) }}</span>
            <span class="q-ops" @click.stop>
              <el-button size="small" text @click="moveUp(s, q)">↑</el-button>
              <el-button size="small" text @click="moveDown(s, q)">↓</el-button>
              <el-button size="small" text @click="openMove(q)">⇄</el-button>
              <el-button size="small" text type="danger" @click="removeQuestion(q)">✖</el-button>
            </span>
          </div>
        </div>
        <el-empty v-if="!practice?.sections?.length" description="暂无题目" :image-size="60" />
      </div>

      <!-- 中：单题所见即所得编辑区（阶段 1） -->
      <div class="edit-panel">
        <el-empty v-if="!selected" description="从左侧选择一道题开始编辑" />
        <div v-else class="question-editor">
          <div class="qe-header">
            <b>第 {{ selected.question_number }} 题</b>
            <el-tag v-if="selected.is_modified" size="small" type="warning">已修改</el-tag>
            <el-select v-model="selected.question_type" size="small" style="width:110px" @change="updateMeta">
              <el-option v-for="(zh, k) in QUESTION_TYPE_MAP" :key="k" :label="zh" :value="k" />
            </el-select>
            <el-select v-model="selected.difficulty" size="small" placeholder="难度" clearable style="width:90px" @change="updateMeta">
              <el-option v-for="d in 5" :key="d" :label="`${d} 级`" :value="d" />
            </el-select>
            <el-input-number v-model="selected.score" size="small" :min="0" :precision="1" placeholder="分值" controls-position="right" style="width:110px" @change="updateMeta" />
            <span class="flex-gap" />
            <el-button size="small" @click="openImagePicker"><el-icon><Picture /></el-icon> 插入图片</el-button>
            <el-button size="small" @click="restoreQuestion"><el-icon><RefreshLeft /></el-icon> 恢复题库版本</el-button>
          </div>

          <!-- 题号由系统管理不入正文；整题一个连续画布（题干/图/选项/留白） -->
          <QuestionRichEditor
            :key="selected.id"
            ref="questionRichEditorRef"
            :doc="selected.rich_document"
            :practice-id="practiceId"
            :question-id="selected.id"
            :default-style="practiceDefaultStyle"
            @saved="onDocSaved"
            @request-replace-image="openReplacePicker" />
        </div>
      </div>

      <!-- 右：A4 预览（后端渲染，与 PDF 同源），分隔条可拖拽调宽 -->
      <div class="pv-resizer" @mousedown="startPvResize"></div>
      <div class="preview-panel" :style="{ width: panelW + 'px' }">
        <div class="pv-toolbar">
          <el-button size="small" text :disabled="preview.page <= 1" @click="preview.page--">‹</el-button>
          <span class="pv-pos">{{ preview.page }} / {{ preview.pages || '-' }}</span>
          <el-button size="small" text :disabled="preview.page >= preview.pages" @click="preview.page++">›</el-button>
          <el-select v-model="preview.zoom" size="small" style="width:96px">
            <el-option v-for="z in [1, 1.5, 2]" :key="z" :label="Math.round(z * 100) + '%'" :value="z" />
          </el-select>
          <el-button size="small" text @click="showFullscreen = true" :disabled="!preview.pages">⛶</el-button>
          <el-button size="small" text @click="refreshPreview" :loading="preview.busy">↻</el-button>
        </div>
        <div class="pv-scroll" ref="pvPanel" v-if="preview.pages">
          <img :src="pageImgUrl" :style="{ width: pvImgWidth }" />
        </div>
        <el-empty v-else-if="preview.busy" description="正在渲染预览…" :image-size="60" />
        <el-empty v-else description="编辑后自动刷新预览" :image-size="60" />
      </div>
    </div>

    <!-- 整理结构确认 -->
    <el-dialog v-model="showRegroup" title="整理结构" width="480px">
      <template v-if="regroup.changes?.length">
        <p>将发生以下变化：</p>
        <ul><li v-for="(c, i) in regroup.changes" :key="i">{{ c }}</li></ul>
      </template>
      <p v-else>当前结构已符合题型分组规则，无需调整。</p>
      <template #footer>
        <el-button @click="showRegroup = false">取消</el-button>
        <el-button type="primary" :disabled="!regroup.changes?.length" @click="applyRegroup">确认整理</el-button>
      </template>
    </el-dialog>

    <!-- 从题库添加题目 -->
    <el-dialog v-model="addQ.show" title="从题库添加题目" width="720px" top="6vh">
      <div class="addq-filter">
        <el-input v-model="addQ.search" placeholder="搜索题目内容…" clearable style="width:260px"
                  @keyup.enter="loadAddQList" @clear="loadAddQList" />
        <el-select v-model="addQ.type" placeholder="题型" clearable style="width:120px" @change="loadAddQList">
          <el-option v-for="t in ['选择题','多选题','填空题','实验题','计算题','解答题','简答题']" :key="t" :label="t" :value="t" />
        </el-select>
        <el-button :loading="addQ.loading" @click="loadAddQList">搜索</el-button>
      </div>
      <el-table :data="addQ.list" v-loading="addQ.loading" height="380" size="small"
                @selection-change="rows => addQ.selected = rows">
        <el-table-column type="selection" width="42" :selectable="row => !addQ.existing.has(row.id)" />
        <el-table-column label="题目" min-width="380">
          <template #default="{ row }"><div class="addq-content">{{ addQText(row.content) }}</div></template>
        </el-table-column>
        <el-table-column label="题型" width="90">
          <template #default="{ row }">
            <el-tag size="small">{{ QUESTION_TYPE_MAP[row.question_type] || row.question_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="70">
          <template #default="{ row }">
            <el-tag v-if="addQ.existing.has(row.id)" size="small" type="success">已添加</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="addQ.show = false">取消</el-button>
        <el-button type="primary" :disabled="!addQ.selected.length" :loading="addQ.adding" @click="addSelectedQuestions">
          添加所选 {{ addQ.selected.length }} 题
        </el-button>
      </template>
    </el-dialog>

    <!-- 移动到小节 -->
    <el-dialog v-model="showMove" title="移动到小节" width="380px">
      <el-select v-model="moveTarget" placeholder="选择目标小节" style="width:100%">
        <el-option v-for="s in practice.sections" :key="s.id" :label="s.title" :value="s.id" />
      </el-select>
      <template #footer>
        <el-button @click="showMove = false">取消</el-button>
        <el-button type="primary" @click="doMove">移动</el-button>
      </template>
    </el-dialog>

    <!-- 练习设置 -->
    <el-dialog v-model="showSettings" title="练习设置" width="420px">
      <el-form label-width="90px">
        <el-form-item label="标题"><el-input v-model="settingsForm.title" /></el-form-item>
        <el-form-item label="副标题"><el-input v-model="settingsForm.subtitle" /></el-form-item>
        <el-form-item label="学生信息栏"><el-switch v-model="settingsForm.showInfoBar" />
          <span class="hint">导出时显示姓名/班级/日期栏</span></el-form-item>
        <el-form-item label="页边距">
          <el-select v-model="settingsForm.marginPreset" style="width:160px">
            <el-option label="窄（15mm）" value="narrow" />
            <el-option label="标准（25mm）" value="normal" />
            <el-option label="宽（32mm）" value="wide" />
          </el-select>
        </el-form-item>
        <el-form-item label="页码"><el-switch v-model="settingsForm.showPageNumber" /></el-form-item>
        <el-form-item label="显示分值"><el-switch v-model="settingsForm.showScore" /></el-form-item>
        <el-form-item label="显示总分"><el-switch v-model="settingsForm.showTotalScore" /></el-form-item>
        <el-divider content-position="left">默认正文样式（未局部覆盖的内容跟随）</el-divider>
        <el-form-item label="默认字体">
          <el-select v-model="settingsForm.defaultFont" style="width:160px">
            <el-option v-for="f in FONT_NAMES" :key="f" :label="f" :value="f" />
          </el-select>
        </el-form-item>
        <el-form-item label="默认字号">
          <el-select v-model="settingsForm.defaultFontSize" style="width:160px">
            <el-option v-for="s in FONT_SIZES" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="默认行距">
          <el-select v-model="settingsForm.defaultLineHeight" style="width:160px">
            <el-option v-for="lh in LINE_HEIGHTS" :key="lh" :label="`${lh} 倍`" :value="lh" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSettings = false">取消</el-button>
        <el-button type="primary" @click="saveSettings">保存</el-button>
      </template>
    </el-dialog>

    <!-- 插入图片 -->
    <el-dialog v-model="showImagePicker" :title="replaceMode ? '替换图片' : '插入图片'" width="420px">
      <el-empty v-if="!assets.length" description="该练习暂无图片资产" :image-size="60" />
      <div v-else class="asset-grid">
        <div v-for="a in assets" :key="a" class="asset-item" @click="insertImage(a)">
          <img :src="`/api/practices/${practiceId}/assets/${a}`" />
          <span>{{ a.slice(0, 18) }}</span>
        </div>
      </div>
    </el-dialog>

    <!-- 全屏预览 -->
    <el-dialog v-model="showFullscreen" title="全屏预览" width="900px" top="4vh">
      <div class="fs-preview" v-if="preview.pages">
        <img :src="pageImgUrl" :style="{ width: (794 * preview.zoom) + 'px' }" />
      </div>
      <template #footer>
        <el-button :disabled="preview.page <= 1" @click="preview.page--">上一页</el-button>
        <span>{{ preview.page }} / {{ preview.pages }}</span>
        <el-button :disabled="preview.page >= preview.pages" @click="preview.page++">下一页</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { QUESTION_TYPE_MAP } from '../utils/questionTypes'
import QuestionRichEditor from '../components/richeditor/QuestionRichEditor.vue'
import { FONT_NAMES, FONT_SIZES, LINE_HEIGHTS, DEFAULT_STYLE } from '../components/richeditor/typography'

const route = useRoute()
const router = useRouter()
const practiceId = route.query.id

const practice = ref(null)
const selected = ref(null)
const selectedSection = ref(null)
const showRegroup = ref(false)
const regroup = ref({ changes: [] })
const showMove = ref(false)
const moveTarget = ref('')
const moveQuestionTarget = ref(null)
const showSettings = ref(false)
const settingsForm = reactive({ title: '', subtitle: '', showInfoBar: true,
  marginPreset: 'normal', showPageNumber: true, showScore: false, showTotalScore: false,
  defaultFont: DEFAULT_STYLE.font_family, defaultFontSize: DEFAULT_STYLE.font_size,
  defaultLineHeight: DEFAULT_STYLE.line_height })

// 练习默认样式：供编辑器画布跟随（后端渲染同样读 page_config.default_style）
const practiceDefaultStyle = computed(() => ({
  ...DEFAULT_STYLE, ...(practice.value?.page_config?.default_style || {}),
}))

const load = async () => {
  const res = await axios.get(`/api/practices/${practiceId}/detail`)
  practice.value = res.data
  schedulePreview()
}

const selectQuestion = async (s, q) => {
  if (selected.value && selected.value.id !== q.id) {
    await questionRichEditorRef.value?.flush?.()   // 切题前先把当前题落盘（不丢修改）
  }
  selected.value = q; selectedSection.value = s
}
const refresh = async () => { await load(); selected.value = null }

// 从题库继续添加题目到已有练习（重复题不可再选，后端也会去重）
const addQ = reactive({ show: false, search: '', type: '', loading: false, adding: false,
  list: [], selected: [], existing: new Set() })
const openAddQuestions = async () => {
  addQ.existing = new Set(
    (practice.value?.sections || []).flatMap(s => s.questions.map(q => q.source_question_id)))
  addQ.selected = []
  addQ.show = true
  await loadAddQList()
}
const loadAddQList = async () => {
  addQ.loading = true
  try {
    const res = await axios.get('/api/questions', { params: {
      search: addQ.search || undefined, question_type: addQ.type || undefined, page_size: 100 } })
    addQ.list = res.data.questions
  } finally { addQ.loading = false }
}
const addQText = (c) => (c || '').replace(/!\[[^\]]*\]\([^)]*\)/g, '[图]').slice(0, 80)
const addSelectedQuestions = async () => {
  addQ.adding = true
  try {
    const res = await axios.post(`/api/practices/${practiceId}/questions/add`,
      { question_ids: addQ.selected.map(r => r.id) })
    practice.value = res.data
    addQ.show = false
    schedulePreview()
    ElMessage.success(`已添加 ${addQ.selected.length} 题`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '添加失败')
  } finally { addQ.adding = false }
}

/* ---- 小节管理 ---- */
const addSection = async () => {
  const { value } = await ElMessageBox.prompt('小节名称', '新增小节', { inputValue: '自定义小节' })
  if (!value?.trim()) return
  await axios.post(`/api/practices/${practiceId}/sections`, { title: value.trim() })
  await load()
}
const renameSection = async (s) => {
  const { value } = await ElMessageBox.prompt('小节名称', '重命名小节', { inputValue: s.title })
  if (!value?.trim()) return
  await axios.put(`/api/practices/${practiceId}/sections/${s.id}`, { title: value.trim() })
  await load()
}
const patchSection = async (s, patch) => {
  await axios.put(`/api/practices/${practiceId}/sections/${s.id}`, patch)
}
const removeSection = async (s) => {
  if (s.questions?.length) { ElMessage.warning('该小节内仍有题目，请先移走或删除题目'); return }
  await ElMessageBox.confirm(`删除小节“${s.title}”？`, '提示', { type: 'warning' })
  await axios.delete(`/api/practices/${practiceId}/sections/${s.id}`)
  await load()
}

/* ---- 题目移动/删除 ---- */
const moveUp = async (s, q) => {
  const idx = s.questions.findIndex(x => x.id === q.id)
  if (idx <= 0) return
  await questionRichEditorRef.value?.flush?.()
  await axios.put(`/api/practices/${practiceId}/questions/${q.id}/move`,
    { target_section_id: s.id, target_position: s.questions[idx - 1].position })
  await refresh()
}
const moveDown = async (s, q) => {
  const idx = s.questions.findIndex(x => x.id === q.id)
  if (idx < 0 || idx >= s.questions.length - 1) return
  await questionRichEditorRef.value?.flush?.()
  await axios.put(`/api/practices/${practiceId}/questions/${q.id}/move`,
    { target_section_id: s.id, target_position: s.questions[idx + 1].position })
  await refresh()
}
const openMove = (q) => { moveQuestionTarget.value = q; moveTarget.value = ''; showMove.value = true }
const doMove = async () => {
  if (!moveTarget.value) return
  await axios.put(`/api/practices/${practiceId}/questions/${moveQuestionTarget.value.id}/move`,
    { target_section_id: moveTarget.value })
  showMove.value = false
  await refresh()
}
const removeQuestion = async (q) => {
  await ElMessageBox.confirm(`删除第 ${q.question_number} 题？删除后不可恢复。`, '提示', { type: 'warning' })
  await questionRichEditorRef.value?.flush?.()
  await axios.delete(`/api/practices/${practiceId}/questions/${q.id}`)
  await refresh()
}

/* ---- 一键排版 ---- */
const previewRegroup = async () => {
  const res = await axios.post(`/api/practices/${practiceId}/regroup/preview`)
  regroup.value = res.data
  showRegroup.value = true
}
const applyRegroup = async () => {
  await axios.post(`/api/practices/${practiceId}/regroup/apply`)
  showRegroup.value = false
  ElMessage.success('已按题型整理结构')
  await refresh()
}
const unifyLayout = async () => {
  const res = await axios.post(`/api/practices/${practiceId}/layout/unify`)
  ElMessage.success(`已统一排版，调整了 ${res.data.adjusted} 个内容块`)
  await refresh()
}

/* ---- 练习设置 ---- */
const openSettings = () => {
  settingsForm.title = practice.value.title
  settingsForm.subtitle = practice.value.subtitle || ''
  settingsForm.showInfoBar = practice.value.page_config?.show_info_bar ?? true
  settingsForm.marginPreset = practice.value.page_config?.margin_preset || 'normal'
  settingsForm.showPageNumber = practice.value.page_config?.show_page_number ?? true
  settingsForm.showScore = practice.value.page_config?.show_score ?? false
  settingsForm.showTotalScore = practice.value.page_config?.show_total_score ?? false
  const ds = practice.value.page_config?.default_style || {}
  settingsForm.defaultFont = ds.font_family ?? DEFAULT_STYLE.font_family
  settingsForm.defaultFontSize = ds.font_size ?? DEFAULT_STYLE.font_size
  settingsForm.defaultLineHeight = ds.line_height ?? DEFAULT_STYLE.line_height
  showSettings.value = true
}
const saveSettings = async () => {
  await axios.put(`/api/practices/${practiceId}`, {
    title: settingsForm.title,
    subtitle: settingsForm.subtitle || null,
    page_config: { ...(practice.value.page_config || {}),
      show_info_bar: settingsForm.showInfoBar,
      margin_preset: settingsForm.marginPreset,
      show_page_number: settingsForm.showPageNumber,
      show_score: settingsForm.showScore,
      show_total_score: settingsForm.showTotalScore,
      default_style: {
        font_family: settingsForm.defaultFont,
        font_size: settingsForm.defaultFontSize,
        line_height: settingsForm.defaultLineHeight,
      } },
  })
  showSettings.value = false
  ElMessage.success('已保存')
  await load()
}

/* ---- 单题富文本编辑（阶段 1：编辑器为新真源，保存反推旧块/快照） ---- */
const questionRichEditorRef = ref(null)

const assets = ref([])
const showImagePicker = ref(false)
const replaceMode = ref(false)   // true = 替换模式（保留宽高/对齐）

// 左树预览：剔除 Markdown 图包装与公式包装，只看正文概要
const treePreview = (c) => (c || '')
  .replace(/!\[[^\]]*\]\([^)]*\)/g, '[图]').replace(/\$\$[^$]*\$\$|\$[^$\n]*\$/g, '[公式]').slice(0, 24)

// 保存成功：就地刷新左树“改”标记/预览文本/富文本文档（避免切回时用旧文档覆盖），延迟刷新右侧预览（不在打字时重复渲染）
const onDocSaved = (payload) => {
  const q = payload.question
  const sec = (practice.value?.sections || []).find(s => s.questions.some(x => x.id === q.id))
  if (!sec) return
  const target = sec.questions.find(x => x.id === q.id)
  target.is_modified = q.is_modified
  target.content = q.content
  target.rich_document = q.rich_document
  schedulePreview()
}

const openImagePicker = async () => {
  const res = await axios.get(`/api/practices/${practiceId}/assets-list`)
  assets.value = res.data.assets
  replaceMode.value = false
  showImagePicker.value = true
}
const openReplacePicker = async () => {
  const res = await axios.get(`/api/practices/${practiceId}/assets-list`)
  assets.value = res.data.assets
  replaceMode.value = true
  showImagePicker.value = true
}
const insertImage = (name) => {
  const src = `asset://practice/${name}`
  if (replaceMode.value) {
    questionRichEditorRef.value?.replaceImageBlock?.(src)
  } else {
    questionRichEditorRef.value?.insertImageBlock?.(src)
  }
  replaceMode.value = false
  showImagePicker.value = false
}
const restoreQuestion = async () => {
  await questionRichEditorRef.value?.flush?.()
  await ElMessageBox.confirm('恢复为题库原始内容？当前练习中对该题的所有修改将丢失（题库原题不受影响）。', '提示', { type: 'warning' })
  const res = await axios.post(`/api/practices/${practiceId}/questions/${selected.value.id}/restore`)
  selected.value = res.data.question
  await load()   // 同步左树；随后把 selected 指回刷新后的同一题（含重建的富文本文档）
  const sec = practice.value.sections.find(s => s.questions.some(q => q.id === res.data.question.id))
  if (sec) { selectedSection.value = sec; selected.value = sec.questions.find(q => q.id === res.data.question.id) }
  schedulePreview()
  ElMessage.success('已恢复为题库原始内容')
}
const updateMeta = async () => {
  await axios.put(`/api/practices/${practiceId}/questions/${selected.value.id}`, {
    question_type: selected.value.question_type,
    difficulty: selected.value.difficulty ?? null,
    score: selected.value.score ?? null,
  })
  await load()
}
const goBack = async () => {
  await questionRichEditorRef.value?.flush?.()
  router.push('/practices')
}

/* ---- 预览与导出（阶段三） ---- */
const showFullscreen = ref(false)
const preview = reactive({ pages: 0, page: 1, sha: '', zoom: 1, busy: false })   // zoom 相对铺满宽：1=100%
let previewTimer = null

// 预览面板宽度：分隔条可拖拽调整（向左拖变宽），记住上次宽度
const panelW = ref(Math.min(Math.max(Number(localStorage.getItem('pvPanelW')) || 380, 280), 1200))
const startPvResize = (e) => {
  e.preventDefault()
  const startX = e.clientX
  const startW = panelW.value
  const maxW = Math.floor(window.innerWidth * 0.75)
  const onMove = (ev) => {
    panelW.value = Math.min(Math.max(startW + (startX - ev.clientX), 280), maxW)
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    document.body.style.userSelect = ''
    localStorage.setItem('pvPanelW', String(panelW.value))
  }
  document.body.style.userSelect = 'none'
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// 预览图宽 = 面板内宽 × 缩放（100% 即铺满面板，不再按绝对 794px 溢出）
const pvPanel = ref(null)
const pvWidth = ref(340)
let pvObserver = null
onMounted(() => {
  pvObserver = new ResizeObserver(() => {
    if (pvPanel.value) pvWidth.value = pvPanel.value.clientWidth
  })
})
watch(() => pvPanel.value, el => { if (el && pvObserver) pvObserver.observe(el) })
onBeforeUnmount(() => pvObserver && pvObserver.disconnect())
const pvImgWidth = computed(() => {
  const base = Math.max(pvWidth.value - 24, 200)
  return (base * (preview.zoom || 1)) + 'px'
})

const pageImgUrl = computed(() => preview.pages
  ? `/api/practices/${practiceId}/preview/page/${preview.page}?scale=2&t=${preview.sha}`
  : '')

const refreshPreview = async () => {
  preview.busy = true
  try {
    const res = await axios.post(`/api/practices/${practiceId}/render`)
    preview.pages = res.data.pages
    preview.sha = res.data.sha
    if (preview.page > preview.pages) preview.page = 1
  } catch { /* 渲染失败不阻断编辑 */ } finally { preview.busy = false }
}
const schedulePreview = () => {   // 编辑后防抖刷新（规格 10.1）
  clearTimeout(previewTimer)
  previewTimer = setTimeout(refreshPreview, 800)
}

const exportFile = async (fmt) => {
  try {
    const res = await axios.get(`/api/practices/${practiceId}/export/${fmt}`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `${practice.value.title || '练习'}.${fmt}`
    a.click()
    URL.revokeObjectURL(url)
    // Word 公式降级为图片：后端经响应头明确列出（不静默丢失，阶段 3）
    const degraded = res.headers['x-formula-degraded']
    if (fmt === 'docx' && degraded) {
      ElMessage({
        type: 'warning', duration: 8000,
        message: `导出成功，但以下公式无法转为 Word 原生公式，已降级为图片：${decodeURIComponent(degraded)}`,
      })
    } else {
      ElMessage.success('导出成功')
    }
    await load()
  } catch { ElMessage.error('导出失败') }
}

onMounted(async () => {
  if (!practiceId) { router.push('/practices'); return }
  await load()
})
</script>

<style scoped>
.editor-page { display: flex; flex-direction: column; height: calc(100vh - 60px); }
.editor-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; border-bottom: 1px solid #ebeef5; }
.header-left { display: flex; align-items: center; gap: 8px; }
.qcount { color: #909399; font-size: 13px; }
.editor-body { flex: 1; display: flex; min-height: 0; }
.tree-panel { width: 290px; border-right: 1px solid #ebeef5; overflow-y: auto; padding: 8px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; padding: 4px 4px 8px; font-weight: bold; }
.tree-section { margin-bottom: 10px; }
.section-row { display: flex; align-items: center; gap: 6px; padding: 4px; background: #f5f7fa; border-radius: 4px; }
.section-row b { flex: 1; font-size: 13px; }
.row-ops { display: flex; align-items: center; gap: 2px; }
.tree-question { display: flex; align-items: center; gap: 6px; padding: 5px 6px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.tree-question:hover { background: #f0f9eb; }
.tree-question.active { background: #ecf5ff; }
.q-label { white-space: nowrap; }
.q-preview { flex: 1; color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.q-ops { display: none; }
.tree-question:hover .q-ops { display: inline-flex; }
.edit-panel { flex: 1; overflow-y: auto; padding: 16px; background: #fafafa; }
.pv-resizer { width: 5px; cursor: col-resize; background: #ebeef5; flex-shrink: 0; transition: background .15s; }
.addq-filter { display: flex; gap: 8px; margin-bottom: 10px; }
.addq-content { font-size: 12px; line-height: 1.5; white-space: normal; color: #303133; }
.pv-resizer:hover { background: #c0c4cc; }
.preview-panel { flex-shrink: 0; border-left: 1px solid #ebeef5; display: flex; flex-direction: column; background: #f0f2f5; }
.pv-toolbar { display: flex; align-items: center; gap: 2px; padding: 6px 8px; border-bottom: 1px solid #ebeef5; background: #fff; }
.pv-pos { font-size: 12px; color: #606266; white-space: nowrap; }
.pv-scroll { flex: 1; overflow: auto; padding: 10px; display: flex; justify-content: center; }
.pv-scroll img { box-shadow: 0 1px 6px rgba(0,0,0,.18); background: #fff; }
.fs-preview { display: flex; justify-content: center; overflow: auto; max-height: 76vh; }
.fs-preview img { box-shadow: 0 1px 8px rgba(0,0,0,.22); background: #fff; }
.hint { color: #909399; font-size: 12px; margin-left: 8px; }
.question-editor { max-width: 760px; margin: 0 auto; }
.qe-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.flex-gap { flex: 1; }
.qe-block { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.block-tools { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; }
.block-tools .el-button { padding: 0 4px; }
.img-block img { max-width: 100%; max-height: 240px; border-radius: 4px; }
.option-row { display: flex; gap: 6px; margin-bottom: 6px; align-items: center; }
.space-block { color: #909399; font-size: 13px; }
.qe-actions { margin-top: 12px; }
.asset-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.asset-item { cursor: pointer; text-align: center; font-size: 12px; color: #606266; }
.asset-item img { width: 100%; max-height: 90px; object-fit: contain; border: 1px solid #ebeef5; border-radius: 4px; }
</style>
