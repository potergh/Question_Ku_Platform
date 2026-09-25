"""MinerU 通道的 Job / Source 生命周期锁。

为什么必须单独测这一层：``scripts/mineru_extract.py`` 是离线回归，它绕过了
``mineru_service`` —— 没有 Job、没有 Source 状态流转。也就是说「上传之后到底有没有
正确置 staging」「失败时错误信息说不说得清」在真跑里完全没被覆盖，而 MinerU
每次真跑都要花每日页数额度，不该靠它来验证错误分支。

这里把 ``parse_pdf``（花钱）与 ``run_extract``（花 token）换成桩，让真实代码只负责
它自己的职责：配置校验顺序、状态流转、错误分类。``build_lines`` 走真实实现，
顺带锁住「适配层产出的行清单确实被交给了管线」。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models import Job, Source
from app.services import mineru_service
from app.services.api_extract.vlm_client import VLMConfigError
from app.services.api_extract_adapter import (
    CHANNEL_MINERU,
    STAGING_STATUS,
    ExtractItemData,
    ExtractResult,
)
from app.services.mineru_client import MineruArtifacts, MineruTaskError

VISION_CONFIG = {
    "base_url": "https://example.invalid/v1",
    "api_key": "k",
    "model": "qwen-vl-max",
}

MINERU_CONFIG = {
    "token": "tok",
    "model_version": "vlm",
    "language": "ch",
    "enable_formula": True,
    "enable_table": True,
}

# 最小的 content_list：两行正文 + 一行页眉（页眉必须被剔除，见断言）。
CONTENT_LIST = [
    {"type": "text", "text": "1．（3 分）第一题", "bbox": [100, 100, 900, 130], "page_idx": 0},
    {"type": "text", "text": "2．（3 分）第二题", "bbox": [100, 200, 900, 230], "page_idx": 0},
    {"type": "header", "text": "页眉文字", "bbox": [100, 10, 900, 30], "page_idx": 0},
]

# 带一个表格块的最小清单：这张表的渲染图存不存在，决定 tables_as_figures 开关。
CONTENT_LIST_WITH_TABLE = [
    {"type": "text", "text": "24．测量小瓷杯的密度", "bbox": [100, 100, 900, 130], "page_idx": 0},
    {"type": "table", "table_body": '<table><tr><td rowspan="3">方案一</td></tr></table>',
     "img_path": "images/t.jpg", "bbox": [100, 200, 900, 500], "page_idx": 0},
]


async def _seed(test_db, tmp_path: Path, *, cancelled: bool = False) -> tuple[str, str]:
    async with test_db() as db:
        source = Source(
            filename="doc1.pdf",
            file_path=str(tmp_path / "doc1.pdf"),
            file_type="pdf",
            role="paper",
            subject="physics",
            ocr_status="pending",
            extract_channel=CHANNEL_MINERU,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)

        job = Job(
            job_type=CHANNEL_MINERU,
            source_id=source.id,
            status="queued",
            payload=json.dumps({"doc_kind": "paper"}, ensure_ascii=False),
            cancelled=cancelled,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return source.id, job.id


def _stub(
    monkeypatch,
    test_db,
    tmp_path: Path,
    *,
    skip_token_stub: bool = False,
    vision_error: Exception | None = None,
    parse_error: Exception | None = None,
    extract_error: Exception | None = None,
    blocks: list | None = None,
) -> dict:
    """装桩并返回 calls（记录 parse_pdf 是否被调、run_extract 收到的参数）。

    blocks 用来替换 CONTENT_LIST（例如加一个表格块），默认仍是最小那三条。
    """
    calls: dict = {}
    document_dir = tmp_path / "ocr_output" / "doc1"
    document_dir.mkdir(parents=True, exist_ok=True)
    content_list = tmp_path / "content_list.json"
    content_list.write_text(
        json.dumps(blocks if blocks is not None else CONTENT_LIST, ensure_ascii=False),
        encoding="utf-8",
    )

    result = ExtractResult(
        output_dir=document_dir,
        items=[
            ExtractItemData(qid=1, question_number=1, label="1．", needs_review=False),
            ExtractItemData(qid=2, question_number=2, label="2．", needs_review=True),
        ],
        audit={"blocked": False, "coverage_ratio": 1.0, "reasons": []},
        document_name="doc1",
        channel=CHANNEL_MINERU,
    )

    async def fake_parse_pdf(token, pdf_path, dest_dir, **kwargs):
        calls["parse_pdf"] = {"token": token, **kwargs}
        if parse_error is not None:
            raise parse_error
        return MineruArtifacts(
            batch_id="b1",
            zip_path=tmp_path / "x.zip",
            extract_dir=tmp_path,
            members=["x_content_list.json"],
            content_list_path=content_list,
        )

    async def fake_run_extract(config, pdf_path, output_root, **kwargs):
        calls["run_extract"] = kwargs
        if extract_error is not None:
            raise extract_error
        return result

    async def fake_token(db) -> dict:
        return dict(MINERU_CONFIG)

    async def fake_vision(db) -> dict:
        if vision_error is not None:
            raise vision_error
        return VISION_CONFIG

    monkeypatch.setattr(mineru_service, "async_session_factory", test_db)
    monkeypatch.setattr(mineru_service, "parse_pdf", fake_parse_pdf)
    monkeypatch.setattr(mineru_service, "run_extract", fake_run_extract)
    monkeypatch.setattr(mineru_service, "get_vision_config", fake_vision)
    monkeypatch.setattr(mineru_service, "page_sizes_from_pdf", lambda pdf: {0: (595.0, 842.0)})
    monkeypatch.setattr(mineru_service.settings, "ocr_output_dir", tmp_path / "ocr_output")
    if not skip_token_stub:
        monkeypatch.setattr(mineru_service, "get_mineru_config", fake_token)
    return calls


async def _state(test_db, source_id: str, job_id: str) -> tuple[Source, Job]:
    async with test_db() as db:
        return await db.get(Source, source_id), await db.get(Job, job_id)


# ── 成功路径 ─────────────────────────────────────────────────────────


async def test_reaches_staging_and_marks_job_success(test_db, tmp_path, monkeypatch):
    source_id, job_id = await _seed(test_db, tmp_path)
    calls = _stub(monkeypatch, test_db, tmp_path)

    await mineru_service.process_pdf_async(source_id, str(tmp_path / "doc1.pdf"), job_id)

    source, job = await _state(test_db, source_id, job_id)
    assert source.ocr_status == STAGING_STATUS
    assert source.extract_channel == CHANNEL_MINERU
    assert source.question_count == 2
    assert source.review_count == 1
    assert source.ocr_result_path
    assert job.status == "success"
    assert job.progress == 100.0

    # 设置页里的解析参数必须真的下发到客户端，否则界面改了也白改
    assert calls["parse_pdf"]["model_version"] == "vlm"
    assert calls["parse_pdf"]["language"] == "ch"
    assert calls["parse_pdf"]["enable_formula"] is True
    assert calls["parse_pdf"]["enable_table"] is True

    # 行清单确实交给了管线，且页眉被适配层剔掉（3 个块 → 2 行）
    handed = calls["run_extract"]
    assert handed["channel"] == CHANNEL_MINERU
    assert len(handed["lines_override"]) == 2
    assert all("页眉文字" not in line.text for line in handed["lines_override"])
    # 适配层的告警要一并带进本次识别，否则问题只留在上游日志里
    assert isinstance(handed["override_warnings"], list)


# ── 失败路径：每条都必须说清是哪一边的问题 ───────────────────────────


async def test_missing_token_fails_before_calling_mineru(test_db, tmp_path, monkeypatch):
    """Token 没配是配置问题，必须报「去设置页填」，且不该白调 MinerU。"""
    source_id, job_id = await _seed(test_db, tmp_path)
    # 不装 token 桩：走真实的 get_mineru_config，针对空测试库它会抛配置错误
    calls = _stub(monkeypatch, test_db, tmp_path, skip_token_stub=True)

    await mineru_service.process_pdf_async(source_id, str(tmp_path / "doc1.pdf"), job_id)

    source, job = await _state(test_db, source_id, job_id)
    assert job.status == "failed"
    assert "未配置 MinerU Token" in job.error_message
    assert "系统设置" in job.error_message
    assert source.ocr_status == "error"
    assert "parse_pdf" not in calls


async def test_vision_config_checked_before_submitting_to_mineru(
    test_db, tmp_path, monkeypatch
):
    """视觉模型缺失要在提交 MinerU 之前发现 —— 否则白跑一趟还占掉当天的页数额度。"""
    source_id, job_id = await _seed(test_db, tmp_path)
    calls = _stub(
        monkeypatch,
        test_db,
        tmp_path,
        vision_error=VLMConfigError("AI 功能已关闭，请在设置页面开启"),
    )

    await mineru_service.process_pdf_async(source_id, str(tmp_path / "doc1.pdf"), job_id)

    source, job = await _state(test_db, source_id, job_id)
    assert job.status == "failed"
    assert "视觉模型配置不可用" in job.error_message
    assert source.ocr_status == "error"
    assert "parse_pdf" not in calls


async def test_mineru_error_is_labelled(test_db, tmp_path, monkeypatch):
    """MinerU 的失败要带前缀，用户才能分清是解析失败还是模型失败。"""
    source_id, job_id = await _seed(test_db, tmp_path)
    _stub(
        monkeypatch,
        test_db,
        tmp_path,
        parse_error=MineruTaskError("文件超过 200 页上限，需拆分后再传"),
    )

    await mineru_service.process_pdf_async(source_id, str(tmp_path / "doc1.pdf"), job_id)

    source, job = await _state(test_db, source_id, job_id)
    assert job.status == "failed"
    assert job.error_message.startswith("MinerU 解析失败：")
    assert "200 页" in job.error_message
    assert source.ocr_status == "error"


async def test_pipeline_failure_is_reported(test_db, tmp_path, monkeypatch):
    """管线阶段失败（视觉模型报错等）原样落到任务上，且 Source 不留在 processing。"""
    source_id, job_id = await _seed(test_db, tmp_path)
    _stub(monkeypatch, test_db, tmp_path, extract_error=RuntimeError("结构化阶段炸了"))

    await mineru_service.process_pdf_async(source_id, str(tmp_path / "doc1.pdf"), job_id)

    source, job = await _state(test_db, source_id, job_id)
    assert job.status == "failed"
    assert "结构化阶段炸了" in job.error_message
    assert source.ocr_status == "error"


async def test_cancel_before_start_skips_everything(test_db, tmp_path, monkeypatch):
    source_id, job_id = await _seed(test_db, tmp_path, cancelled=True)
    calls = _stub(monkeypatch, test_db, tmp_path)

    await mineru_service.process_pdf_async(source_id, str(tmp_path / "doc1.pdf"), job_id)

    source, job = await _state(test_db, source_id, job_id)
    assert job.status == "failed"
    assert job.error_message == "用户取消"
    assert source.ocr_status == "error"
    assert "parse_pdf" not in calls


# ── 表格当插图：规则按「题」判断，类型信息必须跟着候选走 ──────────────


async def test_table_candidate_carries_kind(test_db, tmp_path, monkeypatch):
    """表格候选必须带 kind="table"，结构化阶段靠它按题统计「几张表有图」。

    旧实现是一个全局布尔（tables_as_figures）：实测 9 张表里 1 张没图，就把
    其余 8 张有图的也拖回 Markdown 重抄，合并单元格照样丢。改成按题判断后，
    候选必须自己声明类型，service 才能算出每题的表格图数。
    """
    source_id, job_id = await _seed(test_db, tmp_path)
    calls = _stub(monkeypatch, test_db, tmp_path, blocks=CONTENT_LIST_WITH_TABLE)
    images = tmp_path / "images"
    images.mkdir(exist_ok=True)
    (images / "t.jpg").write_bytes(b"jpg")

    await mineru_service.process_pdf_async(source_id, str(tmp_path / "doc1.pdf"), job_id)

    handed = calls["run_extract"]
    assert handed["figures_override"] is not None
    assert [candidate.kind for candidate in handed["figures_override"]] == ["table"]


async def test_table_without_image_produces_no_candidate(
    test_db, tmp_path, monkeypatch
):
    """表格没图时没有候选可给 —— 该题退回 Markdown 抄。

    图不存在、抄又被禁，表格内容就整块没了，所以没图的题绝不能启用「只认图」。
    """
    source_id, job_id = await _seed(test_db, tmp_path)
    calls = _stub(monkeypatch, test_db, tmp_path, blocks=CONTENT_LIST_WITH_TABLE)

    await mineru_service.process_pdf_async(source_id, str(tmp_path / "doc1.pdf"), job_id)

    handed = calls["run_extract"]
    assert handed["figures_override"] is None
