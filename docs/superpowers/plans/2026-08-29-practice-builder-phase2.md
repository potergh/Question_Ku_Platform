# 练习制作系统 · 阶段二：块式编辑器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现练习块式编辑器：题目内容分解为可排序内容块（文字/图片/选项/留白），支持纠错编辑、图片操作、结构编排（小节与题目增删移动）、恢复题库版本、一键整理结构与统一排版。

**Architecture:** 复用阶段一的 `PracticeContentBlock` 表：题目加入练习时即物化内容块（文字/图片交错 + 选项块 + 留白块），块编辑后重建 `content_snapshot`（阶段三预览/导出的唯一内容来源）。结构编排直接操作 `practice_sections / practice_questions`，每次结构变化后全练习连续重编号。前端新增 `/practice/editor` 双栏编辑器（左结构树 + 中块编辑区，右预览区阶段三接入）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + pytest（asyncio_mode=auto，复用 conftest 的 `client`/`test_db`）+ Vue3 + Element Plus + axios。

**Spec:** `docs/superpowers/plans/2026-08-28-practice-builder-spec.md` 第 7-9 章（快照关系、编辑器、一键排版）。前置：阶段一已完成（提交 `c246764`…`c36c48f`），练习表/选题池/快照服务已上线。

## Global Constraints

- **题库零侵入**：所有编辑只改练习快照；恢复操作只读题库原题，永不写回（决策 3）。
- **`content_snapshot` 是渲染唯一来源**：块的任何增删改之后必须调用 `rebuild_content_from_blocks` 重建快照；`options` 块同时回写 `options_snapshot`。
- **`style_config` 为空 = 未定制**：一键统一排版只覆盖 `style_config` 为空的块（规格 9.3 核心约束）。
- **块存储约定**：`PracticeContentBlock.content` 为 Text 列——image 块存 `asset://practice/<name>`，options 块存选项数组的 JSON 字符串，text 块存文字；`answer_space` 与分页约束存 `style_config`。单题留白覆盖存 `PracticeQuestion.layout_config`（JSON，模型已有字段）。
- 本阶段不做 A4 预览与导出（阶段三，决策 8）。
- 后端命令（工作目录 `backend/`，conda 环境 `question_platform`；若 `conda run` 异常，直接调用 `C:\Users\Administrator\.conda\envs\question_platform\python.exe`）：
  - 测试：`python -m pytest tests -q`
  - 无需新迁移：`PracticeContentBlock` 表与全部字段（含 `layout_config`/`page_config`）阶段一已建。
- 前端构建（工作目录 `frontend/`）：`$env:PATH = "C:\Users\Administrator\.conda\envs\question_platform;" + $env:PATH ; node node_modules/vite/bin/vite.js build`
- 每个任务结束必须通过对应测试并提交。

---

### Task 1: 块服务（物化 / 重建 / 恢复）

**Files:**
- Create: `backend/app/services/block_service.py`
- Test: `backend/tests/test_block_service.py`

**Interfaces:**
- Consumes: 阶段一 `practice_service.ASSET_RE` / `snapshot_question` / `_copy_referenced_assets` / `practice_assets_dir`；模型 `Practice / PracticeSection / PracticeQuestion / PracticeContentBlock`。
- Produces:
  - `materialize_blocks(db, pq) -> list[PracticeContentBlock]`：把 `content_snapshot` 按图片引用切分为 text/image 交错块，追加 options 块（有选项时）与 answer_space 块（默认行数按题型）。幂等：已有块则原样返回。
  - `rebuild_content_from_blocks(pq) -> str`：text 块按顺序用空行拼接，image 块内联为 `![图](asset://practice/xxx)`；同时回写 `pq.content_snapshot` 与 `pq.options_snapshot`，并置 `pq.is_modified = True`。
  - `restore_question_from_source(db, pq) -> PracticeQuestion`：从题库原题重新快照（图片重新复制），重建块；原题不存在返回 `None`。
  - 常量：`DEFAULT_ANSWER_SPACE`（题型英文名 → 默认留白行数）、`IMAGE_DEFAULT_STYLE`。
- 注意：块服务中 `selectinload` 只在 Task 3/4 的路由里使用；本任务全部通过显式查询操作。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_block_service.py`：

```python
"""Block service tests — materialize / rebuild / restore."""

from app.models import Source, Question
from app.models.practice import PracticeQuestion
from app.services import practice_service, block_service
from sqlalchemy import select
from sqlalchemy.orm import selectinload


async def _make_practice(test_db, tmp_path, monkeypatch):
    """造一个带图选择题的练习，返回 practice。"""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True)
    (ocr_dir / "figures" / "f.webp").write_bytes(b"img")

    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q1", question_number=1,
                     question_type="single_choice",
                     content="题干第一段 ![图](asset://figures/f.webp) 题干第二段",
                     options=[{"label": "A", "content": "x"}, {"label": "B", "content": "y"}])
        db.add(q)
        await db.commit()
        await db.refresh(q)
        practice = await practice_service.create_practice_from_questions(
            db, "t", None, None, None, [q])
        return practice


async def test_materialize_blocks(test_db, tmp_path, monkeypatch):
    practice = await _make_practice(test_db, tmp_path, monkeypatch)
    async with test_db() as db:
        pq = (await db.execute(select(PracticeQuestion))).scalars().first()
        blocks = await block_service.materialize_blocks(db, pq)
        types = [b.block_type for b in blocks]
        assert types == ["text", "image", "text", "options", "answer_space"]
        assert "asset://practice/" in blocks[1].content
        import json as _json
        assert _json.loads(blocks[3].content) == [
            {"label": "A", "content": "x"}, {"label": "B", "content": "y"}]
        assert blocks[0].position == 0 and blocks[4].position == 4
        # 幂等
        again = await block_service.materialize_blocks(db, pq)
        assert [b.id for b in again] == [b.id for b in blocks]


async def test_rebuild_content(test_db, tmp_path, monkeypatch):
    practice = await _make_practice(test_db, tmp_path, monkeypatch)
    async with test_db() as db:
        # 显式预加载 blocks，避免 rebuild_content_from_blocks 内部懒加载报 MissingGreenlet
        pq = (await db.execute(
            select(PracticeQuestion).options(selectinload(PracticeQuestion.blocks))
        )).scalar_one()
        blocks = await block_service.materialize_blocks(db, pq)
        pq = (await db.execute(
            select(PracticeQuestion).options(selectinload(PracticeQuestion.blocks))
        )).scalar_one()
        pq.blocks[0].content = "修改后的题干"
        await db.commit()
        block_service.rebuild_content_from_blocks(pq)
        await db.commit()
        assert pq.is_modified is True
        assert pq.content_snapshot.startswith("修改后的题干")
        assert "asset://practice/" in pq.content_snapshot
        assert "题干第二段" in pq.content_snapshot


async def test_restore_from_source(test_db, tmp_path, monkeypatch):
    practice = await _make_practice(test_db, tmp_path, monkeypatch)
    async with test_db() as db:
        pq = (await db.execute(select(PracticeQuestion))).scalars().first()
        blocks = await block_service.materialize_blocks(db, pq)
        blocks[0].content = "被改坏了"
        await db.commit()
        block_service.rebuild_content_from_blocks(pq)
        await db.commit()

        restored = await block_service.restore_question_from_source(db, pq)
        assert restored.is_modified is False
        assert "题干第一段" in restored.content_snapshot
        # restored 由服务内部以 selectinload 重新加载，可安全访问 blocks
        assert [b.block_type for b in restored.blocks] == ["text", "image", "text", "options", "answer_space"]
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m pytest tests/test_block_service.py -q`
Expected: FAIL（ModuleNotFoundError: block_service）

- [ ] **Step 3: 实现 block_service.py**

```python
"""Block service — materialize question content into editable blocks and rebuild."""

import json

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Question, Source
from app.models.practice import PracticeContentBlock, PracticeQuestion
from app.services.practice_service import (
    ASSET_RE,
    _copy_referenced_assets,
    practice_assets_dir,
    snapshot_question,
)

# 题型英文名 → 默认答题留白行数（决策 6：默认值由题型决定，单题可覆盖）
DEFAULT_ANSWER_SPACE = {
    "single_choice": 0, "multiple_choice": 0,
    "fill_blank": 2, "experiment": 4, "calculation": 8,
    "short_answer": 6, "essay": 6, "comprehensive": 6, "unknown": 4,
}

# 一键统一排版时应用到未定制图片块的默认样式
IMAGE_DEFAULT_STYLE = {"align": "center", "width": "fit"}


async def materialize_blocks(db: AsyncSession, pq: PracticeQuestion) -> list[PracticeContentBlock]:
    """把快照内容分解为内容块（幂等：已有块直接返回）。"""
    existing = (await db.execute(
        select(PracticeContentBlock)
        .where(PracticeContentBlock.practice_question_id == pq.id)
        .order_by(PracticeContentBlock.position)
    )).scalars().all()
    if existing:
        return list(existing)

    blocks: list[PracticeContentBlock] = []

    def add(block_type: str, content, style: dict | None = None):
        blocks.append(PracticeContentBlock(
            practice_question_id=pq.id, block_type=block_type,
            position=len(blocks), content=content, style_config=style,
        ))

    content = pq.content_snapshot or ""
    last = 0
    for m in ASSET_RE.finditer(content):
        pre = content[last:m.start()].strip()
        if pre:
            add("text", pre)
        add("image", f"asset://{m.group(1)}", style=dict(IMAGE_DEFAULT_STYLE))  # 默认居中/适应（规格 9.2）
        last = m.end()
    tail = content[last:].strip()
    if tail:
        add("text", tail)
    if pq.options_snapshot:
        add("options", json.dumps(pq.options_snapshot, ensure_ascii=False))
    add("answer_space", None, {"rows": DEFAULT_ANSWER_SPACE.get(pq.question_type, 4)})

    db.add_all(blocks)
    await db.commit()
    for b in blocks:
        await db.refresh(b)
    return blocks


