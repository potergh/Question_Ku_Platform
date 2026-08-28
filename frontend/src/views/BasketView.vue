<template>
  <div class="basket-view">
    <div class="basket-header">
      <div>
        <h2>临时选题池</h2>
        <p class="subtitle">本次练习的候选题目，刷新不丢失</p>
      </div>
      <div>
        <el-button @click="$router.push('/library')">继续选题</el-button>
        <el-button danger plain :disabled="!items.length" @click="clearBasket">清空</el-button>
        <el-button type="primary" :disabled="!items.length" @click="showCreate = true">创建练习</el-button>
      </div>
    </div>

    <el-card v-if="items.length" style="margin-bottom: 12px;">
      <el-tag v-for="(n, t) in basket.type_stats" :key="t" style="margin-right: 8px;">{{ t }} × {{ n }}</el-tag>
      <el-select v-model="typeFilter" placeholder="按题型筛选" clearable style="width: 140px; margin-left: 16px;">
        <el-option v-for="t in Object.keys(basket.type_stats || {})" :key="t" :label="t" :value="t" />
      </el-select>
    </el-card>

    <el-card>
      <el-empty v-if="!items.length" description="选题池为空，去题库选题吧">
        <el-button type="primary" @click="$router.push('/library')">去题库</el-button>
      </el-empty>
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
.basket-view { max-width: 1000px; margin: 0 auto; }
.basket-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.subtitle { color: #909399; }
.basket-item { display: flex; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid #ebeef5; }
.item-main { flex: 1; min-width: 0; }
.item-meta { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.item-content { color: #303133; font-size: 14px; }
.item-content :deep(img) { max-height: 80px; }
.item-actions { display: flex; flex-direction: column; }
</style>
