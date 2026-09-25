<template>
  <div class="page-shell max-w-[800px] page-enter">
    <header class="page-head" style="--i: 0">
      <span class="icon-chip icon-chip--sm bg-tint-slate text-on-tint-slate">
        <el-icon :size="17"><Setting /></el-icon>
      </span>
      <h1 class="page-title">系统设置</h1>
      <p class="page-subtitle">配置识别模式、模型参数与导出选项</p>
    </header>

    <el-card>
      <template #header>
        <div class="card-header">
          <span>识别与模型配置</span>
          <!--
            右上角状态改为「凭据是否配齐」，不再显示识别模式。
            模式那三档已在导入页的通道单选项里选了，这里再显示一遍只会让人
            以为存在第二个开关（实测确实有人在这里切成"本地识别"后，
            反而把导入页选的大模型通道效果改没了）。
          -->
          <el-tag :type="configStatusType" size="small">{{ configStatusText }}</el-tag>
        </div>
      </template>

      <el-form label-width="120px" style="max-width: 600px;">
        <!--
          为什么没有「识别模式」总开关：它和导入页的通道单选项是同一件事的两处
          表达，会互相打架；而且关掉后连"改回来"的按钮都会一起消失。
          现在通道只在导入页选一次，本页只负责配凭据。
          后端判据已同步为「只看有没有 Key / Base URL」，见 get_vision_config
          与 ai_service._get_ai_config。
        -->

        <!--
          MinerU 段放在**最前**：它替换的只是"把 PDF 变成文字行"这一步，
          后面的判题边界与逐题结构化仍要调大模型，所以顺序是
          「先配解析通道，再配切题参数」。
        -->
        <!--
          注意：这里**不能用裸 <template> 包裹分节**。没有指令的 <template> 会被
          Vue 当普通元素渲染进 DOM，而浏览器的 UA 样式对它是 display:none 且内容
          不参与布局 —— 表现就是整节"看得见标题、填不了参数"（实测就是这条）。
          分节只靠 el-divider，不需要包裹元素。
        -->
        <el-divider content-position="left">
          <span class="divider-text">MinerU 识别通道</span>
        </el-divider>

          <el-form-item label="MinerU Token">
            <el-input
              v-model="form.mineru_api_token"
              :type="showMineruToken ? 'text' : 'password'"
              :placeholder="mineruTokenPlaceholder"
              clearable
            >
              <template #suffix>
                <el-icon @click="showMineruToken = !showMineruToken" style="cursor: pointer;">
                  <View v-if="showMineruToken" /><Hide v-else />
                </el-icon>
              </template>
            </el-input>
            <!--
              落库状态必须独立成行、带颜色地说。保存后输入框会被清空（密码不回显
              明文），而这句话原来只写在灰色 placeholder 里 —— 和"请输入"长得一模一样，
              实测用户填完 Token 点保存、看到空框就断定"没保存上"，其实库里早存好了。
            -->
            <div class="secret-state" :class="maskedMineruToken ? 'is-saved' : 'is-empty'">
              <template v-if="maskedMineruToken">已保存 {{ maskedMineruToken }}</template>
              <template v-else>尚未配置</template>
            </div>
            <div class="form-hint">
              在 mineru.net 的「API 管理」里申请。该通道只替换文字识别那一步，
              下面的大模型参数（判题边界与逐题结构化）也要配好，缺一个都用不了。
            </div>
          </el-form-item>

          <el-form-item label="解析后端">
            <el-select v-model="form.mineru_model_version" style="width: 240px">
              <el-option label="vlm（推荐）" value="vlm" />
              <el-option label="pipeline" value="pipeline" />
            </el-select>
            <div class="form-hint">
              vlm 会把选择题的 A/B/C/D 拆成各自独立的块，pipeline 会把它们挤成一行。
              实测两者耗时与页数消耗相同，所以默认 vlm。
            </div>
          </el-form-item>

          <el-form-item label="文档语言">
            <el-select v-model="form.mineru_language" style="width: 240px">
              <el-option
                v-for="lang in MINERU_LANGUAGES"
                :key="lang.value"
                :label="lang.label"
                :value="lang.value"
              />
            </el-select>
            <div class="form-hint">手写体试卷选 ch_server；纯英文卷选 en 更准</div>
          </el-form-item>

          <el-form-item label="公式识别">
            <el-switch v-model="form.mineru_enable_formula" />
            <div class="form-hint">理科文档保持开启；关掉会失去公式转 LaTeX 的能力</div>
          </el-form-item>

          <el-form-item label="表格识别">
            <el-switch v-model="form.mineru_enable_table" />
            <div class="form-hint">关掉后表格只能以图片形式保留</div>
          </el-form-item>

        <!-- 大模型参数：大模型识别与 MinerU 混合识别都要用 -->
        <el-divider content-position="left">
          <span class="divider-text">大模型参数（判题边界与逐题结构化）</span>
        </el-divider>

          <el-form-item label="API Key">
            <el-input
              v-model="form.ai_api_key"
              :type="showKey ? 'text' : 'password'"
              :placeholder="keyPlaceholder"
              clearable
            >
              <template #suffix>
                <el-icon @click="showKey = !showKey" style="cursor: pointer;">
                  <View v-if="showKey" /><Hide v-else />
                </el-icon>
              </template>
            </el-input>
            <!-- 与 MinerU Token 同一套：状态独立成行，不再藏在 placeholder 里 -->
            <div class="secret-state" :class="maskedKey ? 'is-saved' : 'is-empty'">
              <template v-if="maskedKey">已保存 {{ maskedKey }}</template>
              <template v-else>尚未配置</template>
            </div>
          </el-form-item>

          <el-form-item label="Base URL">
            <!-- 预设 + 自定义二合一：filterable allow-create 既能选预设也能手输
                 任意地址，不必再放一个"其他"单选项去切换两套输入框。 -->
            <el-select
              v-model="form.ai_base_url"
              filterable
              allow-create
              default-first-option
              placeholder="选择厂商预设，或直接粘贴自定义地址"
              style="width: 100%"
            >
              <el-option v-for="p in BASE_URL_PRESETS" :key="p.value" :label="p.label" :value="p.value" />
            </el-select>
          </el-form-item>

          <el-form-item label="模型">
            <el-input v-model="form.ai_model" placeholder="如 gpt-4o / qwen-plus / glm-4" />
          </el-form-item>

          <el-form-item label="Temperature">
            <el-slider v-model="form.ai_temperature" :min="0" :max="2" :step="0.1" show-input />
          </el-form-item>

          <el-form-item label="修正 Prompt">
            <el-input
              v-model="form.ai_review_prompt"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 10 }"
              placeholder="留空使用默认 Prompt。可自定义 AI 修正指令"
            />
            <div class="form-hint">AI 修正题目时使用的系统提示词，留空使用默认模板</div>
          </el-form-item>

          <el-divider content-position="left">
            <span class="divider-text">视觉模型（判题边界、逐题结构化与答案归一）</span>
          </el-divider>

          <el-form-item label="视觉模型">
            <el-input v-model="form.ai_vision_model" placeholder="qwen-vl-max" />
            <div class="form-hint">留空按 qwen-vl-max 处理</div>
          </el-form-item>

          <el-form-item label="视觉 Base URL">
            <el-select
              v-model="form.ai_vision_base_url"
              filterable
              allow-create
              default-first-option
              placeholder="留空回退上面的 Base URL"
              style="width: 100%"
            >
              <el-option v-for="p in BASE_URL_PRESETS" :key="p.value" :label="p.label" :value="p.value" />
            </el-select>
            <div class="form-hint">
              文本与视觉常属不同供应商，例如 gpt-4o 走 OpenAI、qwen-vl-max 走 DashScope compatible-mode
            </div>
          </el-form-item>

          <el-form-item label="视觉 API Key">
            <el-input
              v-model="form.ai_vision_api_key"
              :type="showVisionKey ? 'text' : 'password'"
              :placeholder="visionKeyPlaceholder"
              clearable
            >
              <template #suffix>
                <el-icon @click="showVisionKey = !showVisionKey" style="cursor: pointer;">
                  <View v-if="showVisionKey" /><Hide v-else />
                </el-icon>
              </template>
            </el-input>
            <div class="secret-state" :class="maskedVisionKey ? 'is-saved' : 'is-empty'">
              <template v-if="maskedVisionKey">已保存 {{ maskedVisionKey }}</template>
              <template v-else>尚未配置（将共用上面的文本 Key）</template>
            </div>
          </el-form-item>

        <!--
          测试按钮常驻。原来它们被包在"仅在启用 AI 的模式才显示"的判断里，
          把模式切成「本地识别」后整排消失，连改回来都点不了。
          另外原「当前为本地识别」提示里写"智能选题不可用"是错的：
          recommend.py 是纯确定性打分，不读任何 AI 配置，随模式一起删掉。
        -->
        <el-form-item>
          <el-button @click="testConnection('text')" :loading="testing">测试文本模型</el-button>
          <el-button @click="testConnection('vision')" :loading="testingVision">测试视觉模型</el-button>
          <el-button type="primary" @click="saveSettings" :loading="saving">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Export settings (placeholder for future) -->
    <el-card style="margin-top: 16px;">
      <template #header>
        <span>导出设置</span>
      </template>
      <el-form label-width="120px" style="max-width: 600px;">
        <el-form-item label="PDF 纸张">
          <el-select v-model="exportPaper">
            <el-option label="A4" value="A4" />
            <el-option label="Letter" value="Letter" />
          </el-select>
        </el-form-item>
        <el-form-item label="导出目录">
          <el-input :value="exportDir" disabled />
          <div class="form-hint">导出文件保存在此目录</div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 外观：明暗模式原来挂在侧栏底部，按"设置项住在设置页"收进来 -->
    <el-card style="margin-top: 16px;">
      <template #header>
        <span>外观</span>
      </template>
      <el-form label-width="120px" style="max-width: 600px;">
        <el-form-item label="暗色模式">
          <el-switch :model-value="isDark" @update:model-value="applyTheme" />
          <div class="form-hint">切换后立即生效，选择记在本机浏览器里</div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Test result -->
    <el-dialog v-model="showTestResult" :title="testResult.ok ? '连接成功' : '连接失败'" width="400px">
      <el-result :icon="testResult.ok ? 'success' : 'error'" :title="testResult.message">
        <p>[{{ testResult.kind === 'vision' ? '视觉模型' : '文本模型' }}] {{ testResult.model }}</p>
        <p v-if="testResult.latency_ms">响应时间: {{ testResult.latency_ms }}ms</p>
      </el-result>
      <template #footer>
        <el-button @click="showTestResult = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const form = reactive({
  // 没有 ai_mode：识别模式已在导入页的通道单选项里选过，本页不再重复表达。
  // 后端判据同步为「只看有无 Key / Base URL」，所以这里也不需要一个模式字段。
  ai_api_key: '',
  // Base URL / 模型名默认留空（与后端列默认一致）：预设值会让人误以为已能用了。
  ai_base_url: '',
  ai_model: '',
  ai_vision_model: 'qwen-vl-max',
  ai_vision_base_url: '',
  ai_vision_api_key: '',
  ai_temperature: 0.7,
  ai_review_prompt: '',
  // MinerU 识别通道的 Token。与 AI 无关的独立凭证，只输入不回显明文。
  mineru_api_token: '',
  // MinerU 解析参数。默认值即官方默认值，改坏了下一次识别立刻能看出来。
  mineru_model_version: 'vlm',
  mineru_language: 'ch',
  mineru_enable_formula: true,
  mineru_enable_table: true,
})

