<template>
  <div class="editor-page">
    <div class="editor-header">
      <div class="header-left">
        <el-button text @click="goBack">&larr; 返回列表</el-button>
        <b>{{ practice?.title || '加载中…' }}</b>
        <el-tag v-if="practice?.grade" size="small">{{ practice.grade }}</el-tag>
        <span class="qcount">{{ practice?.question_count || 0 }} 题</span>
        <el-radio-group v-model="mode" size="small" style="margin-left:8px" @change="onModeChange">
          <el-radio-button label="single">单题编辑</el-radio-button>
          <el-radio-button label="workbook">整册编排</el-radio-button>
        </el-radio-group>
      </div>
      <div>
        <el-button v-if="mode === 'workbook'" type="primary" @click="saveLayout(true)" :loading="layoutSaving">保存整册</el-button>
        <el-button @click="openSettings"><el-icon><Setting /></el-icon> 练习设置</el-button>
        <el-button v-if="mode === 'single'" @click="previewRegroup"><el-icon><Sort /></el-icon> 整理结构</el-button>
        <el-button v-if="mode === 'single'" @click="unifyLayout"><el-icon><MagicStick /></el-icon> 统一排版</el-button>
        <el-button @click="exportFile('pdf')"><el-icon><Document /></el-icon> 导出 PDF</el-button>
        <el-button @click="exportFile('docx')"><el-icon><Tickets /></el-icon> 导出 Word</el-button>
      </div>
    </div>

    <div class="editor-body">
      <!-- 左：结构树 -->
      <div class="tree-panel">
        <div class="panel-head">
          <span>练习结构</span>
          <span v-if="mode === 'single'">
            <el-button size="small" text type="primary" @click="openAddQuestions">+ 添加题目</el-button>
            <el-button size="small" text type="primary" @click="addSection">+ 小节</el-button>
          </span>
        </div>
        <div v-for="s in practice?.sections || []" :key="s.id" class="tree-section">
          <div class="section-row">
            <b>{{ s.title }}</b>
            <el-tag v-if="s.section_type === 'custom'" size="small">自定义</el-tag>
            <span class="row-ops" v-if="mode === 'single'">
              <el-tooltip content="显示/隐藏标题"><el-switch v-model="s.show_title" size="small" @change="patchSection(s, { show_title: $event })" /></el-tooltip>
              <el-tooltip content="从新页开始"><el-switch v-model="s.start_on_new_page" size="small" @change="patchSection(s, { start_on_new_page: $event })" /></el-tooltip>
              <el-button size="small" text @click="renameSection(s)">✏</el-button>
              <el-button size="small" text type="danger" @click="removeSection(s)">✖</el-button>
            </span>
          </div>
          <div v-for="q in s.questions" :key="q.id"
               class="tree-question" :class="{ active: selected?.id === q.id }"
               @click="onTreeQuestionClick(s, q)">
            <span class="q-label">{{ q.question_number }}.
              <el-tag v-if="q.is_modified" size="small" type="warning">改</el-tag>
            </span>
            <span class="q-preview">{{ treePreview(q.content) }}</span>
            <span class="q-ops" v-if="mode === 'single'" @click.stop>
              <el-button size="small" text @click="moveUp(s, q)">↑</el-button>
              <el-button size="small" text @click="moveDown(s, q)">↓</el-button>
              <el-button size="small" text @click="openMove(q)">⇄</el-button>
              <el-button size="small" text type="danger" @click="removeQuestion(q)">✖</el-button>
            </span>
          </div>
        </div>
        <el-empty v-if="!practice?.sections?.length" description="暂无题目" :image-size="60" />
      </div>

      <!-- 中：整册编排画布 / 单题所见即所得编辑区 -->
      <div class="edit-panel">
        <WorkbookCanvas v-if="mode === 'workbook'"
          :practice-id="practiceId"
          :sections="practice?.sections || []"
          :layout="layout"
          :title="practice?.title || ''"
          @change="onLayoutChange"
          @open-question="openQuestionFromWorkbook"
          @insert-question="insertQuestionFromWorkbook"
          @remove-question="removeQuestionFromWorkbook"
          @update:title="onWorkbookTitleChange" />
        <template v-else>
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
        </template>
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
        <el-input v-model="addQ.search" placeholder="搜索题目内容…" clearable style="width:230px"
                  @keyup.enter="loadAddQList" @clear="loadAddQList" />
        <el-select v-model="addQ.subject" placeholder="学科" clearable style="width:96px" @change="loadAddQList">
          <el-option v-for="t in SUBJECT_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-select v-model="addQ.grade" placeholder="年级" clearable style="width:96px" @change="loadAddQList">
          <el-option v-for="g in ['初一','初二','初三','中考','高一','高二','高三']" :key="g" :label="g" :value="g" />
        </el-select>
        <el-select v-model="addQ.type" placeholder="题型" clearable style="width:100px" @change="loadAddQList">
          <el-option v-for="t in ['选择题','多选题','填空题','实验题','计算题','解答题','简答题']" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="addQ.difficulty" placeholder="难度" clearable style="width:90px" @change="loadAddQList">
          <el-option v-for="d in [1,2,3,4,5]" :key="d" :label="['容易','较易','中等','较难','困难'][d-1]" :value="d" />
        </el-select>
        <el-select v-model="addQ.has_explanation" placeholder="解析" clearable style="width:90px" @change="loadAddQList">
          <el-option label="有解析" :value="true" />
          <el-option label="无解析" :value="false" />
        </el-select>
        <el-select v-model="addQ.tag_id" placeholder="标签" clearable filterable style="width:130px" @change="loadAddQList">
          <el-option-group v-for="g in addQTagGroups" :key="g" :label="g">
            <el-option v-for="t in addQ.tags.filter(x => x.category === g)"
                       :key="t.id" :label="t.name" :value="t.id" />
          </el-option-group>
        </el-select>
        <el-select v-model="addQ.source_id" placeholder="来源试卷" clearable filterable style="width:150px" @change="loadAddQList">
          <el-option v-for="src in addQ.sources" :key="src.id" :label="`${src.filename}（${src.question_count}题）`" :value="src.id" />
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

    <!-- 练习设置（阶段 6：方向/页边距/页眉页脚三栏/变量/模板） -->
    <el-dialog v-model="showSettings" title="练习设置" width="660px">
      <el-tabs>
        <el-tab-pane label="页面">
          <el-form label-width="90px">
            <el-form-item label="标题"><el-input v-model="settingsForm.title" /></el-form-item>
            <el-form-item label="副标题"><el-input v-model="settingsForm.subtitle" /></el-form-item>
            <el-form-item label="纸张方向">
              <el-radio-group v-model="settingsForm.orientation">
                <el-radio-button value="portrait">A4 纵向</el-radio-button>
                <el-radio-button value="landscape">A4 横向</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="页边距">
              <el-radio-group v-model="settingsForm.marginPreset">
                <el-radio-button value="narrow">窄(15)</el-radio-button>
                <el-radio-button value="normal">标准(25)</el-radio-button>
                <el-radio-button value="wide">宽(32)</el-radio-button>
                <el-radio-button value="custom">自定义</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="settingsForm.marginPreset === 'custom'" label="边距(mm)">
              <div class="margin-grid">
                <span>上<el-input-number v-model="settingsForm.margins.top" :min="5" :max="60" size="small" /></span>
                <span>下<el-input-number v-model="settingsForm.margins.bottom" :min="5" :max="60" size="small" /></span>
                <span>左<el-input-number v-model="settingsForm.margins.left" :min="5" :max="60" size="small" /></span>
                <span>右<el-input-number v-model="settingsForm.margins.right" :min="5" :max="60" size="small" /></span>
              </div>
            </el-form-item>
            <el-form-item label="学生信息栏">
              <el-switch v-model="settingsForm.showInfoBar" />
              <template v-if="settingsForm.showInfoBar">
                <el-radio-group v-model="settingsForm.infoBarAlign" size="small" style="margin-left:10px">
                  <el-radio-button value="left">左</el-radio-button>
                  <el-radio-button value="center">居中</el-radio-button>
                  <el-radio-button value="right">右</el-radio-button>
                </el-radio-group>
              </template>
              <span class="hint">导出时显示姓名/班级/日期栏</span>
            </el-form-item>
            <el-form-item label="学校(可选)"><el-input v-model="settingsForm.school" placeholder="用于 {school} 变量" /></el-form-item>
            <el-form-item label="教师(可选)"><el-input v-model="settingsForm.teacher" placeholder="用于 {teacher} 变量" /></el-form-item>
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
        </el-tab-pane>
        <el-tab-pane label="页眉">
          <el-form label-width="72px">
            <el-form-item label="启用页眉"><el-switch v-model="settingsForm.header.enabled" /></el-form-item>
            <template v-if="settingsForm.header.enabled">
              <el-form-item v-for="key in ['left','center','right']" :key="key"
                :label="key === 'left' ? '左' : (key === 'center' ? '中' : '右')">
                <div class="zone-row">
                  <el-input v-model="settingsForm.header[key]" placeholder="留空则不显示" />
                  <el-select :value="''" size="small" style="width:148px;margin-left:6px" placeholder="插入变量"
                    @change="v => appendZoneVar('header', key, v)">
                    <el-option v-for="ov in PAGE_VAR_OPTIONS" :key="ov.value" :label="ov.label" :value="ov.value" />
                  </el-select>
                </div>
              </el-form-item>
              <el-form-item label="字号">
                <el-input-number v-model="settingsForm.header.fontSize" :min="6" :max="24" size="small" />
                <span class="hint">pt</span>
              </el-form-item>
              <el-form-item label="分隔线"><el-switch v-model="settingsForm.header.line" /></el-form-item>
              <el-form-item label="首页不同">
                <el-switch v-model="settingsForm.header.firstPageDifferent" />
                <span class="hint" style="margin-left:10px">首页隐藏页眉</span>
                <el-switch v-if="settingsForm.header.firstPageDifferent" v-model="settingsForm.header.firstHidden"
                  style="margin-left:8px" />
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="页脚">
          <el-form label-width="72px">
            <el-form-item label="启用页脚"><el-switch v-model="settingsForm.footer.enabled" /></el-form-item>
            <template v-if="settingsForm.footer.enabled">
              <el-form-item v-for="key in ['left','center','right']" :key="key"
                :label="key === 'left' ? '左' : (key === 'center' ? '中' : '右')">
                <div class="zone-row">
                  <el-input v-model="settingsForm.footer[key]" placeholder="留空则不显示" />
                  <el-select :value="''" size="small" style="width:148px;margin-left:6px" placeholder="插入变量"
                    @change="v => appendZoneVar('footer', key, v)">
                    <el-option v-for="ov in PAGE_VAR_OPTIONS" :key="ov.value" :label="ov.label" :value="ov.value" />
                  </el-select>
                </div>
              </el-form-item>
              <el-form-item label="字号">
                <el-input-number v-model="settingsForm.footer.fontSize" :min="6" :max="24" size="small" />
                <span class="hint">pt</span>
              </el-form-item>
              <el-form-item label="分隔线"><el-switch v-model="settingsForm.footer.line" /></el-form-item>
              <el-form-item label="首页隐藏"><el-switch v-model="settingsForm.footer.firstHidden" /></el-form-item>
            </template>
            <el-divider content-position="left">快速模板</el-divider>
            <el-form-item label="套用模板">
              <el-select v-model="settingsForm.hfTemplate" style="width:220px" @change="applyHfTemplate">
                <el-option v-for="t in HF_TEMPLATES" :key="t.value" :label="t.label" :value="t.value" />
              </el-select>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
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
import WorkbookCanvas from '../components/WorkbookCanvas.vue'
import { FONT_NAMES, FONT_SIZES, LINE_HEIGHTS, DEFAULT_STYLE } from '../components/richeditor/typography'

