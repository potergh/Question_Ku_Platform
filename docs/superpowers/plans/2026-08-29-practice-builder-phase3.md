# 练习制作系统阶段三：预览与导出 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为练习提供 A4 真实分页预览（页码/缩放/全屏）与 Word / PDF 导出（仅学生版），完成规格场景三全链路。

**Architecture:** 预览与 PDF 走同一条后端渲染管线（决策 8）：`render_service` 把练习块组装成 HTML（KaTeX 本地渲染，不依赖外网），Playwright 生成 PDF，PyMuPDF 把 PDF 逐页转 PNG 供前端分页展示——预览与导出天然一致。Word 用 python-docx 从同一套块数据独立构建，保证内容结构与图片顺序一致。

**Tech Stack:** FastAPI + Playwright 1.62（chromium 已装）+ PyMuPDF（新增）+ python-docx 1.2 + Vue3/Element Plus。

**Spec:** `docs/superpowers/plans/2026-08-28-practice-builder-spec.md` §10 预览、§11 导出、场景三、决策 2/8。

## Global Constraints

- **仅学生版**：导出/预览不含答案与解析（规格 11.2，决策 2）。
- **预览与 PDF 基本一致**（10.2）：二者共用同一份 HTML + 同一个 PDF 文件。
- **Word 可继续编辑**：标准 docx 段落/图片，不用文本框拼图（10.2）。
- **零侵入题库**：渲染只读练习快照，永不写回题库（决策 3）。
- **A4 纵向**，页边距三档预设（窄 15mm / 标准 25mm / 宽 32mm），默认标准（11.3）。
- **无新数据库迁移**：所有渲染设置存已有 `practices.page_config` JSON 列。
- **渲染设置键**（存 `page_config`）：`show_info_bar`(默认 true)、`show_page_number`(默认 true)、`show_score`(默认 false)、`show_total_score`(默认 false)、`margin_preset`(narrow/normal/wide，默认 normal)。
- **块数据形态**（阶段二约定）：text 块 content 为 Markdown-lite+LaTeX 文本；image 块 content 为 `asset://practice/<name>`、style `{align,width}`；options 块 content 为选项数组的 **JSON 字符串**；answer_space 块行数在 `style.rows`。
- **环境命令**：后端测试 `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests -q`（工作目录 `backend/`）；前端构建 `cd frontend; $env:PATH = "C:\Users\Administrator\.conda\envs\question_platform;" + $env:PATH ; node node_modules/vite/bin/vite.js build`（ExitCode 1 但输出 "built in Xs" 即成功）；PowerShell 勿用 `$pid`（只读内置变量）。
- **SQLAlchemy 注意**（阶段二教训）：渲染只读数据用 `selectinload` + `.execution_options(populate_existing=True)`；服务函数内不 `commit()`，提交留给路由。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/services/render_service.py` | 新建 | 练习→HTML 组装、Playwright 出 PDF、预览缓存 |
| `backend/app/services/preview_service.py` | 新建 | PDF→分页 PNG（PyMuPDF）+ PDF 导出取件 |
| `backend/app/services/docx_export.py` | 新建 | 练习→docx 构建（python-docx，同步） |
| `backend/app/routers/practices.py` | 修改 | 追加 5 个端点：render / preview 页图 / export-pdf / export-docx；块懒物化复用 |
| `backend/app/schemas/practice.py` | 修改 | `PreviewRenderResponse` |
| `backend/requirements.txt` | 修改 | 追加 `pymupdf` |
| `backend/tests/test_render_service.py` | 新建 | HTML 组装单测（无浏览器） |
| `backend/tests/test_preview_api.py` | 新建 | render/页图/PDF 导出 API（真实 chromium） |
| `backend/tests/test_docx_export.py` | 新建 | docx 构建单测 + 导出端点 |
| `frontend/src/views/PracticeEditorView.vue` | 修改 | 右侧预览面板（分页/缩放/全屏/防抖刷新）+ 导出按钮 + 设置扩展 |

**块出参复用**：渲染直接读 ORM 对象，不经 API 出参；options 块记得 `json.loads(block.content)`。

---

### Task 1: render_service —— 练习→HTML 组装

**Files:**
- Create: `backend/app/services/render_service.py`
- Test: `backend/tests/test_render_service.py`

**Interfaces:**
- Consumes: `app.models.practice` 四个模型（调用方保证 `sections→questions→blocks` 已 selectinload）；`app.services.practice_service.practice_assets_dir`。
- Produces:
  - `render_settings(practice) -> dict`：解析 `page_config` 为 `{margin, show_info_bar, show_page_number, show_score, show_total_score}`，margin 为 CSS 长度字符串。
  - `build_practice_html(practice, practice_id) -> str`：完整独立 HTML（内联 CSS，KaTeX 占位由 `_katex_tags()` 相对引用 `katex/` 子目录）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_render_service.py
"""HTML 组装单测：不经浏览器，直接断言 HTML 文本。"""

import json

from test_blocks_api import _create_practice
from app.services.render_service import build_practice_html, render_settings


async def _full_practice(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    detail = (await client.get(f"/api/practices/{practice['id']}/detail")).json()
    return detail


async def _load_with_blocks(test_db, pid):
    """test_db 是 session 工厂；直接查测试库，勿用生产 get_db。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.practice import Practice, PracticeSection, PracticeQuestion
    async with test_db() as db:
        return (await db.execute(
            select(Practice).where(Practice.id == pid)
            .options(selectinload(Practice.sections)
                     .selectinload(PracticeSection.questions)
                     .selectinload(PracticeQuestion.blocks))
            .execution_options(populate_existing=True)
        )).scalar_one()


def test_render_settings_defaults():
    class FakePractice:
        page_config = None
    s = render_settings(FakePractice())
    assert s["margin"] == "25mm"
    assert s["show_info_bar"] is True
    assert s["show_page_number"] is True
    assert s["show_score"] is False


async def test_build_html_contains_structure(client, test_db, tmp_path):
    detail = await _full_practice(client, test_db, tmp_path)
    practice = await _load_with_blocks(test_db, detail["id"])
    html = build_practice_html(practice, detail["id"])
    assert detail["title"] in html
    assert "姓名" in html                      # 默认显示学生信息栏
    assert "1." in html                        # 题号
    assert "q-option" in html                  # 单选题必带选项块
    assert "answer-space" in html              # 留白块
    assert "katex" in html                     # KaTeX 标签


async def test_build_html_respects_page_config(client, test_db, tmp_path):
    detail = await _full_practice(client, test_db, tmp_path)
    pid = detail["id"]
    await client.put(f"/api/practices/{pid}", json={"title": detail["title"],
        "page_config": {"show_info_bar": False, "show_score": True, "margin_preset": "narrow"}})
    practice = await _load_with_blocks(test_db, pid)
    html = build_practice_html(practice, pid)
    settings = render_settings(practice)
    assert "姓名" not in html                  # 信息栏关闭
    assert settings["margin"] == "15mm"
```

