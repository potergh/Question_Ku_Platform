<template>
  <div class="extract-review">
    <!-- 顶部工具条 -->
    <div class="topbar">
      <div class="topbar-left">
        <el-button text size="small" @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          <span>返回</span>
        </el-button>
        <span class="doc-name">{{ doc?.document_name || doc?.filename || '识别暂存区' }}</span>
        <template v-if="doc">
          <el-tag size="small" type="success" effect="plain">{{ docKindText }}</el-tag>
          <el-tag size="small" type="info" effect="plain">{{ channelText }}</el-tag>
          <el-tag size="small" :type="statusType(doc.ocr_status)">{{ statusText(doc.ocr_status) }}</el-tag>
        </template>
      </div>
      <div class="topbar-right">
        <span v-if="doc && loaded" class="counter">
          共 {{ keptItems.length }} 题 · 待复核 {{ reviewCount }} · 已剔除 {{ excludedItems.length }}
        </span>
        <el-button size="small" title="刷新暂存结果" @click="load">
          <el-icon><Refresh /></el-icon>
        </el-button>
        <el-button size="small" :disabled="!loaded" :loading="rerunning" @click="rerun">重跑识别</el-button>
        <el-button size="small" type="danger" plain :disabled="!loaded" :loading="discarding" @click="discard">
          丢弃暂存
        </el-button>
        <el-button size="small" type="primary" :disabled="!canConfirm" :loading="confirming" @click="confirm()">
          {{ doc?.confirmed ? '重新入库' : '确认入库' }}
        </el-button>
      </div>
    </div>

    <el-empty v-if="!loading && !doc" description="暂存结果不存在或识别尚未完成">
      <el-button size="small" @click="load">刷新</el-button>
      <el-button size="small" type="primary" @click="goBack">返回文档列表</el-button>
    </el-empty>

    <template v-else-if="doc">
      <!-- 主体：左侧题目列表 / 右侧复核详情 -->
      <!-- 识别质量摘要 / 管线诊断 / 逐题黄色警告已按产品要求移除：
           这些是排查识别管线用的诊断信息，复核人员只需要看题、改题、确认。 -->

      <div class="main">
        <div class="list-pane">
          <div class="list-head">
            <!-- 批量入库：点按钮进入勾选模式，勾完出现「确认入库」逐题确认。
                 原「只看待复核」过滤器已删——待复核状态直接看卡片上的黄标。 -->
            <el-button size="small" :type="batchMode ? 'primary' : 'default'" @click="toggleBatchMode">
              批量入库
            </el-button>
            <el-button
              v-if="batchMode && selectedQids.size"
              size="small"
              type="primary"
              :loading="batchConfirming"
              @click="confirmSelected"
            >
              确认入库（{{ selectedQids.size }}）
            </el-button>
            <el-button v-if="batchMode" text size="small" @click="toggleBatchMode">取消</el-button>
          </div>
          <div
            v-for="item in visibleItems"
            :key="item.qid"
            class="q-card"
            :class="{ active: item.qid === activeQid, failed: !!item.error }"
            @click="batchMode ? toggleSelectQid(item.qid) : select(item.qid)"
          >
            <el-checkbox
              v-if="batchMode"
              :model-value="selectedQids.has(item.qid)"
              @click.stop
              @change="toggleSelectQid(item.qid)"
              class="q-check"
            />
            <div class="q-body">
            <div class="q-head">
              <span class="q-label">{{ itemTitle(item) }}</span>
              <span class="muted">{{ typeText(item.question_type) }}</span>
            </div>
            <div class="q-flags">
              <el-tag v-if="item.answer_conflict" size="small" type="danger" effect="dark">答案冲突</el-tag>
              <el-tag v-else-if="item.answer_origin" size="small" type="success" effect="plain">
                {{ originText(item.answer_origin) }}
              </el-tag>
              <el-tag v-if="!item.answer" size="small" type="info" effect="plain">无答案</el-tag>
              <el-tag v-if="item.has_formula" size="small" effect="plain">公式</el-tag>
              <el-tag v-if="item.is_cross_page" size="small" effect="plain">跨页</el-tag>
              <el-tag v-if="item.needs_review" size="small" type="warning" effect="plain">待复核</el-tag>
              <el-tag v-if="(item.changed_fields || []).length" size="small" type="success" effect="plain">
                已改 {{ item.changed_fields.length }}
              </el-tag>
              <el-tag v-if="(item.audit_flags || []).length" size="small" type="danger" effect="plain">
                审计 {{ item.audit_flags.length }}
              </el-tag>
              <el-tag v-if="(item.warnings || []).length" size="small" type="warning" effect="plain">
                警告 {{ item.warnings.length }}
              </el-tag>
              <el-tag v-if="item.error" size="small" type="danger" effect="dark">识别失败</el-tag>
            </div>
            <div class="q-preview" v-html="renderPreview(item.stem_md || item.raw_text, 56)"></div>
            </div>
          </div>

          <el-empty
            v-if="!visibleItems.length"
            description="没有可入库的题目（全部被剔除或识别为空）"
            :image-size="70"
          />

          <el-collapse v-if="excludedItems.length" class="excluded-box">
            <el-collapse-item :title="`已剔除 ${excludedItems.length} 题（不入库，可恢复）`">
              <div v-for="item in excludedItems" :key="item.qid" class="q-card excluded" @click="select(item.qid)">
                <div class="q-head">
                  <span class="q-label">{{ itemTitle(item) }}</span>
                  <el-button text size="small" type="primary" @click.stop="restore(item)">恢复</el-button>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div v-if="active" class="detail-pane">
          <div class="detail-head">
            <div class="detail-title">
              <span class="detail-name">{{ itemTitle(active) }}</span>
            </div>
            <div class="detail-actions">
              <!-- 编辑/预览二选一：默认预览（题卡原图），点「编辑」才出现表单 -->
              <el-radio-group v-model="detailMode" size="small">
                <el-radio-button value="preview">预览</el-radio-button>
                <el-radio-button value="edit">编辑</el-radio-button>
              </el-radio-group>
              <el-switch
                v-model="edit.needs_review"
                size="small"
                active-text="待复核"
                inactive-text="确认审核"
                :loading="togglingReview"
                @change="onToggleReview"
              />
              <el-button v-if="active.excluded" size="small" type="primary" plain @click="restore(active)">恢复本题</el-button>
              <el-button size="small" type="primary" :loading="saving" @click="save">
                {{ dirty ? '保存并入库 *' : '保存并入库' }}
              </el-button>
            </div>
          </div>

          <el-alert v-if="active.error" type="error" :closable="false" show-icon class="item-alert" :title="active.error" />
          <el-alert
            v-if="active.answer_conflict"
            type="error"
            :closable="false"
            show-icon
            class="item-alert"
            :title="`答案冲突：多个来源给出不同答案，已按优先级选用「${originText(active.answer_origin)}」`"
          />
          <!-- 逐题的审计标记/识别警告（黄色警示）已按产品要求移除 -->

          <!--
            预览态（默认）：渲染后的整题内容直接铺在右栏 —— 题干、选项、答案、
            解析全部经 KaTeX/图片渲染，第一眼就是最终样子。
          -->
          <div v-show="detailMode === 'preview'" class="col-preview">
            <div class="rich" v-html="renderFullContent(edit.stem_md)"></div>
            <template v-if="!isPassageType(edit.question_type)">
              <div v-for="(opt, i) in edit.options" :key="i" class="rich-opt" v-html="optionHtml(opt)"></div>
            </template>
            <div v-else class="rich-opt muted">（{{ typeText(edit.question_type) }}：一篇材料挂多个小题，小题选项待结构化，暂不展示，答案见下）</div>
            <div v-if="edit.answer" class="rich-opt">
              答案：<span v-html="renderFullContent(edit.answer)"></span>
            </div>
            <div v-if="edit.explanation" class="rich-opt">
              解析：<span v-html="renderFullContent(edit.explanation)"></span>
            </div>
          </div>

          <!-- 编辑态：题卡原图 + 编辑表单 -->
          <div v-show="detailMode === 'edit'" class="detail-body">
            <div class="col-card">
              <el-image
                v-if="active.card_image_url"
                :src="active.card_image_url"
                :preview-src-list="previewList"
                :preview-teleported="true"
                fit="contain"
                class="card-image"
              />
              <div v-else class="muted pad">本题没有题卡原图</div>
              <div v-if="(active.figure_urls || []).length" class="figures">
                <span class="muted fig-label">插图 {{ active.figure_urls.length }} 张</span>
                <el-image
                  v-for="url in active.figure_urls"
                  :key="url"
                  :src="url"
                  :preview-src-list="active.figure_urls"
                  :preview-teleported="true"
                  fit="contain"
                  class="figure-thumb"
                />
              </div>
            </div>

            <div v-show="detailMode === 'edit'" class="col-edit">
              <div class="field-row">
                <el-input v-model="edit.label" size="small" placeholder="题号" style="width: 96px" />
                <el-select v-model="edit.question_type" size="small" placeholder="题型" style="width: 132px">
                  <el-option v-for="(name, key) in QUESTION_TYPE_MAP" :key="key" :label="name" :value="key" />
                </el-select>
                <el-input-number v-model="edit.score" size="small" :min="0" :precision="1" controls-position="right" style="width: 108px" />
                <el-input v-model="edit.section" size="small" placeholder="所属板块（可空）" style="width: 170px" />
              </div>

              <div class="field-label">题干（Markdown / LaTeX）</div>
              <el-input v-model="edit.stem_md" type="textarea" :rows="7" />

              <template v-if="!isPassageType(edit.question_type)">
                <div class="field-label">选项</div>
                <div v-for="(opt, i) in edit.options" :key="i" class="opt-row">
                  <el-input v-model="opt.label" size="small" style="width: 58px" />
                  <el-input v-model="opt.content" size="small" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" />
                  <el-button text type="danger" size="small" @click="edit.options.splice(i, 1)">
                    <el-icon><Close /></el-icon>
                  </el-button>
                </div>
                <el-button text size="small" type="primary" @click="addOption">+ 添加选项</el-button>
              </template>
              <div v-else class="field-label muted">选项（{{ typeText(edit.question_type) }}为篇章题，小题选项待结构化，暂不展示）</div>

              <div class="field-label">答案（来源：{{ originText(active.answer_origin) }}）</div>
              <el-input v-model="edit.answer" type="textarea" :rows="3" />
              <div v-if="(active.answer_blocks || []).length" class="answer-blocks">
                <div v-for="(block, i) in active.answer_blocks" :key="i" class="answer-block">
                  <span class="block-label">{{ block.label || '答案' }}</span>
                  <span>{{ block.text }}</span>
                  <div v-if="(block.figure_urls || []).length" class="figures block-figures">
                    <el-image
                      v-for="url in block.figure_urls"
                      :key="url"
                      :src="url"
                      :preview-src-list="block.figure_urls"
                      :preview-teleported="true"
                      fit="contain"
                      class="figure-thumb"
                    />
                  </div>
                </div>
              </div>
              <div v-if="(active.answer_figure_urls || []).length" class="figures">
                <span class="muted fig-label">
                  答案插图 {{ active.answer_figure_urls.length }} 张（来自文末答案区；卷面只写「如上图所示」时看这里）
                </span>
                <el-image
                  v-for="url in active.answer_figure_urls"
                  :key="url"
                  :src="url"
                  :preview-src-list="active.answer_figure_urls"
                  :preview-teleported="true"
                  fit="contain"
                  class="figure-thumb"
                />
              </div>
              <div v-if="(active.answer_figure_refs || []).length" class="figures">
                <span class="muted fig-label">
                  答案引用题干图 {{ active.answer_figure_refs.length }} 张（答案区只是把题干配图重印了一遍，不重复裁图）
                </span>
                <div
                  v-for="ref in active.answer_figure_refs"
                  :key="ref.stem_figure"
                  class="ref-item"
                >
                  <el-image
                    :src="ref.stem_figure_url"
                    :preview-src-list="[ref.stem_figure_url]"
                    :preview-teleported="true"
                    fit="contain"
                    class="figure-thumb"
                  />
                  <span class="muted">题干图 {{ ref.stem_index }}</span>
                </div>
              </div>
              <div v-if="active.answer_note" class="muted note-line">{{ active.answer_note }}</div>

              <div class="field-label">解析</div>
              <el-input v-model="edit.explanation" type="textarea" :rows="4" />

              <el-collapse v-if="(active.answer_sources || []).length" class="sub-collapse">
                <el-collapse-item
                  :title="`答案来源对照（${originCount(active.answer_sources)} 路来源 · ${active.answer_sources.length} 条证据）`"
                >
                  <el-table :data="active.answer_sources" size="small" border>
                    <el-table-column label="来源" width="130">
                      <template #default="{ row }">{{ originText(row.origin) }}</template>
                    </el-table-column>
                    <el-table-column prop="label" label="题号" width="80" />
                    <el-table-column prop="answer" label="答案" width="150" show-overflow-tooltip />
                    <el-table-column prop="explanation" label="解析" show-overflow-tooltip />
                  </el-table>
                </el-collapse-item>
              </el-collapse>

              <!-- 渲染预览已上移到右栏「预览」态（默认呈现），编辑态只留表单 -->
            </div>
          </div>
        </div>

        <el-empty v-else class="detail-pane" description="在左侧选择一道题开始复核" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { CHANNEL_REVIEW_LABELS } from '../utils/channels'
