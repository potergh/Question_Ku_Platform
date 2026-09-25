# 英语题型识别专项优化 —— 计划

## 背景（实测证据）
《2023年天津市河西区中考英语一模试卷》经 `api_extract` 通道识别出 43 题（`data/ocr_output/1358bedb_*/extract.json`，staging）。
核对后发现：小节(section)识别正确（听力/单项填空/完形填空/阅读理解/完成句子/任务型阅读/综合填空/书面表达），
但**题型全部套理化枚举**，且**篇章题被压平成一道题**：

- 完形填空 qid32：全文 1390 字 + 15 个空 → 只剩第 1 空的 4 选项，答案 `B`（15 空答案丢失）。
- 阅读理解 qid33/34/35：整篇文章 + 一组选项，答案却是 `ACDCB` / `（1）C（2）A（3）D（4）B（5）B` 多小题串。
  → 即用户截图的「题十」：右侧显示一套 A/B/C/D「选项」，但它根本不是单选题。
- 听力 qid15/16：3 个小题并成 1 条，9 个选项堆一起，答案 `BAB`。
- 题型语义错误：完形/阅读被判 `multiple_choice`，完成句子/任务型阅读/综合填空被判 `fill_blank`，书面表达被判 `short_answer`。

## 根因
1. 数据模型是「单题」导向：一条 Question = 一个 content + 一组 options + 一个 answer，无法表达「一篇材料挂多小题」。
2. 题型枚举是理化导向：`app/utils/question_types.py` / `frontend/.../questionTypes.js` 无英语专属题型。
3. 篇章块只切一条：options 取第一组、answer 取整串 → 结构与答案对不上。

## 分期策略
- **Phase 1（本计划执行，自洽可测）**：英语专属题型 + 按 section 推断题型 + 篇章题在复核/详情里不再误显示「单选选项」。
  `question_type` 是自由 `String(50)`（无 DB 枚举约束），加类型码无需迁移；推断在「读取序列化」处生效，
  **已 staging 的这份卷子不重跑即可显示正确**。
- **Phase 2（需拍板 + 改识别管线，暂不做）**：引入「语篇 + 小题」两级数据模型（material + sub_questions[]），
  让完形/阅读/听力长对话的每个小题成为独立可编号、可取答案、可组卷的记录。涉及 DB、边界/视觉 prompt、
  rich_document、render_ir、docx_export、全部 UI，且必须重跑识别验证——风险与工作量都大，单列一期。

## Phase 1 改动清单

### 后端
1. `app/utils/question_types.py`
   - `QUESTION_TYPE_MAP` 增加英语题型码：`listening 听力题 / grammar_choice 单项填空 / cloze 完形填空 /
     reading 阅读理解 / task_reading 任务型阅读 / use_of_english 综合填空 / sentence_completion 完成句子 / writing 书面表达`。
   - 新增 `infer_question_type_from_section(section) -> str | None`：按关键词（带优先级）把中文板块映射到英语题型码。
   - 新增 `PASSAGE_TYPES`（cloze/reading/task_reading/use_of_english/sentence_completion/writing）。
2. `app/services/api_extract_adapter.py` → `ExtractItemData.to_question_data`
   - 当现有题型为「理化通用码」且 section 能映射到英语题型时，用推断结果覆盖（用户已手改成具体英语题型则保留）。
3. `app/routers/extract.py` → `_serialize_item`
   - 同样规则在序列化给预览页时归一 `question_type`，让已 staging 数据不重跑即显示正确。

### 前端
4. `frontend/src/utils/questionTypes.js`：补同上 8 个英语题型码 + 导出 `PASSAGE_TYPES`。
5. `frontend/src/views/ExtractReviewView.vue`：篇章题（PASSAGE_TYPES）隐藏「选项」预览块与「选项」编辑区，
   改显示一行提示（小题选项待结构化，答案见下），避免「阅读理解显示一套单选选项」的误导。
6. `frontend/src/views/LibraryView.vue`（题目详情弹窗）：篇章题同样隐藏「选项」区。

### 测试
7. `backend/tests/test_question_types_english.py`（新增）：
   - section→type 映射全枚举 + 优先级（任务型阅读≠阅读理解、单项填空≠完形/综合填空）+ 理化板块返回 None。
   - `to_question_data`：通用码 + 英语 section → 覆盖为英语码；已是英语码 → 保留不覆盖。

## 验证
- 前端 `npm run build`；后端 `pytest`（含新增用例，且不破既有 499）。
- 重启后端；刷新复核页确认：完形→完形填空、阅读→阅读理解 且不再出现「选项」块；完成句子/任务型阅读/综合填空/书面表达各归其型。

## git
- Phase 1 全绿后一次提交。

## 明确不做（本期）
- 不拆分小题（qid32 仍是一条记录，只是题型正确为完形填空、不再误显选项）。
- 不修听力选项恒为 3、36 号题缺失——属切分/识别质量问题，归 Phase 2 管线一并处理。