注意：`test_db` 夹具是 session 工厂（见 conftest），用 `async with test_db() as db` 取会话；绝不能在测试里直接调生产 `get_db()`。

- [ ] **Step 2: 跑测试确认失败**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests/test_render_service.py -q`
Expected: FAIL（ModuleNotFoundError: render_service）

- [ ] **Step 3: 实现 render_service.py**

```python
"""Render service — 练习块 → 独立 HTML（供 Playwright 出 PDF）。"""

import html as _html
import json
import re
from pathlib import Path

from app.models.practice import Practice
from app.services import practice_service

MARGIN_PRESETS = {"narrow": "15mm", "normal": "25mm", "wide": "32mm"}


def katex_dist_dir() -> Path:
    """frontend/node_modules/katex/dist（渲染时整目录拷入临时渲染目录）。"""
    d = Path(__file__).resolve().parents[3] / "frontend" / "node_modules" / "katex" / "dist"
    if not d.exists():
        raise RuntimeError("KaTeX 未安装：请先在 frontend/ 执行 npm install")
    return d


def render_settings(practice: Practice) -> dict:
    cfg = practice.page_config or {}
    return {
        "margin": MARGIN_PRESETS.get(cfg.get("margin_preset", "normal"), "25mm"),
        "show_info_bar": cfg.get("show_info_bar", True),
        "show_page_number": cfg.get("show_page_number", True),
        "show_score": cfg.get("show_score", False),
        "show_total_score": cfg.get("show_total_score", False),
    }


def _text_to_html(text: str) -> str:
    """Markdown-lite：转义后处理加粗/换行；LaTeX 定界符原样保留交给 KaTeX。"""
    s = _html.escape(text or "")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = s.replace("\n", "<br>")
    return s


def _block_html(b, practice_id: str) -> str:
    style = b.style_config or {}
    if b.block_type == "text":
        return f'<div class="q-text">{_text_to_html(b.content)}</div>'
    if b.block_type == "image":
        name = (b.content or "").removeprefix("asset://practice/")
        src = (practice_service.practice_assets_dir(practice_id) / name).as_uri()
        align = style.get("align", "center")
        w = style.get("width", "fit")
        width_css = "max-width:100%" if w == "fit" else f"width:{w}"
        return (f'<div class="q-img" style="text-align:{align}">'
                f'<img src="{src}" style="{width_css};height:auto"></div>')
    if b.block_type == "options":
        try:
            opts = json.loads(b.content) if b.content else []
        except (TypeError, json.JSONDecodeError):
            opts = []
        rows = "".join(
            f'<div class="q-option"><span class="opt-label">{_html.escape(o.get("label", ""))}.</span>'
            f'{_text_to_html(o.get("content", ""))}</div>' for o in opts)
        return f'<div class="q-options">{rows}</div>'
    if b.block_type == "answer_space":
        rows = int(style.get("rows", 0))
        lines = '<div class="space-line"></div>' * rows
        return f'<div class="answer-space">{lines}</div>'
    return ""  # answer/explanation 块学生版不输出（规格 11.2）


def build_practice_html(practice: Practice, practice_id: str) -> str:
    """页头（标题/副标题/总分/信息栏）+ 小节（标题/分页）+ 题目。"""
    s = render_settings(practice)
    head: list[str] = [f'<div class="p-title">{_html.escape(practice.title)}</div>']
    if practice.subtitle:
        head.append(f'<div class="p-subtitle">{_html.escape(practice.subtitle)}</div>')

    total_score = 0.0
    has_score = False
    for sec in practice.sections:
        for pq in sec.questions:
            if pq.score is not None:
                total_score += pq.score
                has_score = True
    if s["show_total_score"] and has_score:
        head.append(f'<div class="p-total">满分：{total_score:g} 分</div>')
    if s["show_info_bar"]:
        head.append('<div class="info-bar">姓名：____________　班级：____________　日期：____________</div>')

    body = _section_bodies(practice, s)
    return _head_css() + '<body>' + "".join(head + body) + _katex_tags() + '</body></html>'


