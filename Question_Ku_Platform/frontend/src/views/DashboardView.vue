<template>
  <div class="page-shell page-enter">
    <header class="page-head" style="--i: 0">
      <span class="icon-chip icon-chip--sm bg-tint-brand text-on-tint-brand">
        <el-icon :size="17"><HomeFilled /></el-icon>
      </span>
      <h1 class="page-title">题库工作台</h1>
      <p class="page-subtitle">导入试卷 → 切题复核 → 选题组卷</p>
    </header>

    <!-- 统计卡：白底 + 柔投影 + 彩色图标芯片，hover 微抬 -->
    <div class="stagger mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <article
        v-for="(c, i) in statCards"
        :key="c.label"
        class="stat-card"
        :style="`--i: ${i}`"
      >
        <span class="icon-chip" :class="c.chip">
          <el-icon :size="18"><component :is="c.icon" /></el-icon>
        </span>
        <div class="min-w-0">
          <p class="stat-card__value tabular-nums">{{ loading ? '—' : c.value }}</p>
          <p class="stat-card__label">{{ c.label }}</p>
        </div>
      </article>
    </div>

    <!--
      两块等宽面板并排：左「最近动态」（题库侧），右「最近保存的练习」（编排侧）。
      两块都用 .panel-scroll 限高，内容超出时在**卡片内部**滚动，页面本身不被撑长；
      等宽等高也让两侧节奏一致。
    -->
    <div class="mt-5 grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
      <!-- 左：最近动态 -->
      <section class="panel" style="--i: 5">
        <header class="panel-head">
          <div>
            <h2 class="panel-title">最近动态</h2>
            <p class="panel-hint">题库与练习记录的最新变化</p>
          </div>
        </header>
        <ul v-if="recentSources.length" class="panel-scroll border-t border-line px-5 py-1">
          <li v-for="s in recentSources" :key="s.id" class="tl-item">
            <span class="tl-dot" :class="statusDot(s.ocr_status)"></span>
            <div class="min-w-0 flex-1 py-1">
              <p class="truncate text-sm text-ink">{{ s.filename }}</p>
              <p class="mt-1.5 flex items-center gap-2 text-xs text-ink-muted">
                <span>{{ statusText(s.ocr_status) }}</span>
                <span class="text-line">·</span>
                <span class="tabular-nums">{{ formatTime(s.created_at) }}</span>
              </p>
            </div>
            <el-button
              v-if="s.ocr_status === 'staging' || s.ocr_status === 'done'"
              text
              size="small"
              type="primary"
              class="shrink-0"
              @click="$router.push(`/extract/${s.id}`)"
            >
              复核
            </el-button>
            <el-button
              v-else-if="s.ocr_status === 'error'"
              text
              size="small"
              class="shrink-0"
              @click="$router.push('/upload')"
            >
              处理
            </el-button>
          </li>
        </ul>
        <div v-else class="border-t border-line px-6 py-12 text-center">
          <p class="text-sm text-ink-muted">
            {{ loading ? '正在读取最近动态…' : '还没有导入记录' }}
          </p>
        </div>
      </section>

      <!-- 右：最近保存的练习 -->
      <section class="panel" style="--i: 6">
        <header class="panel-head">
          <div>
            <h2 class="panel-title">最近保存的练习</h2>
            <p class="panel-hint">打开已保存的练习，继续选题与编排</p>
          </div>
          <el-button text size="small" type="primary" @click="$router.push('/practices')">
            查看全部<el-icon class="ml-1"><ArrowRight /></el-icon>
          </el-button>
        </header>

        <ul v-if="recentPractices.length" class="panel-scroll border-t border-line">
          <li v-for="p in recentPractices" :key="p.id" class="row-item">
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-medium text-ink">{{ p.title }}</p>
              <p class="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                <span class="tabular-nums">{{ p.question_count ?? 0 }} 题</span>
                <span class="text-line">·</span>
                <span class="tabular-nums">{{ formatTime(p.updated_at || p.created_at) }}</span>
                <el-tag v-if="p.is_baseline" size="small" effect="plain">基线</el-tag>
              </p>
            </div>
            <div class="row-actions shrink-0">
              <el-button size="small" @click="openPractice(p)">继续编辑</el-button>
            </div>
          </li>
        </ul>

        <div v-else class="border-t border-line px-6 py-14 text-center">
          <p class="text-base font-medium text-ink">
            {{ loading ? '正在读取练习记录…' : '还没有保存过练习' }}
          </p>
          <template v-if="!loading">
            <p class="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-ink-muted">
              去选题池挑几道题，创建第一份练习册，再进入编辑器排版导出。
            </p>
            <el-button class="mt-4" size="small" type="primary" @click="$router.push('/basket')">
              前往选题池
            </el-button>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const router = useRouter()
