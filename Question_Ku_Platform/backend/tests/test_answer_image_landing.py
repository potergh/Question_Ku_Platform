"""答案区插图落库链路：相对路径 -> 绝对路径 -> HTTP URL。

答案是图的题（卷面「【答案】」下面直接是一幅图，或只写「如上图所示」）
在 api_extract 通道里由 answer_figures 裁出来挂在
ExtractItemData.answer_figures（相对 document_dir）。这里验证它一路走到
Question.answer_image_paths 并在出参时变成可直接访问的 URL。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.schemas.question import QuestionResponse
from app.services.api_extract_adapter import ExtractItemData


def test_to_question_data_promotes_answer_figures_to_absolute_paths(tmp_path):
    item = ExtractItemData(
        qid=1,
        question_number=20,
        answer_figures=["figures/answer_Q020_01.webp", "figures/answer_Q020_02.webp"],
    )

    question = item.to_question_data(tmp_path)

    assert question.answer_image_paths == [
        str(tmp_path / "figures/answer_Q020_01.webp"),
        str(tmp_path / "figures/answer_Q020_02.webp"),
    ]


def test_to_question_data_without_answer_figures(tmp_path):
    item = ExtractItemData(qid=2, question_number=1)

    assert item.to_question_data(tmp_path).answer_image_paths == []


def _question_row(**overrides) -> SimpleNamespace:
    base = {
        "id": "q-1",
        "source_id": "source-1",
        "source_question_id": "Q020",
        "question_number": 20,
        "question_type": None,
        "subject": None,
        "difficulty": None,
        "grade": None,
        "content": None,
        "options": None,
        "answer": None,
        "explanation": None,
        "score": None,
        "card_image_path": None,
        "answer_image_paths": None,
        "needs_review": False,
        "review_status": "approved",
        "ocr_confidence": None,
        "is_deleted": False,
        "ai_suggestions": None,
        "tags": [],
        "created_at": datetime(2026, 9, 12, 0, 0, 0),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_response_converts_absolute_paths_to_urls():
    response = QuestionResponse.model_validate(
        _question_row(
            answer_image_paths=[
                r"D:\tiku\data\ocr_output\2022年和平一模\figures\answer_Q020_01.webp"
            ]
        )
    )

    assert response.answer_image_paths == [
        "/api/ocr-assets/source-1/figures/answer_Q020_01.webp"
    ]


def test_response_normalizes_null_paths_to_empty_list():
    """迁移前的存量行这一列是 NULL，不能让它把序列化炸掉。"""
    response = QuestionResponse.model_validate(_question_row())

    assert response.answer_image_paths == []