import { QUESTION_TYPE_MAP, isPassageType } from '../utils/questionTypes'
import { renderFullContent, renderOptionContent, renderPreview } from '../utils/render'

// 与后端 audit.COVERAGE_FLOOR 保持一致，仅用于横幅文案展示。
const COVERAGE_FLOOR = 0.95

const ORIGIN_TEXT = {
  inline: '题内',
  inline_llm: '题内(模型)',
  answer_key_llm: '文末答案区',
  companion: '答案文档',
  answer_key_regex: '文末答案区(规则)',
}
const OPTION_LABELS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']

const route = useRoute()
const router = useRouter()
const sourceId = route.params.sourceId

const loading = ref(true)
const doc = ref(null)
// 右栏「预览 / 编辑」二选一：默认预览（渲染后的整题内容），点编辑才出现表单。
const detailMode = ref('preview')
// 批量入库：勾选模式 + 已勾选的题（qid 集合）。
const batchMode = ref(false)
const selectedQids = reactive(new Set())
const batchConfirming = ref(false)
// 待复核开关即时落库的进行中标记（与「保存本题」的 saving 分开，避免按钮一起转圈）。
const togglingReview = ref(false)
const activeQid = ref(null)
const saving = ref(false)
const confirming = ref(false)
const rerunning = ref(false)
const discarding = ref(false)