const loading = ref(true)
const totalQuestions = ref(0)
const pendingQuestions = ref(0)
const practices = ref([])
const sources = ref([])

// 统计口径全部走现有接口：题量用 /api/questions 的 total（只要 1 条即可），
// 不为了统计新增后端端点。
const load = async () => {
  loading.value = true
  try {
    const [all, pending, practiceRes, sourceRes] = await Promise.all([
      axios.get('/api/questions', { params: { page: 1, page_size: 1 } }),
      axios.get('/api/questions', { params: { page: 1, page_size: 1, review_status: 'pending' } }),
      axios.get('/api/practices'),
      axios.get('/api/sources'),
    ])
    totalQuestions.value = all.data.total || 0
    pendingQuestions.value = pending.data.total || 0
    practices.value = practiceRes.data.practices || []
    sources.value = sourceRes.data.sources || []
  } catch (e) {
    ElMessage.error('工作台数据加载失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

const thisMonthImports = computed(() => {
  const now = new Date()
  return sources.value.filter((s) => {
    if (!s.created_at) return false
    const d = new Date(s.created_at)
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
  }).length
})

// chip 用成对色阶：模板不自己配颜色，暗色下整站自动换一套
const statCards = computed(() => [
  {
    label: '题库总量',
    value: totalQuestions.value,
    hint: '已入库的题目',
    icon: 'Files',
    chip: 'bg-tint-brand text-on-tint-brand',
  },
  {
    label: '待复核',
    value: pendingQuestions.value,
    hint: '需要人工核对答案',
    icon: 'WarningFilled',
    chip: 'bg-tint-amber text-on-tint-amber',
  },
  {
    label: '练习册',
    value: practices.value.length,
    hint: '已保存可编辑',
    icon: 'Notebook',
    chip: 'bg-tint-emerald text-on-tint-emerald',
  },
  {
    label: '本月导入',
    value: thisMonthImports.value,
    hint: '本月新增的试卷',
    icon: 'Upload',
    chip: 'bg-tint-slate text-on-tint-slate',
  },
])

// 两块卡片内部可滚动，所以不再只取三五条：以前截断是为了不让页面变长，
// 现在页面长度由卡片高度上限控制，多列一些才对得起那个滚动条。
const recentPractices = computed(() => practices.value.slice(0, 20))
const recentSources = computed(() => sources.value.slice(0, 20))

const openPractice = (p) => {
  router.push(`/practice/editor?id=${p.id}`)
}

const statusText = (status) => {
  const map = {
    pending: '等待中',
    processing: '处理中',
    staging: '待确认',
    done: '已入库',
    error: '失败',
  }
  return map[status] || status || '—'
}

const statusDot = (status) => {
  if (status === 'done') return 'bg-emerald-500'
  if (status === 'staging') return 'bg-amber-500'
  if (status === 'error') return 'bg-red-500'
  if (status === 'processing') return 'bg-primary-500'
  return 'bg-slate-300'
}

const formatTime = (t) => {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<style scoped>
/* 最近动态：竖向发丝线 + 状态点。
   行距与按钮对齐：两行文本（标题 + 元信息）加按钮挤在 12px 行距里显得局促，
   行距放宽到 18px、按钮与文本块垂直居中。 */
.tl-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 0;
}

.tl-item::before {
  position: absolute;
  top: 30px;
  bottom: -18px;
  left: 3px;
  width: 1px;
  background: var(--color-line);
  content: '';
}

.tl-item:last-child::before {
  display: none;
}

.tl-dot {
  position: relative;
  z-index: 1;
  width: 7px;
  height: 7px;
  margin-top: 0;
  flex-shrink: 0;
  border-radius: 999px;
}
</style>
