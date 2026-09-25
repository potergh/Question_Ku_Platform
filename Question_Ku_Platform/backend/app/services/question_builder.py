"""QuestionData → Question 的唯一构造点。

两条识别通道（本地 OCR `ocr_service`、大模型 `api_extract` 经 `routers/extract.py`
确认入库）原先各自手写一份 15 字段的 `Question(...)` 映射，两份拷贝靠注释
"与 ocr_service.py 完全一致" 维持同步，极易漂移。此处收敛为单一实现。
"""

from app.models import Question
from app.services.ocr_adapter import QuestionData


def build_question(
    qd: QuestionData,
    *,
    source_id: str,
    subject: str | None = None,
) -> Question:
    """把通道无关的 QuestionData 落成 SQLAlchemy Question（未 add/未 commit）。

    需要复核的题统一置 review_status="pending"，否则直接 approved。
    """
    return Question(
        source_id=source_id,
        source_question_id=qd.source_question_id,
        question_number=qd.question_number,
        question_type=qd.question_type,
        subject=subject,
        raw_ocr_content=qd.raw_ocr_content,
        content=qd.content,
        options=qd.options,
        sub_questions=qd.sub_questions,
        answer=qd.answer,
        explanation=qd.explanation,
        score=qd.score,
        card_image_path=qd.card_image_path,
        answer_image_paths=qd.answer_image_paths,
        needs_review=qd.needs_review,
        review_status="pending" if qd.needs_review else "approved",
        ocr_confidence=qd.ocr_confidence,
    )