const edit = reactive({
  label: '',
  section: null,
  question_type: null,
  score: null,
  stem_md: '',
  options: [],
  answer: null,
  explanation: null,
  needs_review: true,
})

// doc 为 null 可能是「还没识别完」，此时重跑/丢弃没有意义。
const loaded = computed(() => !!doc.value)
const items = computed(() => doc.value?.items || [])
const keptItems = computed(() => items.value.filter((item) => !item.excluded))
const excludedItems = computed(() => items.value.filter((item) => item.excluded))
const active = computed(() => items.value.find((item) => item.qid === activeQid.value) || null)
const reviewCount = computed(() => keptItems.value.filter((item) => item.needs_review).length)
// 「只看待复核」过滤器已删（批量入库取代）：列表恒显全部未剔除的题，
// 待复核状态看卡片上的黄标。当前选中的题若被剔除，右侧详情仍保留。
const visibleItems = computed(() => keptItems.value)

// 批量入库：进入/退出勾选模式；确认时逐题把 needs_review 置 false
// （即「确认审核」），与右栏开关走同一个接口，成功后黄标即时消失。
const toggleBatchMode = () => {
  batchMode.value = !batchMode.value
  selectedQids.clear()
  // 进入勾选模式即默认全选当前列表：批量入库的主场景就是"这批都核对完了"
  if (batchMode.value) visibleItems.value.forEach((item) => selectedQids.add(item.qid))
}

