<template>
  <div class="practice-list-view">
    <div class="page-header">
      <div>
        <h2>练习列表</h2>
        <p class="subtitle">从选题池创建练习，点击进入编辑器开始整理题目</p>
      </div>
      <el-button @click="$router.push('/basket')"><el-icon><ShoppingCart /></el-icon> 去选题池创建</el-button>
    </div>

    <el-empty v-if="!practices.length" description="还没有练习，从选题池创建一份吧" />
    <div class="practice-grid" v-else>
      <el-card v-for="p in practices" :key="p.id" class="practice-card" shadow="hover" @click="openDetail(p)">
        <div class="card-title">
          <span>{{ p.title }}</span>
          <el-tag v-if="p.is_baseline" size="small" type="warning">基线样本</el-tag>
          <el-tag size="small" :type="p.status === 'exported' ? 'success' : 'info'">{{ p.status === 'exported' ? '已导出' : '草稿' }}</el-tag>
        </div>
        <div class="card-meta">
          <span v-if="p.subject">{{ p.subject }}</span>
          <span v-if="p.grade">{{ p.grade }}</span>
          <span>{{ p.question_count }} 题</span>
        </div>
        <div class="card-footer">
          <span class="card-time">{{ formatTime(p.updated_at || p.created_at) }}</span>
          <span>
            <el-button size="small" text @click.stop="rename(p)">重命名</el-button>
            <el-button size="small" text type="danger" @click.stop="remove(p)">删除</el-button>
          </span>
        </div>
      </el-card>
    </div>

    <!-- 重命名 -->
    <el-dialog v-model="showRename" title="重命名练习" width="380px">
      <el-input v-model="renameTitle" />
      <template #footer>
        <el-button @click="showRename = false">取消</el-button>
        <el-button type="primary" @click="doRename">保存</el-button>
      </template>
    </el-dialog>

    <!-- 只读详情 -->
    <el-dialog v-model="showDetail" :title="detail?.title" width="720px" top="6vh">
      <div v-if="detail">
        <div v-for="s in detail.sections" :key="s.id" class="detail-section">
          <h4>{{ s.title }}</h4>
          <div v-for="(q, qi) in s.questions" :key="q.id" class="detail-question">
            <div class="q-meta">
              <b>{{ globalNumber(s, qi) }}.</b>
              <el-tag v-if="q.is_modified" size="small" type="warning">已修改</el-tag>
            </div>
            <div class="q-content" v-html="renderPreview(q.content, 400)"></div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="$router.push('/practice/editor?id=' + detail.id)">进入编辑器</el-button>
        <el-button @click="showDetail = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { renderPreview } from '../utils/render'

const practices = ref([])
const showRename = ref(false)
const renameTitle = ref('')
const renameTarget = ref(null)
const showDetail = ref(false)
const detail = ref(null)

const load = async () => {
  const res = await axios.get('/api/practices')
  practices.value = res.data.practices
}

const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : ''

const globalNumber = (section, idx) => {
  // 只读预览用：按小节顺序连续编号（与后续编辑器的编号规则一致）
  let n = 0
  for (const s of detail.value.sections) {
    if (s.id === section.id) return n + idx + 1
    n += s.questions.length
  }
  return idx + 1
}

const openDetail = async (p) => {
  const res = await axios.get(`/api/practices/${p.id}`)
  detail.value = res.data
  showDetail.value = true
}

const rename = (p) => {
  renameTarget.value = p
  renameTitle.value = p.title
  showRename.value = true
}

const doRename = async () => {
  if (!renameTitle.value.trim()) return
  await axios.put(`/api/practices/${renameTarget.value.id}`, { title: renameTitle.value.trim() })
  showRename.value = false
  ElMessage.success('已重命名')
  await load()
}

const remove = async (p) => {
  const warn = p.is_baseline
    ? `“${p.title}”是基线样本，删除后需重新构建基线。确定删除？`
    : `确定删除练习“${p.title}”？删除后不可恢复。`
  await ElMessageBox.confirm(warn, '提示', { type: 'warning' })
  await axios.delete(`/api/practices/${p.id}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.practice-list-view { max-width: 1100px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.subtitle { color: #909399; }
.practice-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.practice-card { cursor: pointer; }
.card-title { display: flex; justify-content: space-between; align-items: center; font-weight: bold; margin-bottom: 8px; }
.card-meta { display: flex; gap: 8px; color: #606266; font-size: 13px; margin-bottom: 8px; }
.card-footer { display: flex; justify-content: space-between; align-items: center; }
.card-time { color: #909399; font-size: 12px; }
.detail-section { margin-bottom: 16px; }
.detail-question { padding: 8px 0; border-bottom: 1px dashed #ebeef5; }
.q-meta { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
.q-content { color: #303133; font-size: 14px; }
.q-content :deep(img) { max-height: 100px; }
</style>
