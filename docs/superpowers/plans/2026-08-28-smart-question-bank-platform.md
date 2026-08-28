# 智能题库讲义制作平台 V1.0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建家教老师可用的智能题库讲义制作平台，V1.0 验收标准：**初高中物理 PDF 题库工作流完整跑通**。

**Architecture:** FastAPI 后端（单进程 serve 前端静态文件）+ Vue 3 SPA，SQLite + Alembic，OCR 通过 adapter 调用独立 package（不改源码），Markdown canonical 内容模型，WeasyPrint 导出 PDF（待 Phase 0 Spike 验证）。

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy / Alembic / Vue 3 / Vite / Element Plus / md-editor-v3 / vuedraggable / KaTeX / WeasyPrint / python-docx / PyMuPDF / RapidOCR

**Spec:** `docs/superpowers/specs/2026-08-28-smart-question-bank-platform-design.md`

## Global Constraints

- Python >= 3.10，所有数据存储在 `data/` 目录
- **OCR 不改源码**：`packages/physics_paper_splitter/` 保持独立，平台只写 adapter
- **Markdown canonical**：Question.content 是 Markdown（含内联图片 `![](asset://path)` + LaTeX `$...$`），不用 TipTap
- **Soft delete**：Question 删除只标记 is_deleted，HandoutItem 存 question_snapshot
- **raw_ocr_content**：永远保留 OCR 原始输出，用户编辑只修改 content
- **AI 三种模式**：OFF / Local / Remote；LLM 只返回 tag_id，不自由生成 taxonomy
- **API Key 脱敏**：GET 返回 masked_key，不传 key 保留原值
- **单进程部署**：FastAPI serve `frontend/dist/`，用户只需 `start.bat`
- **Alembic**：所有 DB schema 变更通过 migration
- **V1.0 验收只验物理**，架构保持学科无关

## 构建流程

每个 Task 走同一个验收循环：

```
① 页面跑起来（UI 骨架，浏览器能看到）
  → ② 加入表单（交互、数据绑定）
  → ③ 接入存储（后端 API + 数据库）
  → ④ 跑验收（全流程走通，数据正确）
  → ⑤ commit（存档点）
```

## 文件结构总览

```
packages/
└── physics_paper_splitter/        # OCR 原封不动复制，不改源码
    ├── pipeline.py
    ├── models.py
    └── ...
backend/
├── app/
│   ├── main.py                    # FastAPI 入口 + serve frontend/dist/
│   ├── config.py                  # 路径配置（AI 配置存 DB）
│   ├── database.py                # SQLAlchemy async engine + session
│   ├── models/                    # Source, Question, Tag, Handout, HandoutItem, Settings, Job
│   ├── schemas/                   # Pydantic 请求/响应 schema
│   ├── routers/                   # upload, questions, tags, review, handouts, settings, jobs
│   ├── services/                  # ocr_adapter, pdf_export, word_export, ai_service
│   └── init_tags.py               # 预设标签初始化
├── alembic/                       # DB migration
├── templates/                     # Jinja2 HTML 模板（PDF 导出）
├── tests/
├── requirements.txt
└── pyproject.toml
frontend/
├── src/
│   ├── App.vue                    # 侧边栏布局（6 个菜单）
│   ├── router/index.js            # 6 个路由
│   ├── stores/                    # Pinia: questions, tags, handouts, settings
│   ├── api/index.js               # Axios 封装
│   ├── components/                # QuestionCard, TagSelector, DragList, MarkdownEditor
│   └── views/                     # Upload, Review, Library, Handout, Tag, Settings
├── package.json
└── vite.config.js
test_data/                         # OCR 回归测试用
├── paper01.pdf
└── expected/
data/                              # 运行时创建（db, uploads, ocr_output, exports）
setup.bat / start.bat
```

---

## Phase 0 — Architecture Lock / Risk Spike

**目标：** 在写任何业务代码之前，钉死五个最危险的契约。全部 PASS 才进入 Phase 1。

### Task 1: Schema 冻结 + Alembic 就绪

**目标：** Question/Tag/Source 等核心模型定义完成，Alembic migration 能跑通