const route = useRoute()
const router = useRouter()
const practiceId = route.query.id

const practice = ref(null)
const selected = ref(null)
const selectedSection = ref(null)

/* ---- 阶段 5：整册编排 ---- */
const mode = ref('single')
const layout = ref([])
const layoutDirty = ref(false)
const layoutSaving = ref(false)
let layoutTimer = null
const pendingQIndex = ref(null)
const uid = () => 'wb_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
const normalizeLayout = (arr) => (arr || []).filter(b => b && b.type)

const flushLayout = async () => { if (layoutDirty.value) await saveLayout(false) }
const onModeChange = async (val) => {
  if (val === 'workbook') {
    await questionRichEditorRef.value?.flush?.()
    layout.value = normalizeLayout(practice.value?.layout_document)
    mode.value = 'workbook'
    schedulePreview()
  } else {
    await flushLayout()
    mode.value = 'single'
  }
}
const onLayoutChange = (arr) => {
  layout.value = arr
  layoutDirty.value = true
  clearTimeout(layoutTimer)
  layoutTimer = setTimeout(() => saveLayout(false), 1200)
}
const saveLayout = async (manual) => {
  clearTimeout(layoutTimer)
  layoutDirty.value = false
  layoutSaving.value = true
  try {
    const res = await axios.put(`/api/practices/${practiceId}/layout`, { layout: layout.value })
    practice.value = res.data
    layout.value = normalizeLayout(res.data.layout_document)
    if (manual) ElMessage.success('整册结构已保存')
    schedulePreview()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
    layoutDirty.value = true
  } finally { layoutSaving.value = false }
}
const onTreeQuestionClick = async (s, q) => {
  if (mode.value === 'workbook') await flushLayout()
  await selectQuestion(s, q)
}
const openQuestionFromWorkbook = async (qid) => {
  await flushLayout()
  const s = (practice.value?.sections || []).find(sec => sec.questions.some(x => x.id === qid))
  const q = s?.questions.find(x => x.id === qid)
  if (!s || !q) return
  mode.value = 'single'
  await selectQuestion(s, q)
}
const insertQuestionFromWorkbook = (index) => {
  pendingQIndex.value = index
  openAddQuestions()
}
const afterQuestionsAdded = (addedIds) => {
  if (pendingQIndex.value === null || !addedIds?.length) { pendingQIndex.value = null; return }
  const idx = pendingQIndex.value
  const blocks = JSON.parse(JSON.stringify(layout.value))
  addedIds.forEach((qid, k) => {
    blocks.splice(idx + k, 0, { type: 'question_ref', id: uid(), question_id: qid })
  })
  layout.value = blocks
  pendingQIndex.value = null
  layoutDirty.value = true
  clearTimeout(layoutTimer)
  layoutTimer = setTimeout(() => saveLayout(false), 600)
}
const removeQuestionFromWorkbook = async (qid) => {
  await axios.delete(`/api/practices/${practiceId}/questions/${qid}`)
  layout.value = (layout.value || []).filter(b => !(b.type === 'question_ref' && b.question_id === qid))
  layoutDirty.value = true
  await saveLayout(false)
  await load()
}
const onWorkbookTitleChange = async (t) => {
  if (!t || t === practice.value?.title) return
  await axios.put(`/api/practices/${practiceId}`, { title: t })
  if (practice.value) practice.value.title = t
  schedulePreview()
}
const showRegroup = ref(false)
const regroup = ref({ changes: [] })
const showMove = ref(false)
const moveTarget = ref('')
const moveQuestionTarget = ref(null)
const showSettings = ref(false)
const settingsForm = reactive({ title: '', subtitle: '', showInfoBar: true,
  infoBarAlign: 'left',
  marginPreset: 'normal', margins: { top: 25, bottom: 25, left: 25, right: 25 },
  orientation: 'portrait', showPageNumber: true, showScore: false, showTotalScore: false,
  school: '', teacher: '', hfTemplate: 'custom',
  header: { enabled: true, left: '', center: '{title}', right: '', fontSize: 9, distance: 8,
    line: false, firstPageDifferent: true, firstHidden: true },
  footer: { enabled: true, left: '', center: '{page} / {total}', right: '', fontSize: 9,
    distance: 8, line: false, firstHidden: false },
  defaultFont: DEFAULT_STYLE.font_family, defaultFontSize: DEFAULT_STYLE.font_size,
  defaultLineHeight: DEFAULT_STYLE.line_height })

