<template>
  <div class="editor-page">
    <div class="editor-header">
      <div class="header-left">
        <el-button text @click="$router.push('/practices')">&larr; 返回列表</el-button>
        <b>{{ practice?.title || '加载中…' }}</b>
        <el-tag v-if="practice?.grade" size="small">{{ practice.grade }}</el-tag>
        <span class="qcount">{{ practice?.question_count || 0 }} 题</span>
      </div>
      <div>
        <el-button @click="openSettings"><el-icon><Setting /></el-icon> 练习设置</el-button>
        <el-button @click="previewRegroup"><el-icon><Sort /></el-icon> 整理结构</el-button>
        <el-button @click="unifyLayout"><el-icon><MagicStick /></el-icon> 统一排版</el-button>
      </div>
    </div>

    <div class="editor-body">
      <!-- 左：结构树 -->
      <div class="tree-panel">
        <div class="panel-head">
          <span>练习结构</span>
          <el-button size="small" text type="primary" @click="addSection">+ 小节</el-button>
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
            <span class="q-preview">{{ (q.content || '').slice(0, 20) }}</span>
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

      <!-- 中：块编辑区（Task 6 实现） -->
      <div class="edit-panel">
        <el-empty v-if="!selected" description="从左侧选择一道题开始编辑" />
      </div>

      <!-- 右：预览占位（阶段三接入） -->
      <div class="preview-panel">
        <el-empty description="A4 预览将在阶段三接入" :image-size="80" />
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
      </el-form>
      <template #footer>
        <el-button @click="showSettings = false">取消</el-button>
        <el-button type="primary" @click="saveSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

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
const settingsForm = reactive({ title: '', subtitle: '', showInfoBar: true })

const load = async () => {
  const res = await axios.get(`/api/practices/${practiceId}/detail`)
  practice.value = res.data
}

const selectQuestion = (s, q) => { selected.value = q; selectedSection.value = s; normalizeBlocks() }
const normalizeBlocks = () => {  // 旧块可能无 style，前端统一补空对象避免模板报错
  for (const b of (selected.value?.blocks || [])) { if (!b.style) b.style = {} }
}
const refresh = async () => { await load(); selected.value = null }

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
  await axios.put(`/api/practices/${practiceId}/questions/${q.id}/move`,
    { target_section_id: s.id, target_position: s.questions[idx - 1].position })
  await refresh()
}
const moveDown = async (s, q) => {
  const idx = s.questions.findIndex(x => x.id === q.id)
  if (idx < 0 || idx >= s.questions.length - 1) return
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
  showSettings.value = true
}
const saveSettings = async () => {
  await axios.put(`/api/practices/${practiceId}`, {
    title: settingsForm.title,
    subtitle: settingsForm.subtitle || null,
    page_config: { ...(practice.value.page_config || {}), show_info_bar: settingsForm.showInfoBar },
  })
  showSettings.value = false
  ElMessage.success('已保存')
  await load()
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
.preview-panel { width: 260px; border-left: 1px solid #ebeef5; display: flex; align-items: center; justify-content: center; color: #c0c4cc; }
.hint { color: #909399; font-size: 12px; margin-left: 8px; }
</style>
