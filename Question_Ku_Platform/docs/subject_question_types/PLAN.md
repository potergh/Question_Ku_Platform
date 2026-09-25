# 分学科题型适配 —— 计划

## 背景（四科实测体检）
每科各导入一份天津中考一模：物理(done,25)、数学(staging,25)、化学(staging,26)、英语(staging,43)。
核对 `data/ocr_output/*/extract.json` 与 `questions` 表后确认：

- **A 类 题型与学科不适配**（本计划解决）
  1. 题库筛选题型下拉写死 4 项（选择/填空/解答/实验），与所选学科无关（`LibraryView.vue:67-72`）。
  2. section→题型推断只做了英语；化学「实验题/计算题/简答题」、物理实验/计算全被压成 `comprehensive`，
     `experiment/calculation/short_answer` 码存在却没被赋值。
  3. 数学「解答题」显示为「综合题」，语义偏。
- **B 类 识别/切分质量**（数据层，多数归 Phase 2，不在本计划强修）
  4. 英语听力 1–14 选项恒为 3（疑漏 D 项）。
  5. 英语 q15/16 九选项堆叠、q32/34/35/42/43 整篇压成一条（篇章多小题未拆分）。
  6. 物理 q22、数学 q22 解答题答案为空。
- **C 类 一致性**
  7. 物理已入库(done)，推断改动不回溯；staging 三科读取时即时生效。

## 目标
让「题型」成为学科感知的概念：每个学科有自己的题型目录，识别按板块自动归位，筛选按学科联动。

## 学科题型目录（拟定，待确认）
- **通用**：选择题 single_choice、多选题 multiple_choice、填空题 fill_blank、综合题 comprehensive、
  简答题 short_answer、实验题 experiment、计算题 calculation、未知 unknown
- **物理**：选择题、填空题、实验题、计算题、综合题、简答题
- **数学**：选择题、填空题、解答题(comprehensive，显示名按学科可覆写为「解答题」)
- **化学**：选择题、填空题、简答题、实验题、计算题、综合题
- **英语**：听力题、单项填空、完形填空、阅读理解、任务型阅读、综合填空、完成句子、书面表达

## 改动清单

### 后端
1. `app/utils/question_types.py`
   - 扩展 `infer_question_type_from_section`：在英语规则后追加理化生规则
     （实验题→experiment、计算题→calculation、简答题→short_answer、解答题/综合→comprehensive、
     选择题→single_choice、填空题→fill_blank、多选题→multiple_choice）。保持既有优先级与「只覆盖通用码」策略。
   - 新增 `SUBJECT_TYPE_CATALOG: dict[str, list[str]]`（学科→适用题型码），供 API/校验使用。
2. （可选，取决于决策③）`app/routers/questions.py`
   - 若需回溯已入库物理题型：加一次性归一脚本或读取时按存储 section 推断。物理 done 未存 section，只能重跑或手改，
     默认**不**回溯（见决策③）。

### 前端
3. `frontend/src/utils/questionTypes.js`
   - 新增 `SUBJECT_TYPE_CATALOG`（与后端一致）+ `typesForSubject(subject)`（无学科返回全量并集）。
4. `frontend/src/views/LibraryView.vue`
   - 题型下拉选项改为 `typesForSubject(filters.subject)`；`@change` 选学科时若当前 question_type 不在新目录则清空。

### 测试
5. `backend/tests/test_question_types_english.py` 扩展或新增 `test_question_types_sections.py`：
   - 理化生 section→type（实验题→experiment 等）；
   - 覆盖仍只作用于通用码、不冲用户手改；
   - SUBJECT_TYPE_CATALOG 每科都是 QUESTION_TYPE_MAP 的子集。

## 验证
- 后端 pytest 全绿（含新增）；前端 build。
- 重启后端；刷新化学/数学复核页：实验/计算/简答/解答各归其型。
- 题库筛选：选「化学」→ 题型下拉只出化学六类；选「英语」→ 出英语八类；切学科清空不兼容题型。

## git
- 全绿后一次提交。

## 明确不做（本计划外）
- 篇章题小题拆分、听力选项补全、空答案回填 —— 属识别管线/Phase 2。