- [ ] 创建 `backend/requirements.txt`（fastapi, uvicorn, sqlalchemy[asyncio], aiosqlite, alembic, pydantic-settings, python-multipart, httpx, pytest, pytest-asyncio）
- [ ] 创建 `backend/app/config.py` — BASE_DIR, DATA_DIR, UPLOAD_DIR, OCR_OUTPUT_DIR, EXPORT_DIR, DB_PATH，自动创建目录
- [ ] 创建 `backend/app/database.py` — async engine + session + Base
- [ ] 创建 `backend/app/models/` — source.py, question.py, tag.py, handout.py, settings.py, job.py + `__init__.py`
  - Question: `raw_ocr_content`, `content`(Markdown canonical), `options: Mapped[list]`, `is_deleted`, `deleted_at`
  - HandoutItem: `question_snapshot: Mapped[dict]`
  - Settings: `ai_mode`(off/local/remote), `ai_api_key`, `ai_base_url`, `ai_model`, `ai_temperature`
  - Job: `job_type`, `status`(queued/running/success/failed/cancelled), `progress`, `error_message`
- [ ] 初始化 Alembic：`alembic init alembic`，配置 `env.py` 使用 async engine
- [ ] 第一次 migration：`alembic revision --autogenerate -m "initial schema"`
- [ ] 创建 `backend/tests/test_models.py` — 验证所有表创建、关联、soft delete
- [ ] 验证：`alembic upgrade head` + `pytest` 全部 PASS

**验收：** DB schema 正确，migration 可跑通 ✅
- [ ] `git commit -m "feat: schema freeze + alembic"`

---

### Task 2: Export Spike — PDF 公式链路验证

**目标：** 验证 WeasyPrint 能否稳定生成含中文+公式+图片的 PDF

- [ ] 创建 `backend/tests/test_export_spike.py`
- [ ] 写一页测试 HTML，包含：
  - 中文 + 英文混排
  - 行内公式 `$F=ma$`
  - 行间公式 `$$\frac{1}{2}mv^2$$`
  - 分数、根号、上下标
  - 物理插图（`<img>` 本地路径）
  - 表格
  - 选择题（A/B/C/D 排列）
- [ ] 方案 A：直接 Jinja2 → HTML → WeasyPrint → PDF（测试 WeasyPrint 对 LaTeX 的处理）
- [ ] 方案 B：KaTeX 预渲染 → SVG 内联 → WeasyPrint → PDF
- [ ] 方案 C（如需）：Playwright 渲染 KaTeX → 抓取 SVG → WeasyPrint
- [ ] 对比三种方案的 PDF 输出质量
- [ ] 记录决策：选择哪种方案，写入 spec 或 ADR

**验收：** 至少一种方案能生成可接受的 PDF（中文正常、公式可见、图片显示） ✅
- [ ] `git commit -m "spike: export technology decision"`

---

### Task 3: OCR Adapter + 回归测试

**目标：** OCR adapter 层就绪，回归测试 baseline 建立

- [ ] 复制 `D:\家教\讲义_OCR\physics-paper-splitter` → `packages/physics_paper_splitter/`（**不改源码**）
- [ ] 配置 Python path：`pyproject.toml` 中添加 `packages/` 或 `sys.path.insert`
- [ ] 创建 `backend/app/services/ocr_adapter.py`：
  ```python
  class OCRAdapter:
      def process_pdf(self, pdf_path, output_dir) -> list[QuestionData]:
          # 调用 SplitPipeline，转换为平台 Question 格式
          # 输出 Markdown canonical（图片内联 ![](asset://path)）
  ```
- [ ] 验证：`python -c "from physics_paper_splitter import SplitPipeline; print('OK')"`
- [ ] 从 40 份已验证试卷中选 10 份，建立 `test_data/` golden corpus
- [ ] 编写回归测试：切分数量、边界、漏题/重复题检查
- [ ] 将 OCR 依赖加入 requirements.txt（PyMuPDF, Pillow, opencv-python, rapidocr-onnxruntime）

**验收：** OCR import OK + adapter 可调用 + 回归测试 baseline 建立 ✅
- [ ] `git commit -m "feat: OCR adapter + regression baseline"`

---

### Phase 0 Gate

> **STOP. 检查三件事：**
> 1. Alembic migration 跑通，所有表正确创建
> 2. PDF 至少一种方案能输出中文+公式+图片
> 3. OCR adapter 能处理一份物理 PDF，回归测试 baseline 记录
>
> **全部 PASS → 进入 Phase 1。任何 FAIL → 先解决。**

---

## Phase 1 — 最小 Vertical Slice

