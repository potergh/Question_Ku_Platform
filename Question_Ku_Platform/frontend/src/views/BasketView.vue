<template>
  <div class="page-shell max-w-[1000px] page-enter">
    <header class="page-head" style="--i: 0">
      <span class="icon-chip icon-chip--sm bg-tint-amber text-on-tint-amber">
        <el-icon :size="17"><ShoppingCart /></el-icon>
      </span>
      <h1 class="page-title">临时选题池</h1>
      <p class="page-subtitle">本次练习的候选题目，刷新不丢失</p>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <el-button type="primary" plain @click="openRecommend">智能选题</el-button>
        <el-button @click="$router.push('/library')">继续选题</el-button>
        <el-button danger plain :disabled="!items.length" @click="clearBasket">清空</el-button>
        <el-button type="primary" :disabled="!items.length" @click="showCreate = true">创建练习</el-button>
      </div>
    </header>

    <el-card v-if="items.length" style="margin-bottom: 12px;">
      <el-tag v-for="(n, t) in basket.type_stats" :key="t" style="margin-right: 8px;">{{ t }} × {{ n }}</el-tag>
      <el-select v-model="typeFilter" placeholder="按题型筛选" clearable style="width: 140px; margin-left: 16px;">
        <el-option v-for="t in Object.keys(basket.type_stats || {})" :key="t" :label="t" :value="t" />
      </el-select>
    </el-card>

    <el-card>
      <!-- 空状态手写而不是 el-empty：它的默认插画已全局隐藏，手写才能带上图标芯片，
           并且把"空"讲成"下一步做什么"。 -->
      <div v-if="!items.length" class="flex flex-col items-center justify-center py-12 text-center">
        <span class="icon-chip icon-chip--lg bg-tint-slate text-on-tint-slate">
          <el-icon :size="20"><ShoppingCart /></el-icon>
        </span>
        <p class="mt-3 text-base font-medium text-ink">选题池是空的</p>
        <p class="mt-1 text-sm text-ink-muted">去题库挑选题目，或用「智能选题」生成候选</p>
        <el-button class="mt-4" type="primary" @click="$router.push('/library')">去题库选题</el-button>
      </div>
      <div v-for="(it, idx) in filteredItems" :key="it.question.id" class="basket-item">
        <div class="item-main">
          <div class="item-meta">
            <el-tag size="small">{{ typeZh(it.question.question_type) }}</el-tag>
            <el-tag v-if="it.question.difficulty" size="small" type="warning">{{ it.question.difficulty }} 星</el-tag>
          </div>
          <div class="item-content" v-html="renderPreview(it.question.content)"></div>
        </div>
        <div class="item-actions">
          <el-button size="small" text :disabled="idx === 0" @click="move(idx, -1)"><el-icon><Top /></el-icon></el-button>
          <el-button size="small" text :disabled="idx === filteredItems.length - 1" @click="move(idx, 1)"><el-icon><Bottom /></el-icon></el-button>
          <el-button size="small" text type="danger" @click="remove(it)"><el-icon><Delete /></el-icon></el-button>
        </div>
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="创建练习" width="420px">
      <el-form label-width="90px">
        <el-form-item label="练习标题" required>
          <el-input v-model="createForm.title" placeholder="如：浮力专项练习" />
        </el-form-item>
        <el-form-item label="学科">
          <el-input v-model="createForm.subject" placeholder="如：物理（可留空）" />
        </el-form-item>
        <el-form-item label="年级">
          <el-select v-model="createForm.grade" clearable style="width: 100%;">
            <el-option v-for="g in ['初一', '初二', '初三', '中考']" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="创建后">
          <el-checkbox v-model="createForm.clear_basket">清空选题池</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createPractice">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showRecommend" title="智能选题" top="6vh" draggable class="rec-dialog">
      <div class="rec-layout">
        <div class="rec-form">
          <el-form label-position="top">
            <el-form-item label="学科">
              <el-select v-model="recForm.subject" clearable filterable placeholder="全部学科" style="width: 100%;">
                <el-option v-for="s in subjectOptions" :key="s.value" :label="s.label" :value="s.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="年级">
              <el-select v-model="recForm.grade" clearable placeholder="全部年级" style="width: 100%;">
                <el-option v-for="g in ['初一', '初二', '初三', '中考']" :key="g" :label="g" :value="g" />
              </el-select>
            </el-form-item>
            <el-form-item label="考点标签">
              <el-select v-model="recForm.tag_ids" multiple filterable collapse-tags placeholder="选择考点（可多选）" style="width: 100%;">
                <el-option v-for="t in tagOptions" :key="t.id" :label="t.name" :value="t.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="难度（多选平均分配）">
              <el-select v-model="recForm.difficulty_bands" multiple placeholder="全部难度" style="width: 100%;">
                <el-option label="容易" value="easy" />
                <el-option label="中等" value="medium" />
                <el-option label="困难" value="hard" />
              </el-select>
            </el-form-item>
            <el-form-item label="题型">
              <el-select v-model="recForm.question_types" multiple placeholder="全部题型" style="width: 100%;">
                <el-option v-for="t in ['选择题', '多选题', '填空题', '解答题', '计算题', '实验题', '简答题']" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="题量（推荐条数 = 题量 × 2）">
              <el-input-number v-model="recForm.count" :min="1" :max="50" style="width: 100%;" />
            </el-form-item>
            <el-form-item label="排除已用题目（选题池已有 / 已入练习）">
              <el-switch v-model="recForm.exclude_used" />
            </el-form-item>
            <el-button type="primary" :loading="recLoading" style="width: 100%;" @click="generateRecommend">生成推荐</el-button>
          </el-form>
        </div>
        <div class="rec-results">
          <el-empty v-if="!recItems.length && !recLoading" description="设置条件后点击「生成推荐」" />
          <template v-if="recItems.length">
            <el-checkbox-group v-model="recSelected">
              <div v-for="it in recItems" :key="it.id" class="rec-item">
                <el-checkbox :value="it.id" class="rec-check">
                  <div class="rec-slot">
                    <div class="rec-meta">
                      <el-tag size="small">{{ typeZh(it.question_type) }}</el-tag>
                      <el-tag v-if="it.difficulty" size="small" type="warning">{{ it.difficulty }} 星</el-tag>
                      <span v-if="it.grade" class="rec-grade">{{ it.grade }}</span>
                    </div>
                    <div class="rec-tags">
                      <el-tag v-for="t in it.tags.slice(0, 4)" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
                    </div>
                    <div class="rec-content" v-html="renderPreview(it.content)"></div>
                    <div class="rec-reason">{{ it.reason }}</div>
                  </div>
                </el-checkbox>
              </div>
            </el-checkbox-group>
            <div class="rec-footer">
              <span>已选 {{ recSelected.length }} 题</span>
              <div>
                <el-button :disabled="recLoading" @click="generateRecommend">换一批</el-button>
                <el-button type="primary" :disabled="!recSelected.length" :loading="recAdding" @click="addSelected">加入选题池 ({{ recSelected.length }})</el-button>
              </div>
            </div>
          </template>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { renderPreview } from '../utils/render'
