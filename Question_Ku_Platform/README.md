# 智能题库讲义制作平台

把试卷 PDF 变成可编辑的题库，再组成练习册导出 Word / PDF。

整条链路：**导入试卷 → 识别切题 → 人工复核 → 题库管理 → 选题组卷 → 所见即所得编辑 → 导出**。

## 功能

- **三条识别通道**（按文档形态选）：
  - `本地 OCR`：RapidOCR 本地引擎，补扫描页文字层，零外部依赖
  - `大模型`：VLM 整页转写 + 判题边界 + 逐题结构化 + 答案归一
  - `MinerU`：mineru.net 版面解析（矢量图/表格也能拿到），复用同一条识别管线
- **确定性质检**：行覆盖率审计、题号连续性、区间重叠/首行题号校验——几何事实零模型成本
- **复核工作台**：渲染预览与编辑二选一、批量确认、剔除/恢复、三源答案冲突仲裁
- **练习编辑器**：Tiptap 所见即所得（公式 KaTeX、并排图、答题留白），整册编排，右侧 PDF 实时预览
- **导出**：Word（公式转 OMML 原生公式）与 PDF（Playwright 渲染），页眉页脚/纸张方向可配

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI + SQLAlchemy(async) + SQLite + Alembic |
| 识别 | PyMuPDF + RapidOCR + OpenAI 兼容 VLM + MinerU API |
| 前端 | Vue 3 + Vite + Element Plus + Tiptap |
| 渲染 | Playwright（Chromium）+ KaTeX + pymupdf |

## 快速开始

```bat
:: 1. 安装依赖（Python 虚拟环境 + 前端依赖）
setup.bat

:: 2. 启动（后端 :8000，自动开浏览器）
start.bat

:: 前端开发模式（可选，代理到 :8001，见 vite.config.js）
cd frontend && npm run dev
```

渲染 PDF 预览/导出需要 Chromium：

```
venv\Scripts\python -m playwright install chromium
```

## 测试

```bat
venv\Scripts\activate
cd backend
python -m pytest
```

golden 语料回归（MinerU 通道，需要 Token）：

```
python -m scripts.mineru_extract            :: 全部样卷
python -m scripts.mineru_extract --reuse    :: 离线重放已有结果包
```

## 目录结构

```
backend/          FastAPI 应用（app/routers services models）+ Alembic 迁移 + 测试
frontend/         Vue 3 应用（Vite），构建产物 dist/ 由后端静态托管
packages/         physics_paper_splitter：切题/裁卡/审计算法（OCR 包，源码零改动约定）
test_data/        测试样卷 PDF + golden 验收语料（expected/）
docs/             设计文档与实施计划
data/             运行时数据（数据库、上传件、识别产物）——不入库
```

## 注意

- `data/db.sqlite3` 存有 API Key 等凭据，**已在 .gitignore 排除**，切勿手动加入版本库
- API Key / MinerU Token 在「系统设置」页填写，存本地库，不随仓库分发
- 访客部署：设置页自行填写自己的 Key（部署包不含任何凭据）