def _section_bodies(practice: Practice, s: dict) -> list[str]:
    out: list[str] = []
    for section in practice.sections:
        if section.start_on_new_page:
            out.append('<div class="new-page"></div>')
        if section.show_title:
            out.append(f'<div class="section-title">{_html.escape(section.title)}</div>')
        for pq in section.questions:
            blocks_html = "".join(_block_html(b, practice.id) for b in pq.blocks)
            score_txt = ""
            if s["show_score"] and pq.score is not None:
                score_txt = f'<span class="q-score">（{pq.score:g} 分）</span>'
            out.append(f'<div class="question">'
                       f'<div class="q-head">{pq.question_number}. {score_txt}</div>'
                       f'{blocks_html}</div>')
    return out


def _head_css() -> str:
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>'
            'body { font-family: "SimSun", "Microsoft YaHei", serif; font-size: 10.5pt;'
            ' line-height: 1.7; color: #000; margin: 0; }'
            '.p-title { text-align: center; font-size: 18pt; font-weight: bold; margin-bottom: 4px; }'
            '.p-subtitle { text-align: center; font-size: 12pt; color: #333; margin-bottom: 8px; }'
            '.p-total { text-align: center; font-size: 10.5pt; margin-bottom: 6px; }'
            '.info-bar { margin: 8px 0 14px; font-size: 10.5pt; }'
            '.section-title { font-weight: bold; font-size: 12pt; margin: 14px 0 8px; }'
            '.new-page { page-break-before: always; }'
            '.question { margin-bottom: 12px; }'
            '.q-text { margin: 2px 0; }'
            '.q-img img { max-height: 420px; }'
            '.q-options { margin: 4px 0 4px 2em; }'
            '.q-option { margin: 1px 0; }'
            '.opt-label { margin-right: 4px; }'
            '.q-score { font-size: 9pt; }'
            '.answer-space { margin: 4px 0; }'
            '.space-line { height: 1.9em; border-bottom: 1px solid #999; }'
            '</style></head>')


def _katex_tags() -> str:
    return ('<link rel="stylesheet" href="katex/katex.min.css">'
            '<script defer src="katex/katex.min.js"></script>'
            '<script defer src="katex/contrib/auto-render.min.js"></script>'
            '<script>window.addEventListener("DOMContentLoaded", function(){'
            'renderMathInElement(document.body, {delimiters:['
            '{left:"$$",right:"$$",display:true},{left:"\\\\[",right:"\\\\]",display:true},'
            '{left:"$",right:"$",display:false},{left:"\\\\(",right:"\\\\)",display:false}]});'
            'window.__katexDone = true;});</script>')
```

要点：
- 题目只在 `_section_bodies` 中输出一次；页头顺序 = 标题→副标题→总分→信息栏。
- `new-page` 用独立空 div 承载 `page-break-before`，与小节标题显隐解耦。
- `_text_to_html` 先转义再处理加粗，LaTeX 定界符（$ \( \) 等）都是转义安全字符，KaTeX auto-render 在浏览器内解析。
- margin 不写进 CSS，由 Playwright `page.pdf(margin=...)` 与 docx section margins 分别承载，保证两路一致。

- [ ] **Step 4: 跑测试确认通过**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests/test_render_service.py -q`
Expected: PASS（3 项）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/render_service.py backend/tests/test_render_service.py
git commit -m "feat: 渲染服务——练习块组装 A4 HTML（KaTeX/留白/分页/导出设置）"
```

---

### Task 2: 预览管线 —— Playwright 出 PDF + 分页 PNG + render/页图端点

**Files:**
- Modify: `backend/requirements.txt`（追加 pymupdf）
- Modify: `backend/app/services/render_service.py`（追加 PDF 渲染与缓存）
- Create: `backend/app/services/preview_service.py`
- Modify: `backend/app/schemas/practice.py`（`PreviewRenderResponse`）
- Modify: `backend/app/routers/practices.py`（`POST /render`、`GET /preview/page/{index}`、`_load_practice_full_for_render` helper）
- Test: `backend/tests/test_preview_api.py`

**Interfaces:**
- Consumes: Task 1 全部产出；`block_service.materialize_blocks`（懒物化，阶段二）。
- Produces:
  - `render_service.render_pdf_bytes(html, settings) -> bytes`（Playwright，异步）。
  - `render_service.ensure_preview_pdf(practice_id, html, settings) -> tuple[Path, str, int]`：缓存于 `data/practices/<id>/preview.pdf` + `preview_meta.json`，返回 `(路径, sha, 页数)`；sha = sha1(html)，命中缓存则跳过浏览器。
  - `preview_service.page_png(pdf_path, index, scale) -> bytes`（1 基页码，越界抛 IndexError）。
  - 端点 `POST /api/practices/{id}/render` → `{"pages": n, "sha": sha}`（懒物化 + 重建缓存）；`GET /api/practices/{id}/preview/page/{index}?scale=2` → image/png；未先 render 返 404。
- 页码脚注：`show_page_number` 时 `page.pdf(display_header_footer=True, footer_template=...)`，且底部边距额外 +10mm 预留脚注空间。

- [ ] **Step 1: 装依赖并固定版本**

Run:
```powershell
& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pip install pymupdf
& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pip freeze | Select-String -Pattern "pymupdf"
```
把输出的精确版本写入 `backend/requirements.txt`（如 `pymupdf==1.24.x`），紧跟 `playwright==1.62.0` 之后。验证 `python -c "import fitz; print(fitz.__version__)"` 可运行。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_preview_api.py
"""预览/导出管线 API 测试：真实启动 chromium（单用例约 2-4 秒）。"""

from test_blocks_api import _create_practice


async def test_render_and_page_image(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.post(f"/api/practices/{pid}/render")
    assert res.status_code == 200
    data = res.json()
    assert data["pages"] >= 1 and len(data["sha"]) == 40

    img = await client.get(f"/api/practices/{pid}/preview/page/1")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content.startswith(b"\x89PNG")

    bad = await client.get(f"/api/practices/{pid}/preview/page/999")
    assert bad.status_code == 404


async def test_render_refreshes_after_edit(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    sha1 = (await client.post(f"/api/practices/{pid}/render")).json()["sha"]
    # 改第一个文字块 → HTML 变化 → sha 变化；页面图片缓存命中旧文件则重新生成
    detail = (await client.get(f"/api/practices/{pid}/detail")).json()
    q = detail["sections"][0]["questions"][0]
    bid = next(b["id"] for b in q["blocks"] if b["block_type"] == "text")
    await client.put(f"/api/practices/{pid}/questions/{q['id']}/blocks/{bid}", json={"content": "预览缓存验证"})
    sha2 = (await client.post(f"/api/practices/{pid}/render")).json()["sha"]
    assert sha1 != sha2
    assert (await client.get(f"/api/practices/{pid}/preview/page/1")).status_code == 200


async def test_page_requires_render(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    res = await client.get(f"/api/practices/{practice['id']}/preview/page/1")
    assert res.status_code == 404   # 未先 POST render
```