**目标：** 一份物理 PDF → OCR → 入库 → 复核 → 选 3 题 → 讲义 → PDF 导出。**端到端跑通，哪怕只有 3 道题。**

### Task 4: 项目初始化 + 上传流程

**① 页面跑起来：**
- [ ] 创建 `frontend/package.json`（vue 3.5, vue-router 4, pinia 2, axios, element-plus, vuedraggable, md-editor-v3, katex, markdown-it-katex, vite, sass）
- [ ] 创建 `frontend/vite.config.js` — port 3000, proxy `/api` → 8000
- [ ] 创建 `src/main.js` + `src/App.vue`（侧边栏 6 菜单：上传/复核/题库/讲义/标签/设置）
- [ ] 创建 `src/router/index.js`（6 路由）+ 6 个占位 View
- [ ] 创建 `backend/app/main.py` — FastAPI 入口，CORS，lifespan 初始化 Alembic 检查 + 预设标签
- [ ] 验证：后端 `/api/health` 返回 ok + 前端侧边栏显示

**② 加入表单：**
- [ ] UploadView — el-upload 拖拽区 + 学科选择 + 处理队列表格 + 进度轮询

**③ 接入存储：**
- [ ] `backend/app/schemas/source.py` — SourceCreate, SourceResponse
- [ ] `backend/app/routers/upload.py` — `POST /api/upload`（保存文件 → 创建 Job → 后台调 OCR Adapter → 写入 Question）
- [ ] `GET /api/sources`、`DELETE /api/sources/{id}`
- [ ] `GET /api/jobs`、`GET /api/jobs/{id}` — Job 进度查询
- [ ] `frontend/src/api/index.js` — axios 封装

**④ 跑验收：**
- [ ] 上传一份物理 PDF → 等待 OCR → 数据库 questions 表有记录 → 前端显示题目数

**⑤ commit：**
- [ ] `git commit -m "feat: upload + OCR flow (vertical slice step 1)"`

---

### Task 5: 复核流程（含 merge/split/recrop）

**① 页面跑起来：**
- [ ] ReviewView — 待复核题目列表，按 ocr_confidence 升序

**② 加入表单：**
- [ ] 每题：左侧题卡图片 + 右侧 Markdown 编辑器（md-editor-v3，编辑 content）
- [ ] 低置信度高亮标红
- [ ] 基础操作：通过 / 手动编辑保存 / 废弃 / 全部通过
- [ ] **异常修复操作：**
  - 合并上一题 / 合并下一题按钮
  - 拆分按钮（选中文本区域 → 拆为两题）
  - 重新裁切（在图片上框选区域 → 替换当前题卡）
  - 调整题号

**③ 接入存储：**
- [ ] `backend/app/schemas/question.py` — QuestionUpdate, QuestionResponse
- [ ] `backend/app/routers/review.py` — approve, approve-all, edit
- [ ] `backend/app/routers/questions.py` — merge, split, recrop, renumber
- [ ] 编辑时：只更新 `content`，`raw_ocr_content` 不变

**④ 跑验收：**
- [ ] 上传 PDF → 复核页看到待复核题 → 编辑内容 → 通过 → 状态变 approved
- [ ] 模拟两题被切错 → 合并 → 成功

**⑤ commit：**
- [ ] `git commit -m "feat: review flow with merge/split/recrop"`

---

### Task 6: 最小讲义 + PDF 导出

**① 页面跑起来：**
- [ ] HandoutView — 讲义列表 + 条目编排区 + 导出按钮

**② 加入表单：**
- [ ] 新建讲义：标题 + 学科 + 学生画像
- [ ] 从题库选 3 题加入讲义
- [ ] DragList 组件（vuedraggable）拖拽排序
- [ ] 导出选项：PDF 学生版/教师版

**③ 接入存储：**
- [ ] `backend/app/schemas/handout.py`
- [ ] `backend/app/routers/handouts.py` — 讲义 CRUD + items（add/reorder/remove）
- [ ] 添加题目时自动创建 `question_snapshot`
- [ ] `backend/templates/handout.html` — Jinja2 模板
- [ ] `backend/app/services/pdf_export.py` — 使用 Task 2 Spike 验证的方案
- [ ] `POST /api/handouts/{id}/export`

**④ 跑验收：**
- [ ] 创建讲义 → 选 3 题 → 拖拽排序 → 导出 PDF 学生版（无答案）→ 教师版（含答案）→ 内容正确