const toggleSelectQid = (qid) => {
  if (selectedQids.has(qid)) selectedQids.delete(qid)
  else selectedQids.add(qid)
}

async function confirmSelected() {
  const qids = [...selectedQids]
  if (!qids.length) return
  batchConfirming.value = true
  let ok = 0
  try {
    for (const qid of qids) {
      const item = items.value.find((it) => it.qid === qid)
      if (!item || item.excluded) continue
      try {
        await axios.put(`/api/sources/${sourceId}/extract/items/${qid}`, {
          needs_review: false,
        })
        item.needs_review = false
        ok += 1
      } catch {
        /* 单题失败不中断整批，最后统一提示 */
      }
    }
    if (ok === qids.length) ElMessage.success(`已确认 ${ok} 题（不再标记待复核）`)
    else ElMessage.warning(`已确认 ${ok} 题，${qids.length - ok} 题失败，请重试`)
    selectedQids.clear()
    batchMode.value = false
  } finally {
    batchConfirming.value = false
  }
}
const canConfirm = computed(() => !!doc.value && keptItems.value.length > 0)

const audit = computed(() => doc.value?.audit || {})
const qa = computed(() => doc.value?.qa || {})
const answerReport = computed(() => doc.value?.answer_report || {})
// 大模型用量：老暂存文件没有 usage（空字典），如实显示「未记录」而不是 0。
const usageText = computed(() => {
  const usage = doc.value?.usage || {}
  if (!usage.calls) return '未记录'
  const tokens = usage.total_tokens || 0
  return `${usage.calls} 次调用 · ${tokens.toLocaleString()} tokens`
})
// 总用时：摘要默认收起，但它是最该一眼看到的信息，所以提到收起行上（明细在展开区）
const totalTimeText = computed(() => {
  const total = Object.values(doc.value?.timings || {}).reduce((a, b) => a + b, 0)
  if (!total) return '未记录'
  const minutes = Math.floor(total / 60)
  const seconds = Math.round(total % 60)
  return minutes ? `${minutes} 分 ${seconds} 秒` : `${seconds} 秒`
})

