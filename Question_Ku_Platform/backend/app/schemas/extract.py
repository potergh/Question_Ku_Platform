"""Pydantic schemas for the API-extract staging area (extract.json).

暂存区不建表，response 直接由 ExtractResult / ExtractItemData 序列化而来。
这里显式列出字段而不是透传 dict，是为了让「前端能拿到什么」成为可锁定的
契约（tests/test_extract_api_lock.py 依赖它）。
"""

from pydantic import BaseModel


class ExtractItemPatch(BaseModel):
    """单题人工修改。只列 apply_item_patch 允许改的字段。

    qid / raw_text / segments / card_image 等溯源信息不可改，因此不在此列；
    多传的字段会被 apply_item_patch 忽略，不会静默写入。
    """

    label: str | None = None
    section: str | None = None
    question_type: str | None = None
    score: float | None = None
    stem_md: str | None = None
    options: list[dict] | None = None
    sub_questions: list[dict] | None = None
    content: str | None = None
    answer: str | None = None
    explanation: str | None = None
    needs_review: bool | None = None
    excluded: bool | None = None
    audit_flags: list[str] | None = None
    warnings: list[str] | None = None


class ExtractItemResponse(BaseModel):
    """一道题在预览页的完整状态。图片路径已解析成可直接访问的 HTTP URL。"""

    qid: int
    question_number: int
    label: str = ""
    section: str | None = None
    question_type: str | None = None
    score: float | None = None

    stem_md: str = ""
    options: list[dict] = []
    # 语篇题（完形/阅读等）的材料+小题 两级结构；普通题为空列表。
    sub_questions: list[dict] = []
    content: str = ""
    raw_text: str = ""

    answer: str | None = None
    explanation: str | None = None
    answer_origin: str | None = None
    answer_sources: list[dict] = []
    answer_note: str | None = None
    answer_conflict: bool = False

    # 题卡原图 URL；无题卡时为 None。
    card_image_url: str | None = None
    figure_urls: list[str] = []
    # 答案区插图 URL。答案是图的题（卷面只写「如上图所示」、或答案字段为空）
    # 靠它把图带给核对者，否则预览页只看到一行没有指向的文字。
    answer_figure_urls: list[str] = []
    # 答案引用的图就是题干图本身时的标注（答案区重印件不重复裁）：
    # [{"stem_figure": "figures/Q024_01.webp", "stem_index": 1, "stem_figure_url": "..."}]
    answer_figure_refs: list[dict] = []
    # 多小问答案按小问分块，figures 为相对路径、figure_urls 为可直接预览的 URL：
    # [{"label": "（2）", "text": "如上图所示；", "figures": [...], "figure_urls": [...]}]
    answer_blocks: list[dict] = []

    segments: list[dict] = []
    start_page: int = 0
    end_page: int = 0
    is_cross_page: bool = False
    width_px: int = 0
    height_px: int = 0

    has_formula: bool = False
    audit_flags: list[str] = []
    warnings: list[str] = []
    error: str | None = None
    needs_review: bool = True
    llm_confidence: float | None = None
    excluded: bool = False

    # 首次人工修改时的快照；配合 changed_fields 展示「改了什么」。
    original: dict | None = None
    changed_fields: list[str] = []


class ExtractResponse(BaseModel):
    """暂存区整份文档。审计摘要与三源答案对照一并返回，供预览页顶部横幅使用。"""

    source_id: str
    filename: str
    document_name: str
    doc_kind: str
    channel: str
    schema_version: int
    ocr_status: str
    confirmed: bool
    created_at: str | None = None
    updated_at: str | None = None

    question_count: int
    review_count: int
    excluded_count: int

    # CoverageReport.to_dict()：total_lines / coverage_ratio / lost_chars /
    # orphan_pages / reasons ...；blocked 另在顶层给一份，前端不必钻字典。
    audit: dict
    blocked: bool
    # 两阶段 QA 报告（行清单解析、答案归一的警告汇总）。
    qa: dict
    answer_report: dict
    non_question_regions: list[dict]
    # 用户可行动的警告（某几页没有文字层、答案区正文重印被剔除…）。
    # 带内部行号 / 术语的管线诊断另在 diagnostics，前端折叠展示。
    warnings: list[str]
    diagnostics: list[str] = []
    # 本次识别的大模型用量（usage.UsageLedger.to_dict()）；老暂存文件为空字典。
    usage: dict = {}
    # 各阶段耗时（秒）：{"行清单": 240.1, "逐题结构化": 268.3, ...}。
    # 用于定位"为什么一份卷要十几分钟"——四个 VLM 阶段里三个是串行的。
    timings: dict = {}

    items: list[ExtractItemResponse]