- [ ] **Step 3: 跑测试确认失败**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests/test_preview_api.py -q`
Expected: FAIL（404：端点不存在 / fitz 未装）

- [ ] **Step 4: 实现**

`render_service.py` 追加：

```python
import hashlib
import shutil
import tempfile

PAGE_FOOTER = ('<div style="width:100%;text-align:center;font-size:8px;color:#555;">'
               '第 <span class="pageNumber"></span> 页 / 共 <span class="totalPages"></span> 页</div>')


async def render_pdf_bytes(html: str, settings: dict) -> bytes:
    """HTML → A4 PDF：临时目录内 page.html + katex/ 子目录，file:// 加载（离线可用）。"""
    from playwright.async_api import async_playwright
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "practice.html").write_text(html, encoding="utf-8")
        shutil.copytree(katex_dist_dir(), root / "katex")
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.goto((root / "practice.html").as_uri(), wait_until="load")
                await page.wait_for_function("window.__katexDone === true", timeout=15000)
                margin = settings["margin"]
                # 页码脚注预留 10mm：Chromium pdf margin 只收数值长度，不支持 calc()
                bottom_mm = float(margin.removesuffix("mm")) + (10 if settings["show_page_number"] else 0)
                return await page.pdf(
                    format="A4", print_background=True,
                    margin={"top": margin, "bottom": f"{bottom_mm}mm", "left": margin, "right": margin},
                    display_header_footer=settings["show_page_number"],
                    header_template="<div></div>", footer_template=PAGE_FOOTER,
                )
            finally:
                await browser.close()


async def ensure_preview_pdf(practice_id: str, html: str, settings: dict) -> tuple[Path, str, int]:
    """缓存预览 PDF；sha 命中则跳过浏览器。返回 (路径, sha, 页数)。"""
    from app.services.preview_service import pdf_page_count
    sha = hashlib.sha1(html.encode("utf-8")).hexdigest()
    pdir = practice_service.practices_root() / practice_id
    pdf_path, meta_path = pdir / "preview.pdf", pdir / "preview_meta.json"
    if pdf_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("sha") == sha:
            return pdf_path, sha, meta["pages"]
    pdf = await render_pdf_bytes(html, settings)
    pdf_path.write_bytes(pdf)
    pages = pdf_page_count(pdf_path)
    meta_path.write_text(json.dumps({"sha": sha, "pages": pages}), encoding="utf-8")
    return pdf_path, sha, pages
```

（`json` 模块在文件顶部已导入；`settings` 参数指 render_settings 结果，非 app.config。）

新建 `preview_service.py`：

```python
"""Preview service — PDF 转分页 PNG（PyMuPDF）。"""

from pathlib import Path


def pdf_page_count(pdf_path: Path) -> int:
    import fitz
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def page_png(pdf_path: Path, index: int, scale: float = 2.0) -> bytes:
    """index 从 1 开始；越界抛 IndexError。"""
    import fitz
    with fitz.open(pdf_path) as doc:
        if index < 1 or index > doc.page_count:
            raise IndexError(f"page {index} out of range {doc.page_count}")
        pix = doc[index - 1].get_pixmap(matrix=fitz.Matrix(scale, scale))
        return pix.tobytes("png")
```

`schemas/practice.py` 追加：

```python
class PreviewRenderResponse(BaseModel):
    pages: int
    sha: str
```

`routers/practices.py` 追加（放在排版端点之后）：

```python
async def _load_for_render(db: AsyncSession, practice_id: str) -> Practice:
    """渲染专用加载：懒物化块 + 三层 selectinload + populate_existing。"""
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    changed = False
    for sec in practice.sections:
        for pq in sec.questions:
            if not pq.blocks:
                block_service.materialize_blocks(db, pq)
                changed = True
    if changed:
        await db.commit()   # materialize 只 flush；提交后必须重取（缓存已过期）
        practice = await _get_practice_full(db, practice_id)
    return practice


