# 智能题库讲义制作平台 — 设计文档

> **版本**：v1.1（红队审查修订版）  
> **日期**：2026-08-28  
> **状态**：已审查，契约已冻结

---

## 一、产品定位

面向家教老师的个人备课工具，核心价值：**从试卷到讲义的全流程提效**。

用户上传试卷 PDF → OCR 自动切题 → 人工复核 → 题目变成可编辑卡片 → 打标签 → 基于标签 + 学生特点，AI 辅助生成讲义 → 导出 PDF / Word。

### 关键约束

- **用户**：家教老师（个人使用）
- **低门槛**：浏览器打开即用，不要求用户安装额外软件
- **数据本地**：所有持久化数据存储在本地磁盘；AI 功能可选联网，启用远程模型时仅将当前任务所需内容发送至用户配置的 API
- **学科**：架构支持任意学科，**V1.0 验收只验物理**（初高中物理 PDF 题库工作流完整跑通）
- **V1.0 目标**：一份物理 PDF → OCR → 复核 → 题库 → 讲义 → PDF 导出，全流程端到端可用

### 已有资产

| 资产 | 位置 | 说明 |
|------|------|------|
| OCR 切题系统 | `D:\家教\讲义_OCR\physics-paper-splitter` | 切分准确率 98.8%，40 份试卷验证 |
| 讲义生成 Skill | `github.com/potergh/build-tutoring-handout` | LaTeX 模板 + 教学经验访谈 + 双版本输出 |

---

## 二、整体架构

```
用户浏览器（Vue 3 SPA）
    ↕  REST API (JSON)
FastAPI 后端（单进程，同时 serve 前端静态文件）
    ├── OCR Adapter（调用 packages/physics-paper-splitter，不改源码）
    ├── PDF 导出（Export Spike 验证后确定方案）
    ├── Word 导出（python-docx，纯 Python，V1.1 优先级低于 PDF）
    └── AI 服务（可选联网，LLM API 调用）
SQLite 数据库（Alembic migration）+ 本地文件存储
```

### 技术选型

| 层 | 技术 | 理由 |
|---|------|------|
| **后端** | FastAPI + Python | 与 OCR 系统同语言，直接复用 |
| **前端** | Vue 3 + Vite + Element Plus | 拖拽/编辑器组件生态成熟 |
| **数据库** | SQLite + SQLAlchemy + Alembic | 零运维 + schema 迁移能力 |
| **PDF 导出** | Phase 0 Spike 验证后确定（WeasyPrint 或 Playwright+WeasyPrint） | 必须先验证中文+公式+图片链路 |
| **Word 导出** | python-docx | 纯 Python，V1.1 优先级低于 PDF |
| **公式渲染** | KaTeX（前端）；PDF 导出待 Spike 验证 | 浏览器和 PDF 均支持 |
| **富文本编辑** | **V1 用 Markdown 编辑器**（md-editor-v3 + KaTeX） | 避免 Markdown↔TipTap JSON 转换地狱 |
| **拖拽排序** | vuedraggable | 成熟稳定 |
| **部署** | 一键脚本，**单进程**（FastAPI serve 静态文件） | 用户只需 Python |

---

## 三、项目结构