// 页眉/页脚三栏可用变量
const PAGE_VAR_OPTIONS = [
  { value: '{title}', label: '{title} 练习标题' },
  { value: '{subject}', label: '{subject} 科目' },
  { value: '{grade}', label: '{grade} 年级' },
  { value: '{date}', label: '{date} 日期' },
  { value: '{page}', label: '{page} 页码' },
  { value: '{total}', label: '{total} 总页数' },
  { value: '{school}', label: '{school} 学校' },
  { value: '{teacher}', label: '{teacher} 教师' },
]
// 页眉/页脚一键模板
const HF_TEMPLATES = [
  { value: 'custom', label: '保持当前' },
  { value: 'none', label: '无页眉页脚' },
  { value: 'title', label: '标题页眉 + 居中页码' },
  { value: 'centerpage', label: '仅居中页码' },
  { value: 'rightpage', label: '仅右侧页码' },
]
const applyHfTemplate = (v) => {
  if (v === 'none') {
    settingsForm.header.enabled = false
    settingsForm.footer.enabled = false
  } else if (v === 'title') {
    settingsForm.header.enabled = true
    settingsForm.header.left = ''; settingsForm.header.center = '{title}'; settingsForm.header.right = ''
    settingsForm.footer.enabled = true
    settingsForm.footer.left = ''; settingsForm.footer.center = '{page} / {total}'; settingsForm.footer.right = ''
  } else if (v === 'centerpage') {
    settingsForm.header.enabled = false
    settingsForm.footer.enabled = true
    settingsForm.footer.left = ''; settingsForm.footer.center = '{page} / {total}'; settingsForm.footer.right = ''
  } else if (v === 'rightpage') {
    settingsForm.header.enabled = false
    settingsForm.footer.enabled = true
    settingsForm.footer.left = ''; settingsForm.footer.center = ''; settingsForm.footer.right = '{page}'
  }
  settingsForm.hfTemplate = 'custom'
}
// 向页眉/页脚某栏追加变量（可多次插入）
const appendZoneVar = (zone, key, value) => {
  if (!value) return
  settingsForm[zone][key] = (settingsForm[zone][key] || '') + value
}

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
// 学科取值与题库一致（英文 code），展示统一中文
const SUBJECT_OPTIONS = [
  { value: 'physics', label: '物理' },
  { value: 'math', label: '数学' },
  { value: 'chemistry', label: '化学' },
  { value: 'english', label: '英语' },
]