// 阶段耗时：按耗时降序取前三，一眼看出瓶颈在哪一段（老暂存文件没有此键）
const timingsText = computed(() => {
  const rows = Object.entries(doc.value?.timings || {}).sort((a, b) => b[1] - a[1])
  if (!rows.length) return '未记录'
  return rows.slice(0, 3).map(([name, sec]) => `${name} ${sec}s`).join(' · ')
})
const previewList = computed(() => {
  const item = active.value
  if (!item?.card_image_url) return []
  return [item.card_image_url, ...(item.figure_urls || [])]
})

const docKindText = computed(
  () => ({ paper: '试卷', handout: '讲义' }[doc.value?.doc_kind] || doc.value?.doc_kind || ''),
)
// 通道名从共享表取：以前是三元写死，加通道后 MinerU 的产物会被显示成「本地 OCR」，
// 而这份暂存 JSON 明明是 MinerU 切出来的。
const channelText = computed(
  () => CHANNEL_REVIEW_LABELS[doc.value?.channel] || doc.value?.channel || '',
)
const orphanText = computed(() => {
  const pages = audit.value.orphan_pages || []
  return pages.length ? pages.join('、') : '无'
})
const regionSummary = computed(() => {
  const names = {
    cover: '卷首',
    section_header: '章节标题',
    instruction: '说明',
    answer_key: '答案区',
    other: '其他',
  }
  const counter = {}
  for (const region of doc.value?.non_question_regions || []) {
    const name = names[region.kind] || region.kind || '其他'
    counter[name] = (counter[name] || 0) + 1
  }
  return Object.entries(counter).map(([name, count]) => `${name} ${count}`).join('，')
})

const itemTitle = (item) => item.label || `第 ${item.question_number} 题`
const originText = (origin) => (origin ? ORIGIN_TEXT[origin] || origin : '无')
// 「几路来源」必须按 origin 去重后再数：同一份答案区被 LLM 拆一遍、被正则拆一遍，
// 那是 2 条证据、1 路来源，写成「三源对照（2 条）」会让人误以为有两路独立来源交叉验证。
const originCount = (sources) => new Set((sources || []).map((row) => row.origin)).size
const typeText = (type) => QUESTION_TYPE_MAP[type] || type || '未知题型'
const pct = (value) =>
  value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
const optionHtml = (opt) => `${opt.label || ''}. ${renderOptionContent(opt.content)}`
const statusType = (status) =>
  ({ pending: 'warning', processing: 'warning', staging: 'warning', done: 'success', error: 'danger' }[status] || 'info')
const statusText = (status) =>
  ({ pending: '等待中', processing: '识别中', staging: '待确认', done: '已入库', error: '失败' }[status] || status || '')