```
d:\家教\Question_Ku_Platform\
├── packages/
│   └── physics_paper_splitter/        # OCR 原封不动复制，不改源码
│       ├── pipeline.py
│       ├── splitter.py
│       ├── cropper.py
│       ├── inspector.py
│       ├── answers.py
│       ├── figures.py
│       ├── quality.py
│       ├── models.py
│       └── ocr/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI 入口 + serve 静态文件
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/                    # Source, Question, Tag, Handout, HandoutItem, Settings, Job
│   │   ├── schemas/
│   │   ├── routers/                   # upload, questions, tags, review, handouts, settings
│   │   ├── services/
│   │   │   ├── ocr_adapter.py         # OCR 适配层（调用 packages/，输出转 Question）
│   │   │   ├── pdf_export.py          # 待 Phase 0 Spike 确定方案
│   │   │   ├── word_export.py
│   │   │   └── ai_service.py
│   │   └── init_tags.py
│   ├── alembic/                       # DB migration
│   ├── tests/
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.vue                    # 侧边栏布局
│   │   ├── router/index.js
│   │   ├── stores/
│   │   ├── views/                     # Upload, Review, Library, Handout, Tag, Settings
│   │   ├── components/                # QuestionCard, TagSelector, DragList, MarkdownEditor
│   │   └── api/
│   ├── package.json
│   └── vite.config.js
├── test_data/                         # OCR 回归测试用试卷 + 期望结果
│   ├── paper01.pdf
│   └── expected/
├── data/                              # 运行时创建
│   ├── db.sqlite3
│   ├── uploads/
│   ├── ocr_output/
│   └── exports/
├── setup.bat                           # pip install + npm run build（一次性）
├── start.bat                           # uvicorn（单进程）→ 打开浏览器
└── docs/

---

## 四、数据模型

### 4.1 ER 关系

```
Source  1:N  →  Question  N:M  ↔  Tag
Handout  1:N  →  HandoutItem  N:1  →  Question（可选）
```

### 4.2 Source（试卷来源）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| filename | str | 原始文件名 |
| file_path | str | 本地存储路径（data/uploads/） |
| file_type | str | pdf / word / ppt / latex / txt |
| subject | str | 学科（自动推断或手动指定） |
| ocr_status | enum | pending / processing / done / error |
| ocr_result_path | str | OCR 输出目录路径 |
| question_count | int | 切出的题目数 |
| review_count | int | 需复核的题目数 |
| created_at | datetime | 上传时间 |

### 4.3 Question（题目卡片）— 核心实体

**内容模型决策：Markdown canonical。** 题干内容用 Markdown 存储，图片内联 `![fig](asset://path)`，公式用 `$...$`。这样图片位置直接保留在正文中，避免 `stem + figures[]` 无法恢复顺序的问题。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| source_id | FK → Source | 来源试卷 |
| source_question_id | str | OCR 原始 ID（如 `河北区一模_Q001`） |
| question_number | int | 原题号 |
| question_type | str | 选择题 / 填空题 / 解答题 / 实验题 / ...（**结构化列，不用 Tag**） |
| subject | str | 学科（**结构化列，不用 Tag**） |
| difficulty | int | 难度 1-5（**结构化列，不用 Tag**） |
| grade | str | 年级（如"高一""高三"） |
| raw_ocr_content | text | **OCR 原始输出，永远不覆盖**（用于评估/对比/重新 OCR） |
| content | text | **题干正文（Markdown canonical）**，含内联图片 `![](asset://path)` 和 LaTeX `$...$` |
| options | json | 选项列表 `[{"label": "A", "content": "..."}]` |
| answer | text | 答案（Markdown） |
| explanation | text | 解析（Markdown） |
| score | float | 分值 |
| card_image_path | str | 题卡图片路径（webp） |
| needs_review | bool | 是否需要人工复核 |
| review_status | enum | pending / approved / edited |
| ocr_confidence | float | OCR 置信度 |
| is_deleted | bool | **Soft delete 标记**（默认 false） |
| deleted_at | datetime | 删除时间（nullable） |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 最后编辑时间 |

**关键设计决策：**
- `raw_ocr_content` 永远保留 OCR 原始输出，用户编辑只修改 `content`。用于评估 OCR 质量、重新 OCR 对比。
- `content` 是 Markdown canonical，图片位置内联，不再单独存 `figures` 列表。
- `knowledge_points` JSON 字段删除——知识点通过 Tag N:M 关联，避免"两个真相"。
- `subject`/`difficulty`/`question_type` 是结构化列，Tag 不承担这些职责。
- **Soft delete**：删除题目只标记 `is_deleted=true`，已关联的讲义仍可打开。

### 4.4 Tag（标签）

Tag **只负责**知识点、技能、错误类型、自定义标签。学科/难度/题型是 Question 的结构化列，不通过 Tag 管理（避免"两个真相"）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| name | str | 标签名 |
| category | str | **knowledge / skill / error_type / custom**（不再含 subject/difficulty/type） |
| color | str | 显示颜色 |
| parent_id | FK → Tag（nullable） | 父标签，支持层级 |

### 4.5 Question ↔ Tag（多对多）

| 字段 | 类型 | 说明 |
|------|------|------|
| question_id | FK → Question | |
| tag_id | FK → Tag | |

### 4.6 Handout（讲义）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| title | str | 讲义标题 |
| subject | str | 学科 |
| target_student | json | 学生画像 `{"grade", "weaknesses", "focus_areas", "notes"}` |
| teaching_notes | text | 教学备注 |
| status | enum | draft / ready / exported |
| config | json | 讲义配置 `{"has_answer_section", "has_knowledge_summary"}` |
| created_at | datetime | |
| updated_at | datetime | |

### 4.7 HandoutItem（讲义条目）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| handout_id | FK → Handout | 所属讲义 |
| order | int | 排列顺序 |
| item_type | enum | question / knowledge_note / example / exercise / section_title |
| question_id | FK → Question（nullable） | 关联题目（纯笔记条目为空） |
| question_snapshot | json | **题目快照**（创建时复制 content/options/answer），防止原题修改后历史讲义变化 |
| custom_content | text | 自定义内容 |
| show_answer | bool | 教师版是否显示答案 |
| config | json | 条目级配置 |

**关键决策：** `question_snapshot` 在添加条目时从 Question 复制关键字段。即使原题被编辑或删除，历史讲义内容不变。

### 4.8 Job（异步任务跟踪）

程序崩溃时防止任务永远卡住。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| job_type | enum | ocr / ai_generate / export |
| status | enum | queued / running / success / failed / cancelled |
| progress | float | 进度 0-100 |
| source_id | FK（nullable） | 关联的 Source |
| handout_id | FK（nullable） | 关联的 Handout |
| error_message | text | 错误信息 |
| created_at | datetime | 创建时间 |
| started_at | datetime | 开始时间 |
| finished_at | datetime | 完成时间 |

启动时检查：`status=running` 但进程已死 → 标记为 `failed`。

### 4.9 Settings（系统设置）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键（单行记录） |
| ai_mode | enum | **off / local / remote**（三种模式） |
| ai_api_key | str | API 密钥（**API 返回时脱敏：`sk-****xyz`**） |
| ai_base_url | str | API 地址 |
| ai_model | str | 模型名称 |
| ai_temperature | float | 温度参数 0-1 |

- `GET /api/settings` 返回 `api_key_set: true/false` + `masked_key`，不返回完整密钥
- 更新时不传 key → 保留原 key

### 4.10 预设标签体系

Tag 只负责知识点/技能/错误类型/自定义。学科、难度、题型是 Question 的结构化列。

```
knowledge（知识点）：按学科分层树形结构
  物理 → 力学 → 牛顿定律 / 功和能 / ...
       → 热学 / 光学 / 电学 / ...
  化学 → 物质构成 / 化学反应 / ...
  数学 → 代数 / 几何 / 函数 / ...
  英语 → 听力 / 完形 / 阅读 / 写作 / ...

skill（技能）：分析 / 计算 / 推理 / 实验 / ...
error_type（错误类型）：概念混淆 / 计算失误 / 审题不清 / ...
custom（自定义）：用户自建标签
```

---

## 五、API 设计

### 5.1 文件上传 & OCR

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 上传文件（支持多文件），触发 OCR |
| GET | `/api/sources` | 试卷来源列表 |
| GET | `/api/sources/{id}` | 单份试卷详情 |
| GET | `/api/sources/{id}/status` | OCR 处理进度 |
| DELETE | `/api/sources/{id}` | 删除试卷及所有题目 |

### 5.2 题目卡片

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/questions` | 题目列表（支持多条件筛选） |
| GET | `/api/questions/{id}` | 单题详情 |
| PUT | `/api/questions/{id}` | 编辑题目 |
| DELETE | `/api/questions/{id}` | **Soft delete**（标记 is_deleted） |
| POST | `/api/questions/{id}/approve` | 标记复核通过 |
| POST | `/api/questions/batch-tag` | 批量打标签 |
| GET | `/api/questions/search?q=...` | 全文搜索 |

### 5.2.1 复核异常修复

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/questions/{id}/merge/{other_id}` | 合并两题 |
| POST | `/api/questions/{id}/split` | 拆分一题为两题 |
| POST | `/api/questions/{id}/recrop` | 重新裁切（上传新区域） |
| PUT | `/api/questions/{id}/renumber` | 调整题号 |

### 5.3 标签

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tags` | 标签树（按 category 分组） |
| POST | `/api/tags` | 创建标签 |
| PUT | `/api/tags/{id}` | 编辑标签 |
| DELETE | `/api/tags/{id}` | 删除标签 |

### 5.4 讲义

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/handouts` | 讲义列表 |
| POST | `/api/handouts` | 创建讲义 |
| GET | `/api/handouts/{id}` | 讲义详情（含条目） |
| PUT | `/api/handouts/{id}` | 更新讲义信息 |
| DELETE | `/api/handouts/{id}` | 删除讲义 |
| POST | `/api/handouts/{id}/items` | 添加条目 |
| PUT | `/api/handouts/{id}/items/reorder` | 拖拽排序 |
| DELETE | `/api/handouts/{id}/items/{item_id}` | 移除条目 |
| POST | `/api/handouts/{id}/ai-generate` | AI 辅助生成 |
| POST | `/api/handouts/{id}/export` | 导出 PDF/Word |

### 5.5 设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 获取设置（**API Key 脱敏返回**） |
| PUT | `/api/settings` | 更新设置（不传 key → 保留原 key） |
| POST | `/api/settings/test` | 测试 AI API 连接 |

### 5.6 任务状态

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs` | 任务列表（查看 OCR/AI 进度） |
| GET | `/api/jobs/{id}` | 单个任务详情 |

### 5.7 API 设计要点

- **OCR 异步**：上传后返回 `source_id`，后台线程处理，前端轮询进度（通过 Job 表跟踪）
- **筛选**：`GET /questions?subject=物理&difficulty_gte=3&tags=牛顿定律&review_status=pending`
- **导出同步**：V1.0 讲义不长，直接等待生成后下载
- **AI 异步**：创建 Job 记录，返回任务 ID，前端轮询结果
- **Soft delete**：题目删除只标记 is_deleted，已关联讲义通过 snapshot 不受影响
- **API Key 安全**：GET 返回 `api_key_set: true/false` + `masked_key`，不返回完整密钥

---

## 六、前端页面设计

### 6.1 导航结构

6 个主页面，侧边栏导航：

1. **上传**（UploadView）— 文件上传 & OCR 处理进度
2. **复核**（ReviewView）— 人工复核 OCR 结果（有待复核时高亮）
3. **题库**（LibraryView）— 浏览、筛选、编辑题目卡片
4. **讲义**（HandoutView）— 讲义编排 & AI 辅助 & 导出
5. **标签**（TagView）— 标签管理
6. **设置**（SettingsView）— AI 配置

### 6.2 UploadView

- 拖拽上传区域，支持多文件
- 上传前选择学科
- 处理队列显示进度条
- 完成后提示需复核题目数

### 6.3 ReviewView

- 左右对照：题卡原图 vs OCR 文本
- 低置信度题目排前面、高亮标红
- 可直接编辑 OCR 文本（Markdown 编辑器）
- 支持“全部通过”批量操作
- 每道题：通过 / 手动编辑 / 废弃
- **切题异常修复（V1 必备，不是高级功能）：**
  - **合并上一题 / 合并下一题**（Q12+Q13 被切成一题时）
  - **拆分**（一道题被切成两张时）
  - **重新裁切**（图片被切掉一半时，手动选区）
  - **调整题号**
  - **替换/增加插图**

核心目标：**任何 OCR 错误都能人工救回来。**

### 6.4 LibraryView

- 卡片网格布局
- 标签筛选栏（多选组合）
- 全文搜索框
- 勾选题目后可加入讲义
- 点击卡片进入编辑详情

### 6.5 HandoutView

- 左侧：讲义结构列表（拖拽排序）
- 右侧：AI 助手面板
- 条目类型：题目引用 / 知识讲解 / 章节标题 / 例题 / 练习
- 底部导出按钮（PDF 学生版/教师版、Word）

### 6.6 SettingsView

- AI 模式切换：OFF / Local LLM / Remote LLM（三种模式）
- Remote 模式：API Key（密码框，显示脱敏）、Base URL、模型名、Temperature 滑块
- “测试连接”按钮，验证 API 是否可用
- 保存按钮（不传 key → 保留原 key）

### 6.7 前端依赖

| 库 | 用途 |
|---|------|
| Vue 3 + Composition API | 框架 |
| Vite | 构建 |
| Vue Router | 路由 |
| Pinia | 状态管理 |
| Axios | HTTP |
| Element Plus | UI 组件 |
| vuedraggable | 拖拽排序 |
| **md-editor-v3** | **Markdown 编辑器（V1 富文本编辑，替代 TipTap）** |
| KaTeX | LaTeX 公式渲染 |
| markdown-it-katex | Markdown 渲染时支持 LaTeX |

---

## 七、导出系统

> **⚠️ 待 Phase 0 Export Spike 验证后冻结方案。** 以下设计为当前最佳猜测，Spike 可能推翻。

### 7.1 PDF 导出

| 项目 | 设计 |
|------|------|
| 引擎 | WeasyPrint（HTML → PDF，纯 Python）——前提是 Spike 验证通过 |
| 模板 | Jinja2 渲染 HTML 模板 |
| 公式 | **Spike 验证两种方案：** ① Playwright 无头浏览器渲染 KaTeX → 抓取 SVG 嵌入 ② 服务端直接渲染 KaTeX → SVG 内联 |
| 图片 | Markdown 中的 `![](asset://path)` 解析为 `<img>` 引用本地路径 |
| 学生版 | 题干 + 留白答题区 |
| 教师版 | 题干 + 答案 + 解析 + 教学提示 |
| 输出 | `data/exports/{handout_id}/` |

**Spike 必须验证的清单：** 中文字体、数学公式（行内/行间）、分数/根号/上下标、物理图、表格、选择题排版、跨页、页眉页脚。

### 7.2 Word 导出（python-docx）— V1.1 优先级低于 PDF

| 项目 | 设计 |
|------|------|
| 引擎 | python-docx |
| 公式 | 简单公式 OMML 转换，复杂公式降级为图片 |
| 图片 | `add_picture()` 插入 |
| 模板 | 基础 .docx 定义样式，内容动态填充 |
| 学生版 | 题干 + 留白 |
| 教师版 | 题干 + 答案 + 解析 |

### 7.3 导出 API

```
POST /api/handouts/{id}/export
Body: {"format": "pdf|docx|both", "version": "student|teacher|both"}
Response: 单文件直接返回，多文件打包 zip
```

---

## 八、AI 集成

### 8.1 AI 模式（三种）

| 模式 | 说明 | 数据流向 |
|------|------|----------|
| **OFF** | 完全离线，不使用任何 AI 功能 | 无外部请求 |
| **Local** | 连接本地 LLM（如 Ollama） | 仅发送到 localhost |
| **Remote** | 连接用户配置的远程 API | 仅发送当前任务所需内容 |

**产品承诺：** 所有持久化数据本地存储；AI 功能可选联网，启用远程模型时仅将当前任务所需内容发送至用户配置的 API。

### 8.2 辅助录题（题目入库时）

| 触发时机 | AI 功能 | 说明 |
|----------|---------|------|
| OCR 完成 | 自动标注知识点 | 题干文本 → LLM → **返回已有 tag_id**（不是自由生成） |
| OCR 完成 | 评估难度 | LLM 判断 1-5 星 |
| OCR 完成 | 确认题型 | 补充 OCR 推断的题型 |
| 人工复核 | 建议修正 | 低置信度题目，LLM 建议修正文本 |

**关键约束：** LLM 不能自由生成知识点名字（避免 taxonomy 搞烂）。正确流程：
1. 将现有知识点 taxonomy 发给 LLM
2. LLM 只能返回 `tag_id`
3. 如果确实没有匹配的标签，返回 `{"existing_tags": [], "suggested_new_tag": "..."}`
4. 新标签需人工确认后才创建

V1.0 策略：AI 标注为建议，人工确认后生效。

### 8.3 辅助讲义制作（核心功能）

整合 `build-tutoring-handout` Skill 逻辑：

| Skill 原始步骤 | 平台化实现 |
|----------------|-----------|
| 教学经验访谈 | 创建讲义时填写学生画像表单 |
| 章节覆盖矩阵 | AI 根据标签 + 学生弱点生成覆盖建议 |
| 题库检索筛选 | **先 SQLite 本地筛选 50 题 → LLM rerank**（不把全部题库发给 LLM） |
| 例题与练习分层 | AI 区分“讲解例题”和“学生练习” |
| LaTeX 排版 | 导出时自动渲染，用户不接触 LaTeX |

### 8.4 AI API

```
POST /api/handouts/{id}/ai-generate
Body: {"action": "suggest_structure|recommend_questions|generate_notes"}

suggest_structure  → 建议讲义条目序列
recommend_questions → 推荐题目列表（含理由和优先级）
generate_notes     → 生成知识讲解 / 教学提示 / 易错点
```

### 8.5 LLM 配置

通过前端 SettingsView 管理，配置存入 SQLite `settings` 表（详见 4.9 节）。

- 设置页面提供“测试连接”按钮，验证 API 是否可用
- 支持 OpenAI 兼容 API（覆盖大部分国内外模型服务）
- API Key 脱敏返回：`sk-****xyz`
- 更新时不传 key → 保留原 key

---

## 九、部署方案

### 一键脚本（唯一部署方式）

**前提**：用户已有 Python 3.10+。

**开发模式：**
- Vue dev server :3000（热更新）
- FastAPI :8000（CORS 允许 localhost:3000）

**发布模式（用户实际使用）：**
- `npm run build` → `frontend/dist/`
- FastAPI 同时 serve `/api` 和 `/`（静态文件）
- **单进程**，用户只需 `start.bat`

**setup.bat**（首次运行）：
1. 创建 Python venv
2. 安装后端依赖（pip install）
3. 安装前端依赖（npm install）— 仅开发时需要
4. 构建前端（npm run build）— 生成 `frontend/dist/`
5. 初始化 SQLite 数据库（Alembic migration）
6. 创建 data/ 子目录

**start.bat**（日常启动）：
1. 激活 venv
2. 启动 FastAPI（uvicorn，端口 8000，serve `frontend/dist/` + `/api`）
3. 自动打开浏览器 `http://localhost:8000`

**未来可选：** PyInstaller 打包为 `QuestionBank.exe`，实现真正零依赖。

**注意：** setup.bat 需要 Node.js（仅首次构建），但用户日常使用只需 Python。可以考虑在 setup 中嵌入 Node.js 便携版下载。

---

## 十、OCR 集成（Adapter 模式）

**核心原则：OCR 已经 40 份试卷验证，切分准确率 98.8%。不改源码，只写 adapter。**

### 10.1 目录结构

```
packages/
└── physics_paper_splitter/        # OCR 原封不动复制，不改源码
    ├── pipeline.py
    ├── models.py
    └── ...

backend/
└── app/
    └── services/
        └── ocr_adapter.py         # 适配层：调 OCR → 转 Question
```

### 10.2 Adapter 层职责

```python
# ocr_adapter.py
from physics_paper_splitter import SplitPipeline

class OCRAdapter:
    def process_pdf(self, pdf_path, output_dir) -> list[QuestionData]:
        """调用 OCR pipeline，将输出转换为平台 Question 格式"""
        pipeline = SplitPipeline(...)
        result = pipeline.process(pdf_path, output_dir)
        return self._convert_to_questions(result)
```

- OCR 内部完全不知道 FastAPI / SQLite / Handout / Vue
- 平台不依赖 OCR 内部实现，只依赖其公开接口
- 以后继续改善 OCR，不会同时把题库平台改坏

### 10.3 OCR 回归测试

利用已有的 40 份验证过的试卷，建立 golden regression corpus：

```
test_data/
├── paper01.pdf
│   └── expected/
│       ├── question_count.json
│       ├── boundaries.json
│       └── questions.json
└── ...
```

每次 OCR 改动后跑回归测试，要求：
- 切分数量不低于 baseline
- 题目边界不偏移
- 无漏题/重复题
- OCR 文本得分不低于 baseline

### 10.4 依赖管理

将 OCR 依赖加入 `backend/requirements.txt`：
- PyMuPDF >= 1.24
- Pillow >= 10
- opencv-python >= 4.9
- rapidocr-onnxruntime >= 1.3

将 `packages/` 加入 Python path（通过 `pyproject.toml` 或 `sys.path`）。

---

## 十一、数据流总览

```
用户上传 PDF
    → 保存到 data/uploads/
    → 创建 Job（status=queued）
    → 后台调用 OCR Adapter（packages/physics_paper_splitter，不改源码）
    → OCR 输出：题卡图片 + 插图 + questions.json
    → Adapter 转换为平台 Question 格式（Markdown canonical）
    → 保存到 data/ocr_output/
    → 写入 SQLite（Source + Question + Job status=success）
    → 前端展示复核队列
    → 用户复核编辑（修改 content，保留 raw_ocr_content）
    → 用户可合并/拆分/重新裁切异常题目
    → 用户在题库浏览 & 打标签（知识点通过 Tag N:M）
    → 用户创建讲义 → 选择卡片 → 拖拽排序（创建 question_snapshot）
    → AI 辅助生成讲义内容（先本地筛选 50 题 → LLM rerank）
    → 导出 PDF（待 Phase 0 Spike 验证方案）或 Word（python-docx）
    → 保存到 data/exports/
```

所有数据（数据库、上传文件、OCR 输出、导出文件）均在 `data/` 目录下，完全本地化。AI 功能可选联网，启用时仅发送当前任务所需内容。

---

## 十二、红队审查决策记录

| # | 问题 | 决策 | 影响 |
|---|------|------|------|
| 1 | Question 内容模型 | Markdown canonical，图片内联，删 figures JSON | Question 表 |
| 2 | TipTap vs Markdown | V1 用 md-editor-v3，不上 TipTap | 前端依赖 |
| 3 | PDF 公式链路矛盾 | Phase 0 Spike 先验证再决定 | 新增 Phase 0 |
| 4 | OCR 不要复制改源码 | Adapter 模式，OCR 保持独立 package | 项目结构 |
| 5 | OCR 回归测试 | Golden corpus 10-20 份试卷 | 新增 test_data/ |
| 6 | Review 缺 merge/split/recrop | V1 必备 | 新增 API + UI |
| 7 | 两个真相（difficulty vs Tag） | 结构化列 vs Tag 职责分离 | 数据模型 |
| 8 | options 类型错误 | dict → list | 数据模型 |
| 9 | 异步任务无 Job | 新增 Job 表 | 新增表 |
| 10 | “全本地”与 LLM API 矛盾 | 三种模式：OFF/Local/Remote | AI 集成 |
| 11 | API Key 安全 | 脱敏返回 + 不传保留 | Settings API |
| 12 | 部署需 npm | 单进程，FastAPI serve 静态文件 | 部署方案 |
| 13 | API contract 漂移 | 统一补全缺失 endpoints | API 设计 |
| 14 | 无 DB migration | 引入 Alembic | 基础设施 |
| 15 | 删除语义未定 | Soft delete + question_snapshot | 数据模型 |
| 16 | OCR 原文被覆盖 | 保留 raw_ocr_content | Question 表 |
| 17 | AI 自由生成 taxonomy | LLM 只返回 tag_id，新标签需人工确认 | AI 集成 |