// 常见厂商的 OpenAI 兼容端点。列表刻意保持短：全列出来反而找不到自己那家，
// 不在名单里的用 allow-create 直接粘贴即可。
const BASE_URL_PRESETS = [
  { value: 'https://dashscope.aliyuncs.com/compatible-mode/v1', label: '阿里百炼 DashScope（qwen 系列）' },
  { value: 'https://open.bigmodel.cn/api/paas/v4', label: '智谱 GLM' },
  { value: 'https://api.moonshot.cn/v1', label: 'Moonshot Kimi' },
  { value: 'https://api.openai.com/v1', label: 'OpenAI' },
  { value: 'http://localhost:11434/v1', label: '本地 Ollama' },
]

// MinerU 支持的文档语言（官方文档「language 取值参考」的常用子集）
const MINERU_LANGUAGES = [
  { value: 'ch', label: '中英文（ch）' },
  { value: 'ch_server', label: '中英文 + 手写体（ch_server）' },
  { value: 'en', label: '纯英文（en）' },
  { value: 'japan', label: '日文（japan）' },
  { value: 'korean', label: '韩文（korean）' },
]

const maskedKey = ref(null)
const showKey = ref(false)
const maskedVisionKey = ref(null)
const showVisionKey = ref(false)
const maskedMineruToken = ref(null)
const showMineruToken = ref(false)
const testing = ref(false)
const testingVision = ref(false)
const saving = ref(false)
const showTestResult = ref(false)
// kind/model 记录本次测的是哪一侧，弹窗里要能区分文本模型与视觉模型。
const testResult = reactive({ ok: false, message: '', latency_ms: null, kind: 'text', model: '' })
const exportPaper = ref('A4')
const exportDir = ref('data/exports')

