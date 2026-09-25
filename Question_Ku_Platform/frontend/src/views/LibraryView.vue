<template>
  <!-- .bank-page 让整页高度锁定视口（lg 起生效，见样式区）：两栏工作台的滚动
       交给左右各自持有，整页不再滚 —— 否则 50 道题会把文档撑到一万多 px。 -->
  <div class="page-shell bank-page page-enter">
    <header class="page-head" style="--i: 0">
      <span class="icon-chip icon-chip--sm bg-tint-brand text-on-tint-brand">
        <el-icon :size="17"><Files /></el-icon>
      </span>
      <h1 class="page-title">题库管理</h1>
      <p class="page-subtitle">
        共 {{ total }} 道题<template v-if="selectedIds.size > 0"> · 已选 {{ selectedIds.size }} 题</template>
      </p>
    </header>

    <!-- 单栏布局：列表占满整页宽度，题目详情改为点开弹窗（原先的左右分栏 +
         可拖拽分隔条已删）。宽屏下 45% 宽的列表栏太挤，筛选控件常年折行；
         单栏后筛选一行放得下，卡片视图也能用上横向空间。 -->
    <div class="bank-single" :style="{ '--i': 1 }">
      <section class="panel bank-list min-w-0">
        <header class="border-b border-line px-4 pb-3 pt-4">
          <!-- 「本地题库 / 待复核」分段已删：它与筛选里的「状态」下拉是同一件事
               的两处表达（分段选中"待复核"＝状态选 pending），留两处会互相打架。
               待复核入口收敛到状态筛选，页首直接就是搜索框。 -->
          <el-input
            v-model="filters.search"
            placeholder="搜索题干、知识点或来源..."
            clearable
            @keyup.enter="loadQuestions"
            @clear="loadQuestions"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>

          <!-- 筛选默认收起（参考稿是「筛选条件」+「清除筛选」两个入口） -->
          <div class="mt-2 flex items-center justify-between">
            <el-button text size="small" @click="showBankFilters = !showBankFilters">
              筛选条件
              <el-icon class="ml-1"><component :is="showBankFilters ? 'ArrowUp' : 'ArrowDown'" /></el-icon>
            </el-button>
            <div class="flex items-center gap-1">
              <el-button v-if="hasActiveFilters" text size="small" @click="clearBankFilters">
                清除筛选
              </el-button>
              <el-button text size="small" @click="loadQuestions">
                <el-icon><Refresh /></el-icon>
              </el-button>
              <el-button text size="small" @click="$router.push('/basket')">
                选题池 ({{ basketTotal }})
              </el-button>
              <!-- 卡片/列表切换：选择记进 localStorage，下次进来保持。按钮文案
                   显示的是**要切换到**的那一种（与图标类切换钮同一惯例）。 -->
              <el-button text size="small" @click="toggleViewMode">
                {{ viewMode === 'card' ? '列表视图' : '卡片视图' }}
              </el-button>
            </div>
          </div>

    <!--
      筛选栏：一行放下全部七个下拉 + 标签管理。改成单栏后容器有整页宽
      （原先挤在 45% 的左栏里，~500px 只能折成两行），八个控件合计约 900px，
      宽屏一行放得下。仍保留 flex-wrap 兜底：窗口窄时自然换行，不挤爆容器。
    -->
    <div v-show="showBankFilters" class="mt-2 mb-3 flex flex-wrap items-center gap-2">
      <el-select v-model="filters.subject" placeholder="学科" clearable style="width: 110px" @change="loadQuestions">
        <el-option v-for="s in availableSubjects" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-select v-model="filters.question_type" placeholder="题型" clearable style="width: 110px" @change="loadQuestions">
        <el-option label="选择题" value="选择题" />
        <el-option label="填空题" value="填空题" />
        <el-option label="解答题" value="解答题" />
        <el-option label="实验题" value="实验题" />
      </el-select>
      <!-- 原「待复核」分段的唯一入口：待审核/已通过/已驳回都在这里 -->
      <el-select v-model="filters.review_status" placeholder="状态" clearable style="width: 110px" @change="loadQuestions">
        <el-option label="待审核" value="pending" />
        <el-option label="已通过" value="approved" />
        <el-option label="已驳回" value="rejected" />
      </el-select>
      <el-select v-model="filters.difficulty" placeholder="难度" clearable style="width: 100px" @change="loadQuestions">
        <el-option v-for="d in 5" :key="d" :label="`${d} 星`" :value="d" />
      </el-select>
      <el-select v-model="filters.grade" placeholder="年级" clearable style="width: 84px" @change="loadQuestions">
        <el-option v-for="g in gradeOptions" :key="g" :label="g" :value="g" />
      </el-select>
      <el-select v-model="filters.source_id" placeholder="试卷" clearable style="width: 150px" @change="loadQuestions">
        <el-option v-for="s in doneSources" :key="s.id" :label="s.filename" :value="s.id" />
      </el-select>
      <el-select
        v-model="filters.tag_ids"
        multiple
        placeholder="按标签筛选"
        clearable
        filterable
        style="width: 130px"
        @change="loadQuestions"
      >
        <el-option label="⚠ 未打标签" value="none" />
        <el-option v-for="t in allTags" :key="t.id" :label="`${subjectText(t.subject)} / ${categoryText(t.category)} / ${t.name}`" :value="t.id" />
      </el-select>
      <el-button size="small" @click="showTagMgmt = true">
        <el-icon><PriceTag /></el-icon> 标签管理
      </el-button>
    </div>
        </header>

        <!-- 列表滚动区：列表变长时滚的是它，不是整页（ref 供一键到底/到顶用） -->
        <div class="bank-list-body p-3" ref="listBodyRef">
    <!-- 批量操作条：选中后才出现，用主色底区别于普通卡片 -->
    <div
      v-if="selectedIds.size > 0"
      class="mb-4 flex flex-wrap items-center gap-2 rounded-card border border-primary-200 bg-primary-50 px-4 py-3"
    >
      <span class="mr-1 text-sm font-medium text-primary-700">已选 {{ selectedIds.size }} 题</span>
      <el-button type="success" size="small" @click="batchApprove">批量通过</el-button>
      <el-button type="warning" size="small" @click="batchAICorrect">AI 批量修正</el-button>
      <el-button type="info" size="small" @click="showTagDialog = true">批量打标签</el-button>
      <el-button type="warning" size="small" @click="batchAITag">AI 批量打标</el-button>
      <el-button type="primary" size="small" @click="addToBasket">加入选题池</el-button>
      <el-button type="danger" size="small" @click="batchDelete">批量删除</el-button>
      <el-button text size="small" @click="selectedIds.clear()">取消选择</el-button>
    </div>

    <!-- 全选与计数 -->
    <div v-if="questions.length > 0" class="mb-3 flex items-center justify-between px-1">
      <el-checkbox
        :model-value="allSelected"
        :indeterminate="someSelected"
        @change="toggleSelectAll"
      >
        全选当前页 ({{ questions.length }} 题)
      </el-checkbox>
      <span class="flex items-center gap-2">
        <span class="tabular-nums text-sm text-ink-muted">共 {{ total }} 题</span>
        <el-button size="small" text @click="scrollListTo('bottom')">
          <el-icon><Bottom /></el-icon> 到底
        </el-button>
      </span>
    </div>

        <!-- 列表/卡片共用同一套 article 标记，只换容器布局：内容两处各写一份
             迟早改得不一样，布局交给 CSS，模板里没有分支。 -->
        <div v-if="questions.length > 0" class="bank-items" :class="`bank-items--${viewMode}`">
          <article
            v-for="q in questions"
            :key="q.id"
            class="glass-item cursor-pointer px-4 py-3"
            :class="
              detailQuestion && detailQuestion.id === q.id
                ? 'border-primary-500 ring-1 ring-primary-200'
                : ''
            "
            @click="openDetail(q)"
          >
            <header class="flex flex-wrap items-center gap-2">
              <el-checkbox
                :model-value="selectedIds.has(q.id)"
                @click.stop="toggleSelect(q.id)"
              />
              <span class="tabular-nums text-xs text-ink-muted">#{{ q.question_number }}</span>
              <el-tag v-if="q.question_type" size="small" type="info" effect="plain">
                {{ q.question_type_zh || q.question_type }}
              </el-tag>
              <el-tag :type="reviewTagType(q.review_status)" size="small" effect="plain">
                {{ reviewText(q.review_status) }}
              </el-tag>
              <el-tag v-if="q.ai_suggestions" size="small" type="warning" effect="plain">AI</el-tag>
              <span class="ml-auto flex items-center gap-2 text-xs text-ink-muted">
                <span v-if="q.score" class="tabular-nums">{{ q.score }}分</span>
                <span v-if="q.ocr_confidence" class="tabular-nums">
                  {{ (q.ocr_confidence * 100).toFixed(0) }}%
                </span>
              </span>
            </header>

            <!-- 预览字数按视图区分：列表是整页宽，150 字只够一行；配合两行
                 截断（.q-brief），行高稳定。卡片窄，150 字恰好两三行。 -->
            <div
              class="q-brief mt-2 text-sm leading-relaxed text-ink"
              v-html="renderPreview(q.content, viewMode === 'list' ? 420 : 150)"
            ></div>
            <div v-if="viewMode === 'card' && q.options?.length" class="mt-1.5 space-y-0.5">
              <div
                v-for="opt in q.options.slice(0, 4)"
                :key="opt.label"
                class="text-sm text-ink-soft"
                v-html="opt.label + '. ' + renderOptionContent(opt.content)"
              ></div>
            </div>

            <footer v-if="viewMode === 'card' && q.tags?.length" class="mt-2.5 flex flex-wrap gap-1.5">
              <el-tag v-for="t in q.tags" :key="t.id" size="small" :color="t.color" effect="dark">
                {{ t.name }}
              </el-tag>
            </footer>
          </article>
        </div>

        <el-empty v-else description="暂无题目" />

        <!-- 翻页行的末尾接一个「到顶」：与列表上方的「到底」互为往返。
             一行题目多于 50（没有翻页器）时也保留这一行，否则回不去顶部。 -->
        <div v-if="questions.length > 0" class="mt-4 flex items-center justify-center gap-3">
          <el-pagination
            v-if="total > pageSize"
            v-model:current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="total, prev, pager, next"
            @current-change="loadQuestions"
          />
          <el-button size="small" text @click="scrollListTo('top')">
            <el-icon><Top /></el-icon> 到顶
          </el-button>
        </div>
        </div>
      </section>

      <!--
        题目详情改为**弹窗**：单栏布局后右侧不再有常驻面板，点列表里的题即弹出。
        原先的空状态分支删了 —— 弹窗只在点题后出现，"没选题"这个状态不存在。
      -->
      <el-dialog v-model="showDetail" title="题目详情" width="760px" top="4vh" draggable>
        <div class="bank-detail-body">
          <template v-if="detailQuestion">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="题号">{{ detailQuestion.question_number }}</el-descriptions-item>
          <el-descriptions-item label="题型">{{ questionTypeText(detailQuestion) }}</el-descriptions-item>
          <el-descriptions-item label="学科">{{ subjectText(detailQuestion.subject) }}</el-descriptions-item>
          <el-descriptions-item label="难度">
            <el-rate v-model="detailQuestion.difficulty" :max="5" disabled size="small" />
          </el-descriptions-item>
          <el-descriptions-item label="分值">{{ detailQuestion.score || '-' }}</el-descriptions-item>
          <el-descriptions-item label="年级">{{ detailQuestion.grade || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="reviewTagType(detailQuestion.review_status)">{{ reviewText(detailQuestion.review_status) }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <h4 style="margin: 16px 0 8px;">
          题目内容
          <el-switch v-model="detailPreviewMode" active-text="预览" inactive-text="编辑" size="small" style="margin-left: 12px;" />
        </h4>
        <!-- Rendered preview (with LaTeX + images) -->
        <div v-if="detailPreviewMode" class="rendered-preview" v-html="renderFullContent(detailQuestion.content)"></div>
        <!-- Raw editor -->
        <el-input v-else v-model="detailQuestion.content" type="textarea" :autosize="{ minRows: 3, maxRows: 12 }" />

        <div v-if="detailQuestion.options?.length" style="margin-top: 12px;">
          <h4 style="display: flex; align-items: center; gap: 8px;">
            选项
            <el-tag v-if="detailQuestion.options.length < 4" type="warning" size="small" effect="dark">
              选项不完整({{ detailQuestion.options.length }}/4)
            </el-tag>
          </h4>
          <!-- Preview mode: rendered LaTeX + images -->
          <template v-if="detailPreviewMode">
            <div v-for="(opt, i) in detailQuestion.options" :key="i" class="option-rendered"
              v-html="opt.label + '. ' + renderOptionContent(opt.content)">
            </div>
          </template>
          <!-- Edit mode: input fields -->
          <template v-else>
            <div v-for="(opt, i) in detailQuestion.options" :key="i" style="margin-bottom: 6px; display: flex; gap: 6px; align-items: center;">
              <el-input v-model="opt.content" size="small" style="flex: 1;">
                <template #prepend>
                  <el-select v-model="opt.label" size="small" style="width: 60px;">
                    <el-option label="A" value="A" />
                    <el-option label="B" value="B" />
                    <el-option label="C" value="C" />
                    <el-option label="D" value="D" />
                    <el-option label="E" value="E" />
                    <el-option label="F" value="F" />
                  </el-select>
                </template>
              </el-input>
              <el-button type="danger" size="small" @click="detailQuestion.options.splice(i, 1)" :icon="Delete" circle />
            </div>
            <el-button type="primary" size="small" @click="addOption" style="margin-top: 6px;">
              <el-icon><Plus /></el-icon> 添加选项
            </el-button>
          </template>
        </div>

        <el-row :gutter="12" style="margin-top: 12px;">
          <el-col :span="8">
            <el-input v-model="detailQuestion.answer" placeholder="答案">
              <template #prepend>答案</template>
            </el-input>
          </el-col>
          <el-col :span="8">
            <el-input v-model="detailQuestion.explanation" placeholder="解析">
              <template #prepend>解析</template>
            </el-input>
          </el-col>
          <el-col :span="8">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="color: var(--color-ink-soft); font-size: 14px; white-space: nowrap;">难度:</span>
              <el-rate v-model="detailQuestion.difficulty" :max="5" show-score text-color="var(--el-color-warning)" />
            </div>
          </el-col>
        </el-row>

        <!-- 答案区插图：卷面答案是图时 answer 只会写「如上图所示」，图在这里 -->
        <div v-if="(detailQuestion.answer_image_paths || []).length" class="answer-figures">
          <span class="answer-figures-label">
            答案插图 {{ detailQuestion.answer_image_paths.length }} 张（卷面答案为图时看这里）
          </span>
          <div class="answer-figures-row">
            <el-image
              v-for="(url, i) in previewAnswerImages"
              :key="i"
              :src="url"
              :preview-src-list="previewAnswerImages"
              :initial-index="i"
              :preview-teleported="true"
              fit="contain"
              class="answer-figure"
            />
          </div>
        </div>

        <div style="margin-top: 12px; display: flex; align-items: center; gap: 8px;">
          <span style="color: var(--color-ink-soft); font-size: 14px; white-space: nowrap;">年级:</span>
          <el-select v-model="detailQuestion.grade" placeholder="选择年级" clearable style="width: 160px;">
            <el-option v-for="g in gradeOptions" :key="g" :label="g" :value="g" />
          </el-select>
        </div>

        <!-- Tags Section -->
        <div style="margin-top: 16px;">
          <h4 style="margin-bottom: 8px;">标签</h4>
          <div style="display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 8px;">
            <el-tag v-for="t in detailQuestion.tags" :key="t.id" :color="t.color" effect="dark" closable @close="removeTagFromDetail(t.id)" style="margin: 2px;">
              {{ t.name }}
            </el-tag>
            <span v-if="!detailQuestion.tags?.length" style="color: var(--color-ink-muted); font-size: 13px;">暂无标签</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <el-select v-model="detailTagSelect" placeholder="添加标签" filterable size="small" style="width: 200px;">
              <el-option v-for="t in availableTagsForDetail" :key="t.id" :label="`${categoryText(t.category)} / ${t.name}`" :value="t.id" />
            </el-select>
            <el-button size="small" @click="addTagToDetail" :disabled="!detailTagSelect">添加</el-button>
            <el-button size="small" type="warning" @click="aiTagSingle" :loading="aiTagging">AI 打标</el-button>
          </div>
        </div>

        <!-- AI 解析结果：未落库，确认后才填入表单 -->
        <div
          v-if="solveResult && solveResult.qid === detailQuestion.id"
          class="mt-4 rounded-card border border-line bg-canvas px-4 py-3"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="text-sm font-medium text-ink">AI 解析（未保存）</span>
            <div class="flex items-center gap-1.5">
              <el-button size="small" type="primary" @click="applySolveResult">
                填入答案与解析
              </el-button>
              <el-button size="small" text @click="solveResult = null">关闭</el-button>
            </div>
          </div>
          <p v-if="solveResult.answer" class="mt-2 text-sm text-ink">
            <span class="text-ink-muted">答案：</span>{{ solveResult.answer }}
          </p>
          <div
            v-if="solveResult.explanation"
            class="mt-2 text-sm leading-relaxed text-ink-soft"
            v-html="renderFullContent(solveResult.explanation)"
          ></div>
        </div>

        <div style="margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap;">
          <el-button type="primary" @click="saveDetail">保存</el-button>
          <el-button type="warning" @click="aiCorrectSingle" :loading="aiCorrecting">
            <el-icon v-if="!aiCorrecting"><MagicStick /></el-icon>
            AI 修正
          </el-button>
          <el-button type="warning" plain @click="aiSolveSingle" :loading="aiSolving">
            <el-icon v-if="!aiSolving"><MagicStick /></el-icon>
            AI 解析
          </el-button>
          <el-button v-if="detailQuestion.review_status === 'pending'" type="success" @click="quickReview('approve')">通过</el-button>
          <el-button v-if="detailQuestion.review_status === 'pending'" type="danger" @click="quickReview('reject')">驳回</el-button>
        </div>

        <!-- AI Suggestions -->
        <div v-if="detailQuestion.ai_suggestions" class="ai-suggest-box">
          <div class="ai-suggest-header">
            <el-icon style="color: var(--el-color-warning);"><MagicStick /></el-icon>
            <span>AI 建议</span>
            <el-tag size="small" type="warning">{{ Math.round((detailQuestion.ai_suggestions.confidence || 0) * 100) }}% 置信</el-tag>
          </div>
          <div class="ai-suggest-body">
            <span v-if="detailQuestion.ai_suggestions.question_type">题型: {{ QUESTION_TYPE_MAP[detailQuestion.ai_suggestions.question_type] || detailQuestion.ai_suggestions.question_type }}</span>
            <span v-if="detailQuestion.ai_suggestions.difficulty">难度: {{ detailQuestion.ai_suggestions.difficulty }}星</span>
          </div>
          <el-button size="small" type="warning" @click="acceptAI" :disabled="aiAccepted">采纳 AI 建议</el-button>
        </div>
      </template>
        </div>
      </el-dialog>
    </div>

    <!-- Tag Management Dialog -->
    <el-dialog v-model="showTagMgmt" title="标签管理" width="600px">
      <!-- Subject tabs (primary level) -->
      <el-tabs v-model="mgmtSubject" style="margin-bottom: 12px;">
        <el-tab-pane label="物理" name="physics" />
        <el-tab-pane label="数学" name="math" />
        <el-tab-pane label="化学" name="chemistry" />
        <el-tab-pane label="英语" name="english" />
      </el-tabs>
      <!-- Category sub-tabs (secondary level) -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <el-radio-group v-model="mgmtCategory" size="small">
          <el-radio-button label="knowledge">知识点</el-radio-button>
          <el-radio-button label="skill">技能</el-radio-button>
          <el-radio-button label="error_type">错因</el-radio-button>
          <el-radio-button label="custom">自定义</el-radio-button>
        </el-radio-group>
        <el-button type="primary" size="small" @click="showCreateTag = true">
          <el-icon><Plus /></el-icon> 新增
        </el-button>
        <el-button size="small" @click="showBatchImport = true">
          <el-icon><Upload /></el-icon> 批量导入
        </el-button>
      </div>
      <div style="display: flex; flex-wrap: wrap; gap: 8px;">
        <div v-for="t in filteredMgmtTags" :key="t.id" class="mgmt-tag">
          <span>{{ t.name }}</span>
          <span class="mgmt-tag-actions">
            <el-button text size="small" @click="editTagItem(t)">编辑</el-button>
            <el-button text type="danger" size="small" @click="deleteTagItem(t)">删除</el-button>
          </span>
        </div>
      </div>
      <el-empty v-if="filteredMgmtTags.length === 0" description="该分类暂无标签" :image-size="40" />
    </el-dialog>

    <!-- Create/Edit Tag Dialog -->
    <el-dialog v-model="showCreateTag" :title="editingTagItem ? '编辑标签' : '新增标签'" width="400px" append-to-body>
      <el-form @submit.prevent="saveTagItem">
        <el-form-item label="学科">
          <el-select v-model="tagForm.subject" :disabled="!!editingTagItem">
            <el-option label="物理" value="physics" />
            <el-option label="数学" value="math" />
            <el-option label="化学" value="chemistry" />
            <el-option label="英语" value="english" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="tagForm.name" placeholder="标签名称" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="tagForm.category" :disabled="!!editingTagItem">
            <el-option label="知识点" value="knowledge" />
            <el-option label="技能" value="skill" />
            <el-option label="错因" value="error_type" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色（可选）">
          <el-color-picker v-model="tagForm.color" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateTag = false; editingTagItem = null">取消</el-button>
        <el-button type="primary" @click="saveTagItem" :disabled="!tagForm.name">保存</el-button>
      </template>
    </el-dialog>

    <!-- Batch Import Tags Dialog -->
    <el-dialog v-model="showBatchImport" title="批量导入标签" width="500px" append-to-body>
      <p style="color: var(--color-ink-muted); font-size: 13px; margin-bottom: 8px;">
        每行一个标签名，将导入到当前选中的学科和分类：
        <b>{{ subjectText(mgmtSubject) }} / {{ categoryText(mgmtCategory) }}</b>
      </p>
      <el-input
        v-model="batchImportText"
        type="textarea"
        :rows="10"
        placeholder="每行一个标签名，例如：&#10;电磁学&#10;力学&#10;光学&#10;热学"
      />
      <p style="color: var(--el-color-success); font-size: 12px; margin-top: 6px;" v-if="batchImportNames.length > 0">
        将导入 {{ batchImportNames.length }} 个标签
      </p>
      <template #footer>
        <el-button @click="showBatchImport = false">取消</el-button>
        <el-button type="primary" @click="doBatchImport" :disabled="batchImportNames.length === 0">导入</el-button>
      </template>
    </el-dialog>

    <!-- Batch Tag Dialog -->
    <el-dialog v-model="showTagDialog" title="批量标签操作" width="450px">
      <el-radio-group v-model="batchTagMode" style="margin-bottom: 12px;">
        <el-radio-button label="add">添加标签</el-radio-button>
        <el-radio-button label="remove">移除标签</el-radio-button>
      </el-radio-group>
      <el-select v-model="batchTagSubject" placeholder="按学科筛选" clearable @change="() => {}" style="width: 100%; margin-bottom: 8px;">
        <el-option label="物理" value="physics" />
        <el-option label="数学" value="math" />
        <el-option label="化学" value="chemistry" />
        <el-option label="英语" value="english" />
      </el-select>
      <el-select v-model="selectedTagIds" multiple placeholder="选择标签" filterable style="width: 100%;">
        <el-option v-for="t in batchFilteredTags" :key="t.id" :label="`${subjectText(t.subject)} / ${categoryText(t.category)} / ${t.name}`" :value="t.id" />
      </el-select>
      <p style="color: var(--color-ink-muted); font-size: 12px; margin-top: 8px;">
        <span v-if="batchTagMode === 'add'">将为选中的 {{ selectedIds.size }} 道题添加这些标签</span>
        <span v-else style="color: var(--el-color-danger);">将从选中的 {{ selectedIds.size }} 道题移除这些标签</span>
      </p>
      <template #footer>
        <el-button @click="showTagDialog = false">取消</el-button>
        <el-button :type="batchTagMode === 'remove' ? 'danger' : 'primary'" @click="doBatchTag">
          {{ batchTagMode === 'add' ? '确认添加' : '确认移除' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- AI Correction Preview Dialog -->
    <el-dialog v-model="showAIPreview" title="AI 修正预览" width="700px" top="5vh">
      <div v-if="aiPreviewData" class="ai-preview">
        <el-alert type="info" :closable="false" style="margin-bottom: 12px;">
          <span v-if="aiPreviewData.needs_llm">AI 已修正以下内容，请检查后确认应用</span>
          <span v-else>内容质量良好，无需 AI 修正</span>
        </el-alert>
        <div v-if="aiPreviewData.analysis?.problems?.length" class="ai-problems">
          <b>检测到的问题：</b>
          <ul><li v-for="p in aiPreviewData.analysis.problems" :key="p">{{ p }}</li></ul>
        </div>
        <!-- Content comparison -->
        <el-row :gutter="16">
          <el-col :span="12">
            <h4>原始内容</h4>
            <div class="preview-box original">{{ aiPreviewData.original_content }}</div>
          </el-col>
          <el-col :span="12">
            <h4>AI 修正后</h4>
            <div class="preview-box corrected" v-html="renderFullContent(aiPreviewData.content)"></div>
          </el-col>
        </el-row>
        <!-- Options comparison -->
        <div v-if="aiPreviewData.options?.length" style="margin-top: 12px;">
          <h4>选项对比</h4>
          <el-row :gutter="16">
            <el-col :span="12">
              <div v-for="opt in aiPreviewData.original_options" :key="opt.label" class="opt-compare">
                {{ opt.label }}. {{ opt.content || '(空)' }}
              </div>
            </el-col>
            <el-col :span="12">
              <div v-for="opt in aiPreviewData.options" :key="opt.label" class="opt-compare">
                {{ opt.label }}. {{ opt.content || '(空)' }}
              </div>
            </el-col>
          </el-row>
        </div>
      </div>
      <template #footer>
        <el-button @click="showAIPreview = false">取消</el-button>
        <el-button type="primary" @click="acceptAICorrection" :disabled="!aiPreviewData?.needs_llm">
          应用修正
        </el-button>
      </template>
    </el-dialog>

    <!-- Batch AI Progress Dialog -->
    <el-dialog v-model="showBatchAIProgress" title="AI 批量修正" width="500px">
      <div v-if="batchAIState === 'running'">
        <el-progress :percentage="batchAIProgress" :status="batchAIProgress === 100 ? 'success' : ''" />
        <p style="margin-top: 8px; color: var(--color-ink-muted);">正在修正第 {{ batchAICurrent }} / {{ batchAITotal }} 题...</p>
      </div>
      <div v-if="batchAIState === 'done'">
        <el-result icon="success" title="批量修正完成">
          <template #sub-title>
            成功 {{ batchAIResults.filter(r => !r.error).length }} 题，
            失败 {{ batchAIResults.filter(r => r.error).length }} 题
          </template>
        </el-result>
      </div>
      <template #footer>
        <el-button v-if="batchAIState === 'done'" type="primary" @click="showBatchAIProgress = false; loadQuestions()">完成</el-button>
      </template>
    </el-dialog>

    <!-- Batch AI Tag Progress Dialog -->
    <el-dialog v-model="showBatchTagProgress" title="AI 批量打标" width="500px">
      <div v-if="batchTagState === 'running'">
        <el-progress :percentage="batchTagProgress" />
        <p style="margin-top: 8px; color: var(--color-ink-muted);">正在分析 {{ batchTagTotal }} 道题目的标签...</p>
      </div>
      <div v-if="batchTagState === 'done'">
        <el-result icon="success" title="批量打标完成">
          <template #sub-title>
            成功打标 {{ batchTagResult }} 道题
          </template>
        </el-result>
      </div>
      <template #footer>
        <el-button v-if="batchTagState === 'done'" type="primary" @click="showBatchTagProgress = false; loadQuestions()">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { renderFullContent, renderPreview, renderOptionContent } from '../utils/render.js'
import { QUESTION_TYPE_MAP } from '../utils/questionTypes'

const questions = ref([])
const sources = ref([])
const allTags = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const selectedIds = reactive(new Set())
const basketTotal = ref(0)
const showDetail = ref(false)
// 筛选条件默认收起：参考稿把 7 个下拉藏在一个「筛选条件」入口后面，
// 常态只看搜索框，题库页的视觉噪声小很多。
const showBankFilters = ref(false)
const detailQuestion = ref(null)
const detailPreviewMode = ref(true) // true = preview, false = edit
const aiAccepted = ref(false)
const showTagDialog = ref(false)
const selectedTagIds = ref([])
const batchTagSubject = ref('')
const batchTagMode = ref('add') // add / remove

// Tag management state
const showTagMgmt = ref(false)
const showCreateTag = ref(false)
const editingTagItem = ref(null)
const mgmtSubject = ref('physics')
const mgmtCategory = ref('knowledge')
const tagForm = reactive({ name: '', subject: 'physics', category: 'knowledge', color: null })
const detailTagSelect = ref('')
const aiTagging = ref(false)
const showBatchImport = ref(false)
const batchImportText = ref('')

// Batch AI tag progress state
const showBatchTagProgress = ref(false)
const batchTagState = ref('idle') // idle / running / done
const batchTagProgress = ref(0)
const batchTagTotal = ref(0)
const batchTagResult = ref(0)

// AI correction state
const aiCorrecting = ref(false)
const showAIPreview = ref(false)
const aiPreviewData = ref(null)
const showBatchAIProgress = ref(false)
const batchAIState = ref('idle') // idle / running / done
const batchAIProgress = ref(0)
const batchAICurrent = ref(0)
const batchAITotal = ref(0)
const batchAIResults = ref([])

const filters = reactive({
  search: '',
  subject: '',
  question_type: '',
  review_status: '',
  difficulty: null,
  grade: '',
  source_id: '',
  tag_ids: [],
})

// 「清除筛选」只在真的有筛选时才出现（参考稿同样如此），否则一个按不动
// 的按钮只会占地方。
const hasActiveFilters = computed(
  () =>
    Boolean(filters.search) ||
    Boolean(filters.subject) ||
    Boolean(filters.question_type) ||
    Boolean(filters.review_status) ||
    filters.difficulty !== null ||
    Boolean(filters.grade) ||
    Boolean(filters.source_id) ||
    (filters.tag_ids?.length ?? 0) > 0,
)

const clearBankFilters = () => {
  filters.search = ''
  filters.subject = ''
  filters.question_type = ''
  filters.review_status = ''
  filters.difficulty = null
  filters.grade = ''
  filters.source_id = ''
  filters.tag_ids = []
  loadQuestions()
}

// 年级筛选默认选项（题目年级数据后续逐步回填）
const gradeOptions = ['初一', '初二', '初三', '中考']

// Dynamic subjects from API
const availableSubjects = computed(() => {
  const subjects = [
    { value: 'physics', label: '物理' },
    { value: 'math', label: '数学' },
    { value: 'chemistry', label: '化学' },
    { value: 'english', label: '英语' },
  ]
  // Add any additional subjects from sources
  const sourceSubjects = new Set(sources.value.filter(s => s.ocr_status === 'done' && s.subject).map(s => s.subject))
  for (const subj of sourceSubjects) {
    if (!subjects.find(s => s.value === subj)) {
      subjects.push({ value: subj, label: subj })
    }
  }
  return subjects
})

// Only show sources with OCR done
const doneSources = computed(() => {
  return sources.value.filter(s => s.ocr_status === 'done')
})

// Select all functionality
const allSelected = computed(() => {
  return questions.value.length > 0 && questions.value.every(q => selectedIds.has(q.id))
})

const someSelected = computed(() => {
  const selectedCount = questions.value.filter(q => selectedIds.has(q.id)).length
  return selectedCount > 0 && selectedCount < questions.value.length
})

const toggleSelectAll = (checked) => {
  if (checked) {
    questions.value.forEach(q => selectedIds.add(q.id))
  } else {
    questions.value.forEach(q => selectedIds.delete(q.id))
  }
}

const loadSources = async () => {
  try {
    const res = await axios.get('/api/sources')
    sources.value = res.data.sources
  } catch (e) { /* silent */ }
}

const loadTags = async () => {
  try {
    const res = await axios.get('/api/tags')
    allTags.value = res.data
  } catch (e) { /* silent */ }
}

const loadQuestions = async () => {
  try {
    const params = { page: page.value, page_size: pageSize }
    if (filters.search) params.search = filters.search
    if (filters.subject) params.subject = filters.subject
    if (filters.question_type) params.question_type = filters.question_type
    if (filters.review_status) params.review_status = filters.review_status
    if (filters.difficulty) params.difficulty = filters.difficulty
    if (filters.grade) params.grade = filters.grade
    if (filters.source_id) params.source_id = filters.source_id
    if (filters.tag_ids?.length) params.tag_ids = filters.tag_ids.join(',')

    const res = await axios.get('/api/questions', { params })
    questions.value = res.data.questions
    total.value = res.data.total
  } catch (e) {
    ElMessage.error('加载失败')
  }
}

const toggleSelect = (id) => {
  if (selectedIds.has(id)) selectedIds.delete(id)
  else selectedIds.add(id)
}

// 答案区插图：后端出参时已把绝对路径转成 /api/ocr-assets/...；万一拿到的
// 还是本地路径（例如迁移前的历史数据），按 source_id 拼一个兜底 URL，
// 避免图片直接裂掉。
const resolveAnswerImageUrl = (url) => {
  if (!url) return ''
  const normalized = String(url).replace(/\\/g, '/')
  if (normalized.startsWith('/api/')) return normalized
  const marker = 'ocr_output/'
  const index = normalized.indexOf(marker)
  let relative = normalized
  if (index !== -1) {
    // 去掉 ocr_output/<文档目录>/ 两级，剩下 figures/answer_Q020_01.webp
    relative = normalized.slice(index + marker.length).split('/').slice(1).join('/')
  }
  return `/api/ocr-assets/${detailQuestion.value?.source_id || ''}/${relative}`
}

const previewAnswerImages = computed(() =>
  (detailQuestion.value?.answer_image_paths || []).map(resolveAnswerImageUrl),
)

const openDetail = (q) => {
  detailQuestion.value = JSON.parse(JSON.stringify(q))
  detailPreviewMode.value = true
  aiAccepted.value = false
  showDetail.value = true
}

const saveDetail = async () => {
  try {
    const q = detailQuestion.value
    await axios.put(`/api/questions/${q.id}`, {
      content: q.content,
      options: q.options,
      answer: q.answer,
      explanation: q.explanation,
      difficulty: q.difficulty,
      grade: q.grade,
    })
    ElMessage.success('已保存')
    loadQuestions()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const addOption = () => {
  if (!detailQuestion.value.options) {
    detailQuestion.value.options = []
  }
  const labels = ['A', 'B', 'C', 'D', 'E', 'F']
  const existingLabels = new Set(detailQuestion.value.options.map(o => o.label))
  const nextLabel = labels.find(l => !existingLabels.has(l)) || String.fromCharCode(65 + detailQuestion.value.options.length)
  detailQuestion.value.options.push({ label: nextLabel, content: '' })
}

const quickReview = async (action) => {
  try {
    await axios.post(`/api/questions/${detailQuestion.value.id}/review?action=${action}`)
    ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
    showDetail.value = false
    loadQuestions()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

const acceptAI = async () => {
  try {
    await axios.post(`/api/questions/${detailQuestion.value.id}/accept-ai`)
    ElMessage.success('已采纳 AI 建议')
    aiAccepted.value = true
    loadQuestions()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

const batchApprove = async () => {
  try {
    await ElMessageBox.confirm(`确定通过 ${selectedIds.size} 道题？`)
    await axios.post('/api/questions/batch-approve', { question_ids: [...selectedIds] })
    ElMessage.success('批量通过成功')
    selectedIds.clear()
    loadQuestions()
  } catch (e) { if (e !== 'cancel') ElMessage.error('操作失败') }
}

const batchDelete = async () => {
  try {
    await ElMessageBox.confirm(`确定删除 ${selectedIds.size} 道题？`, '警告', { type: 'warning' })
    await axios.post('/api/questions/batch-delete', { question_ids: [...selectedIds] })
    ElMessage.success('批量删除成功')
    selectedIds.clear()
    loadQuestions()
  } catch (e) { if (e !== 'cancel') ElMessage.error('操作失败') }
}

const doBatchTag = async () => {
  if (selectedTagIds.value.length === 0) {
    ElMessage.warning('请选择至少一个标签')
    return
  }

  const isRemove = batchTagMode.value === 'remove'
  const actionText = isRemove ? '移除' : '添加'

  try {
    await ElMessageBox.confirm(
      `确定要${actionText} ${selectedTagIds.value.length} 个标签到 ${selectedIds.size} 道题？`,
      '确认操作', { type: isRemove ? 'warning' : 'info' }
    )
  } catch { return }

  try {
    const endpoint = isRemove ? '/api/questions/batch-untag' : '/api/questions/batch-tag'
    await axios.post(endpoint, {
      question_ids: [...selectedIds],
      tag_ids: selectedTagIds.value,
    })
    ElMessage.success(`标签已${actionText}`)
    showTagDialog.value = false
    selectedTagIds.value = []
    loadQuestions()
  } catch (e) {
    ElMessage.error(`${actionText}标签失败`)
  }
}

// ── AI Correction ──

// AI 解析：让模型补答案与解析。结果**不落库**，与 AI 修正一致 ——
// 答案错了会被组卷印出去，宁可多一步人工确认。
const aiSolving = ref(false)
const solveResult = ref(null)

const aiSolveSingle = async () => {
  if (!detailQuestion.value) return
  aiSolving.value = true
  try {
    const res = await axios.post(`/api/questions/${detailQuestion.value.id}/ai-solve`)
    if (!res.data?.answer && !res.data?.explanation) {
      ElMessage.warning('模型没有给出可用内容，请重试或检查 AI 设置')
      solveResult.value = null
      return
    }
    // 带上 qid：切换题目后旧结果不再显示，避免张冠李戴
    solveResult.value = { ...res.data, qid: detailQuestion.value.id }
  } catch (e) {
    ElMessage.error('AI 解析失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    aiSolving.value = false
  }
}

const applySolveResult = () => {
  if (!solveResult.value || !detailQuestion.value) return
  const q = detailQuestion.value
  if (solveResult.value.answer) q.answer = solveResult.value.answer
  if (solveResult.value.explanation) q.explanation = solveResult.value.explanation
  solveResult.value = null
  ElMessage.success('已填入，确认无误后点「保存」')
}

const aiCorrectSingle = async () => {
  if (!detailQuestion.value) return
  aiCorrecting.value = true
  try {
    const res = await axios.post(`/api/questions/${detailQuestion.value.id}/ai-correct`)
    aiPreviewData.value = {
      ...res.data,
      original_content: detailQuestion.value.content || '',
      original_options: detailQuestion.value.options ? JSON.parse(JSON.stringify(detailQuestion.value.options)) : [],
    }
    showAIPreview.value = true
  } catch (e) {
    ElMessage.error('AI 修正失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    aiCorrecting.value = false
  }
}

const acceptAICorrection = async () => {
  if (!aiPreviewData.value || !detailQuestion.value) return
  const d = aiPreviewData.value
  const q = detailQuestion.value
  q.content = d.content
  if (d.options && d.options.length > 0) q.options = d.options
  if (d.answer) q.answer = d.answer
  if (d.explanation) q.explanation = d.explanation
  try {
    await axios.put(`/api/questions/${q.id}`, {
      content: q.content,
      options: q.options,
      answer: q.answer,
      explanation: q.explanation,
    })
    ElMessage.success('已应用 AI 修正')
    showAIPreview.value = false
    loadQuestions()
    const res2 = await axios.get(`/api/questions/${q.id}`)
    detailQuestion.value = res2.data
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const batchAICorrect = async () => {
  if (selectedIds.size === 0) return
  try {
    await ElMessageBox.confirm(
      `将对 ${selectedIds.size} 道题执行 AI 批量修正，所有题目会合并处理。继续？`,
      'AI 批量修正', { type: 'info' }
    )
  } catch { return }

  showBatchAIProgress.value = true
  batchAIState.value = 'running'
  batchAITotal.value = selectedIds.size
  batchAICurrent.value = selectedIds.size
  batchAIProgress.value = 50
  batchAIResults.value = []

  try {
    const res = await axios.post('/api/questions/batch-ai-correct', {
      question_ids: [...selectedIds],
    })
    const results = res.data.results || []

    // Auto-apply corrections
    for (const r of results) {
      if (!r.error && r.needs_llm && r.content) {
        try {
          await axios.put(`/api/questions/${r.question_id}`, {
            content: r.content,
            options: r.options,
            answer: r.answer,
            explanation: r.explanation,
          })
        } catch (e) {
          r.error = '应用失败: ' + (e.response?.data?.detail || e.message)
        }
      }
    }

    batchAIResults.value = results
    batchAIProgress.value = 100
    batchAIState.value = 'done'
    selectedIds.clear()
  } catch (e) {
    batchAIResults.value = [{ error: e.response?.data?.detail || e.message }]
    batchAIState.value = 'done'
  }
}

const truncate = (text, len) => {
  if (!text) return ''
  return text.length > len ? text.slice(0, len) + '...' : text
}

const reviewTagType = (s) => ({ pending: 'warning', approved: 'success', rejected: 'danger' })[s] || 'info'
const reviewText = (s) => ({ pending: '待审核', approved: '已通过', rejected: '已驳回' })[s] || s
const categoryText = (c) => ({ knowledge: '知识点', skill: '技能', error_type: '错因', custom: '自定义' })[c] || c
const subjectText = (s) => ({ physics: '物理', math: '数学', chemistry: '化学', english: '英语' })[s] || s || '未分类'
// 题型中文：优先后端 question_type_zh，否则本地映射兜底（详情弹窗保存后重取可能不带 zh）
const questionTypeText = (q) => q?.question_type_zh || QUESTION_TYPE_MAP[q?.question_type] || q?.question_type || '-'

// ── Tag Management ──

const filteredMgmtTags = computed(() => allTags.value.filter(t => t.subject === mgmtSubject.value && t.category === mgmtCategory.value))

const batchFilteredTags = computed(() => {
  if (!batchTagSubject.value) return allTags.value
  return allTags.value.filter(t => t.subject === batchTagSubject.value)
})

const availableTagsForDetail = computed(() => {
  if (!detailQuestion.value) return allTags.value
  const currentIds = new Set(detailQuestion.value.tags?.map(t => t.id) || [])
  const subject = detailQuestion.value.subject
  return allTags.value.filter(t => !currentIds.has(t.id) && (!subject || !t.subject || t.subject === subject))
})

const addTagToDetail = async () => {
  if (!detailTagSelect.value || !detailQuestion.value) return
  try {
    await axios.post('/api/questions/batch-tag', {
      question_ids: [detailQuestion.value.id],
      tag_ids: [detailTagSelect.value],
    })
    const tag = allTags.value.find(t => t.id === detailTagSelect.value)
    if (tag && !detailQuestion.value.tags) detailQuestion.value.tags = []
    if (tag) detailQuestion.value.tags.push({ id: tag.id, name: tag.name, category: tag.category, color: tag.color })
    detailTagSelect.value = ''
    loadQuestions()
  } catch (e) {
    ElMessage.error('添加标签失败')
  }
}

const removeTagFromDetail = async (tagId) => {
  if (!detailQuestion.value) return
  try {
    await axios.post('/api/questions/batch-untag', {
      question_ids: [detailQuestion.value.id],
      tag_ids: [tagId],
    })
    // Reload question from backend to ensure data consistency
    const res = await axios.get(`/api/questions/${detailQuestion.value.id}`)
    detailQuestion.value.tags = res.data.tags || []
    loadQuestions()
    ElMessage.success('标签已移除')
  } catch (e) {
    ElMessage.error('移除标签失败')
  }
}

const aiTagSingle = async () => {
  if (!detailQuestion.value) return

  // Check if any tags exist
  if (!allTags.value || allTags.value.length === 0) {
    ElMessage.warning('请先在标签管理中创建标签，AI 只能从已有标签中选择')
    return
  }

  aiTagging.value = true
  try {
    const res = await axios.post('/api/questions/batch-ai-tag', {
      question_ids: [detailQuestion.value.id],
    })
    if (res.data.tagged > 0) {
      ElMessage.success('AI 打标完成')
      // Reload question to get updated tags
      const qRes = await axios.get(`/api/questions/${detailQuestion.value.id}`)
      detailQuestion.value.tags = qRes.data.tags || []
      loadQuestions()
    } else {
      ElMessage.info('AI 未找到合适标签')
    }
  } catch (e) {
    ElMessage.error('AI 打标失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    aiTagging.value = false
  }
}

const batchAITag = async () => {
  if (selectedIds.size === 0) return

  // Check if any tags exist
  if (!allTags.value || allTags.value.length === 0) {
    ElMessage.warning('请先在标签管理中创建标签，AI 只能从已有标签中选择')
    return
  }

  // Get subjects of selected questions and filter tags by those subjects
  const selectedSubjects = new Set()
  for (const q of questions.value) {
    if (selectedIds.has(q.id) && q.subject) {
      selectedSubjects.add(q.subject)
    }
  }

  // Filter tags by selected subjects
  const relevantTags = allTags.value.filter(t => selectedSubjects.has(t.subject))
  const tagCount = relevantTags.length

  if (tagCount === 0) {
    const subjectNames = Array.from(selectedSubjects).map(s => subjectText(s)).join('、')
    ElMessage.warning(`请先为${subjectNames}学科创建标签`)
    return
  }

  try {
    await ElMessageBox.confirm(
      `将对 ${selectedIds.size} 道题执行 AI 批量打标，AI 会从已创建的 ${tagCount} 个${Array.from(selectedSubjects).length === 1 ? subjectText(Array.from(selectedSubjects)[0]) : '相关'}学科的标签中选择合适的。继续？`,
      'AI 批量打标', { type: 'info' }
    )
  } catch { return }

  showBatchTagProgress.value = true
  batchTagState.value = 'running'
  batchTagTotal.value = selectedIds.size
  batchTagProgress.value = 0
  batchTagResult.value = 0

  // Smooth progress animation - increment gradually
  const progressInterval = setInterval(() => {
    if (batchTagProgress.value < 90) {
      batchTagProgress.value += 8
      if (batchTagProgress.value > 90) batchTagProgress.value = 90
    }
  }, 600)

  try {
    const res = await axios.post('/api/questions/batch-ai-tag', {
      question_ids: [...selectedIds],
    })
    clearInterval(progressInterval)
    batchTagResult.value = res.data.tagged || 0
    batchTagProgress.value = 100
    batchTagState.value = 'done'
    selectedIds.clear()
    loadQuestions()
  } catch (e) {
    clearInterval(progressInterval)
    batchTagProgress.value = 100
    batchTagState.value = 'done'
    ElMessage.error('AI 批量打标失败: ' + (e.response?.data?.detail || e.message))
  }
}

// Tag CRUD
const editTagItem = (tag) => {
  editingTagItem.value = tag
  tagForm.name = tag.name
  tagForm.subject = tag.subject || 'physics'
  tagForm.category = tag.category
  tagForm.color = tag.color
  showCreateTag.value = true
}

const saveTagItem = async () => {
  try {
    if (editingTagItem.value) {
      await axios.put(`/api/tags/${editingTagItem.value.id}`, { ...tagForm })
      ElMessage.success('标签已更新')
    } else {
      await axios.post('/api/tags', { name: tagForm.name, subject: mgmtSubject.value, category: mgmtCategory.value, color: tagForm.color })
      ElMessage.success('标签已创建')
    }
    showCreateTag.value = false
    editingTagItem.value = null
    tagForm.name = ''
    tagForm.color = null
    loadTags()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const deleteTagItem = async (tag) => {
  try {
    await ElMessageBox.confirm(`确定删除标签“${tag.name}”？`, '警告', { type: 'warning' })
    await axios.delete(`/api/tags/${tag.id}`)
    ElMessage.success('已删除')
    loadTags()
    loadQuestions()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// Batch import tags
const batchImportNames = computed(() => {
  return batchImportText.value.split('\n').map(s => s.trim()).filter(s => s.length > 0)
})

const doBatchImport = async () => {
  const names = batchImportNames.value
  if (names.length === 0) return
  try {
    const res = await axios.post('/api/tags/batch-create', {
      names,
      subject: mgmtSubject.value,
      category: mgmtCategory.value,
    })
    ElMessage.success(`导入成功：${res.data.created} 个新标签，${res.data.skipped} 个重复跳过`)
    showBatchImport.value = false
    batchImportText.value = ''
    loadTags()
  } catch (e) {
    ElMessage.error('导入失败')
  }
}

// ── Selection basket ──

const loadBasketTotal = async () => {
  try {
    const res = await axios.get('/api/basket')
    basketTotal.value = res.data.total
  } catch (e) { /* 静默 */ }
}

const addToBasket = async () => {
  try {
    const res = await axios.post('/api/basket/items', { question_ids: [...selectedIds] })
    if (res.data.added === 0) {
      ElMessage.warning('所选题目均已在选题池中')
    } else {
      ElMessage.success(`已加入选题池 ${res.data.added} 题（池中共 ${res.data.total} 题）`)
    }
    basketTotal.value = res.data.total
  } catch (e) {
    ElMessage.error('加入选题池失败')
  }
}

// 「本地题库 / 待复核」分段已删：待复核改由筛选里的「状态」下拉承担。
// 原先为分段徽标单独请求 pendingTotal 的逻辑随之移除 —— 没有消费方了。

// ── 列表一键到底 / 一键到顶 ──────────────────────────────────────────
// 滚的是左栏自己的滚动区（.bank-list-body），不是整页：
// 整页在 lg 断点下已经不滚了，用 window.scrollTo 会一点反应都没有。
const listBodyRef = ref(null)
const scrollListTo = (where) => {
  const el = listBodyRef.value
  if (!el) return
  el.scrollTo({ top: where === 'bottom' ? el.scrollHeight : 0, behavior: 'smooth' })
}

// ── 视图模式：卡片 / 列表 ───────────────────────────────────────────
// 记住选择：布局偏好和上次选的宽度一样，每次进页面都复位会很烦。
// 默认卡片：单栏后列表行被拉到整页宽，一行题干两边大片留白；卡片网格
// 才用得上横向空间。用户显式切过之后以 localStorage 为准。
const viewMode = ref(localStorage.getItem('bankViewMode') === 'list' ? 'list' : 'card')
const toggleViewMode = () => {
  viewMode.value = viewMode.value === 'card' ? 'list' : 'card'
  localStorage.setItem('bankViewMode', viewMode.value)
}

onMounted(() => {
  loadSources()
  loadTags()
  loadQuestions()
  loadBasketTotal()
})

onUnmounted(() => {
  // 监听挂在 window 上，不摘掉会在页面切走后继续改这里的 ref
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', stopResize)
})
</script>

<style scoped>
/*
 * 两栏工作台：整页锁定为视口高度，滚动条交给左右两栏各自持有。
 *
 * 为什么要这么改：50 道题全部渲染在文档流里，整页会被撑到 10000+px（实测溢出
 * 10402px），而右侧详情又用了 lg:sticky top-0 去顶住 —— 结果就是"页面在滚、
 * 左栏看着没滚"，两边的滚动互不同步，翻到下面还会看到右侧一大片空白。
 *
 * 只在 lg 起生效：窄屏会退化成单列上下堆叠，那时两栏都得靠整页滚动，不能锁高。
 */
@media (min-width: 1024px) {
  .bank-page {
    display: flex;
    flex-direction: column;
    /* 必须显式 border-box：本项目全局是 content-box（没引 Tailwind preflight），
       否则 100vh 之外还要再加 page-shell 的上下内边距，反而多出 54px 滚动。 */
    box-sizing: border-box;
    height: 100vh;
    padding-bottom: 16px;
  }

  .bank-page .bank-single {
    flex: 1;
    min-height: 0;
  }

  .bank-list {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .bank-list-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }
}

/*
 * 滚动卡顿修复（性能）：
 * 1) 题库列表这块面板里滚的是 50 张含图卡片，而 .panel 的 backdrop-filter 会在
 *    每一帧滚动时重算整块模糊 —— 这是拖动掉帧的主因。只把「会滚长列表」的这一处
 *    降级为半透明实色背景、关掉模糊，其余静态面板保留玻璃质感不受影响。
 * 2) 离屏卡片用 content-visibility 跳过布局/绘制，滚进视口才渲染；
 *    contain-intrinsic-size 的 auto 关键字会记住卡片上次实际高度，减少滚动条跳动。
 */
.bank-list.panel {
  -webkit-backdrop-filter: none;
  backdrop-filter: none;
  background: var(--glass-bg-strong);
}

.bank-list-body .glass-item {
  content-visibility: auto;
  contain-intrinsic-size: auto 200px;
}

.library-view { max-width: 1200px; margin: 0 auto; }
.library-header { margin-bottom: 16px; display: flex; justify-content: space-between; align-items: flex-start; }
.subtitle { color: var(--color-ink-muted); margin-top: 4px; }
.filter-card { margin-bottom: 12px; }

.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--color-primary-50);
  border: 1px solid var(--color-primary-200);
  border-radius: 6px;
  margin-bottom: 12px;
}

.select-all-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: var(--color-canvas);
  border: 1px solid var(--color-line);
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
}

.total-count {
  color: var(--color-ink-muted);
}

.question-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}

/* 单栏容器：题库页不再左右分栏，列表占满整页宽度。 */
.bank-single {
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: stretch;
  min-height: 0;
}

/* 题目列表的两种排法。内容同一套 article 标记，只有容器布局不同。 */
/* 列表视图：一行一行的紧凑行，不是卡片 —— 去圆角去间隙，行间用发丝线，
   题干限两行，一屏能扫更多题。 */
.bank-items--list {
  display: flex;
  flex-direction: column;
}

.bank-items--list > article {
  padding: 7px 12px;
  border-radius: 0;
  border-top: none;
  border-left: none;
  border-right: none;
  border-bottom: 1px solid var(--color-line);
}

.bank-items--list > article:first-child {
  border-top: 1px solid var(--color-line);
}

/* 题干预览单行省略：列表视图一行一行扫，选项/标签都不铺开（仅卡片视图有）。
   nowrap + ellipsis，不用 -webkit-line-clamp（其 display:-webkit-box 会被
   Tailwind v4 的 Lightning CSS 压缩剥掉，实测静默失效）。 */
.bank-items--list .q-brief {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 行式视图里预览图也不铺开（图高 ~74px，一张图就把"行"撑回卡片）；
   要看图切卡片视图或点开详情。
   必须 :deep()：img 是 v-html 生成的，不带本组件的 scoped data 属性，
   普通 `.q-brief img` 选择器匹配不到（实测静默失效）。 */
.bank-items--list .q-brief :deep(img) {
  display: none;
}

.bank-items--card {
  display: grid;
  /* auto-fill + minmax：容器多宽就放几列，不需要再写断点；窄屏自然退化为单列 */
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 12px;
  align-items: start;
}

.q-card {
  border: 1px solid var(--color-line);
  border-radius: 8px;
  padding: 12px;
  background: var(--color-surface);
  cursor: pointer;
  transition: all 0.2s;
}
.q-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
.q-card.selected { border-color: var(--color-primary-500); background: var(--color-primary-50); }
.q-card.needs-review { border-left: 3px solid var(--el-color-warning); }

.q-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.q-num { font-weight: bold; color: var(--color-ink); }

.q-card-body { margin-bottom: 8px; }
.q-content-preview {
  font-size: 13px;
  color: var(--color-ink-soft);
  line-height: 1.6;
  max-height: 80px;
  overflow: hidden;
}
.q-options-preview { margin-top: 6px; }
.opt-line { font-size: 12px; color: var(--color-ink-muted); line-height: 1.5; }
.opt-line :deep(img) { max-height: 24px; vertical-align: middle; margin: 0 2px; border-radius: 2px; }
.opt-line :deep(.katex) { font-size: 0.95em; }

.q-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.q-tags { flex: 1; }
.q-meta { font-size: 12px; color: var(--color-ink-muted); display: flex; gap: 8px; }
.confidence { color: var(--el-color-success); }

.pagination { margin-top: 16px; text-align: center; }

/* AI Suggestions */
.ai-suggest-box {
  margin-top: 16px; padding: 12px; background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning-light-5); border-radius: 6px;
}
.ai-suggest-header {
  display: flex; align-items: center; gap: 6px;
  font-weight: 500; margin-bottom: 8px;
}
.ai-suggest-body {
  display: flex; gap: 16px; font-size: 13px; color: var(--color-ink-soft);
  margin-bottom: 8px;
}

/* Rendered preview in detail drawer */
.rendered-preview {
  padding: 12px 16px;
  background: var(--color-canvas);
  border: 1px solid var(--color-line);
  border-radius: 6px;
  line-height: 1.8;
  font-size: 14px;
  color: var(--color-ink);
  word-break: break-word;
  overflow-wrap: break-word;
}
.rendered-preview :deep(img) {
  max-width: min(100%, 400px);
  max-height: 300px;
  height: auto;
  border-radius: 4px;
  margin: 6px 0;
  display: block;
}
.rendered-preview :deep(.katex) {
  font-size: 1.05em;
}
.rendered-preview :deep(.katex-display) {
  margin: 12px 0;
  overflow-x: auto;
}

/* AI Correction Preview */
.ai-preview .ai-problems {
  background: var(--el-color-danger-light-9);
  border: 1px solid var(--el-color-danger-light-5);
  border-radius: 4px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.ai-preview .ai-problems ul {
  margin: 4px 0 0 16px;
  padding: 0;
}
.preview-box {
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  max-height: 300px;
  overflow-y: auto;
  min-height: 80px;
}
.preview-box.original {
  background: var(--color-canvas);
  border: 1px solid var(--color-line);
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-ink-soft);
}
.preview-box.corrected {
  background: var(--el-color-success-light-9);
  border: 1px solid var(--el-color-success-light-5);
  color: var(--color-ink);
}
.opt-compare {
  font-size: 13px;
  padding: 2px 0;
  color: var(--color-ink-soft);
}

/* Rendered options in detail drawer */
.option-rendered {
  padding: 6px 10px;
  margin-bottom: 4px;
  background: var(--color-canvas);
  border: 1px solid var(--color-line);
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-ink);
}
.option-rendered :deep(img) {
  max-height: 40px;
  vertical-align: middle;
  margin: 0 4px;
  border-radius: 3px;
}
.option-rendered :deep(.katex) {
  font-size: 1.0em;
}

/* Tag management */
.mgmt-tag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--color-canvas);
  border: 1px solid var(--color-line);
  border-radius: 4px;
  font-size: 13px;
  min-width: 120px;
}
.mgmt-tag-actions {
  opacity: 0;
  transition: opacity 0.2s;
  margin-left: 8px;
}
.mgmt-tag:hover .mgmt-tag-actions {
  opacity: 1;
}
.answer-figures {
  margin-top: 12px;
}
.answer-figures-label {
  font-size: 13px;
  color: var(--color-ink-muted);
}
.answer-figures-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
}
.answer-figure {
  width: 150px;
  height: 115px;
  border: 1px solid var(--color-line);
  border-radius: 4px;
  background: var(--color-surface);
  cursor: zoom-in;
}
</style>
