<template>
  <div class="page-shell page-enter">
    <header class="page-head" style="--i: 0">
      <span class="icon-chip icon-chip--sm bg-tint-amber text-on-tint-amber">
        <el-icon :size="17"><Notebook /></el-icon>
      </span>
      <h1 class="page-title">练习组卷</h1>
      <p class="page-subtitle">
        共 {{ practices.length }} 份<template v-if="totalQuestions"> · 合计 {{ totalQuestions }} 题</template>
      </p>
      <div class="ml-auto flex items-center gap-2">
        <el-button size="small" @click="load"><el-icon><Refresh /></el-icon></el-button>
        <el-button size="small" type="primary" @click="$router.push('/basket')">
          <el-icon><ShoppingCart /></el-icon> 去选题池创建
        </el-button>
      </div>
    </header>

    <div
      v-if="loading"
      class="rounded-card border border-line bg-surface px-6 py-10 text-center text-sm text-ink-muted"
    >
      正在读取练习…
    </div>

    <div
      v-else-if="!practices.length"
      class="rounded-card border border-line bg-surface px-6 py-14 text-center"
    >
      <p class="text-sm font-medium text-ink">还没有练习</p>
      <p class="mx-auto mt-1.5 max-w-sm text-sm leading-relaxed text-ink-muted">
        去选题池挑几道题，创建第一份练习册，再进入编辑器排版导出。
      </p>
      <el-button class="mt-4" size="small" @click="$router.push('/basket')">前往选题池</el-button>
    </div>

    <!-- 单列一行行：练习数不多（个位数到几十），两三列栅格让标题/时间/操作
         挤在窄卡里，一行通栏反而看得清楚 -->
    <div v-else class="grid grid-cols-1 gap-3">
      <article
        v-for="p in practices"
        :key="p.id"
        class="card-interactive flex cursor-pointer flex-col rounded-card border border-line bg-surface px-5 py-4"
        @click="openDetail(p)"
        @mouseenter="preloadEditor"
      >
        <header class="flex items-start justify-between gap-3">
          <h3 class="truncate text-sm font-semibold text-ink">{{ p.title }}</h3>
          <span class="flex shrink-0 items-center gap-1">
            <el-tag v-if="p.is_baseline" size="small" type="warning" effect="plain">基线样本</el-tag>
            <el-tag size="small" :type="p.status === 'exported' ? 'success' : 'info'" effect="plain">
              {{ p.status === 'exported' ? '已导出' : '草稿' }}
            </el-tag>
          </span>
        </header>

        <p class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
          <span v-if="p.subject">{{ p.subject }}</span>
          <span v-if="p.grade">{{ p.grade }}</span>
          <span class="tabular-nums">{{ p.question_count }} 题</span>
        </p>

        <footer class="mt-4 flex items-center justify-between border-t border-line pt-3">
          <span class="tabular-nums text-xs text-ink-muted">
            {{ formatTime(p.updated_at || p.created_at) }}
          </span>
          <span class="flex items-center gap-1">
            <!-- 原「试卷记录」页的导出能力迁到这里：练习列表即归档，导出不必换页 -->
            <el-button size="small" text :loading="exporting === p.id + 'docx'" @click.stop="exportAs(p, 'docx')">
              导出word
            </el-button>
            <el-button size="small" text :loading="exporting === p.id + 'pdf'" @click.stop="exportAs(p, 'pdf')">
              导出PDF
            </el-button>
            <el-button size="small" text @click.stop="rename(p)">重命名</el-button>
            <el-button size="small" text type="danger" @click.stop="remove(p)">删除</el-button>
          </span>
        </footer>
      </article>
    </div>

    <!--
      重命名 / 只读详情两个弹窗都显式 append-to-body：
      默认不 teleport 时，弹窗会留在 .page-shell 内部，一旦页面上任何祖先带了
      transform / filter / backdrop-filter，position:fixed 的 .el-overlay 就会认那个
      祖先当包含块（详见 styles/main.css 里 .page-enter 那段的说明）。
      挂到 body 上就与页面的层叠上下文彻底脱钩。
    -->
    <el-dialog v-model="showRename" title="重命名练习" width="380px" append-to-body>
      <el-input v-model="renameTitle" />
      <template #footer>
        <el-button @click="showRename = false">取消</el-button>
        <el-button type="primary" @click="doRename">保存</el-button>
      </template>
    </el-dialog>

    <!--
      只读详情：练习长起来能到几千 px（实测一份 50 题的练习弹窗高 4487px），
      所以加 .dialog-scroll-body 让正文限高、内部滚动，标题与底部按钮始终可见。
    -->
    <el-dialog
      v-model="showDetail"
      :title="detail?.title"
      width="720px"
      top="6vh"
      append-to-body
      class="dialog-scroll-body"
    >
      <div v-if="detail">
        <!--
          预览直接给**渲染后的 PDF 页图**（与编辑器右栏同一条渲染链路）：
          原先按题罗列 HTML，看的是内容而不是最终排版 —— 行高、分页、公式
          渲染成什么样，只有 PDF 说了算。sha 缓存生效时这个请求是毫秒级的。
        -->
        <div v-if="previewLoading" class="preview-state">正在渲染 PDF 预览…（首次约几秒）</div>
        <div v-else-if="previewError" class="preview-state">{{ previewError }}</div>
        <div v-else-if="previewPages" class="pv-pages">
          <img
            v-for="n in previewPages"
            :key="n"
            class="pv-page"
            :src="`/api/practices/${detail.id}/preview/page/${n}?scale=1.5`"
            :alt="`第 ${n} 页`"
          />
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
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const practices = ref([])
const loading = ref(true)
const showRename = ref(false)
const renameTitle = ref('')
const renameTarget = ref(null)
const showDetail = ref(false)
const detail = ref(null)
const previewPages = ref(0)
const previewLoading = ref(false)
const previewError = ref('')