// 未保存的改动：切题前必须让用户知情，人工校对成本高。
const dirty = computed(() => {
  const item = active.value
  if (!item) return false
  const sameOptions =
    JSON.stringify(edit.options) ===
    JSON.stringify((item.options || []).map((o) => ({ label: o.label || '', content: o.content || '' })))
  return (
    (edit.label || '') !== (item.label || '') ||
    (edit.section ?? null) !== (item.section ?? null) ||
    (edit.question_type ?? null) !== (item.question_type ?? null) ||
    (edit.score ?? null) !== (item.score ?? null) ||
    (edit.stem_md || '') !== (item.stem_md || '') ||
    !sameOptions ||
    (edit.answer ?? null) !== (item.answer ?? null) ||
    (edit.explanation ?? null) !== (item.explanation ?? null) ||
    !!edit.needs_review !== !!item.needs_review
  )
})

function syncEdit() {
  const item = active.value
  if (!item) return
  edit.label = item.label || ''
  edit.section = item.section ?? null
  edit.question_type = item.question_type ?? null
  edit.score = item.score ?? null
  edit.stem_md = item.stem_md || ''
  edit.options = (item.options || []).map((o) => ({ label: o.label || '', content: o.content || '' }))
  edit.answer = item.answer ?? null
  edit.explanation = item.explanation ?? null
  edit.needs_review = !!item.needs_review
}

// active 指向的对象被替换（保存 / 剔除 / 恢复）或切换后重新灌入编辑器。
watch(active, syncEdit)

