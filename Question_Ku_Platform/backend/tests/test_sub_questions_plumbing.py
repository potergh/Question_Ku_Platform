"""两级模型（material + sub_questions）在暂存区→入库→出参的贯通单测（M1）。

覆盖：ExtractItemData 落盘/读回保留 sub_questions；to_question_data 透传；
build_question 落到 Question 列；QuestionResponse 把小题里的 asset:// 选项
解析成 HTTP URL，且普通题（无小题）保持原样、物理等学科零影响。
"""

from datetime import datetime

from app.models import Question
from app.schemas.question import QuestionResponse
from app.services.api_extract_adapter import ExtractItemData
from app.services.question_builder import build_question


def _passage_item(**over):
    base = dict(
        qid=1, question_number=33, label="33", section="二、完形填空",
        question_type="cloze", stem_md="阅读下面短文，从每题所给的四个选项中选出最佳选项。",
        content="完形材料正文……",
        sub_questions=[
            {"label": "（1）", "stem": "What does the author ___?",
             "options": [{"label": "A", "content": "run"}, {"label": "B", "content": "walk"}],
             "answer": "A"},
            {"label": "（2）", "stem": "Why ___.",
             "options": [{"label": "A", "content": "asset://figures/Q001_01.webp"},
                          {"label": "B", "content": "because"}],
             "answer": "B"},
        ],
    )
    base.update(over)
    return ExtractItemData(**base)


def test_extract_item_roundtrip_keeps_sub_questions():
    item = _passage_item()
    data = item.to_dict()
    assert len(data["sub_questions"]) == 2
    back = ExtractItemData.from_dict(data)
    assert back.sub_questions[0]["answer"] == "A"
    assert back.sub_questions[1]["options"][0]["content"] == "asset://figures/Q001_01.webp"


def test_to_question_data_and_build_question_carry_sub_questions():
    from pathlib import Path

    item = _passage_item()
    qd = item.to_question_data(Path("/tmp/doc"))
    assert qd.sub_questions and len(qd.sub_questions) == 2
    q = build_question(qd, source_id="s1", subject="english")
    assert isinstance(q, Question)
    assert q.sub_questions[1]["answer"] == "B"


def test_ordinary_question_has_no_sub_questions():
    # 非语篇题：不传 sub_questions → 空列表，入库为 []，物理等学科不受影响。
    item = ExtractItemData(qid=1, question_number=5, label="5", question_type="single_choice")
    qd = item.to_question_data(__import__("pathlib").Path("/tmp/doc"))
    assert qd.sub_questions == []


def test_response_resolves_asset_urls_in_sub_questions():
    item = _passage_item()
    q = build_question(item.to_question_data(__import__("pathlib").Path("/tmp/doc")),
                       source_id="src9", subject="english")
    q.id = "q1"
    q.created_at = datetime.now()
    # 脱离 Session 的 ORM 对象不会应用列默认值，手动补齐布尔位。
    q.is_deleted = False
    q.needs_review = True
    q.review_status = "pending"
    resp = QuestionResponse.model_validate(q)
    opts = resp.sub_questions[1]["options"]
    assert opts[0]["content"].startswith("/api/ocr-assets/src9/")