import { QUESTION_TYPE_MAP } from '../utils/questionTypes'

const router = useRouter()
const basket = ref({ items: [], type_stats: {} })
const typeFilter = ref('')
const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ title: '', subject: '', grade: '', clear_basket: true })

const items = computed(() => basket.value.items || [])
const filteredItems = computed(() =>
  typeFilter.value
    ? items.value.filter(it => typeZh(it.question.question_type) === typeFilter.value)
    : items.value
)

const typeZh = (t) => QUESTION_TYPE_MAP[t] || t || '未知题型'

const load = async () => {
  const res = await axios.get('/api/basket')
  basket.value = res.data
}

const remove = async (it) => {
  await axios.post('/api/basket/items/remove', { question_ids: [it.question.id] })
  await load()
}

const move = async (idx, dir) => {
  // 筛选子序列内移动，再按原位置回填全量顺序
  const ids = filteredItems.value.map(it => it.question.id)
  const [x] = ids.splice(idx, 1)
  ids.splice(idx + dir, 0, x)
  const visible = new Set(filteredItems.value.map(it => it.question.id))
  let vi = 0
  const merged = items.value.map(it => visible.has(it.question.id) ? ids[vi++] : it.question.id)
  await axios.put('/api/basket/reorder', { question_ids: merged })
  await load()
}

const clearBasket = async () => {
  await ElMessageBox.confirm('确定清空选题池？', '提示', { type: 'warning' })
  await axios.delete('/api/basket')
  ElMessage.success('选题池已清空')
  await load()
}

// ---------- 智能选题 ----------
const showRecommend = ref(false)
const recLoading = ref(false)
const recAdding = ref(false)
const recItems = ref([])
const recSelected = ref([])
const tagOptions = ref([])
const subjectOptions = ref([
  { value: 'physics', label: '物理' },
  { value: 'math', label: '数学' },
  { value: 'chemistry', label: '化学' },
  { value: 'english', label: '英语' },
])
const recForm = ref({
  subject: '', grade: '', tag_ids: [], difficulty_bands: [],
  question_types: [], count: 10, exclude_used: true,
})