async function select(qid) {
  if (qid === activeQid.value) return
  if (dirty.value) {
    try {
      await ElMessageBox.confirm('当前题目有未保存的修改，切换后会被丢弃。', '未保存的修改', {
        confirmButtonText: '丢弃并切换',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
  }
  activeQid.value = qid
}

function replaceItem(next) {
  const list = doc.value?.items
  if (!list) return
  const index = list.findIndex((row) => row.qid === next.qid)
  if (index >= 0) list[index] = next
}

// 后端只在 staging 状态回写计数，前端本地同步一份保证 UI 不滞后。
function syncCounts() {
  if (!doc.value) return
  doc.value.question_count = keptItems.value.length
  doc.value.review_count = reviewCount.value
}

async function load() {
  loading.value = true
  try {
    const res = await axios.get(`/api/sources/${sourceId}/extract`)
    doc.value = res.data
    const stillThere = res.data.items.some((item) => item.qid === activeQid.value)
    if (!stillThere) {
      activeQid.value = keptItems.value[0]?.qid ?? res.data.items[0]?.qid ?? null
    }
    syncEdit()
  } catch (e) {
    doc.value = null
    ElMessage.error(e.response?.data?.detail || '暂存结果加载失败')
  } finally {
    loading.value = false
  }
}

function addOption() {
  const used = edit.options.map((o) => o.label)
  const label = OPTION_LABELS.find((l) => !used.includes(l)) || String(edit.options.length + 1)
  edit.options.push({ label, content: '' })
}

async function save() {
  const item = active.value
  if (!item) return
  saving.value = true
  try {
    const res = await axios.put(`/api/sources/${sourceId}/extract/items/${item.qid}`, {
      label: edit.label,
      section: edit.section,
      question_type: edit.question_type,
      score: edit.score,
      stem_md: edit.stem_md,
      options: edit.options,
      answer: edit.answer,
      explanation: edit.explanation,
      needs_review: edit.needs_review,
    })
    replaceItem(res.data.item)
    syncCounts()
    const changed = res.data.changed || []
    ElMessage.success(changed.length ? `已保存，改动字段：${changed.join('、')}` : '已保存（无字段变化）')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

// 「待复核」开关即时生效：只提交 needs_review 一个字段，表单里其他未保存的修改
// 保持不动。刻意不调用 replaceItem —— 那会替换 active 对象、触发
// watch(active) → syncEdit()，把用户正在编辑却还没保存的内容冲掉。
async function onToggleReview(value) {
  const item = active.value
  if (!item) return
  togglingReview.value = true
  try {
    const res = await axios.put(`/api/sources/${sourceId}/extract/items/${item.qid}`, {
      needs_review: value,
    })
    // 就地改字段（不换对象）：左侧卡片的「待复核」标签随之出现/消失。
    item.needs_review = res.data.item?.needs_review ?? value
    syncCounts()
  } catch (e) {
    edit.needs_review = !value
    ElMessage.error(e.response?.data?.detail || '保存待复核标记失败')
  } finally {
    togglingReview.value = false
  }
}

// 剔除 / 恢复：显式带上 needs_review，避免后端把「未复核」静默置 false。
async function patchFlags(item, patch) {
  try {
    const res = await axios.put(`/api/sources/${sourceId}/extract/items/${item.qid}`, {
      needs_review: item.needs_review,
      ...patch,
    })
    replaceItem(res.data.item)
    syncCounts()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function exclude(item) {
  try {
    await ElMessageBox.confirm(
      `「${itemTitle(item)}」将被剔除、不入库，可在列表底部恢复。`,
      '剔除本题',
      { confirmButtonText: '剔除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await patchFlags(item, { excluded: true })
}

async function restore(item) {
  await patchFlags(item, { excluded: false })
}

async function confirm(force = false) {
  confirming.value = true
  try {
    const res = await axios.post(`/api/sources/${sourceId}/extract/confirm`, null, {
      params: { force },
    })
    doc.value.confirmed = true
    doc.value.ocr_status = 'done'
    doc.value.question_count = res.data.question_count
    doc.value.review_count = res.data.review_count
    ElMessage.success(`已入库 ${res.data.question_count} 题${res.data.forced ? '（强制）' : ''}`)
  } catch (e) {
    const status = e.response?.status
    const detail = e.response?.data?.detail
    if (status === 409 && detail && typeof detail === 'object') {
      const blockedAudit = detail.audit || {}
      const pages = (blockedAudit.orphan_pages || []).join('、') || '无'
      try {
        await ElMessageBox.confirm(
          `${detail.message}。行覆盖率 ${pct(blockedAudit.coverage_ratio)}，丢失 ${blockedAudit.lost_chars ?? 0} 字符，孤儿页 ${pages}。强制入库会把这些内容永久排除在题库之外。`,
          '强制入库？',
          { confirmButtonText: '仍然入库', cancelButtonText: '取消', type: 'error' },
        )
      } catch {
        return
      }
      return confirm(true)
    }
    ElMessage.error(typeof detail === 'string' ? detail : '确认入库失败')
  } finally {
    confirming.value = false
  }
}

async function rerun() {
  try {
    await ElMessageBox.confirm('将丢弃当前暂存结果并重新识别，已人工修改的内容会一并丢失。', '重跑识别', {
      confirmButtonText: '重跑',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  rerunning.value = true
  try {
    await axios.post(`/api/sources/${sourceId}/extract/rerun`)
    ElMessage.success('已提交重跑，识别完成后点刷新查看')
    doc.value = null
    activeQid.value = null
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '重跑失败')
  } finally {
    rerunning.value = false
  }
}

async function discard() {
  const already = doc.value?.confirmed
  try {
    await ElMessageBox.confirm(
      already
        ? '暂存文件将被删除，题库里已入库的题目不受影响。'
        : '暂存结果将被丢弃，文档回到「等待中」，可以重新发起识别。',
      '丢弃暂存',
      { confirmButtonText: '丢弃', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  discarding.value = true
  try {
    await axios.delete(`/api/sources/${sourceId}/extract`)
    ElMessage.success('已丢弃暂存结果')
    router.push('/upload')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '丢弃失败')
  } finally {
    discarding.value = false
  }
}

const goBack = () => router.push('/upload')

onMounted(load)
</script>

<style scoped>
.extract-review {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  /* 与其他页同一套版心节奏：上下更松、左右更紧 */
  padding: 24px 32px 28px;
  box-sizing: border-box;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 16px;
  background: var(--glass-bg);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-card);
  box-shadow:
    inset 0 1px 0 var(--glass-highlight),
    var(--shadow-sm);
}

.topbar-left,
.topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.topbar-right .counter {
  font-size: 12px;
  color: var(--color-ink-soft);
}

.doc-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-ink);
}

.banner {
  border-radius: var(--radius-card);
}

/* 质量摘要折叠条 */
.summary-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-ink);
}

.summary-brief {
  font-weight: 400;
  font-size: 12px;
  color: var(--color-ink-muted);
}

.audit-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 20px;
  margin-top: 4px;
  font-size: 12px;
  line-height: 20px;
}

.reason-list {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 19px;
  /* 审计原因/识别警告可能很长：封顶 + 内部滚动，
     否则固定高度布局下会把下方题目列表挤没。 */
  max-height: 180px;
  overflow-y: auto;
}

.meta-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.meta-card {
  flex: 1 1 340px;
}

.meta-title {
  font-size: 13px;
  font-weight: 600;
}

.meta-line {
  font-size: 12px;
  color: var(--color-ink-soft);
  line-height: 24px;
}

.chip {
  margin-left: 4px;
}

.muted {
  color: var(--color-ink-muted);
}

.danger {
  color: var(--el-color-danger);
}

.main {
  display: flex;
  gap: 12px;
  flex: 1;
  /* 不能是 0：警告块很长时（本例 19 条约 430px），0 会让 flexbox 把整个
     题目列表压成 0 高度——用户看到的全是头部信息，列表"消失"。 */
  min-height: 260px;
}

.list-pane {
  width: 300px;
  flex: 0 0 300px;
  overflow-y: auto;
  background: var(--glass-bg);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-card);
  padding: 8px;
  box-shadow: inset 0 1px 0 var(--glass-highlight);
}

.q-card {
  border: 1px solid var(--color-line);
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

/* 批量入库勾选模式：勾选框贴左，内容整体右移 */
.q-card {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.q-card > .q-body {
  flex: 1;
  min-width: 0;
}

.q-check {
  flex-shrink: 0;
  height: auto;
}

/* 勾选框在卡片里默认有 8px 的行高撑动，压回去与首行文字对齐 */
.q-check :deep(.el-checkbox__inner) {
  margin-top: 2px;
}

.list-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 2px 2px 8px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--color-line);
}

.q-card:hover {
  border-color: var(--color-primary-200);
}

.q-card.active {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.q-card.failed {
  border-left: 3px solid var(--el-color-danger);
}

.q-card.excluded {
  background: var(--color-canvas);
  border-style: dashed;
}

.q-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.q-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-ink);
}

.q-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 6px 0 4px;
}

.q-flags .el-tag {
  margin: 0;
}

.q-preview {
  font-size: 12px;
  color: var(--color-ink-soft);
  line-height: 18px;
  word-break: break-word;
}

.excluded-box {
  margin-top: 4px;
}

.detail-pane {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  background: var(--color-surface);
  border-radius: 4px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--color-line);
}

.detail-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}

.detail-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-ink);
}

.detail-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 详情区是固定高度的 flex 列，子项默认允许收缩：下方的题卡图+编辑表单更高时，
   上方的黄色提示会被压扁到互相重叠（文字糊成一片）。全部禁止收缩，
   改由 .detail-pane 自身的 overflow-y 滚动。 */
.detail-pane > * {
  flex-shrink: 0;
}

.item-alert {
  border-radius: 4px;
}

/* 与题库/工作台统一：详情主面板与质量卡也用同一种毛玻璃 */
.detail-pane {
  background: var(--glass-bg);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-card);
  box-shadow: inset 0 1px 0 var(--glass-highlight);
}

