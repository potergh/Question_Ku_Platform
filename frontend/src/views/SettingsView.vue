<template>
  <div class="settings-view">
    <div class="settings-header">
      <h2>设置</h2>
      <p class="subtitle">配置 AI 模型、导出选项</p>
    </div>

    <el-card>
      <template #header>
        <div class="card-header">
          <span>AI 模型配置</span>
          <el-tag :type="modeTagType" size="small">{{ modeText }}</el-tag>
        </div>
      </template>

      <el-form label-width="120px" style="max-width: 600px;">
        <!-- AI Mode -->
        <el-form-item label="AI 模式">
          <el-radio-group v-model="form.ai_mode">
            <el-radio value="off">关闭</el-radio>
            <el-radio value="local">本地模型</el-radio>
            <el-radio value="remote">远程 API</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- Remote API settings -->
        <template v-if="form.ai_mode === 'remote'">
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
            <div class="form-hint" v-if="maskedKey">
              当前: {{ maskedKey }}（留空保留原 Key）
            </div>
          </el-form-item>

          <el-form-item label="Base URL">
            <el-input v-model="form.ai_base_url" placeholder="https://api.openai.com/v1" />
          </el-form-item>

          <el-form-item label="模型">
            <el-input v-model="form.ai_model" placeholder="gpt-4o" />
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

          <el-form-item>
            <el-button @click="testConnection" :loading="testing">测试连接</el-button>
            <el-button type="primary" @click="saveSettings" :loading="saving">保存</el-button>
          </el-form-item>
        </template>

        <!-- Local mode info -->
        <template v-if="form.ai_mode === 'local'">
          <el-form-item>
            <el-alert type="info" :closable="false" title="本地模型模式">
              本地模型模式需要配置 Ollama 或类似服务。此功能将在后续版本实现。
            </el-alert>
          </el-form-item>
        </template>

        <!-- Off mode info -->
        <template v-if="form.ai_mode === 'off'">
          <el-form-item>
            <el-alert type="info" :closable="false" title="AI 功能已关闭">
              开启 AI 模式后，可使用智能选题、自动生成备注等功能。
            </el-alert>
          </el-form-item>
        </template>
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

    <!-- Test result -->
    <el-dialog v-model="showTestResult" :title="testResult.ok ? '连接成功' : '连接失败'" width="400px">
      <el-result :icon="testResult.ok ? 'success' : 'error'" :title="testResult.message">
        <template v-if="testResult.latency_ms">
          <p>响应时间: {{ testResult.latency_ms }}ms</p>
        </template>
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
  ai_mode: 'off',
  ai_api_key: '',
  ai_base_url: 'https://api.openai.com/v1',
  ai_model: 'gpt-4o',
  ai_temperature: 0.7,
  ai_review_prompt: '',
})

const maskedKey = ref(null)
const showKey = ref(false)
const testing = ref(false)
const saving = ref(false)
const showTestResult = ref(false)
const testResult = reactive({ ok: false, message: '', latency_ms: null })
const exportPaper = ref('A4')
const exportDir = ref('data/exports')

const keyPlaceholder = computed(() => {
  return maskedKey.value ? `当前: ${maskedKey.value}（留空保留）` : '输入 API Key'
})

const modeText = computed(() => ({
  off: 'AI 关闭', local: '本地模型', remote: '远程 API'
})[form.ai_mode])

const modeTagType = computed(() => ({
  off: 'info', local: 'warning', remote: 'success'
})[form.ai_mode])

// Load settings
const loadSettings = async () => {
  try {
    const res = await axios.get('/api/settings')
    const d = res.data
    form.ai_mode = d.ai_mode
    form.ai_base_url = d.ai_base_url
    form.ai_model = d.ai_model
    form.ai_temperature = d.ai_temperature
    form.ai_review_prompt = d.ai_review_prompt || ''
    maskedKey.value = d.ai_api_key_masked
  } catch (e) { console.error(e) }
}

// Save settings
const saveSettings = async () => {
  saving.value = true
  try {
    const payload = {
      ai_mode: form.ai_mode,
      ai_base_url: form.ai_base_url,
      ai_model: form.ai_model,
      ai_temperature: form.ai_temperature,
      ai_review_prompt: form.ai_review_prompt || null,
    }
    // Only send key if user typed something new
    if (form.ai_api_key && form.ai_api_key !== maskedKey.value) {
      payload.ai_api_key = form.ai_api_key
    }
    const res = await axios.put('/api/settings', payload)
    maskedKey.value = res.data.ai_api_key_masked
    form.ai_api_key = ''
    ElMessage.success('设置已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

// Test connection
const testConnection = async () => {
  testing.value = true
  try {
    const res = await axios.post('/api/settings/test', {
      base_url: form.ai_base_url,
      api_key: form.ai_api_key || 'test',
      model: form.ai_model,
    })
    Object.assign(testResult, res.data)
    showTestResult.value = true
  } catch (e) {
    testResult.ok = false
    testResult.message = '请求失败: ' + (e.response?.data?.detail || e.message)
    testResult.latency_ms = null
    showTestResult.value = true
  } finally {
    testing.value = false
  }
}

onMounted(() => { loadSettings() })
</script>

<style scoped>
.settings-view { max-width: 800px; margin: 0 auto; }
.settings-header { margin-bottom: 16px; }
.subtitle { color: #909399; margin-top: 4px; }

.card-header { display: flex; justify-content: space-between; align-items: center; }

.form-hint { font-size: 12px; color: #909399; margin-top: 4px; }
</style>