def rebuild_content_from_blocks(pq: PracticeQuestion) -> str:
    """按块重建 content_snapshot（图片内联），并回写选项快照、标记已修改。"""
    blocks = sorted(pq.blocks, key=lambda b: b.position)
    parts: list[str] = []
    options = None
    for b in blocks:
        if b.block_type == "text" and (b.content or "").strip():
            parts.append(b.content.strip())
        elif b.block_type == "image" and b.content:
            parts.append(f"![图]({b.content})")
        elif b.block_type == "options":
            # options 块的 content 是选项数组的 JSON 字符串；空串 = 删除选项块语义，不回写
            if (b.content or "").strip():
                options = json.loads(b.content)
    pq.content_snapshot = "\n\n".join(parts)
    if options is not None:
        pq.options_snapshot = options
    pq.is_modified = True
    return pq.content_snapshot


async def restore_question_from_source(db: AsyncSession, pq: PracticeQuestion) -> PracticeQuestion | None:
    """恢复为题库原题版本：重新快照内容与图片，重建内容块。原题不存在返回 None。"""
    if not pq.source_question_id:
        return None
    source_q = await db.get(Question, pq.source_question_id)
    if not source_q or source_q.is_deleted:
        return None

    source = await db.get(Source, source_q.source_id)
    ocr_dir = Path(source.ocr_result_path) if source and source.ocr_result_path else None
    content = _copy_referenced_assets(
        source_q.content, ocr_dir, practice_assets_dir(pq.practice_id))

    pq.question_number = source_q.question_number
    pq.question_type = source_q.question_type
    pq.subject = source_q.subject
    pq.difficulty = source_q.difficulty
    pq.score = source_q.score
    pq.content_snapshot = content
    pq.options_snapshot = source_q.options
    pq.answer_snapshot = source_q.answer
    pq.explanation_snapshot = source_q.explanation
    pq.source_version = source_q.updated_at
    pq.is_modified = False
    pq.layout_config = None

    await db.execute(delete(PracticeContentBlock)
                     .where(PracticeContentBlock.practice_question_id == pq.id))
    await db.commit()
    await db.refresh(pq)
    await materialize_blocks(db, pq)
    # 重新加载并预加载块，避免返回后访问 relationship 触发懒加载（MissingGreenlet）
    result = await db.execute(
        select(PracticeQuestion)
        .where(PracticeQuestion.id == pq.id)
        .options(selectinload(PracticeQuestion.blocks))
    )
    return result.scalar_one()
```

顶部补充 import：`from pathlib import Path`（与上面代码一并加入）。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/block_service.py backend/tests/test_block_service.py
git commit -m "feat: 内容块服务（物化/重建快照/恢复题库版本）"
```

---

### Task 2: 块编辑 API + 详情返回块

**Files:**
- Modify: `backend/app/schemas/practice.py`
- Modify: `backend/app/routers/practices.py`
- Test: `backend/tests/test_blocks_api.py`

**Interfaces:**
- Consumes: Task 1 全部函数；阶段一 `_get_practice_full` / `_practice_response`。
- Produces:
  - `PracticeQuestionOut.blocks` 新字段：`[{id, block_type, position, content, style}]`；图片块 `content` 解析为 `/api/practices/{id}/assets/...` HTTP URL；options 块 `content` 为选项数组。
  - `GET /api/practices/{id}/detail`：同详情但**懒物化**（无块则先物化），返回 `PracticeResponse`。
  - `POST /api/practices/{pid}/questions/{qid}/blocks` body `{block_type, content?, style?}` → 新块 + 重建快照。
  - `PUT /api/practices/{pid}/questions/{qid}/blocks/{bid}` body `{content?, style?}` → 更新 + 重建快照。
  - `PUT /api/practices/{pid}/questions/{qid}/blocks/reorder` body `{block_ids: [...]}` → 按列表重排 + 重建快照。
  - `DELETE /api/practices/{pid}/questions/{qid}/blocks/{bid}` → 删除 + 重建快照。
  - `POST /api/practices/{pid}/questions/{qid}/restore` → 恢复题库版本；原题不存在返回 404。
  - `GET /api/practices/{pid}/assets-list` → `{assets: [文件名]}`（编辑器插入图片时选择）。
  - 所有写操作响应：`{"question": PracticeQuestionOut, "blocks": [...]}`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_blocks_api.py`：

```python
"""API tests for question content blocks."""

from app.models import Source, Question

CONTENT = "题干A ![图](asset://figures/f.webp) 题干B"


async def _create_practice(client, test_db, tmp_path, content=CONTENT,
                           question_type="single_choice",
                           options=None):
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True, exist_ok=True)
    (ocr_dir / "figures" / "f.webp").write_bytes(b"img")
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q1", question_number=1,
                     question_type=question_type, content=content,
                     options=options if options is not None
                     else [{"label": "A", "content": "x"}])
        db.add(q)
        await db.commit()
        await db.refresh(q)
        qid = q.id
    res = await client.post("/api/practices", json={
        "title": "t", "from_basket": False, "question_ids": [qid]})
    return res.json()


async def _question(client, practice):
    detail = (await client.get(f"/api/practices/{practice['id']}/detail")).json()
    return detail["sections"][0]["questions"][0]