@router.post("/api/practices/{practice_id}/render", response_model=PreviewRenderResponse)
async def render_practice_preview(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _load_for_render(db, practice_id)
    html = render_service.build_practice_html(practice, practice_id)
    settings = render_service.render_settings(practice)
    _, sha, pages = await render_service.ensure_preview_pdf(practice_id, html, settings)
    return PreviewRenderResponse(pages=pages, sha=sha)


@router.get("/api/practices/{practice_id}/preview/page/{index}")
async def preview_page_image(practice_id: str, index: int, scale: float = 2.0):
    pdf_path = practice_service.practices_root() / practice_id / "preview.pdf"
    meta_path = practice_service.practices_root() / practice_id / "preview_meta.json"
    if not pdf_path.exists() or not meta_path.exists():
        raise HTTPException(404, "请先调用 POST /render 生成预览")
    try:
        png = preview_service.page_png(pdf_path, index, min(max(scale, 0.5), 4.0))
    except IndexError:
        raise HTTPException(404, "页码超出范围")
    return Response(content=png, media_type="image/png")
```

需要的新 import：`from fastapi import Response`、`from app.services import render_service, preview_service`、`PreviewRenderResponse`。

- [ ] **Step 5: 跑测试确认通过**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests/test_preview_api.py -q`
Expected: PASS（3 项；首个用例含浏览器启动，约 3-6 秒正常）
再跑全量：`-m pytest tests -q` 期望 42 项全过。

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/services/render_service.py backend/app/services/preview_service.py backend/app/schemas/practice.py backend/app/routers/practices.py backend/tests/test_preview_api.py
git commit -m "feat: 预览管线（Playwright 出 PDF + PyMuPDF 分页图 + 缓存刷新）"
```

---

### Task 3: Word 导出（python-docx）

**Files:**
- Create: `backend/app/services/docx_export.py`
- Modify: `backend/app/routers/practices.py`（`GET /export/docx`）
- Test: `backend/tests/test_docx_export.py`

**Interfaces:**
- Consumes: Task 1 `render_settings`；`practice_service.practice_assets_dir`；块数据形态（options 为 JSON 字符串）。
- Produces: `docx_export.build_docx(practice, practice_id) -> bytes`（同步，纯 python-docx，路由用 `asyncio.to_thread` 包裹）；端点返回 StreamingResponse，`Content-Disposition` 文件名 = 练习标题（清洗非法字符）+ `.docx`；导出后 `practice.status='exported'`。
- 约束：不输出答案/解析；图片块文件从练习资产目录读；文本块内 LaTeX 原样保留（Word 可编辑，规格 10.2）；图片宽度：fit → 原尺寸封顶内容宽，百分比 → 内容宽×比例；对齐按 style.align。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_docx_export.py
"""Word 导出：构建结果用 python-docx 回读断言。"""

import io

from docx import Document

from test_blocks_api import _create_practice


async def _build(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    res = await client.get(f"/api/practices/{practice['id']}/export/docx")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return practice, Document(io.BytesIO(res.content))


async def test_docx_structure(client, test_db, tmp_path):
    practice, doc = await _build(client, test_db, tmp_path)
    texts = [p.text for p in doc.paragraphs]
    assert any(practice["title"] in t for t in texts)          # 标题
    assert any("姓名" in t for t in texts)                      # 默认学生信息栏
    assert any(t.startswith("1.") for t in texts)               # 题号
    assert any("A." in t for t in texts)                        # 选项（单选题）
    assert len(doc.inline_shapes) >= 1                          # fixture 题带图（块序 text/image/text/options/answer_space）


async def test_docx_export_marks_status(client, test_db, tmp_path):
    practice, _ = await _build(client, test_db, tmp_path)
    item = (await client.get("/api/practices")).json()
    mine = next(p for p in item["practices"] if p["id"] == practice["id"])
    assert mine["status"] == "exported"
```

注：`_create_practice`（阶段二 helper）创建的题带一张 `.webp` 图（块序 text/image/text/options/answer_space），故 `inline_shapes >= 1` 可直接断言。

- [ ] **Step 2: 跑测试确认失败**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests/test_docx_export.py -q`
Expected: FAIL（404：端点不存在）

- [ ] **Step 3: 实现 docx_export.py**

```python
"""Word 导出：练习块 → 可编辑 docx（仅学生版）。"""

import io
import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt

from app.services import practice_service
from app.services.render_service import render_settings

A4_W, A4_H = Cm(21), Cm(29.7)


def build_docx(practice, practice_id: str) -> bytes:
    s = render_settings(practice)
    margin = Cm(float(s["margin"].removesuffix("mm")) / 10)   # mm → cm（Cm() 收厘米）
    content_width = A4_W - 2 * margin

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = A4_W, A4_H
    sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = margin
    if s["show_page_number"]:
        _add_page_number(sec)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(practice.title)
    run.bold = True
    run.font.size = Pt(18)
    _set_cn_font(run)
    if practice.subtitle:
        ps = doc.add_paragraph(practice.subtitle)
        ps.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if s["show_total_score"]:
        total = sum(pq.score or 0 for sec2 in practice.sections for pq in sec2.questions)
        if total > 0:
            pt = doc.add_paragraph(f"满分：{total:g} 分")
            pt.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if s["show_info_bar"]:
        doc.add_paragraph("姓名：____________　班级：____________　日期：____________")

    assets = practice_service.practice_assets_dir(practice_id)
    for section in practice.sections:
        if section.start_on_new_page:
            bp = doc.add_paragraph()
            bp.add_run().add_break(WD_BREAK.PAGE)
        if section.show_title:
            sp = doc.add_paragraph()
            sr = sp.add_run(section.title)
            sr.bold = True
            sr.font.size = Pt(13)
            _set_cn_font(sr)
        for pq in section.questions:
            _add_question(doc, pq, assets, content_width, s)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _set_cn_font(run, name="宋体"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _add_page_number(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for tag, attr, val in [("w:fldChar", "begin", None), ("w:instrText", None, "PAGE"),
                           ("w:fldChar", "end", None)]:
        el = OxmlElement(tag)
        if tag == "w:fldChar":
            el.set(qn("w:fldCharType"), attr)
        else:
            el.text = val
        run._r.append(el)


def _add_question(doc, pq, assets: Path, content_width, s: dict):
    score_txt = f"（{pq.score:g} 分）" if (s["show_score"] and pq.score is not None) else ""
    head = doc.add_paragraph(f"{pq.question_number}. {score_txt}".strip())
    for b in pq.blocks:
        style = b.style_config or {}
        if b.block_type == "text":
            tp = doc.add_paragraph()
            tp.add_run((b.content or "").replace("**", ""))
        elif b.block_type == "image":
            _add_image_block(doc, b, assets, content_width)
        elif b.block_type == "options":
            try:
                opts = json.loads(b.content) if b.content else []
            except (TypeError, json.JSONDecodeError):
                opts = []
            for o in opts:
                op = doc.add_paragraph()
                op.paragraph_format.left_indent = Cm(0.74)
                op.add_run(f"{o.get('label', '')}. {o.get('content', '')}")
        elif b.block_type == "answer_space":
            for _ in range(int(style.get("rows", 0))):
                doc.add_paragraph("")


def _add_image_block(doc, b, assets: Path, content_width):
    name = (b.content or "").removeprefix("asset://practice/")
    path = assets / name
    style = b.style_config or {}
    ip = doc.add_paragraph()
    align = style.get("align", "center")
    ip.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT}.get(
        align, WD_ALIGN_PARAGRAPH.CENTER)
    if not path.exists():
        ip.add_run(f"[图片缺失：{name}]")
        return
    width = None
    w = style.get("width", "fit")
    if isinstance(w, str) and w.endswith("%"):
        width = content_width * float(w.removesuffix("%")) / 100
    run = ip.add_run()
    run.add_picture(str(path), width=width)
    # fit：python-docx 默认原尺寸；若超内容宽由 Word 自动裁剪不处理（V1 可接受）
```

端点（路由，与 Task 4 的 PDF 端点一起分步提交）：

```python
import asyncio
from urllib.parse import quote
from fastapi.responses import StreamingResponse


def _export_filename(title: str, ext: str) -> str:
    clean = re.sub(r'[\\/:*?"<>|]', "_", title or "练习")
    return f"{clean}.{ext}"


@router.get("/api/practices/{practice_id}/export/docx")
async def export_docx(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _load_for_render(db, practice_id)
    data = await asyncio.to_thread(docx_export.build_docx, practice, practice_id)
    practice.status = "exported"
    await db.commit()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition":
                 f"attachment; filename*=utf-8''{quote(_export_filename(practice.title, 'docx'))}"})
```

新 import：`import io, re, asyncio`、`from urllib.parse import quote`、`from fastapi.responses import StreamingResponse`、`from app.services import docx_export`。

- [ ] **Step 4: 跑测试确认通过**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests/test_docx_export.py -q`
Expected: PASS（2 项）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/docx_export.py backend/app/routers/practices.py backend/tests/test_docx_export.py
git commit -m "feat: Word 导出（标题/信息栏/小节分页/块顺序/留白，可继续编辑）"
```

---

### Task 4: PDF 导出端点

**Files:**
- Modify: `backend/app/routers/practices.py`（`GET /export/pdf`）
- Test: `backend/tests/test_preview_api.py`（追加 1 用例）

**Interfaces:**
- Consumes: Task 2 `ensure_preview_pdf`（无缓存则实时生成，预览与导出同一文件——规格 10.2 一致性天然成立）。
- Produces: `GET /api/practices/{id}/export/pdf` → application/pdf 流，文件名同 Task 3 规则；`status='exported'`。

- [ ] **Step 1: 追加失败测试**（写入 `test_preview_api.py` 末尾）

```python
async def test_export_pdf(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.get(f"/api/practices/{pid}/export/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")
    assert "filename" in res.headers.get("content-disposition", "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests/test_preview_api.py::test_export_pdf -q`
Expected: FAIL（404）

- [ ] **Step 3: 实现端点**（紧跟 Task 3 的 docx 端点之后）

```python
@router.get("/api/practices/{practice_id}/export/pdf")
async def export_pdf(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _load_for_render(db, practice_id)
    html = render_service.build_practice_html(practice, practice_id)
    settings = render_service.render_settings(practice)
    pdf_path, _, _ = await render_service.ensure_preview_pdf(practice_id, html, settings)
    practice.status = "exported"
    await db.commit()
    return StreamingResponse(
        io.BytesIO(pdf_path.read_bytes()),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename*=utf-8''{quote(_export_filename(practice.title, 'pdf'))}"})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests -q`
Expected: 45 项全过（39 + 预览 3 + docx 2 + pdf 1）

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/practices.py backend/tests/test_preview_api.py
git commit -m "feat: PDF 导出（与预览同一渲染管线，规格 10.2 一致性）"
```

---

### Task 5: 前端 —— 预览面板 + 导出按钮 + 设置扩展

**Files:**
- Modify: `frontend/src/views/PracticeEditorView.vue`

**Interfaces:**
- Consumes: Task 2/3/4 全部端点；阶段二 `load()`/`normalizeBlocks`。
- Produces：右侧预览区（页图/翻页/缩放/全屏/防抖刷新）、顶栏导出 PDF/Word 按钮、练习设置新增页边距预设 + 页码/分值/总分开关。
- 刷新策略：`load()` 末尾调 `schedulePreview()`（800ms 防抖）——阶段二所有写操作后都会 `load()`，天然覆盖。

- [ ] **Step 1: 模板修改**

把预览占位：

```html
      <!-- 右：预览占位（阶段三接入） -->
      <div class="preview-panel">
        <el-empty description="A4 预览将在阶段三接入" :image-size="80" />
      </div>
```

替换为：

```html
      <!-- 右：A4 预览（后端渲染，与 PDF 同源） -->
      <div class="preview-panel">
        <div class="pv-toolbar">
          <el-button size="small" text :disabled="preview.page <= 1" @click="preview.page--">‹</el-button>
          <span class="pv-pos">{{ preview.page }} / {{ preview.pages || '-' }}</span>
          <el-button size="small" text :disabled="preview.page >= preview.pages" @click="preview.page++">›</el-button>
          <el-select v-model="preview.zoom" size="small" style="width:76px">
            <el-option v-for="z in [0.6, 0.8, 1, 1.5, 2]" :key="z" :label="Math.round(z * 100) + '%'" :value="z" />
          </el-select>
          <el-button size="small" text @click="showFullscreen = true" :disabled="!preview.pages">⛶</el-button>
          <el-button size="small" text @click="refreshPreview" :loading="preview.busy">↻</el-button>
        </div>
        <div class="pv-scroll" v-if="preview.pages">
          <img :src="pageImgUrl" :style="{ width: (220 * preview.zoom) + 'px' }" />
        </div>
        <el-empty v-else-if="preview.busy" description="正在渲染预览…" :image-size="60" />
        <el-empty v-else description="编辑后自动刷新预览" :image-size="60" />
      </div>
```

顶栏按钮区追加导出：

```html
        <el-button @click="exportFile('pdf')"><el-icon><Document /></el-icon> 导出 PDF</el-button>
        <el-button @click="exportFile('docx')"><el-icon><Tickets /></el-icon> 导出 Word</el-button>
```

全屏预览对话框（图片选择器对话框旁追加）：

```html
    <!-- 全屏预览 -->
    <el-dialog v-model="showFullscreen" title="全屏预览" width="900px" top="4vh">
      <div class="fs-preview" v-if="preview.pages">
        <img :src="pageImgUrl" :style="{ width: (794 * preview.zoom) + 'px' }" />
      </div>
      <template #footer>
        <el-button :disabled="preview.page <= 1" @click="preview.page--">上一页</el-button>
        <span>{{ preview.page }} / {{ preview.pages }}</span>
        <el-button :disabled="preview.page >= preview.pages" @click="preview.page++">下一页</el-button>
      </template>
    </el-dialog>
```

练习设置对话框追加三项（`el-form` 内）：

```html
        <el-form-item label="页边距">
          <el-select v-model="settingsForm.marginPreset" style="width:160px">
            <el-option label="窄（15mm）" value="narrow" />
            <el-option label="标准（25mm）" value="normal" />
            <el-option label="宽（32mm）" value="wide" />
          </el-select>
        </el-form-item>
        <el-form-item label="页码"><el-switch v-model="settingsForm.showPageNumber" /></el-form-item>
        <el-form-item label="显示分值"><el-switch v-model="settingsForm.showScore" /></el-form-item>
        <el-form-item label="显示总分"><el-switch v-model="settingsForm.showTotalScore" /></el-form-item>
```

- [ ] **Step 2: script 修改**

追加状态与函数（放在块编辑区代码之后）：

```js
import { computed } from 'vue'   // 并入顶部 vue import

const showFullscreen = ref(false)
const preview = reactive({ pages: 0, page: 1, sha: '', zoom: 1, busy: false })
let previewTimer = null

const pageImgUrl = computed(() => preview.pages
  ? `/api/practices/${practiceId}/preview/page/${preview.page}?scale=2&t=${preview.sha}`
  : '')

const refreshPreview = async () => {
  preview.busy = true
  try {
    const res = await axios.post(`/api/practices/${practiceId}/render`)
    preview.pages = res.data.pages
    preview.sha = res.data.sha
    if (preview.page > preview.pages) preview.page = 1
  } catch { /* 渲染失败不阻断编辑 */ } finally { preview.busy = false }
}
const schedulePreview = () => {   // 编辑后防抖刷新（规格 10.1）
  clearTimeout(previewTimer)
  previewTimer = setTimeout(refreshPreview, 800)
}

const exportFile = async (fmt) => {
  try {
    const res = await axios.get(`/api/practices/${practiceId}/export/${fmt}`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `${practice.value.title || '练习'}.${fmt}`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
    await load()
  } catch { ElMessage.error('导出失败') }
}
```

修改现有函数：
- `load()` 末尾追加 `schedulePreview()`（首次加载也会触发渲染）。
- `openSettings()` 补：`settingsForm.marginPreset = practice.value.page_config?.margin_preset || 'normal'`、`settingsForm.showPageNumber = practice.value.page_config?.show_page_number ?? true`、`settingsForm.showScore = practice.value.page_config?.show_score ?? false`、`settingsForm.showTotalScore = practice.value.page_config?.show_total_score ?? false`。
- `settingsForm` 初始化加 `marginPreset: 'normal', showPageNumber: true, showScore: false, showTotalScore: false`。
- `saveSettings()` 的 `page_config` 展开里补四个键：`margin_preset`、`show_page_number`、`show_score`、`show_total_score`。

- [ ] **Step 3: 样式追加**（并入 `<style scoped>`，替换 `.preview-panel` 原规则）

```css
.preview-panel { width: 280px; border-left: 1px solid #ebeef5; display: flex; flex-direction: column; background: #f0f2f5; }
.pv-toolbar { display: flex; align-items: center; gap: 2px; padding: 6px 8px; border-bottom: 1px solid #ebeef5; background: #fff; }
.pv-pos { font-size: 12px; color: #606266; white-space: nowrap; }
.pv-scroll { flex: 1; overflow: auto; padding: 10px; display: flex; justify-content: center; }
.pv-scroll img { box-shadow: 0 1px 6px rgba(0,0,0,.18); background: #fff; }
.fs-preview { display: flex; justify-content: center; overflow: auto; max-height: 76vh; }
.fs-preview img { box-shadow: 0 1px 8px rgba(0,0,0,.22); background: #fff; }
```

- [ ] **Step 4: 前端构建验证**

Run：`cd frontend; $env:PATH = "C:\Users\Administrator\.conda\envs\question_platform;" + $env:PATH ; node node_modules/vite/bin/vite.js build`
Expected: 输出 "built in Xs"（ExitCode 1 为 PowerShell 已知假报警）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/PracticeEditorView.vue
git commit -m "feat: A4 预览面板（分页/缩放/全屏/防抖刷新）+ PDF/Word 导出入口 + 导出设置"
```

---

### Task 6: 集成验收（阶段三收尾）

**Files:**
- 无新后端改动；全量回归 + 真实库冒烟 + 手工验收清单。

- [ ] **Step 1: 全量回归**

Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m pytest tests -q`（期望 45 项全过）
Run: 前端构建（同 Task 5 Step 4）
Run: `& "C:\Users\Administrator\.conda\envs\question_platform\python.exe" -m alembic current` → 保持 `7be1dc9c4638 (head)`（本阶段无新迁移）

- [ ] **Step 2: 真实库冒烟**（后端 `--reload` 运行中，改动自动生效）

写临时脚本 `backend/smoke_phase3.ps1`（验证后删除），步骤：
1. `GET /api/questions?page=1&page_size=1` 取一题（响应字段 `.questions`）；
2. 入池 → `POST /api/practices {title:'p3-smoke', from_basket:true}`；
3. `POST /{id}/render` → pages≥1、sha；`GET /{id}/preview/page/1` → PNG 魔数；
4. 改一个文字块 → 再 `POST /render` → sha 变化；
5. `GET /{id}/export/pdf` → 字节以 `%PDF` 开头；`GET /{id}/export/docx` → 字节以 `PK` 开头；列表 `status=='exported'`；
6. `DELETE /api/practices/{id}`、`DELETE /api/basket`，确认练习列表回到冒烟前状态（勿删阶段一验收留下的真实练习）。
注意：PowerShell 勿用 `$pid`；含中文的 JSON 请求体用 `[System.Text.Encoding]::UTF8.GetBytes(...)` 发送；`.ps1` 会被 PS 5.1 按 ANSI 读，冒烟数据用 ASCII。

- [ ] **Step 3: 手工验收清单**（浏览器，对应规格场景三）

1. 编辑器右侧预览：首次加载自动出页图；改一个文字块后 ~1 秒自动刷新。
2. 翻页、缩放、全屏正常；页码显示“第 x 页 / 共 y 页”（预览图片即 PDF 原样）。
3. 练习设置：关信息栏/改页边距/开分值总分 → 预览即时变化。
4. 导出 PDF：文件名 = 标题，内容与预览一致；导出 Word：打开后可编辑，图片顺序与块顺序一致。
5. 图片块对齐/宽度设置在预览中生效；`start_on_new_page` 小节预览中真实另起一页。
6. 练习列表卡片状态变为 exported；题库原题零侵入。

- [ ] **Step 4: 同步计划文档偏差 + Commit**

若实施中与本计划有偏差（签名/字段/端点形状），在本文档末尾追加“实施偏差记录”一节（参照阶段二做法），然后：

```bash
git add docs/superpowers/plans/2026-08-29-practice-builder-phase3.md
git commit -m "docs: 阶段三计划偏差记录（如有）"
```

---

## 验收总览（阶段三）

| 规格条目 | 落点 |
|---|---|
| 10.1 A4/真实分页/页码/缩放/全屏/防抖刷新 | Task 2（后端同源渲染）+ Task 5（预览面板） |
| 10.2 PDF 与预览一致；Word 结构/图序/可编辑 | Task 4（同一 PDF 文件）；Task 3（python-docx 标准文档） |
| 11.1 .pdf / .docx | Task 4 / Task 3 |
| 11.2 仅学生版 | Task 1（answer/explanation 块不输出）+ Task 3 |
| 11.3 导出设置（文件名/页边距/页码/信息栏/分值/总分） | Task 1（render_settings）+ Task 5（设置对话框）；纸张 A4 纵向固定 |
| 场景三 | Task 6 冒烟与手工清单 |
| 决策 8 | 全管线：预览与 PDF 共用 Playwright 渲染 + 缓存 |
