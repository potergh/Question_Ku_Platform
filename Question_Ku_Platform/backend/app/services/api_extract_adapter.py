"""API 大模型识别通道的适配层。

与 OCRAdapter 同样的定位：唯一同时了解 api_extract/ 与 physics_paper_splitter
内部结构的层。平台其余部分（routers、其它 services）只见 ExtractResult /
ExtractItemData，不见 QuestionRecord / CoverageReport。

同时它是磁盘暂存区（extract.json）的读写契约持有者：确认入库时把
ExtractItemData 降级成既有的 QuestionData，下游资产服务、复核流、组卷全部
零改动复用。
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add packages/ to sys.path so physics_paper_splitter is importable
# WITHOUT modifying the OCR source code.
_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from app.services.ocr_adapter import QuestionData  # noqa: E402
from app.utils.question_types import normalize_question_type  # noqa: E402

# 暂存文件名。放在 ocr_output/<doc>/ 下：delete_source 已对该目录做 rmtree，
# 生命周期天然对齐；且 resolve_card_image_path 依赖路径里存在 'ocr_output'
# 片段来生成资产 URL，换目录会让题卡图全部 404。
EXTRACT_JSON_NAME = "extract.json"
EXTRACT_SCHEMA_VERSION = 1

# Source.ocr_status 的暂存态取值。
STAGING_STATUS = "staging"

# 识别通道取值。
CHANNEL_API_EXTRACT = "api_extract"
CHANNEL_LOCAL_OCR = "local_ocr"
# MinerU 官方 API：行清单来自它的 content_list，之后完全复用 api_extract 管线。
CHANNEL_MINERU = "mineru"

# 会产出暂存区（extract.json）的通道。extract 路由的预览/重跑放行判断用它 ——
# 以前写死 `== CHANNEL_API_EXTRACT`，加一个通道就要改一处，漏改的表现是
# 「预览/重跑按钮报 400」，而报错信息完全指不到根因。
STAGED_CHANNELS = (CHANNEL_API_EXTRACT, CHANNEL_MINERU)


@dataclass
class ExtractItemData:
    """一道题在暂存区里的完整状态。QuestionData 的超集。

    多出来的字段都是预览页需要的：qid / label / section 用于展示原始编号，
    segments / start_page / end_page 用于溯源到 PDF 位置，answer_sources 用于
    展示三源答案对照，audit_flags 用于逐题标红，original 用于对比人工改动。
    """

    qid: int
    question_number: int
    label: str = ""
    section: str | None = None
    question_type: str | None = None
    score: float | None = None

    stem_md: str = ""
    options: list[dict] = field(default_factory=list)
    # 最终入库用的 Markdown（插图已内联成 asset:// 链接）。
    content: str = ""
    # 原始行文本，与 raw_ocr_content 对应，永不被用户编辑覆盖。
    raw_text: str = ""

    answer: str | None = None
    explanation: str | None = None
    answer_origin: str | None = None
    answer_sources: list[dict] = field(default_factory=list)
    answer_note: str | None = None
    answer_conflict: bool = False

    # 相对 document_dir 的路径，前端拼 /api/ocr-assets/{source_id}/{path}。
    card_image: str | None = None
    figures: list[str] = field(default_factory=list)
    # 答案区（文末答案/解析）里的插图，命名 answer_Q0NN_MM。
    # 只在「答案本身是图、或答案为空但在答案区找到了解析」的题上有值 ——
    # 卷面写「如上图所示」而 answer 字段只有这行字时，图在这里。
    answer_figures: list[str] = field(default_factory=list)
    # 答案引用的图就是题干图本身时的标注（不重复裁图）：
    # [{"stem_figure": "figures/Q024_01.webp", "stem_index": 1}]
    answer_figure_refs: list[dict] = field(default_factory=list)
    # 多小问答案按小问分块（含「如图」引导的小问挂上对应答案图）：
    # [{"label": "（2）", "text": "如上图所示；", "figures": ["figures/answer_Q024_01.webp"]}]
    answer_blocks: list[dict] = field(default_factory=list)
    segments: list[dict] = field(default_factory=list)
    start_page: int = 0
    end_page: int = 0
    is_cross_page: bool = False
    width_px: int = 0
    height_px: int = 0

    has_formula: bool = False
    audit_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    needs_review: bool = True
    # 模型不给数值置信度，这里只记二值：结构化成功 1.0 / 失败 0.0。
    # 细粒度信号由 needs_review 与 audit_flags 承担，不编造小数。
    llm_confidence: float | None = None
    # 用户在预览页剔除了这道题（确认入库时跳过）。
    excluded: bool = False
    # 首次写入时的副本，PUT 修改后用于「改了什么」对比。
    original: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ExtractItemData:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_question_data(self, document_dir: Path) -> QuestionData:
        """降级为既有契约，确认入库时复用 ocr_service 里同一套字段映射。"""
        return QuestionData(
            # source_question_id 的语义本就是「OCR original ID」，
            # 存原始编号（【例1】/随堂检测-1）比存 Q001 更有信息量。
            source_question_id=self.label or f"Q{self.qid:03d}",
            question_number=self.question_number,
            # 英语篇章题：通用码（单选/多选/填空）按板块归一为专属题型，已手改则保留。
            question_type=normalize_question_type(self.question_type, self.section),
            raw_ocr_content=self.raw_text,
            content=self.content,
            options=self.options,
            answer=self.answer,
            explanation=self.explanation,
            score=self.score,
            card_image_path=str(document_dir / self.card_image) if self.card_image else None,
            ocr_confidence=self.llm_confidence,
            needs_review=self.needs_review,
            # answer_figures 存的是相对 document_dir 的路径，落库与
            # card_image_path 统一用绝对路径，QuestionResponse 再转成 URL。
            answer_image_paths=[
                str(document_dir / figure) for figure in self.answer_figures
            ],
        )


@dataclass
class ExtractResult:
    """整份文档的识别结果。既用于内存传递，也是 extract.json 的结构。"""

    output_dir: Path
    doc_kind: str = "paper"
    items: list[ExtractItemData] = field(default_factory=list)
    audit: dict = field(default_factory=dict)
    qa: dict = field(default_factory=dict)
    answer_report: dict = field(default_factory=dict)
    non_question_regions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # LLM 划界的原始行区间（qid/label/start_line/end_line）。落盘的意义：
    # 确定性边界校验吃的就是这份区间；没有它，离线复盘只能从裁图几何「反推」
    # start_line/end_line，而反推出来的相邻区间必然共享边界行，
    # span_overlap 会满屏误报（实测和平卷反推法报 20 处，真跑只报 1 处）。
    boundary_spans: list[dict] = field(default_factory=list)
    # 本次识别的大模型用量（usage.UsageLedger.to_dict()）。老暂存文件没有这个键，
    # from_dict 兜成空字典，前端据此判断「未记录」。
    usage: dict = field(default_factory=dict)
    # 各阶段耗时（秒）。四个 VLM 阶段里三个是串行的，优化前必须先有分布——
    # 否则只能像本次排查那样靠 jobs 表的起止时间反推。老暂存文件没有此键，兜空。
    timings: dict = field(default_factory=dict)
    source_id: str | None = None
    document_name: str = ""
    channel: str = CHANNEL_API_EXTRACT
    schema_version: int = EXTRACT_SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""
    confirmed: bool = False

    @property
    def question_count(self) -> int:
        """未被剔除的题目数。"""
        return sum(1 for item in self.items if not item.excluded)

    @property
    def review_count(self) -> int:
        return sum(1 for item in self.items if not item.excluded and item.needs_review)

    @property
    def blocked(self) -> bool:
        """审计闸门：为真时确认入库必须显式 force。"""
        return bool(self.audit.get("blocked"))

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "channel": self.channel,
            "source_id": self.source_id,
            "document_name": self.document_name,
            "doc_kind": self.doc_kind,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "confirmed": self.confirmed,
            "question_count": self.question_count,
            "review_count": self.review_count,
            "audit": self.audit,
            "qa": self.qa,
            "answer_report": self.answer_report,
            "non_question_regions": self.non_question_regions,
            "warnings": self.warnings,
            "boundary_spans": self.boundary_spans,
            "usage": self.usage,
            "timings": self.timings,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict, output_dir: Path) -> ExtractResult:
        items = [ExtractItemData.from_dict(row) for row in data.get("items", []) if isinstance(row, dict)]
        return cls(
            output_dir=output_dir,
            doc_kind=data.get("doc_kind") or "paper",
            items=items,
            audit=data.get("audit") or {},
            qa=data.get("qa") or {},
            answer_report=data.get("answer_report") or {},
            non_question_regions=data.get("non_question_regions") or [],
            warnings=data.get("warnings") or [],
            boundary_spans=[
                row for row in (data.get("boundary_spans") or []) if isinstance(row, dict)
            ],
            usage=data.get("usage") or {},
            timings=data.get("timings") or {},
            source_id=data.get("source_id"),
            document_name=data.get("document_name") or "",
            channel=data.get("channel") or CHANNEL_API_EXTRACT,
            schema_version=data.get("schema_version") or EXTRACT_SCHEMA_VERSION,
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
            confirmed=bool(data.get("confirmed")),
        )


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_document_dir(output_root: Path, document_name: str) -> Path:
    """拼出并校验输出目录。

    目录名必须落在 output_root（= settings.ocr_output_dir）之下且不含路径分隔符，
    否则 ../ 穿越会写到别处，资产 URL 也会算错。
    """
    if not document_name or Path(document_name).name != document_name:
        raise ValueError(f"非法输出目录名：{document_name!r}")
    return output_root / document_name


def write_extract_json(document_dir: Path, result: ExtractResult) -> Path:
    """把结果写进暂存区。原子写：先写临时文件再替换，避免半途崩溃留下坏 JSON。"""
    document_dir.mkdir(parents=True, exist_ok=True)
    result.updated_at = now_iso()
    if not result.created_at:
        result.created_at = result.updated_at
    target = document_dir / EXTRACT_JSON_NAME
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def read_extract_json(document_dir: Path) -> ExtractResult | None:
    """读暂存区；文件不存在或损坏时返回 None（调用方据此报 404 / 提示重跑）。"""
    path = Path(document_dir) / EXTRACT_JSON_NAME
    if not path.exists():
        return None
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return ExtractResult.from_dict(data, Path(document_dir))


def apply_item_patch(item: ExtractItemData, patch: dict) -> list[str]:
    """把用户的人工修改写回单题，返回被改动的字段名。

    首次修改时把当前值快照进 original，之后 original 保持不变 —— 这样
    「原始识别结果 vs 人工修订」的对比在多次编辑后依然成立。
    不允许改的字段（qid / raw_text / segments / card_image 等溯源信息）被忽略。
    """
    editable = {
        "label",
        "section",
        "question_type",
        "score",
        "stem_md",
        "options",
        "content",
        "answer",
        "explanation",
        "needs_review",
        "excluded",
        "audit_flags",
        "warnings",
    }
    if item.original is None:
        item.original = {key: getattr(item, key) for key in editable}

    changed: list[str] = []
    for key, value in patch.items():
        if key not in editable:
            continue
        current = getattr(item, key)
        if current == value:
            continue
        setattr(item, key, value)
        changed.append(key)
    # 人工改过题干/选项/答案就应该离开「未复核」状态，除非用户显式设了 needs_review。
    if changed and "needs_review" not in patch:
        item.needs_review = False
    return changed