.meta-card {
  border-radius: var(--radius-card);
}

.detail-body {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

/* 预览态：渲染内容铺满右栏，内部滚动（与 detail-body 同一套视口约束） */
.col-preview {
  max-height: calc(100vh - 14rem);
  overflow-y: auto;
  padding: 2px 8px 2px 2px;
}

.col-card {
  flex: 0 0 42%;
  max-width: 42%;
  position: sticky;
  top: 0;
}

.card-image {
  width: 100%;
  border: 1px solid var(--color-line);
  border-radius: 4px;
  background: #fafafa;
}

.pad {
  padding: 12px;
  font-size: 12px;
}

.figures {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.fig-label {
  font-size: 12px;
}

.figure-thumb {
  width: 76px;
  height: 56px;
  border: 1px solid var(--color-line);
  border-radius: 3px;
  background: #fafafa;
}

.ref-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-size: 12px;
}

.answer-blocks {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.answer-block {
  font-size: 13px;
  line-height: 1.6;
}

.block-label {
  display: inline-block;
  min-width: 40px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.block-figures .figure-thumb {
  width: 110px;
  height: 82px;
}

.col-edit {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.field-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-ink-soft);
  margin-top: 6px;
}

.opt-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.opt-row .el-textarea {
  flex: 1;
}

.note-line {
  font-size: 12px;
  line-height: 18px;
}

.sub-collapse {
  margin-top: 8px;
}

.rich {
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-ink);
  word-break: break-word;
}

.rich-opt {
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-ink);
  word-break: break-word;
}

.rich img {
  vertical-align: middle;
}
</style>