const addQ = reactive({ show: false, search: '', type: '', subject: '', grade: '',
  difficulty: undefined, has_explanation: undefined, source_id: '', tag_id: '',
  loading: false, adding: false, list: [], selected: [], existing: new Set(), sources: [], tags: [] })
const openAddQuestions = async () => {
  addQ.existing = new Set(
    (practice.value?.sections || []).flatMap(s => s.questions.map(q => q.source_question_id)))
  addQ.selected = []
  addQ.show = true
  if (!addQ.sources.length) {
    try {
      const res = await axios.get('/api/sources')
      addQ.sources = res.data?.sources || []
    } catch (e) { addQ.sources = [] }
  }
  if (!addQ.tags.length) {
    try {
      const res = await axios.get('/api/tags')
      addQ.tags = res.data || []
    } catch (e) { addQ.tags = [] }
  }
  await loadAddQList()
}
const addQTagGroups = computed(() => [...new Set(addQ.tags.map(t => t.category).filter(Boolean))])
const loadAddQList = async () => {
  addQ.loading = true
  try {
    const res = await axios.get('/api/questions', { params: {
      search: addQ.search || undefined, question_type: addQ.type || undefined,
      subject: addQ.subject || undefined, grade: addQ.grade || undefined,
      difficulty: addQ.difficulty ?? undefined,
      has_explanation: addQ.has_explanation ?? undefined,
      source_id: addQ.source_id || undefined,
      tag_ids: addQ.tag_id || undefined, page_size: 100 } })
    addQ.list = res.data.questions
  } finally { addQ.loading = false }
}
const addQText = (c) => (c || '').replace(/!\[[^\]]*\]\([^)]*\)/g, '[图]').slice(0, 80)
const addSelectedQuestions = async () => {
  addQ.adding = true
  try {
    const before = new Set((practice.value?.sections || []).flatMap(s => s.questions.map(q => q.id)))
    const res = await axios.post(`/api/practices/${practiceId}/questions/add`,
      { question_ids: addQ.selected.map(r => r.id) })
    practice.value = res.data
    addQ.show = false
    const added = (practice.value?.sections || []).flatMap(s => s.questions.map(q => q.id))
      .filter(id => !before.has(id))
    if (mode.value === 'workbook') afterQuestionsAdded(added)
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
  const pc = practice.value.page_config || {}
  settingsForm.showInfoBar = pc.show_info_bar ?? true
  settingsForm.infoBarAlign = pc.info_bar_align || 'left'
  settingsForm.marginPreset = pc.margin_preset || 'normal'
  settingsForm.margins = { top: 25, bottom: 25, left: 25, right: 25, ...(pc.margins || {}) }
  settingsForm.orientation = pc.orientation || 'portrait'
  settingsForm.showPageNumber = pc.show_page_number ?? true
  settingsForm.showScore = pc.show_score ?? false
  settingsForm.showTotalScore = pc.show_total_score ?? false
  const vars = pc.variables || {}
  settingsForm.school = vars.school || ''
  settingsForm.teacher = vars.teacher || ''
  const h = pc.header || {}
  settingsForm.header = {
    enabled: h.enabled ?? false, left: h.left || '', center: h.center || '', right: h.right || '',
    fontSize: h.font_size ?? 9, distance: h.distance ?? 8, line: !!h.line,
    firstPageDifferent: h.first_page_different ?? false, firstHidden: h.first_hidden ?? false }
  const f = pc.footer
  settingsForm.footer = {
    enabled: f?.enabled ?? pc.show_page_number ?? true,
    left: f?.left || '', center: f?.center ?? '{page} / {total}', right: f?.right || '',
    fontSize: f?.font_size ?? 9, distance: f?.distance ?? 8, line: !!f?.line,
    firstHidden: f?.first_hidden ?? false }
  settingsForm.hfTemplate = 'custom'
  const ds = pc.default_style || {}
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
      info_bar_align: settingsForm.infoBarAlign,
      margin_preset: settingsForm.marginPreset,
      margins: settingsForm.margins,
      orientation: settingsForm.orientation,
      show_page_number: settingsForm.showPageNumber,
      show_score: settingsForm.showScore,
      show_total_score: settingsForm.showTotalScore,
      variables: { school: settingsForm.school, teacher: settingsForm.teacher },
      header: {
        enabled: settingsForm.header.enabled,
        left: settingsForm.header.left, center: settingsForm.header.center, right: settingsForm.header.right,
        font_size: settingsForm.header.fontSize, distance: settingsForm.header.distance,
        line: settingsForm.header.line,
        first_page_different: settingsForm.header.firstPageDifferent,
        first_hidden: settingsForm.header.firstHidden,
      },
      footer: {
        enabled: settingsForm.footer.enabled,
        left: settingsForm.footer.left, center: settingsForm.footer.center, right: settingsForm.footer.right,
        font_size: settingsForm.footer.fontSize, distance: settingsForm.footer.distance,
        line: settingsForm.footer.line,
        first_hidden: settingsForm.footer.firstHidden,
      },
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
  await flushLayout()
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
.addq-filter { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.margin-grid { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.margin-grid .el-input-number { width: 92px; }
.zone-row { display: flex; width: 100%; }
.zone-row .el-input { flex: 1; }
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