async def test_detail_materializes_blocks(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    types = [b["block_type"] for b in q["blocks"]]
    assert types == ["text", "image", "text", "options", "answer_space"]
    assert q["blocks"][1]["content"].startswith("/api/practices/")
    assert q["blocks"][3]["content"] == [{"label": "A", "content": "x"}]  # API 层已解析为数组


async def test_block_crud_and_rebuild(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    pid, qid = practice["id"], q["id"]

    # 改文字块 → 快照重建
    res = await client.put(f"/api/practices/{pid}/questions/{qid}/blocks/{q['blocks'][0]['id']}",
                           json={"content": "改过的题干"})
    assert res.json()["question"]["is_modified"] is True
    detail = (await client.get(f"/api/practices/{pid}")).json()
    assert "改过的题干" in detail["sections"][0]["questions"][0]["content"]

    # 新增文字块
    res = await client.post(f"/api/practices/{pid}/questions/{qid}/blocks",
                            json={"block_type": "text", "content": "补充说明"})
    assert res.status_code == 200 and len(res.json()["blocks"]) == 6

    # 重排：把补充说明移到最前
    ids = [b["id"] for b in res.json()["blocks"]]
    ids.insert(0, ids.pop())
    res = await client.put(f"/api/practices/{pid}/questions/{qid}/blocks/reorder",
                           json={"block_ids": ids})
    assert res.json()["blocks"][0]["content"] == "补充说明"

    # 删除图片块
    img = next(b for b in res.json()["blocks"] if b["block_type"] == "image")
    res = await client.delete(f"/api/practices/{pid}/questions/{qid}/blocks/{img['id']}")
    assert all(b["block_type"] != "image" for b in res.json()["blocks"])


async def test_restore(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    pid, qid = practice["id"], q["id"]
    await client.put(f"/api/practices/{pid}/questions/{qid}/blocks/{q['blocks'][0]['id']}",
                     json={"content": "改坏"})
    res = await client.post(f"/api/practices/{pid}/questions/{qid}/restore")
    assert res.status_code == 200
    assert res.json()["question"]["is_modified"] is False
    assert "题干A" in res.json()["question"]["content"]


async def test_assets_list(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    res = await client.get(f"/api/practices/{practice['id']}/assets-list")
    assert res.json()["assets"] and res.json()["assets"][0].endswith(".webp")
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m pytest tests/test_blocks_api.py -q`
Expected: FAIL（404 / 无 blocks 字段）

- [ ] **Step 3: 修改 schemas/practice.py**

顶部 `from pydantic import BaseModel` 改为 `from typing import Any` + `from pydantic import BaseModel`。

`PracticeQuestionOut` 追加字段，并新增块出参模型（`content` 可能是字符串/数组，用 `Any`）：

```python
class PracticeBlockOut(BaseModel):
    id: str
    block_type: str
    position: int
    content: Any = None
    style: dict | None = None
```

```python
class PracticeQuestionOut(BaseModel):
    # ... 现有字段不变，末尾追加：
    blocks: list[PracticeBlockOut] = []
```

- [ ] **Step 4: 修改 routers/practices.py**

顶部补充 import：`from app.models.practice import PracticeContentBlock`、`from app.services import block_service`、`from pydantic import BaseModel`、`import json`。

4.1 `_get_practice_full` 追加块预加载：

```python
        .options(selectinload(Practice.sections)
                 .selectinload(PracticeSection.questions)
                 .selectinload(PracticeQuestion.blocks))
```

4.2 `_practice_response` 中构造 question 出参处追加 `blocks=_block_outs(s_q_list, practice.id)`，并在文件内新增：

```python
def _block_out(pq_id: str, b: PracticeContentBlock, practice_id: str) -> dict:
    content = b.content
    if b.block_type == "image" and content:
        content = practice_service.resolve_practice_asset_urls(content, practice_id)
    elif b.block_type == "options" and content:
        try:
            content = json.loads(content)  # 存储是 JSON 字符串，出参解析为数组供前端直接用
        except (TypeError, ValueError):
            content = None
    return {"id": b.id, "block_type": b.block_type, "position": b.position,
            "content": content, "style": b.style_config}


def _block_outs(questions, practice_id: str) -> list[list[dict]]:
    return [[_block_out(q.id, b, practice_id) for b in q.blocks] for q in questions]
```

（实现上直接在 `_practice_response` 循环内对每道题生成 `blocks=[_block_out(pq.id, b, practice.id) for b in pq.blocks]` 传入 `PracticeQuestionOut` 即可。）

4.3 追加端点：

```python
class BlockCreateRequest(BaseModel):
    block_type: str
    content: Any = None
    style: dict | None = None


class BlockUpdateRequest(BaseModel):
    content: Any = None
    style: dict | None = None


class BlockReorderRequest(BaseModel):
    block_ids: list[str]


async def _load_pq(db: AsyncSession, practice_id: str, pq_id: str) -> PracticeQuestion:
    result = await db.execute(
        select(PracticeQuestion)
        .where(PracticeQuestion.id == pq_id, PracticeQuestion.practice_id == practice_id)
        .options(selectinload(PracticeQuestion.blocks))
    )
    pq = result.scalar_one_or_none()
    if not pq:
        raise HTTPException(404, "Practice question not found")
    return pq


async def _question_payload(db: AsyncSession, pq: PracticeQuestion) -> dict:
    """块写操作统一响应：题目出参 + 块列表。"""
    practice = await db.get(Practice, pq.practice_id)
    pq = await _load_pq(db, pq.practice_id, pq.id)
    from app.schemas.practice import PracticeBlockOut  # 避免循环观感可选
    return {
        "question": _practice_response_single(practice, pq),
        "blocks": [_block_out(pq.id, b, pq.practice_id)
                   for b in sorted(pq.blocks, key=lambda b: b.position)],
    }
```

说明：`_practice_response_single(practice, pq)` 是把 `_practice_response` 中单题出参逻辑抽出的小函数（签名 `(practice: Practice, pq: PracticeQuestion) -> PracticeQuestionOut`），`_practice_response` 内部改为调用它，避免重复。

```python
@router.get("/api/practices/{practice_id}/detail", response_model=PracticeResponse)
async def get_practice_detail(practice_id: str, db: AsyncSession = Depends(get_db)):
    """同详情，但对未物化的题目先生成内容块（懒物化）。"""
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    for s in practice.sections:
        for pq in s.questions:
            await block_service.materialize_blocks(db, pq)
    practice = await _get_practice_full(db, practice_id)
    return _practice_response(practice)


@router.get("/api/practices/{practice_id}/assets-list")
async def list_practice_assets(practice_id: str):
    assets_dir = practice_service.practice_assets_dir(practice_id)
    names = sorted(p.name for p in assets_dir.iterdir() if p.is_file())
    return {"assets": names}


@router.post("/api/practices/{practice_id}/questions/{pq_id}/blocks")
async def add_block(practice_id: str, pq_id: str, req: BlockCreateRequest,
                    db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    if req.block_type not in ("text", "image", "options", "answer_space"):
        raise HTTPException(400, f"不支持的块类型: {req.block_type}")
    content = req.content
    if req.block_type == "options" and not isinstance(content, str):
        content = json.dumps(content or [], ensure_ascii=False)  # 入参数组 → JSON 字符串落库
    pos = max([b.position for b in pq.blocks], default=-1) + 1
    block = PracticeContentBlock(
        practice_question_id=pq.id, block_type=req.block_type,
        position=pos, content=req.content, style_config=req.style)
    db.add(block)
    block_service.rebuild_content_from_blocks(pq)
    await db.commit()
    return await _question_payload(db, pq)


@router.put("/api/practices/{practice_id}/questions/{pq_id}/blocks/reorder")
async def reorder_blocks(practice_id: str, pq_id: str, req: BlockReorderRequest,
                         db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    bmap = {b.id: b for b in pq.blocks}
    for pos, bid in enumerate(req.block_ids):
        if bid in bmap:
            bmap[bid].position = pos
    block_service.rebuild_content_from_blocks(pq)
    await db.commit()
    return await _question_payload(db, pq)


@router.put("/api/practices/{practice_id}/questions/{pq_id}/blocks/{block_id}")
async def update_block(practice_id: str, pq_id: str, block_id: str,
                       req: BlockUpdateRequest, db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    block = next((b for b in pq.blocks if b.id == block_id), None)
    if not block:
        raise HTTPException(404, "Block not found")
    data = req.model_dump(exclude_unset=True)
    if "content" in data:
        block.content = data["content"]
    if "style" in data:
        block.style_config = data["style"]
    block_service.rebuild_content_from_blocks(pq)
    await db.commit()
    return await _question_payload(db, pq)


@router.delete("/api/practices/{practice_id}/questions/{pq_id}/blocks/{block_id}")
async def delete_block(practice_id: str, pq_id: str, block_id: str,
                       db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    block = next((b for b in pq.blocks if b.id == block_id), None)
    if not block:
        raise HTTPException(404, "Block not found")
    await db.delete(block)
    await db.flush()
    for pos, b in enumerate(sorted(pq.blocks, key=lambda x: x.position)):
        b.position = pos
    block_service.rebuild_content_from_blocks(pq)
    await db.commit()
    return await _question_payload(db, pq)


@router.post("/api/practices/{practice_id}/questions/{pq_id}/restore")
async def restore_question(practice_id: str, pq_id: str, db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    restored = await block_service.restore_question_from_source(db, pq)
    if not restored:
        raise HTTPException(404, "题库原题不存在或已删除，无法恢复")
    return await _question_payload(db, restored)
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `python -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/practice.py backend/app/routers/practices.py backend/tests/test_blocks_api.py
git commit -m "feat: 内容块编辑 API（增删改排/恢复/资产清单/详情懒物化）"
```

---

### Task 3: 结构编排 API（小节 + 题目增删移动 + 连续编号）

**Files:**
- Modify: `backend/app/routers/practices.py`
- Test: `backend/tests/test_structure_api.py`

**Interfaces:**
- Consumes: `_get_practice_full` / `_practice_response`；`map_question_type`（`app.utils.question_types`）。
- Produces:
  - `POST /api/practices/{id}/sections` body `{title, position?}` → 新建自定义小节（`section_type="custom"`）。
  - `PUT /api/practices/{id}/sections/{sid}` body `{title?, show_title?, start_on_new_page?}`。
  - `PUT /api/practices/{id}/sections/reorder` body `{section_ids: [...]}`。
  - `DELETE /api/practices/{id}/sections/{sid}`：还有题目时 400。
  - `DELETE /api/practices/{id}/questions/{qid}`：删除题目（块级联删除），重编号。
  - `PUT /api/practices/{id}/questions/{qid}/move` body `{target_section_id, target_position?}`：跨/组内移动；**不改变目标小节的 `section_type` 与标题**（小节名由用户与一键整理结构管理）。
  - `PUT /api/practices/{id}/questions/{qid}` body `{question_type?, difficulty?, score?}`：题目元数据编辑（同样不自动改小节名）。
  - **编号规则**：以上所有结构写操作成功后调用 `_renumber(practice)`——按 `sections.position` 顺序、题内按 `position` 顺序，`question_number` 全局从 1 连续重排。
  - 响应统一返回 `PracticeResponse`（除 move/元数据编辑可返回 `{"practice": PracticeResponse}`）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_structure_api.py`：

```python
"""API tests for practice structure editing."""

from test_blocks_api import _create_practice


async def _two_questions(client, test_db, tmp_path):
    """造含两题（选择题 + 填空题）的练习。"""
    from app.models import Source, Question
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True, exist_ok=True)
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q1 = Question(source_id=source.id, source_question_id="Q1", question_number=1,
                      question_type="single_choice", content="选择题题干",
                      options=[{"label": "A", "content": "x"}])
        q2 = Question(source_id=source.id, source_question_id="Q2", question_number=2,
                      question_type="fill_blank", content="填空题题干")
        db.add_all([q1, q2])
        await db.commit()
        await db.refresh(q1); await db.refresh(q2)
        ids = [q1.id, q2.id]
    res = await client.post("/api/practices", json={
        "title": "t", "from_basket": False, "question_ids": ids})
    return res.json()


async def test_add_and_delete_section(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.post(f"/api/practices/{pid}/sections", json={"title": "附加题"})
    assert res.status_code == 200
    new_sec = res.json()["sections"][-1]
    assert new_sec["title"] == "附加题" and new_sec["section_type"] == "custom"
    # 空小节可删，有题目的小节不可删
    res = await client.delete(f"/api/practices/{pid}/sections/{new_sec['id']}")
    assert res.status_code == 200
    busy = res.json()["sections"][0]
    res = await client.delete(f"/api/practices/{pid}/sections/{busy['id']}")
    assert res.status_code == 400


async def test_move_question_and_renumber(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    sec_choice = practice["sections"][0]   # 选择题（题号1）
    sec_fill = practice["sections"][1]     # 填空题（题号2）
    q_choice = sec_choice["questions"][0]
    # 把选择题移到填空题小节末尾 → 编号变 2，填空变 1；目标小节保留原名（填空题）
    res = await client.put(f"/api/practices/{pid}/questions/{q_choice['id']}/move",
                           json={"target_section_id": sec_fill["id"]})
    data = res.json()
    fill_sec = next(s for s in data["sections"] if s["id"] == sec_fill["id"])
    nums = [q["question_number"] for q in fill_sec["questions"]]
    assert nums == [1, 2]
    assert fill_sec["questions"][1]["id"] == q_choice["id"]
    assert fill_sec["title"] == "填空题"  # 小节名不随移入题目改变；题型归位交给一键整理结构
    assert len(data["sections"]) == 1  # 空选择题小节被保留与否不强制，题目归属正确即可；若实现保留空小节需与前端兼容——本实现删除空小节（见 Step 3）


async def test_delete_question(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    q1 = practice["sections"][0]["questions"][0]
    res = await client.delete(f"/api/practices/{pid}/questions/{q1['id']}")
    assert res.status_code == 200
    numbers = [q["question_number"] for s in res.json()["sections"] for q in s["questions"]]
    assert numbers == [1]  # 重新连续编号，且空小节被移除后只剩填空题（题号1）
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m pytest tests/test_structure_api.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 在 routers/practices.py 追加结构端点**

顶部补充 import：`from app.utils.question_types import map_question_type`。

编号与空小节整理：

```python
async def _renumber(db: AsyncSession, practice: Practice):
    """按小节顺序全练习连续编号；删除已空的小节。"""
    sections = (await db.execute(
        select(PracticeSection)
        .where(PracticeSection.practice_id == practice.id)
        .options(selectinload(PracticeSection.questions))
        .order_by(PracticeSection.position)
    )).scalars().all()
    n = 0
    for s in sections:
        if not s.questions:
            await db.delete(s)
            continue
        for pos, q in enumerate(sorted(s.questions, key=lambda x: x.position)):
            n += 1
            q.position = pos
            q.question_number = n
    kept = [s for s in sections if s.questions]
    for pos, s in enumerate(kept):
        s.position = pos
```

结构端点：

```python
class SectionCreateRequest(BaseModel):
    title: str
    position: int | None = None


class SectionUpdateRequest(BaseModel):
    title: str | None = None
    show_title: bool | None = None
    start_on_new_page: bool | None = None


class SectionReorderRequest(BaseModel):
    section_ids: list[str]


class QuestionMoveRequest(BaseModel):
    target_section_id: str
    target_position: int | None = None


class QuestionMetaUpdateRequest(BaseModel):
    question_type: str | None = None
    difficulty: int | None = None
    score: float | None = None


async def _get_section(db: AsyncSession, practice_id: str, section_id: str) -> PracticeSection:
    result = await db.execute(
        select(PracticeSection)
        .where(PracticeSection.id == section_id, PracticeSection.practice_id == practice_id)
        .options(selectinload(PracticeSection.questions)))
    section = result.scalar_one_or_none()
    if not section:
        raise HTTPException(404, "Section not found")
    return section


async def _practice_resp_after(db: AsyncSession, practice_id: str):
    """结构写操作后统一返回体。"""
    await db.commit()
    practice = await _get_practice_full(db, practice_id)
    return _practice_response(practice)


@router.post("/api/practices/{practice_id}/sections", response_model=PracticeResponse)
async def add_section(practice_id: str, req: SectionCreateRequest,
                      db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    count = len(practice.sections)
    section = PracticeSection(
        practice_id=practice_id, title=req.title, section_type="custom",
        position=req.position if req.position is not None else count)
    db.add(section)
    return await _practice_resp_after(db, practice_id)


@router.put("/api/practices/{practice_id}/sections/reorder", response_model=PracticeResponse)
async def reorder_sections(practice_id: str, req: SectionReorderRequest,
                           db: AsyncSession = Depends(get_db)):
    sections = (await db.execute(
        select(PracticeSection).where(PracticeSection.practice_id == practice_id)
    )).scalars().all()
    smap = {s.id: s for s in sections}
    for pos, sid in enumerate(req.section_ids):
        if sid in smap:
            smap[sid].position = pos
    return await _practice_resp_after(db, practice_id)


@router.put("/api/practices/{practice_id}/sections/{section_id}", response_model=PracticeResponse)
async def update_section(practice_id: str, section_id: str, req: SectionUpdateRequest,
                         db: AsyncSession = Depends(get_db)):
    section = await _get_section(db, practice_id, section_id)
    data = req.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(section, k, v)
    return await _practice_resp_after(db, practice_id)


@router.delete("/api/practices/{practice_id}/sections/{section_id}", response_model=PracticeResponse)
async def delete_section(practice_id: str, section_id: str, db: AsyncSession = Depends(get_db)):
    section = await _get_section(db, practice_id, section_id)
    if section.questions:
        raise HTTPException(400, "小节内仍有题目，无法删除；请先移走或删除题目")
    await db.delete(section)
    await _renumber(db, await db.get(Practice, practice_id))
    return await _practice_resp_after(db, practice_id)


@router.delete("/api/practices/{practice_id}/questions/{pq_id}", response_model=PracticeResponse)
async def delete_question(practice_id: str, pq_id: str, db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    await db.delete(pq)   # 块级联删除（外键 ondelete=CASCADE）
    await db.flush()
    await _renumber(db, await db.get(Practice, practice_id))
    return await _practice_resp_after(db, practice_id)


@router.put("/api/practices/{practice_id}/questions/{pq_id}/move", response_model=PracticeResponse)
async def move_question(practice_id: str, pq_id: str, req: QuestionMoveRequest,
                        db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    target = await _get_section(db, practice_id, req.target_section_id)
    positions = [q.position for q in target.questions if q.id != pq.id]
    pq.section_id = target.id
    pq.position = req.target_position if req.target_position is not None \
        else (max(positions, default=-1) + 1)
    # 不改目标小节的 section_type/标题；题型不一致时由一键整理结构处理
    await db.flush()
    await _renumber(db, await db.get(Practice, practice_id))
    return await _practice_resp_after(db, practice_id)


@router.put("/api/practices/{practice_id}/questions/{pq_id}", response_model=PracticeResponse)
async def update_question_meta(practice_id: str, pq_id: str, req: QuestionMetaUpdateRequest,
                               db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    data = req.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(pq, k, v)
    if data:
        pq.is_modified = True  # 元数据修改也计入已修改；小节名不随之改变
    return await _practice_resp_after(db, practice_id)
```

注意：`_load_pq` 来自 Task 2；`map_question_type` 返回中文题型名（与 `SECTION_TYPE_ORDER` 一致）。
`test_move_question_and_renumber` 断言删除空小节（`len(sections)==1`），与 `_renumber` 行为一致。
`QuestionMetaUpdateRequest.score` 类型与 `PracticeQuestion.score` 列保持一致（检查模型实际类型，若为 `Float` 则用 `float`）。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/practices.py backend/tests/test_structure_api.py
git commit -m "feat: 练习结构编排 API（小节/题目增删移动 + 连续编号）"
```

---

### Task 4: 一键排版 API（整理结构 + 统一排版）

**Files:**
- Modify: `backend/app/services/block_service.py`
- Modify: `backend/app/routers/practices.py`
- Test: `backend/tests/test_format_api.py`

**Interfaces:**
- Consumes: Task 1/2/3 全部；`SECTION_TYPE_ORDER`。
- Produces:
  - `plan_regroup(practice) -> dict`：干跑，返回 `{"changes": [str], "applies": bool}`（规格 9.3：执行前展示变化）。
  - `apply_regroup(db, practice)`：按题型重新分组——题目保留全局原顺序；题型小节按 `SECTION_TYPE_ORDER` 排序并置于最前；`section_type == "custom"` 的小节**整体保留原位置顺序置于最后**，其中的题目不动（不覆盖用户自定义结构）。
  - `unify_layout(db, practice) -> int`：只动 `style_config` 为空的块——image 块设 `IMAGE_DEFAULT_STYLE`；answer_space 块设题型默认行数（选择题类 0 行，`question_type` 为 `single_choice`/`multiple_choice` 时跳过）；返回调整块数。不改块顺序、不改题目顺序。
  - `POST /api/practices/{id}/regroup/preview` → plan 结果。
  - `POST /api/practices/{id}/regroup/apply` → `PracticeResponse`。
  - `POST /api/practices/{id}/layout/unify` → `{"adjusted": n}`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_format_api.py`：

```python
"""API tests for one-click formatting (regroup + unify layout)."""

from test_blocks_api import _create_practice
from test_structure_api import _two_questions


async def test_regroup(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    fill = practice["sections"][1]
    choice = practice["sections"][0]
    q_choice = choice["questions"][0]
    # 打乱：把选择题移到自定义小节之后（先造自定义小节再移入填空小节模拟错序）
    await client.post(f"/api/practices/{pid}/sections", json={"title": "附加题"})
    await client.put(f"/api/practices/{pid}/questions/{q_choice['id']}/move",
                     json={"target_section_id": fill["id"]})

    res = await client.post(f"/api/practices/{pid}/regroup/preview")
    assert res.json()["applies"] is True and res.json()["changes"]

    res = await client.post(f"/api/practices/{pid}/regroup/apply")
    secs = res.json()["sections"]
    assert secs[0]["section_type"] == "选择题"
    assert secs[-1]["section_type"] == "custom"  # 自定义小节置底且保留（空题）
    numbers = [q["question_number"] for s in secs for q in s["questions"]]
    assert numbers == sorted(numbers)


async def test_unify_layout(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path,
                                      question_type="fill_blank",
                                      options=None)
    pid = practice["id"]
    q = (await client.get(f"/api/practices/{pid}/detail")).json() \
        ["sections"][0]["questions"][0]
    # 定制留白 → 统一排版不得覆盖（规格 9.3）
    space = next(b for b in q["blocks"] if b["block_type"] == "answer_space")
    await client.put(f"/api/practices/{pid}/questions/{q['id']}/blocks/{space['id']}",
                     json={"style": {"rows": 12}})
    # 把图片样式清空（模拟未定制）→ 统一排版应补上默认样式，验证 unify 真实生效
    img = next(b for b in q["blocks"] if b["block_type"] == "image")
    await client.put(f"/api/practices/{pid}/questions/{q['id']}/blocks/{img['id']}",
                     json={"style": None})

    res = await client.post(f"/api/practices/{pid}/layout/unify")
    assert res.status_code == 200 and res.json()["adjusted"] >= 1

    q = (await client.get(f"/api/practices/{pid}/detail")).json() \
        ["sections"][0]["questions"][0]
    space = next(b for b in q["blocks"] if b["block_type"] == "answer_space")
    assert space["style"]["rows"] == 12          # 定制保留
    img = next(b for b in q["blocks"] if b["block_type"] == "image")
    assert img["style"] == {"align": "center", "width": "fit"}  # 未定制图片被统一
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m pytest tests/test_format_api.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 在 block_service.py 追加排版函数**

```python
from app.models.practice import Practice, PracticeSection  # 顶部 import 合并进现有行
from app.services.practice_service import SECTION_TYPE_ORDER


async def plan_regroup(practice: Practice) -> dict:
    """干跑整理结构：返回变化描述（规格 9.3 执行前展示变化）。"""
    changes: list[str] = []
    groups: dict[str, list] = {}
    for s in sorted(practice.sections, key=lambda x: x.position):
        for q in sorted(s.questions, key=lambda x: x.position):
            zh = map_question_type(q.question_type)
            groups.setdefault(zh, []).append((s, q))
    expected = [t for t in SECTION_TYPE_ORDER if t in groups]
    # 当前非 custom 小节序列（去重保序）
    current = []
    for s in sorted(practice.sections, key=lambda x: x.position):
        if s.section_type != "custom" and s.title not in current:
            current.append(s.title)
    if current != expected:
        changes.append("题型小节将按固定顺序重排：" + "、".join(expected))
    for zh, qs in groups.items():
        sec_of = {s.title for s, _ in qs}
        if len(sec_of) > 1:
            changes.append(f"《{zh}》的题目分散在多个小节，将合并")
        for s, q in qs:
            if s.section_type == "custom":
                changes.append(f"题目（编号{q.question_number}）将从自定义小节《{s.title}》移入《{zh}》")
    return {"changes": changes, "applies": bool(changes)}


async def apply_regroup(db: AsyncSession, practice: Practice):
    """按题型重新分组；自定义小节整体保留并置底；题目保持全局原顺序。"""
    ordered_qs = [q for s in sorted(practice.sections, key=lambda x: x.position)
                  for q in sorted(s.questions, key=lambda x: x.position)]
    customs = [s for s in sorted(practice.sections, key=lambda x: x.position)
               if s.section_type == "custom"]
    old_sections = [s for s in practice.sections if s.section_type != "custom"]
    for s in old_sections:
        await db.delete(s)
    await db.flush()

    groups: dict[str, list] = {}
    for q in ordered_qs:
        groups.setdefault(map_question_type(q.question_type), []).append(q)
    pos = 0
    for zh in [t for t in SECTION_TYPE_ORDER if t in groups]:
        section = PracticeSection(practice_id=practice.id, title=zh,
                                  section_type=zh, position=pos)
        db.add(section)
        await db.flush()
        for q in groups[zh]:
            q.section_id = section.id
        pos += 1
    for s in customs:
        s.position = pos
        pos += 1
    await db.flush()
    await db.commit()


async def unify_layout(db: AsyncSession, practice: Practice) -> int:
    """统一排版：只覆盖未定制（style_config 为空）的块样式；不动顺序。"""
    adjusted = 0
    qmap = {}
    for s in practice.sections:
        for q in s.questions:
            qmap[q.id] = q
    blocks = (await db.execute(
        select(PracticeContentBlock).where(
            PracticeContentBlock.practice_question_id.in_(list(qmap.keys())))
    )).scalars().all()
    for b in blocks:
        if b.style_config:
            continue  # 用户已定制，不覆盖（规格 9.3）
        if b.block_type == "image":
            b.style_config = dict(IMAGE_DEFAULT_STYLE)
            adjusted += 1
        elif b.block_type == "answer_space":
            q = qmap[b.practice_question_id]
            if q.question_type in ("single_choice", "multiple_choice"):
                continue
            b.style_config = {"rows": DEFAULT_ANSWER_SPACE.get(q.question_type, 4)}
            adjusted += 1
    await db.commit()
    return adjusted
```

顶部补充 import：`from app.utils.question_types import map_question_type`。

- [ ] **Step 4: 在 routers/practices.py 追加排版端点**

```python
@router.post("/api/practices/{practice_id}/regroup/preview")
async def regroup_preview(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    return await block_service.plan_regroup(practice)


@router.post("/api/practices/{practice_id}/regroup/apply", response_model=PracticeResponse)
async def regroup_apply(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    await block_service.apply_regroup(db, practice)
    await _renumber(db, await db.get(Practice, practice_id))
    await db.commit()
    practice = await _get_practice_full(db, practice_id)
    return _practice_response(practice)


@router.post("/api/practices/{practice_id}/layout/unify")
async def layout_unify(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    # 先确保每题已物化块，再统一排版，否则未进过编辑器的题不会被处理
    for s in practice.sections:
        for pq in s.questions:
            await block_service.materialize_blocks(db, pq)
    practice = await _get_practice_full(db, practice_id)
    n = await block_service.unify_layout(db, practice)
    return {"adjusted": n}
```

`_renumber` 来自 Task 3（同文件）。

- [ ] **Step 5: 运行测试，确认通过**

Run: `python -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/block_service.py backend/app/routers/practices.py backend/tests/test_format_api.py
git commit -m "feat: 一键排版（整理结构预览/应用 + 统一排版，尊重用户定制）"
```

---

### Task 5: 练习级设置 + 前端编辑器页面骨架与结构树交互

**Files:**
- Modify: `backend/app/schemas/practice.py`（`PracticeUpdateRequest` 加 `page_config`；`PracticeQuestionOut` 加 `layout_config`；`PracticeResponse` 加 `page_config`）
- Modify: `backend/app/routers/practices.py`（PUT 支持 page_config；出参透出 page_config / layout_config）
- Test: `backend/tests/test_practice_settings.py`
- Create: `frontend/src/views/PracticeEditorView.vue`（本任务完成：页面框架 + 结构树 + 小节管理 + 题目移动/删除 + 练习设置对话框 + 一键排版按钮；块编辑区在 Task 6）
- Modify: `frontend/src/router/index.js`

**Interfaces:**
- Consumes: Task 1-4 全部后端接口；`GET /api/practices/{id}/detail`。
- Produces:
  - `PUT /api/practices/{id}` 新增可选 `page_config`（dict，如 `{show_info_bar: true}`）；`PracticeResponse.page_config`、`PracticeQuestionOut.layout_config` 透出（单题留白覆盖 `{answer_space: {rows}}` 存 `layout_config`，阶段三渲染时优先于块默认值）。
  - 路由 `/practice/editor?id=<practiceId>`；练习列表详情对话框“进入编辑器”按钮启用并跳转。
  - `PracticeEditorView.vue` 对外行为：加载 `GET /api/practices/{id}/detail`；左树点选题目（为 Task 6 预留 `selected` 状态）；新增/重命名/删除小节、显示标题/新页开关；题目上移下移/移到小节/删除；顶栏“整理结构”（先调 `/regroup/preview`，展示变化列表确认后 `/regroup/apply`）、“统一排版”（`/layout/unify` 后提示调整块数）、“练习设置”（标题/副标题/学生信息栏，调 `PUT /api/practices/{id}`）；右侧预览占位面板（阶段三接入）。
- 前端题型选项用全局已注册的 `QUESTION_TYPE_MAP`（`frontend/src/utils/questionTypes.js`）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_practice_settings.py`：

```python
"""API tests for practice-level settings (page_config / layout_config passthrough)."""

from test_blocks_api import _create_practice


async def test_update_page_config(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.put(f"/api/practices/{pid}",
                           json={"title": "新标题", "page_config": {"show_info_bar": True}})
    assert res.status_code == 200
    assert res.json()["page_config"] == {"show_info_bar": True}
    assert res.json()["title"] == "新标题"


async def test_layout_config_passthrough(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    detail = (await client.get(f"/api/practices/{pid}/detail")).json()
    q = detail["sections"][0]["questions"][0]
    assert "layout_config" in q  # 默认 None，字段存在即可（单题留白覆盖用）
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m pytest tests/test_practice_settings.py -q`
Expected: FAIL（page_config 字段未透出/未保存）

- [ ] **Step 3: 后端透出与保存 page_config**

schemas/practice.py：

```python
class PracticeUpdateRequest(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None
    page_config: dict | None = None


class PracticeQuestionOut(BaseModel):
    # ... 现有字段不变，追加：
    layout_config: dict | None = None


class PracticeResponse(BaseModel):
    # ... 现有字段不变，追加：
    page_config: dict | None = None
```

routers/practices.py：`update_practice` 中对 `PracticeUpdateRequest` 的赋值循环天然包含 `page_config`（`data = req.model_dump(exclude_unset=True)` 后 setattr）——若现有实现逐字段写死，则改为遍历 `model_dump(exclude_unset=True)`。`_practice_response` 追加 `page_config=practice.page_config`；构造 `PracticeQuestionOut` 处追加 `layout_config=pq.layout_config`。

- [ ] **Step 4: 运行后端测试**

Run: `python -m pytest tests -q`
Expected: PASS

- [ ] **Step 5: 路由与编辑器页面框架**

`frontend/src/router/index.js` 追加：

```js
{
  path: '/practice/editor',
  name: 'PracticeEditor',
  component: () => import('../views/PracticeEditorView.vue'),
},
```

创建 `frontend/src/views/PracticeEditorView.vue`（本任务完成骨架 + 结构树，块编辑区留待 Task 6 在 `<!-- 块编辑区 -->` 占位处实现）：

```vue
<template>
  <div class="editor-page">
    <div class="editor-header">
      <div class="header-left">
        <el-button text @click="$router.push('/practices')">&larr; 返回列表</el-button>
        <b>{{ practice?.title || '加载中…' }}</b>
        <el-tag v-if="practice?.grade" size="small">{{ practice.grade }}</el-tag>
        <span class="qcount">{{ practice?.question_count || 0 }} 题</span>
      </div>
      <div>
        <el-button @click="openSettings"><el-icon><Setting /></el-icon> 练习设置</el-button>
        <el-button @click="previewRegroup"><el-icon><Sort /></el-icon> 整理结构</el-button>
        <el-button @click="unifyLayout"><el-icon><MagicStick /></el-icon> 统一排版</el-button>
      </div>
    </div>

    <div class="editor-body">
      <!-- 左：结构树 -->
      <div class="tree-panel">
        <div class="panel-head">
          <span>练习结构</span>
          <el-button size="small" text type="primary" @click="addSection">+ 小节</el-button>
        </div>
        <div v-for="s in practice?.sections || []" :key="s.id" class="tree-section">
          <div class="section-row">
            <b>{{ s.title }}</b>
            <el-tag v-if="s.section_type === 'custom'" size="small">自定义</el-tag>
            <span class="row-ops">
              <el-tooltip content="显示/隐藏标题"><el-switch v-model="s.show_title" size="small" @change="patchSection(s, { show_title: $event })" /></el-tooltip>
              <el-tooltip content="从新页开始"><el-switch v-model="s.start_on_new_page" size="small" @change="patchSection(s, { start_on_new_page: $event })" /></el-tooltip>
              <el-button size="small" text @click="renameSection(s)">✏</el-button>
              <el-button size="small" text type="danger" @click="removeSection(s)">✖</el-button>
            </span>
          </div>
          <div v-for="q in s.questions" :key="q.id"
               class="tree-question" :class="{ active: selected?.id === q.id }"
               @click="selectQuestion(s, q)">
            <span class="q-label">{{ q.question_number }}.
              <el-tag v-if="q.is_modified" size="small" type="warning">改</el-tag>
            </span>
            <span class="q-preview">{{ (q.content || '').slice(0, 20) }}</span>
            <span class="q-ops" @click.stop>
              <el-button size="small" text @click="moveUp(s, q)">↑</el-button>
              <el-button size="small" text @click="moveDown(s, q)">↓</el-button>
              <el-button size="small" text @click="openMove(q)">⇄</el-button>
              <el-button size="small" text type="danger" @click="removeQuestion(q)">✖</el-button>
            </span>
          </div>
        </div>
        <el-empty v-if="!practice?.sections?.length" description="暂无题目" :image-size="60" />
      </div>

      <!-- 中：块编辑区（Task 6 实现） -->
      <div class="edit-panel">
        <!-- 块编辑区 -->
        <el-empty v-if="!selected" description="从左侧选择一道题开始编辑" />
      </div>

      <!-- 右：预览占位（阶段三接入） -->
      <div class="preview-panel">
        <el-empty description="A4 预览将在阶段三接入" :image-size="80" />
      </div>
    </div>

    <!-- 整理结构确认 -->
    <el-dialog v-model="showRegroup" title="整理结构" width="480px">
      <template v-if="regroup.changes?.length">
        <p>将发生以下变化：</p>
        <ul><li v-for="(c, i) in regroup.changes" :key="i">{{ c }}</li></ul>
      </template>
      <p v-else>当前结构已符合题型分组规则，无需调整。</p>
      <template #footer>
        <el-button @click="showRegroup = false">取消</el-button>
        <el-button type="primary" :disabled="!regroup.changes?.length" @click="applyRegroup">确认整理</el-button>
      </template>
    </el-dialog>

    <!-- 移动到小节 -->
    <el-dialog v-model="showMove" title="移动到小节" width="380px">
      <el-select v-model="moveTarget" placeholder="选择目标小节" style="width:100%">
        <el-option v-for="s in practice.sections" :key="s.id" :label="s.title" :value="s.id" />
      </el-select>
      <template #footer>
        <el-button @click="showMove = false">取消</el-button>
        <el-button type="primary" @click="doMove">移动</el-button>
      </template>
    </el-dialog>

    <!-- 练习设置 -->
    <el-dialog v-model="showSettings" title="练习设置" width="420px">
      <el-form label-width="90px">
        <el-form-item label="标题"><el-input v-model="settingsForm.title" /></el-form-item>
        <el-form-item label="副标题"><el-input v-model="settingsForm.subtitle" /></el-form-item>
        <el-form-item label="学生信息栏"><el-switch v-model="settingsForm.showInfoBar" />
          <span class="hint">导出时显示姓名/班级/日期栏</span></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSettings = false">取消</el-button>
        <el-button type="primary" @click="saveSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const router = useRouter()
const practiceId = route.query.id

const practice = ref(null)
const selected = ref(null)
const selectedSection = ref(null)
const showRegroup = ref(false)
const regroup = ref({ changes: [] })
const showMove = ref(false)
const moveTarget = ref('')
const moveQuestionTarget = ref(null)
const showSettings = ref(false)
const settingsForm = reactive({ title: '', subtitle: '', showInfoBar: true })

const load = async () => {
  const res = await axios.get(`/api/practices/${practiceId}/detail`)
  practice.value = res.data
}

const selectQuestion = (s, q) => { selected.value = q; selectedSection.value = s; normalizeBlocks() }
const normalizeBlocks = () => {  // 旧块可能无 style，前端统一补空对象避免模板报错
  for (const b of (selected.value?.blocks || [])) { if (!b.style) b.style = {} }
}
const refresh = async () => { await load(); selected.value = null }

/* ---- 小节管理 ---- */
const addSection = async () => {
  const { value } = await ElMessageBox.prompt('小节名称', '新增小节', { inputValue: '自定义小节' })
  if (!value?.trim()) return
  await axios.post(`/api/practices/${practiceId}/sections`, { title: value.trim() })
  await load()
}
const renameSection = async (s) => {
  const { value } = await ElMessageBox.prompt('小节名称', '重命名小节', { inputValue: s.title })
  if (!value?.trim()) return
  await axios.put(`/api/practices/${practiceId}/sections/${s.id}`, { title: value.trim() })
  await load()
}
const patchSection = async (s, patch) => {
  await axios.put(`/api/practices/${practiceId}/sections/${s.id}`, patch)
}
const removeSection = async (s) => {
  if (s.questions?.length) { ElMessage.warning('该小节内仍有题目，请先移走或删除题目'); return }
  await ElMessageBox.confirm(`删除小节“${s.title}”？`, '提示', { type: 'warning' })
  await axios.delete(`/api/practices/${practiceId}/sections/${s.id}`)
  await load()
}

/* ---- 题目移动/删除 ---- */
const moveUp = async (s, q) => {
  const idx = s.questions.findIndex(x => x.id === q.id)
  if (idx <= 0) return
  await axios.put(`/api/practices/${practiceId}/questions/${q.id}/move`,
    { target_section_id: s.id, target_position: s.questions[idx - 1].position })
  await refresh()
}
const moveDown = async (s, q) => {
  const idx = s.questions.findIndex(x => x.id === q.id)
  if (idx < 0 || idx >= s.questions.length - 1) return
  await axios.put(`/api/practices/${practiceId}/questions/${q.id}/move`,
    { target_section_id: s.id, target_position: s.questions[idx + 1].position })
  await refresh()
}
const openMove = (q) => { moveQuestionTarget.value = q; moveTarget.value = ''; showMove.value = true }
const doMove = async () => {
  if (!moveTarget.value) return
  await axios.put(`/api/practices/${practiceId}/questions/${moveQuestionTarget.value.id}/move`,
    { target_section_id: moveTarget.value })
  showMove.value = false
  await refresh()
}
const removeQuestion = async (q) => {
  await ElMessageBox.confirm(`删除第 ${q.question_number} 题？删除后不可恢复。`, '提示', { type: 'warning' })
  await axios.delete(`/api/practices/${practiceId}/questions/${q.id}`)
  await refresh()
}

/* ---- 一键排版 ---- */
const previewRegroup = async () => {
  const res = await axios.post(`/api/practices/${practiceId}/regroup/preview`)
  regroup.value = res.data
  showRegroup.value = true
}
const applyRegroup = async () => {
  await axios.post(`/api/practices/${practiceId}/regroup/apply`)
  showRegroup.value = false
  ElMessage.success('已按题型整理结构')
  await refresh()
}
const unifyLayout = async () => {
  const res = await axios.post(`/api/practices/${practiceId}/layout/unify`)
  ElMessage.success(`已统一排版，调整了 ${res.data.adjusted} 个内容块`)
  await refresh()
}

/* ---- 练习设置 ---- */
const openSettings = () => {
  settingsForm.title = practice.value.title
  settingsForm.subtitle = practice.value.subtitle || ''
  settingsForm.showInfoBar = practice.value.page_config?.show_info_bar ?? true
  showSettings.value = true
}
const saveSettings = async () => {
  await axios.put(`/api/practices/${practiceId}`, {
    title: settingsForm.title,
    subtitle: settingsForm.subtitle || null,
    page_config: { ...(practice.value.page_config || {}), show_info_bar: settingsForm.showInfoBar },
  })
  showSettings.value = false
  ElMessage.success('已保存')
  await load()
}

onMounted(async () => {
  if (!practiceId) { router.push('/practices'); return }
  await load()
})
</script>

<style scoped>
.editor-page { display: flex; flex-direction: column; height: calc(100vh - 60px); }
.editor-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; border-bottom: 1px solid #ebeef5; }
.header-left { display: flex; align-items: center; gap: 8px; }
.qcount { color: #909399; font-size: 13px; }
.editor-body { flex: 1; display: flex; min-height: 0; }
.tree-panel { width: 290px; border-right: 1px solid #ebeef5; overflow-y: auto; padding: 8px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; padding: 4px 4px 8px; font-weight: bold; }
.tree-section { margin-bottom: 10px; }
.section-row { display: flex; align-items: center; gap: 6px; padding: 4px; background: #f5f7fa; border-radius: 4px; }
.section-row b { flex: 1; font-size: 13px; }
.row-ops { display: flex; align-items: center; gap: 2px; }
.tree-question { display: flex; align-items: center; gap: 6px; padding: 5px 6px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.tree-question:hover { background: #f0f9eb; }
.tree-question.active { background: #ecf5ff; }
.q-label { white-space: nowrap; }
.q-preview { flex: 1; color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.q-ops { display: none; }
.tree-question:hover .q-ops { display: inline-flex; }
.edit-panel { flex: 1; overflow-y: auto; padding: 16px; background: #fafafa; }
.preview-panel { width: 260px; border-left: 1px solid #ebeef5; display: flex; align-items: center; justify-content: center; color: #c0c4cc; }
.hint { color: #909399; font-size: 12px; margin-left: 8px; }
</style>
```

说明：`Setting`/`Sort`/`MagicStick` 图标已在 `main.js` 全局注册，模板直接用。
本任务不实现块编辑区；`selected` 状态为 Task 6 预留。

- [ ] **Step 6: 前端构建验证**

Run（工作目录 `frontend/`）：`$env:PATH = "C:\Users\Administrator\.conda\envs\question_platform;" + $env:PATH ; node node_modules/vite/bin/vite.js build`
Expected: build 成功

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/practice.py backend/app/routers/practices.py backend/tests/test_practice_settings.py frontend/src/views/PracticeEditorView.vue frontend/src/router/index.js
git commit -m "feat: 练习编辑器骨架（结构树/小节管理/题目移动/练习设置/一键排版入口）"
```

---

### Task 6: 块编辑区前端实现（纠错/图片/选项/留白/恢复）

**Files:**
- Modify: `frontend/src/views/PracticeEditorView.vue`

**Interfaces:**
- Consumes: Task 2 块 API（增删改排/恢复/资产清单）、Task 3 元数据编辑（`PUT /questions/{qid}`）；`QUESTION_TYPE_MAP`（`frontend/src/utils/questionTypes.js`）。
- Produces: 选中题目后展示全部编辑能力（规格 8.4/8.6 + 决策 6）：
  - 题头：题型下拉（选项来自 `QUESTION_TYPE_MAP`）、难度下拉（1-5）、分值输入、`已修改`标签、`恢复题库版本`按钮（调 `/restore`，成功后 `ElMessage.success('已恢复为题库原始内容')`）。
  - 文字块：`el-input type="textarea" :autosize="{minRows:2}"`，`@change` 调块更新；块工具条：上移/下移/删除/在其后插入文字块。
  - 图片块：`<img :src="b.content">`（已是 HTTP URL）；对齐选择 left/center/right；宽度预设（适应/50%/80%/100%）+ 自定义百分比数字输入；上移/下移/删除；样式变更调块更新 `style`。
  - 选项块：遍历数组渲染 `label + content` 输入，增/删选项按钮；变更后整体调块更新 `content`（数组）。
  - 留白块：行数下拉（无/2/4/8/12/自定义），写入块 `style.rows`；另提供“本题自定义留白”数字输入，写入题目 `layout_config = {answer_space: {rows}}`（调 `PUT /questions/{qid}` 不支持该字段——通过块 style 已够用；本项仅预留说明，实现上以块 style 为准，`layout_config` 字段后端已透出供阶段三使用，前端不写）。
  - 插入图片：对话框列出 `GET /assets-list` 文件名，选中后调块新增 `{block_type:'image', content:'asset://practice/<name>'}`。
  - 所有块操作成功后用响应体就地更新 `selected.value`（响应含 `question` + `blocks`），再 `load()` 同步左树编号。

- [ ] **Step 1: 实现块编辑区**

把 Task 5 模板中的占位：

```html
        <!-- 块编辑区 -->
        <el-empty v-if="!selected" description="从左侧选择一道题开始编辑" />
```

替换为：

```html
        <el-empty v-if="!selected" description="从左侧选择一道题开始编辑" />
        <div v-else class="question-editor">
          <div class="qe-header">
            <b>第 {{ selected.question_number }} 题</b>
            <el-tag v-if="selected.is_modified" size="small" type="warning">已修改</el-tag>
            <el-select v-model="selected.question_type" size="small" style="width:110px" @change="updateMeta">
              <el-option v-for="(zh, k) in QUESTION_TYPE_MAP" :key="k" :label="zh" :value="k" />
            </el-select>
            <el-select v-model="selected.difficulty" size="small" placeholder="难度" clearable style="width:90px" @change="updateMeta">
              <el-option v-for="d in 5" :key="d" :label="`${d} 级`" :value="d" />
            </el-select>
            <el-input-number v-model="selected.score" size="small" :min="0" :precision="1" placeholder="分值" controls-position="right" style="width:110px" @change="updateMeta" />
            <span class="flex-gap" />
            <el-button size="small" @click="restoreQuestion"><el-icon><RefreshLeft /></el-icon> 恢复题库版本</el-button>
          </div>

          <div v-for="b in selected.blocks" :key="b.id" class="qe-block">
            <div class="block-tools">
              <el-tag size="small" type="info">{{ BLOCK_LABEL[b.block_type] }}</el-tag>
              <el-button size="small" text @click="moveBlock(b, -1)">↑</el-button>
              <el-button size="small" text @click="moveBlock(b, 1)">↓</el-button>
              <template v-if="b.block_type === 'text'">
                <el-button size="small" text @click="insertTextAfter(b)">+文字</el-button>
              </template>
              <template v-if="b.block_type === 'image'">
                <el-select v-model="b.style.align" size="small" style="width:88px" @change="saveStyle(b)">
                  <el-option label="左对齐" value="left" /><el-option label="居中" value="center" /><el-option label="右对齐" value="right" />
                </el-select>
                <el-select :model-value="WIDTH_PRESET_MAP[b.style.width] || 'custom'" size="small" style="width:96px" @change="v => applyWidth(b, v)">
                  <el-option v-for="w in WIDTH_PRESETS" :key="w.value" :label="w.label" :value="w.value" />
                  <el-option label="自定义" value="custom" />
                </el-select>
                <el-input-number v-if="WIDTH_PRESET_MAP[b.style.width] === undefined" v-model="customWidth" size="small" :min="10" :max="100" style="width:96px" @change="v => { b.style.width = v + '%'; saveStyle(b) }" />
              </template>
              <template v-if="b.block_type === 'answer_space'">
                <el-select :model-value="b.style.rows" size="small" style="width:104px" @change="v => { b.style.rows = Number(v); saveStyle(b) }">
                  <el-option label="无留白" :value="0" /><el-option label="小（2 行）" :value="2" /><el-option label="中（4 行）" :value="4" /><el-option label="大（8 行）" :value="8" /><el-option label="超大（12 行）" :value="12" />
                </el-select>
              </template>
              <el-button size="small" text type="danger" @click="deleteBlock(b)">删除</el-button>
            </div>

            <div v-if="b.block_type === 'text'">
              <el-input type="textarea" :autosize="{ minRows: 2 }" v-model="b.content" @change="saveText(b)" />
            </div>
            <div v-else-if="b.block_type === 'image'" class="img-block" :style="{ textAlign: (b.style && b.style.align) || 'center' }">
              <img :src="b.content" :style="{ width: widthCss(b) }" />
            </div>
            <div v-else-if="b.block_type === 'options'" class="options-block">
              <div v-for="(opt, oi) in (b.content || [])" :key="oi" class="option-row">
                <el-input v-model="opt.label" style="width:56px" size="small" />
                <el-input v-model="opt.content" size="small" @change="saveOptions(b)" />
                <el-button size="small" text type="danger" @click="removeOption(b, oi)">✖</el-button>
              </div>
              <el-button size="small" @click="addOption(b)">+ 选项</el-button>
            </div>
            <div v-else-if="b.block_type === 'answer_space'" class="space-block">答题留白 {{ (b.style && b.style.rows) || 0 }} 行</div>
          </div>

          <div class="qe-actions">
            <el-button size="small" @click="insertTextAfter(null)">+ 文字块</el-button>
            <el-button size="small" @click="openImagePicker">+ 图片块</el-button>
          </div>
        </div>
```

并在对话框区追加图片选择器（放在练习设置对话框之后）：

```html
    <!-- 插入图片 -->
    <el-dialog v-model="showImagePicker" title="插入图片" width="420px">
      <el-empty v-if="!assets.length" description="该练习暂无图片资产" :image-size="60" />
      <div v-else class="asset-grid">
        <div v-for="a in assets" :key="a" class="asset-item" @click="insertImage(a)">
          <img :src="`/api/practices/${practiceId}/assets/${a}`" />
          <span>{{ a.slice(0, 18) }}</span>
        </div>
      </div>
    </el-dialog>
```

script 追加（放在现有逻辑之后）：

```js
import { QUESTION_TYPE_MAP } from '../utils/questionTypes'

const BLOCK_LABEL = { text: '文字', image: '图片', options: '选项', answer_space: '留白' }
const WIDTH_PRESETS = [
  { label: '适应内容', value: 'fit' },
  { label: '50%', value: '50%' },
  { label: '80%', value: '80%' },
  { label: '100%', value: '100%' },
]
const WIDTH_PRESET_MAP = Object.fromEntries(WIDTH_PRESETS.map(w => [w.value, w.value]))

const assets = ref([])
const showImagePicker = ref(false)
const customWidth = ref(60)

const widthCss = (b) => {
  const w = b.style && b.style.width
  if (!w || w === 'fit') return 'auto'
  if (typeof w === 'number') return w + '%'
  return w
}
const ensureStyle = (b) => { if (!b.style) b.style = {}; return b.style }

/* 块操作：响应体含 { question, blocks }，就地更新当前选中题 */
const applyBlockResp = async (res) => {
  const { question, blocks } = res.data
  selected.value = question
  selected.value.blocks = blocks
  await load()  // 同步左树编号/已修改标记；注意保持 selected 引用：
  const sec = practice.value.sections.find(s => s.questions.some(q => q.id === selected.value.id))
  if (sec) { selectedSection.value = sec; selected.value = sec.questions.find(q => q.id === selected.value.id) }
  normalizeBlocks()
}

const saveText = async (b) => {
  const res = await axios.put(`/api/practices/${practiceId}/questions/${selected.value.id}/blocks/${b.id}`, { content: b.content })
  await applyBlockResp(res)
}
const saveStyle = async (b) => {
  const res = await axios.put(`/api/practices/${practiceId}/questions/${selected.value.id}/blocks/${b.id}`, { style: b.style })
  await applyBlockResp(res)
}
const applyWidth = (b, v) => {
  ensureStyle(b)
  if (v !== 'custom') { b.style.width = v; saveStyle(b) }
}
const saveOptions = async (b) => {
  const res = await axios.put(`/api/practices/${practiceId}/questions/${selected.value.id}/blocks/${b.id}`, { content: b.content })
  await applyBlockResp(res)
}
const addOption = (b) => {
  const labels = 'ABCDEFGHIJKLMN'
  b.content = b.content || []
  b.content.push({ label: labels[b.content.length] || '?', content: '' })
  saveOptions(b)
}
const removeOption = (b, oi) => { b.content.splice(oi, 1); saveOptions(b) }

const moveBlock = async (b, delta) => {
  const ids = selected.value.blocks.map(x => x.id)
  const i = ids.indexOf(b.id)
  const j = i + delta
  if (i < 0 || j < 0 || j >= ids.length) return
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
  const res = await axios.put(`/api/practices/${practiceId}/questions/${selected.value.id}/blocks/reorder`, { block_ids: ids })
  await applyBlockResp(res)
}
const deleteBlock = async (b) => {
  await ElMessageBox.confirm('删除该块？其内容将从练习快照中移除（题库原题不受影响）。', '提示', { type: 'warning' })
  const res = await axios.delete(`/api/practices/${practiceId}/questions/${selected.value.id}/blocks/${b.id}`)
  await applyBlockResp(res)
}
const insertTextAfter = async (b) => {
  const res = await axios.post(`/api/practices/${practiceId}/questions/${selected.value.id}/blocks`,
    { block_type: 'text', content: '' })
  await applyBlockResp(res)
  if (b) {
    // 移到目标块之后：重建顺序数组再调 reorder
    const blocks = selected.value.blocks
    const nb = blocks[blocks.length - 1]
    const ids = blocks.filter(x => x.id !== nb.id).map(x => x.id)
    ids.splice(ids.indexOf(b.id) + 1, 0, nb.id)
    const res2 = await axios.put(`/api/practices/${practiceId}/questions/${selected.value.id}/blocks/reorder`, { block_ids: ids })
    await applyBlockResp(res2)
  }
}
const openImagePicker = async () => {
  const res = await axios.get(`/api/practices/${practiceId}/assets-list`)
  assets.value = res.data.assets
  showImagePicker.value = true
}
const insertImage = async (name) => {
  const res = await axios.post(`/api/practices/${practiceId}/questions/${selected.value.id}/blocks`,
    { block_type: 'image', content: `asset://practice/${name}`, style: { align: 'center', width: 'fit' } })
  await applyBlockResp(res)
  showImagePicker.value = false
}
const restoreQuestion = async () => {
  await ElMessageBox.confirm('恢复为题库原始内容？当前练习中对该题的所有修改将丢失（题库原题不受影响）。', '提示', { type: 'warning' })
  const res = await axios.post(`/api/practices/${practiceId}/questions/${selected.value.id}/restore`)
  await applyBlockResp(res)
  ElMessage.success('已恢复为题库原始内容')
}
const updateMeta = async () => {
  await axios.put(`/api/practices/${practiceId}/questions/${selected.value.id}`, {
    question_type: selected.value.question_type,
    difficulty: selected.value.difficulty ?? null,
    score: selected.value.score ?? null,
  })
  await load()
}
```

样式追加（并入 `<style scoped>`）：

```css
.question-editor { max-width: 760px; margin: 0 auto; }
.qe-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.flex-gap { flex: 1; }
.qe-block { background: #fff; border: 1px solid #ebeef5; border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.block-tools { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; }
.block-tools .el-button { padding: 0 4px; }
.img-block img { max-height: 160px; border-radius: 4px; }
.option-row { display: flex; gap: 6px; margin-bottom: 6px; align-items: center; }
.space-block { color: #909399; font-size: 13px; }
.qe-actions { margin-top: 12px; }
.asset-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.asset-item { cursor: pointer; text-align: center; font-size: 12px; color: #606266; }
.asset-item img { width: 100%; max-height: 90px; object-fit: contain; border: 1px solid #ebeef5; border-radius: 4px; }
```

- [ ] **Step 2: 前端构建验证**

Run：`$env:PATH = "C:\Users\Administrator\.conda\envs\question_platform;" + $env:PATH ; node node_modules/vite/bin/vite.js build`
Expected: build 成功

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/PracticeEditorView.vue
git commit -m "feat: 块编辑区（文字/图片/选项/留白编辑 + 恢复题库版本）"
```

---

### Task 7: 入口打通与验收（阶段二收尾）

**Files:**
- Modify: `frontend/src/views/PracticeListView.vue`（启用“进入编辑器”）
- 无新后端改动；全量回归 + 冒烟。

**Interfaces:**
- Consumes: 全部阶段二成果。
- Produces: 规格场景二全链路可用；阶段二验收通过。

- [ ] **Step 1: 修改 PracticeListView.vue**

将只读详情对话框底部：

```html
        <el-tooltip content="阶段二开放" placement="top">
          <el-button type="primary" disabled>进入编辑器</el-button>
        </el-tooltip>
```

替换为：

```html
        <el-button type="primary" @click="$router.push('/practice/editor?id=' + detail.id)">进入编辑器</el-button>
```

同时把顶部副标题“编辑器即将开放”改为“点击进入编辑器开始整理题目”。
`renderPreview` 已引入，无需变更。
`PracticeListView.openDetail` 可继续用 `GET /api/practices/{id}`（不含块，只读预览够用）。
`main.py` 无需改动（未新增 router）。

- [ ] **Step 2: 全量后端测试 + 前端构建**

Run: `python -m pytest tests -q`（期望 ≥ 40 项全过）
Run: `$env:PATH = "C:\Users\Administrator\.conda\envs\question_platform;" + $env:PATH ; node node_modules/vite/bin/vite.js build`
Expected: 全部通过；`alembic current` 保持 `7be1dc9c4638 (head)`（本阶段无新迁移）

- [ ] **Step 3: 真实库冒烟（后端 `--reload` 已运行，改动自动生效）**

用真实题库数据（取一题带图题目）走完整链路，验证后清理：
1. `GET /api/questions?page=1&page_size=1` 取一题 `questionId`；
2. `POST /api/basket/items {question_ids:[questionId]}`；
3. `POST /api/practices {title:'阶段二冒烟', from_basket:true}` → `practiceId`；
4. `GET /api/practices/{practiceId}/detail`：确认每道题有 `blocks`（含 text/image/options/answer_space）；
5. 修改第一个文字块 `PUT .../blocks/{bid} {content:'冒烟修改'}` → 详情中 `is_modified=true` 且 `content` 含“冒烟修改”；
6. `POST .../restore` → `is_modified=false`；
7. `POST /api/practices/{practiceId}/layout/unify` → 200；
8. `DELETE /api/practices/{practiceId}` → 练习目录与记录清除；
9. `DELETE /api/basket` 清空池，确认 `practices total=0`。
注意：PowerShell 中勿用 `$pid`（只读内置变量），用 `$practiceId` 等。
冒烟产生的数据必须全部清理，不留脏数据。

- [ ] **Step 4: 手工验收清单（需人工在浏览器过一遍，对应规格场景二）**

1. 练习列表 → 详情 → 进入编辑器；左树显示小节与题目。
2. 选中一道题：修正一个错别字（文字块 `@change` 保存）；左树出现“改”标记。
3. 修改一个选项内容；增/删选项生效。
4. 图片块：调整对齐与宽度，预览图即时变化；上移/下移改变图片在题干中的位置。
5. 插入文字块/图片块；删除块；块重排后内容顺序正确。
6. 恢复题库版本 → `已修改` 消失，内容回到原题。
7. 新增自定义小节、把题目移入、再移回；题目删除后编号连续无空洞。
8. 整理结构：预览变化列表 → 确认后按题型归位；统一排版：提示调整块数。
9. 刷新页面：所有编辑不丢失（均已即时入库）。
10. 题库页原题内容与阶段一验收时完全一致（零侵入）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/PracticeListView.vue
git commit -m "feat: 阶段二收尾——启用编辑器入口（块式编辑器全链路上线）"
```

---

## 验收总览（阶段二）

| 规格条目 | 落点 |
|---|---|
| 8.1 编辑器三区域 | Task 5/6（预览区阶段三接入） |
| 8.2 练习级信息 | Task 5（标题/副标题/学生信息栏开关存 page_config；分页符由小节 `start_on_new_page` 与块顺序承载，渲染属阶段三） |
| 8.3 题内内容块 | Task 1（物化）+ Task 2（API）+ Task 6（编辑区） |
| 8.4 内容纠错 | Task 2（块改/恢复）+ Task 6（前端）；拆/合文字块 = 删除块+插入文字块组合 |
| 8.5 结构编排 | Task 3 |
| 8.6 图片操作 | Task 2（style）+ Task 6（对齐/宽度/移动/删除）；“恢复原始图片设置” = 恢复题库版本后图片块重生为默认样式 |
| 9 一键排版 | Task 4（两命令拆分，尊重用户定制） |
| 决策 3/6 | 恢复永不写回题库；留白默认按题型、单题可覆盖 |

## 实施偏差记录（2026-08-29 执行时修正）

1. **`rebuild_content_from_blocks` 签名**：由计划的同步 `(db, pq)` 依赖 relationship 缓存，改为 **async 直接查库**（`select ... where practice_question_id order by position`）。原因：SQLAlchemy identity map 中已加载的空 `blocks` 集合不会被后续 selectinload 重新填充，必须不依赖缓存。
2. **`materialize_blocks` 只 `flush` 不 `commit`**：函数内 `commit()` 会使 `pq.blocks` 关系过期，后续访问触发懒加载报 MissingGreenlet；提交由调用方负责。
3. **`populate_existing`**：`_get_practice_full`、`_load_pq`、`_renumber`、`_get_section` 的查询都加了 `.execution_options(populate_existing=True)`，否则 selectinload 返回 identity map 中的过期集合。
4. **`apply_regroup` 顺序**：先建新小节并用 `section.questions.append(q)` 迁移题目（新小节需先 `db.refresh(section, attribute_names=["questions"])` 初始化集合），再删旧小节；直接赋 `q.section_id` 或先删旧小节都会触发 delete-orphan 级联删题。
5. **`_renumber` 保留空的 custom 小节**：只删空的题型小节。
6. **Task 6 前端小修**：选项块 `label` 输入框补了 `@change="saveOptions(b)"`（计划中仅 content 有），否则只改标签不会保存。
7. **测试数量**：实际累计 39 项（计划预估 ≥40），全部通过；冒烟时真实库响应字段为 `.questions` / `.practices`（非 `.items`）。