const openRecommend = async () => {
  showRecommend.value = true
  recItems.value = []
  recSelected.value = []
  if (!tagOptions.value.length) {
    try {
      const res = await axios.get('/api/tags', { params: { category: 'knowledge' } })
      tagOptions.value = res.data || []
    } catch { /* 标签加载失败不影响弹窗打开 */ }
  }
}

const generateRecommend = async () => {
  recLoading.value = true
  try {
    const res = await axios.post('/api/recommend', {
      subject: recForm.value.subject || null,
      grade: recForm.value.grade || null,
      tag_ids: recForm.value.tag_ids,
      difficulty_bands: recForm.value.difficulty_bands,
      question_types: recForm.value.question_types,
      count: recForm.value.count,
      exclude_used: recForm.value.exclude_used,
    })
    recItems.value = res.data.items || []
    recSelected.value = []
    if (!recItems.value.length) ElMessage.info('没有符合条件的题目，请放宽条件')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '推荐失败')
  } finally {
    recLoading.value = false
  }
}

const addSelected = async () => {
  recAdding.value = true
  try {
    await axios.post('/api/basket/items', { question_ids: recSelected.value })
    ElMessage.success(`已加入 ${recSelected.value.length} 题到选题池`)
    showRecommend.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加入失败')
  } finally {
    recAdding.value = false
  }
}

const createPractice = async () => {
  if (!createForm.value.title.trim()) {
    ElMessage.warning('请输入练习标题')
    return
  }
  creating.value = true
  try {
    await axios.post('/api/practices', {
      title: createForm.value.title.trim(),
      subject: createForm.value.subject || null,
      grade: createForm.value.grade || null,
      from_basket: true,
      clear_basket: createForm.value.clear_basket,
    })
    ElMessage.success('练习已创建')
    router.push('/practices')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

onMounted(load)
</script>

<style scoped>

.basket-item { display: flex; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--color-line); }
.item-main { flex: 1; min-width: 0; }
.item-meta { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.item-content { color: var(--color-ink); font-size: 14px; }
.item-content :deep(img) { max-height: 80px; }
.item-actions { display: flex; flex-direction: column; }
.rec-layout { display: flex; gap: 16px; }
.rec-form { width: 220px; flex-shrink: 0; border-right: 1px solid var(--color-line); padding-right: 14px; }
.rec-results { flex: 1; min-width: 0; min-height: 0; overflow-y: auto; padding: 4px 4px 0; }
.rec-item { padding: 16px; margin-bottom: 14px; background: var(--color-surface); border: 1px solid var(--color-line); border-radius: 10px; transition: border-color .2s, box-shadow .2s; }
.rec-item:hover { border-color: var(--color-primary-200); box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.rec-check { display: flex; width: 100%; align-items: flex-start; height: auto; white-space: normal; }
.rec-check .el-checkbox__label { flex: 1; min-width: 0; line-height: normal; }
.rec-slot { display: block; width: 100%; }
.rec-meta { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.rec-grade { color: var(--color-ink-muted); font-size: 12px; }
.rec-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.rec-content { color: var(--color-ink); font-size: 14px; line-height: 1.7; word-break: break-word; }
.rec-content :deep(img) { max-height: 60px; max-width: 100%; }
.rec-reason { margin-top: 12px; padding: 6px 10px; background: var(--color-canvas); border-radius: 5px; color: var(--color-ink-muted); font-size: 12px; }
.rec-footer { position: sticky; bottom: 0; margin-top: 4px; background: var(--color-surface); padding: 10px 0; border-top: 1px solid var(--color-line); display: flex; justify-content: space-between; align-items: center; }
</style>

<style>
/* 全局（teleport 到 body，scoped 不生效）：智能选题弹窗可拖拽拉伸 */
.rec-dialog.el-dialog {
  resize: both;
  overflow: hidden;
  --el-dialog-width: min(1240px, 96vw) !important;
  min-width: 540px;
  min-height: 440px;
  max-height: 92vh;
  display: flex;
  flex-direction: column;
}
.rec-dialog .el-dialog__header { flex-shrink: 0; }
.rec-dialog .el-dialog__body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.rec-dialog .rec-layout { flex: 1; min-height: 0; display: flex; gap: 16px; overflow: hidden; }
.rec-dialog .rec-results { flex: 1; min-height: 0; overflow-y: auto; }
</style>