**⑤ commit：**
- [ ] `git commit -m "feat: minimum handout + PDF export (vertical slice COMPLETE)"`

---

### Phase 1 Gate

> **STOP. 端到端验证：**
> 1. 上传一份物理 PDF → OCR 自动切题 → 题目入库
> 2. 复核页查看 → 编辑/通过 → 状态正确
> 3. 选 3 题创建讲义 → 拖拽排序 → 导出 PDF
> 4. PDF 中文正常、公式可见、图片显示
>
> **全部 PASS → 核心流程已跑通。进入 Phase 2 扩展能力。**

---

## Phase 2 — 题库能力

### Task 7: 题库浏览 + 搜索 + 筛选

**① 页面跑起来：**
- [ ] LibraryView — 卡片网格布局

**② 加入表单：**
- [ ] 顶部搜索框 + 结构化筛选（subject/difficulty/question_type 下拉）+ Tag 多选
- [ ] QuestionCard 组件：题号/类型/难度/知识点标签/缩略图
- [ ] 勾选卡片 → "已选 N 题" → "加入讲义"
- [ ] 点击卡片 → 编辑详情（Markdown 编辑器）

**③ 接入存储：**
- [ ] Questions API 补全筛选参数 + 全文搜索
- [ ] `POST /api/questions/batch-tag`
- [ ] Pinia questions store

**④ 跑验收：**
- [ ] 题库页看到所有题 → 按"物理+选择题"筛选 → 勾选 3 题打标签 → 标签生效

**⑤ commit：**
- [ ] `git commit -m "feat: library browse + filter + search"`

---

### Task 8: 标签管理

**① 页面跑起来：**
- [ ] TagView — 按 category（knowledge/skill/error_type/custom）分组

**② 加入表单：**
- [ ] el-tree 展示标签层级 + 新增/编辑/删除
- [ ] TagSelector 复用组件

**③ 接入存储：**
- [ ] `backend/app/schemas/tag.py` + `backend/app/routers/tags.py`
- [ ] `backend/app/init_tags.py` — 预设物理知识点标签树
- [ ] Pinia tags store

**④ 跑验收：**
- [ ] 新增"牛顿定律"标签 → 标签树更新 → 题库筛选器能看到 → 题目可关联

**⑤ commit：**
- [ ] `git commit -m "feat: tag management"`

---

## Phase 3 — 完整讲义编辑器

### Task 9: 讲义完整版 — section/note/example/exercise

**① 页面跑起来：**
- [ ] HandoutView 升级 — 左侧结构树 + 中间编辑区 + 右侧 AI 面板（占位）

**② 加入表单：**
- [ ] 条目类型完整：section_title / knowledge_note / example(question) / exercise(question)
- [ ] knowledge_note 用 Markdown 编辑器编辑
- [ ] 每个条目的 show_answer 切换
- [ ] 讲义配置：has_answer_section, has_knowledge_summary

**③ 接入存储：**
- [ ] HandoutItem 的 custom_content 支持 Markdown
- [ ] 讲义 config JSON 字段

**④ 跑验收：**
- [ ] 创建讲义 → 添加章节标题 → 添加知识讲解(Markdown) → 添加例题+练习 → 拖拽排序 → 导出 PDF

**⑤ commit：**
- [ ] `git commit -m "feat: full handout editor"`

---

### Task 10: 设置页面

**① 页面跑起来：**
- [ ] SettingsView — AI 模式切换（OFF/Local/Remote）

**② 加入表单：**
- [ ] Remote 模式：API Key 密码框（脱敏显示）+ Base URL + 模型名 + Temperature 滑块
- [ ] "测试连接"按钮
- [ ] 保存按钮（不传 key → 保留原 key）

**③ 接入存储：**
- [ ] `backend/app/routers/settings.py` — GET/PUT /api/settings, POST /api/settings/test
- [ ] Settings 模型（详见 Task 1）
- [ ] API Key 脱敏逻辑

**④ 跑验收：**
- [ ] 设置 OFF → 无 AI 功能 → 设置 Remote + 填 Key → 测试连接成功

**⑤ commit：**
- [ ] `git commit -m "feat: settings page"`

---

## Phase 4 — AI 集成

### Task 11: AI 服务 + 辅助讲义制作

**① 页面跑起来：**
- [ ] HandoutView 右侧 AI 面板：输入学生特点 → 生成建议 → 采纳