// 明暗模式：原来挂在侧栏底部，现在收进设置页。写 html[data-theme] + localStorage
// （与 main.js 启动时的读取配对），具体色值全在 styles/main.css 的变量层。
const isDark = ref(document.documentElement.dataset.theme === 'dark')
const applyTheme = (dark) => {
  isDark.value = dark
  const root = document.documentElement
  if (dark) root.dataset.theme = 'dark'
  else delete root.dataset.theme
  localStorage.setItem('theme', dark ? 'dark' : 'light')
}

// 「三档识别模式」的说明与选择建议已随模式单选项一并删除：通道在导入页选一次，
// 本页不再重复表达。各通道的实测对比（MinerU 插图 36→75 张、待复核 21→55、
// 矢量图零丢失等）保留在 utils/channels.js 的 CHANNEL_META.pick 与文件头注释里
// —— 那边才是"选通道时该看到"的位置，不要在本页再抄一份。

// placeholder 只说"该做什么"，不再兼做状态显示 —— 已保存的密钥由下方的
// .secret-state 明说（它才是不会被忽略的那一处）。两处都在说同一件事时，
// 用户反而两处都不信。
const keyPlaceholder = computed(() =>
  maskedKey.value ? '留空即保留已保存的 Key' : '粘贴 API Key',
)
const mineruTokenPlaceholder = computed(() =>
  maskedMineruToken.value ? '留空即保留已保存的 Token' : '粘贴 mineru.net 的 API Token',
)
const visionKeyPlaceholder = computed(() =>
  maskedVisionKey.value ? '留空即保留已保存的 Key' : '留空则共用上面的文本 Key',
)