const totalQuestions = computed(() =>
  practices.value.reduce((sum, p) => sum + (p.question_count || 0), 0),
)

const load = async () => {
  loading.value = true
  try {
    const res = await axios.get('/api/practices')
    practices.value = res.data.practices
  } finally {
    loading.value = false
  }
}

// 悬停即预热编辑器的路由分块（~400KB）：首次点击进入编辑器的顿挫，
// 大头是这个懒加载 chunk 的下载，悬停时提前拉取基本可以消掉。
const preloadEditor = () => {
  import('../views/PracticeEditorView.vue')
}

const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : ''

const openDetail = async (p) => {
  const res = await axios.get(`/api/practices/${p.id}`)
  detail.value = res.data
  showDetail.value = true
  // 渲染整册 PDF 并取页数。失败（如部署环境缺 Chromium）时给出后端的
  // 可行动提示，而不是让弹窗空白。
  previewError.value = ''
  previewLoading.value = true
  try {
    const r = await axios.post(`/api/practices/${p.id}/render`)
    previewPages.value = r.data.pages
  } catch (e) {
    previewPages.value = 0
    previewError.value = e.response?.data?.detail || '渲染预览失败'
  } finally {
    previewLoading.value = false
  }
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

// 原 PapersView 的导出逻辑原样迁入：用 blob 接文件而不是直接跳转 <a href>，
// 这样导出失败时能读到后端返回的 JSON 错误并提示，而不是让用户下到一个坏文件。
const exporting = ref('')

const exportAs = async (p, kind) => {
  exporting.value = p.id + kind
  try {
    const res = await axios.get(`/api/practices/${p.id}/export/${kind}`, {
      responseType: 'blob',
    })
    const contentType = String(res.headers?.['content-type'] || '')
    if (contentType.includes('application/json')) {
      // 后端出错时返回的是 JSON，不是文件
      const text = await res.data.text()
      let detail = '导出失败'
      try {
        detail = JSON.parse(text).detail || detail
      } catch {
        /* 保持默认文案 */
      }
      ElMessage.error(detail)
      return
    }
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `${p.title}.${kind}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('导出失败：' + (e.response?.data?.detail || e.message))
  } finally {
    exporting.value = ''
  }
}

onMounted(load)
</script>

<style scoped>
/* PDF 页图预览：纵向连排，页间留缝，跨页一目了然 */
.preview-state { padding: 24px 0; text-align: center; color: var(--color-ink-muted); font-size: 13px; }
.pv-pages { display: flex; flex-direction: column; gap: 14px; }
.pv-page { display: block; width: 100%; box-shadow: 0 1px 6px rgba(0, 0, 0, 0.15); background: #fff; }
</style>