**② 加入表单：**
- [ ] 三个 action 按钮：建议结构 / 推荐题目 / 生成教学备注
- [ ] AI 返回结果展示 + "采纳"按钮

**③ 接入存储：**
- [ ] `backend/app/services/ai_service.py` — 从 DB 读配置，httpx 调用 OpenAI 兼容 API
- [ ] AI 模式检查：OFF → 返回错误；Local → localhost；Remote → 用户配置的 URL
- [ ] `recommend_questions`：先 SQLite 本地筛选 50 题 → LLM rerank
- [ ] `suggest_structure`：LLM 返回 tag_id 序列（不是自由文本）
- [ ] `generate_notes`：生成 Markdown 格式的教学内容
- [ ] `POST /api/handouts/{id}/ai-generate`

**④ 跑验收：**
- [ ] 设置 API Key → 讲义页"推荐题目"→ 返回 5 题 + 理由 → 采纳后加入讲义

**⑤ commit：**
- [ ] `git commit -m "feat: AI integration"`

---

### Task 12: AI 辅助录题

- [ ] OCR 完成后自动触发（Job 链式调用）：
  - AI 标注知识点 → 返回 tag_id（从现有 taxonomy 中选）
  - AI 评估难度 1-5
  - AI 确认题型
- [ ] 复核页显示 AI 建议（低置信度题目标黄）
- [ ] 人工确认后生效

**验收：** OCR → AI 自动标注 → 复核页显示建议 → 确认 → 标签入库 ✅
- [ ] `git commit -m "feat: AI-assisted question tagging"`

---

## Phase 5 — Word 导出

### Task 13: Word 导出

- [ ] `backend/app/services/word_export.py` — python-docx 生成 .docx
- [ ] 学生版：题干 + 留白
- [ ] 教师版：题干 + 答案 + 解析
- [ ] 公式：简单 OMML 转换，复杂降级为图片
- [ ] `POST /api/handouts/{id}/export` 支持 format=docx

**验收：** 讲义导出 Word 学生版+教师版 ✅
- [ ] `git commit -m "feat: Word export"`

---

## Phase 6 — 部署

### Task 14: 一键部署脚本

- [ ] 创建 `setup.bat`：
  1. 创建 Python venv
  2. pip install -r requirements.txt
  3. npm install（仅开发需要）
  4. npm run build → frontend/dist/
  5. alembic upgrade head
  6. 创建 data/ 子目录
- [ ] 创建 `start.bat`：
  1. 激活 venv
  2. uvicorn app.main:app --port 8000（serve frontend/dist/ + /api）
  3. 自动打开浏览器 http://localhost:8000
- [ ] `backend/app/main.py` 添加 serve 静态文件：`app.mount("/", StaticFiles(directory="frontend/dist", html=True))`
- [ ] 验证：全新环境 setup → start → 浏览器全流程走通

**验收：** 双击 bat 即可使用 ✅
- [ ] `git commit -m "feat: deployment scripts"`

---

## 任务总览

| Phase | Task | 功能 | 验收标准 |
|-------|------|------|---------|
| **0** | 1 | Schema + Alembic | DB 表正确，migration 可跑通 |
| **0** | 2 | **Export Spike** | **PDF 能输出中文+公式+图片** |
| **0** | 3 | OCR Adapter + 回归 | adapter 可调用 + baseline 建立 |
| | | **Phase 0 Gate: 三件事全 PASS** | |
| **1** | 4 | 上传 + OCR 流程 | PDF → OCR → 题目入库 |
| **1** | 5 | 复核（含 merge/split） | 复核 → 编辑/合并/拆分 → 状态更新 |
| **1** | 6 | 最小讲义 + PDF | 3 题 → 讲义 → PDF 导出 |
| | | **Phase 1 Gate: 端到端跑通** | |
| **2** | 7 | 题库浏览 + 搜索 | 筛选/编辑/批量标签 |
| **2** | 8 | 标签管理 | 新增/编辑/树形 |
| **3** | 9 | 完整讲义编辑器 | section/note/example/exercise |
| **3** | 10 | 设置页面 | AI 配置 + 脱敏 |
| **4** | 11 | AI 辅助讲义 | 推荐题目 + 生成备注 |
| **4** | 12 | AI 辅助录题 | 自动标注 + 人工确认 |
| **5** | 13 | Word 导出 | docx 学生版+教师版 |
| **6** | 14 | 部署脚本 | setup+start 双击跑 |