// 卡片右上角：凭据是否配齐。
// 必须和后端判据同口径（get_vision_config / _get_ai_config 只看有无 Key 与
// Base URL），否则会出现"标签显示已配置、一保存却报错"这种两头对不上的情况。
const configStatusText = computed(() => {
  const ready = [maskedKey.value && '大模型', maskedMineruToken.value && 'MinerU'].filter(Boolean)
  if (ready.length === 2) return '大模型 + MinerU 已配置'
  if (ready.length === 1) return `${ready[0]} 已配置`
  return '未配置'
})
const configStatusType = computed(() => {
  const n = (maskedKey.value ? 1 : 0) + (maskedMineruToken.value ? 1 : 0)
  return n === 2 ? 'success' : n === 1 ? 'warning' : 'info'
})

// Load settings
const loadSettings = async () => {
  try {
    const res = await axios.get('/api/settings')
    const d = res.data
    // ai_mode 不再读写：模式已由导入页的通道选择代替，本页只管凭据与端点。
    form.ai_base_url = d.ai_base_url
    form.ai_model = d.ai_model
    form.ai_vision_model = d.ai_vision_model || 'qwen-vl-max'
    form.ai_vision_base_url = d.ai_vision_base_url || ''
    form.ai_temperature = d.ai_temperature
    form.ai_review_prompt = d.ai_review_prompt || ''
    maskedKey.value = d.ai_api_key_masked
    maskedVisionKey.value = d.ai_vision_api_key_masked
    maskedMineruToken.value = d.mineru_api_token_masked
    form.mineru_model_version = d.mineru_model_version || 'vlm'
    form.mineru_language = d.mineru_language || 'ch'
    form.mineru_enable_formula = d.mineru_enable_formula !== false
    form.mineru_enable_table = d.mineru_enable_table !== false
  } catch (e) { console.error(e) }
}

// Save settings
const saveSettings = async () => {
  saving.value = true
  try {
    const payload = {
      // 不带 ai_mode：留空即保留库里的原值（后端 SECRET/非密钥字段的既有语义）。
      // 显式传反而会把历史值改掉，而它现在已经不参与任何判断。
      ai_base_url: form.ai_base_url,
      ai_model: form.ai_model,
      // ai_vision_model 列非空，空值必须回落默认值而不是 null。
      ai_vision_model: form.ai_vision_model || 'qwen-vl-max',
      ai_vision_base_url: form.ai_vision_base_url || null,
      ai_temperature: form.ai_temperature,
      ai_review_prompt: form.ai_review_prompt || null,
      mineru_model_version: form.mineru_model_version,
      mineru_language: form.mineru_language,
      mineru_enable_formula: form.mineru_enable_formula,
      mineru_enable_table: form.mineru_enable_table,
    }
    // Only send a secret if the user typed something new — 留空表示后端保留原值，
    // 前端不持有明文，无法回传原值。
    //
    // 两边都先 trim：复制密钥时带上首尾空格是常事，而只粘到空白的输入会被后端
    // 当成"保留原值"（真去存反而会存进一个带空格的坏 Key）。trim 之后这种输入
    // 等同于留空，语义正确、也不会存进垃圾。
    const key = form.ai_api_key.trim()
    const visionKey = form.ai_vision_api_key.trim()
    const token = form.mineru_api_token.trim()
    if (key && key !== maskedKey.value) {
      payload.ai_api_key = key
    }
    if (visionKey && visionKey !== maskedVisionKey.value) {
      payload.ai_vision_api_key = visionKey
    }
    if (token && token !== maskedMineruToken.value) {
      payload.mineru_api_token = token
    }
    const res = await axios.put('/api/settings', payload)
    maskedKey.value = res.data.ai_api_key_masked
    maskedVisionKey.value = res.data.ai_vision_api_key_masked
    maskedMineruToken.value = res.data.mineru_api_token_masked
    form.ai_api_key = ''
    form.ai_vision_api_key = ''
    form.mineru_api_token = ''
    ElMessage.success('设置已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

// Test connection — 'text' 测文本模型，'vision' 测 api_extract 通道的视觉模型。
// 两个模型可以不同供应商，因此 base_url 也要各取各的。
const testConnection = async (kind = 'text') => {
  const isVision = kind === 'vision'
  const loadingFlag = isVision ? testingVision : testing
  const baseUrl = isVision ? form.ai_vision_base_url || form.ai_base_url : form.ai_base_url
  const model = isVision ? form.ai_vision_model || 'qwen-vl-max' : form.ai_model

  loadingFlag.value = true
  testResult.kind = kind
  testResult.model = model
  try {
    const res = await axios.post('/api/settings/test', {
      base_url: baseUrl,
      // 留空时后端按 kind 回退对应的已保存 Key（视觉侧先视觉 Key 再文本 Key）
      api_key: (isVision ? form.ai_vision_api_key : form.ai_api_key) || '',
      model,
      kind,
    })
    Object.assign(testResult, res.data)
    showTestResult.value = true
  } catch (e) {
    testResult.ok = false
    testResult.message = '请求失败: ' + (e.response?.data?.detail || e.message)
    testResult.latency_ms = null
    showTestResult.value = true
  } finally {
    loadingFlag.value = false
  }
}

onMounted(() => { loadSettings() })
</script>

<style scoped>


.card-header { display: flex; justify-content: space-between; align-items: center; }

/* 表单说明一律独占一行。Element Plus 的 .el-form-item__content 是 flex-wrap 容器，
   窄控件（开关、下拉）后面的说明会跟控件挤在同一行，而宽输入框后面的说明落到下一行 ——
   同一页里两种排法，读起来像两套表单。flex-basis: 100% 把它强制换行。 */
.form-hint {
  flex-basis: 100%;
  font-size: 12px;
  color: var(--color-ink-muted);
  margin-top: 4px;
}

/*
 * 密钥字段的落库状态。保存后输入框会被清空（密码不回显明文），所以"到底存上
 * 没有"必须有独立一行、带颜色地说清楚。以前这句话挤在 placeholder 里，灰字、
 * 和"请输入"长得一样，实测用户填完 Token 点保存、看到空框就以为没保存上。
 * 绿点用 --color-on-tint-emerald（明暗两套都有对应值）。
 */
.secret-state {
  flex-basis: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
}

.secret-state::before {
  content: '';
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
}

.secret-state.is-saved {
  color: var(--color-on-tint-emerald);
  font-weight: 500;
}

.secret-state.is-empty {
  color: var(--color-ink-muted);
}

.divider-text { font-size: 12px; color: var(--color-ink-muted); }
</style>
