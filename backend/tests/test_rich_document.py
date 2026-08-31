"""阶段 0：富文本文档转换器单元测试（迁移规则正确性）。"""

import json

from app.services.rich_document import (
    doc_from_blocks,
    doc_from_snapshot,
    serialize,
    DOC_SCHEMA_VERSION,
)


class FakeBlock:
    def __init__(self, block_type, content, style=None, bid="b"):
        self.id = bid
        self.block_type = block_type
        self.content = content
        self.style_config = style


def _types(doc):
    return [n["type"] for n in doc["content"]]


def test_doc_header():
    doc = doc_from_blocks([])
    assert doc["type"] == "doc"
    assert doc["schema_version"] == DOC_SCHEMA_VERSION
    assert doc["content"] == []


def test_text_block_split_by_newline():
    blocks = [FakeBlock("text", "第一行\n第二行")]
    doc = doc_from_blocks(blocks)
    assert _types(doc) == ["paragraph", "paragraph"]
    assert doc["content"][0]["content"][0]["text"] == "第一行"


def test_image_block_keeps_style():
    blocks = [FakeBlock("image", "asset://practice/a.webp",
                        {"align": "center", "width": "fit"})]
    doc = doc_from_blocks(blocks)
    img = doc["content"][0]
    assert img["type"] == "image"
    assert img["attrs"] == {"src": "asset://practice/a.webp",
                            "align": "center", "width": "fit"}


def test_image_block_invalid_content_kept_as_text():
    w = []
    doc = doc_from_blocks([FakeBlock("image", "不是引用", None)], w)
    assert _types(doc) == ["paragraph"]
    assert any("保留为文字段" in x for x in w)


def test_options_to_option_group():
    opts = json.dumps([{"label": "A", "content": "甲"}, {"label": "B", "content": "乙"}],
                      ensure_ascii=False)
    doc = doc_from_blocks([FakeBlock("options", opts)])
    group = doc["content"][0]
    assert group["type"] == "optionGroup"
    assert [o["attrs"]["label"] for o in group["content"]] == ["A", "B"]
    assert group["content"][0]["content"][0]["text"] == "甲"


def test_options_bad_json_kept_as_text():
    w = []
    doc = doc_from_blocks([FakeBlock("options", "{坏JSON", None)], w)
    assert _types(doc) == ["paragraph"]
    assert any("JSON 无法解析" in x for x in w)


def test_answer_space_rows():
    doc = doc_from_blocks([FakeBlock("answer_space", None, {"rows": 8})])
    assert doc["content"][0] == {"type": "answerSpace", "attrs": {"rows": 8}}


def test_inline_image_in_text():
    doc = doc_from_blocks([FakeBlock("text", "看图 asset://practice/a.webp 然后")])
    nodes = doc["content"][0]["content"]
    types = [n["type"] for n in nodes]
    assert types == ["text", "inlineImage", "text"]
    assert nodes[1]["attrs"]["src"] == "asset://practice/a.webp"


def test_inline_formula():
    doc = doc_from_blocks([FakeBlock("text", "速度公式 $v=\\frac{s}{t}$ 成立")])
    nodes = doc["content"][0]["content"]
    formulas = [n for n in nodes if n["type"] == "inlineFormula"]
    assert len(formulas) == 1
    assert formulas[0]["attrs"]["latex"] == "v=\\frac{s}{t}"


def test_display_formula():
    # 阶段 3：独立公式提升为顶层块级节点（前端为 block 节点），前后文字各自成段
    doc = doc_from_blocks([FakeBlock("text", "结论 $$E=mc^2$$ 完毕")])
    top_types = [n["type"] for n in doc["content"]]
    assert top_types == ["paragraph", "displayFormula", "paragraph"]
    assert doc["content"][1]["attrs"]["latex"] == "E=mc^2"


def test_paren_style_formulas():
    doc = doc_from_blocks([FakeBlock("text", "\\(a+b\\) 与 \\[x-y\\]")])
    top_types = [n["type"] for n in doc["content"]]
    assert top_types == ["paragraph", "displayFormula"]   # \[…\] 提升为块级
    inline_types = [n["type"] for n in doc["content"][0]["content"]]
    assert "inlineFormula" in inline_types                  # \(…\) 保持行内


def test_unbalanced_dollar_kept_as_text():
    w = []
    doc = doc_from_blocks([FakeBlock("text", "价格 $5 未闭合", None)], w)
    text = "".join(n.get("text", "") for n in doc["content"][0]["content"]
                   if n["type"] == "text")
    assert "$5" in text
    assert not any(n["type"].endswith("Formula") for n in doc["content"][0]["content"])


def test_currency_not_formula():
    """数字紧跟 $ 视为货币符号，不当公式（防误判）。"""
    doc = doc_from_blocks([FakeBlock("text", "售价 5$ 和 10$ 的区别")])
    assert not any(n["type"].endswith("Formula") for n in doc["content"][0]["content"])


def test_answer_block_not_migrated_but_kept_noted():
    """答案/解析块不迁移进正文（当前版本不含答案），但记录警告。"""
    w = []
    doc = doc_from_blocks([FakeBlock("text", "题干"),
                           FakeBlock("answer", "A", None)], w)
    assert _types(doc) == ["paragraph"]
    assert any("answer" in x for x in w)


def test_snapshot_fallback_matches_blocks():
    doc = doc_from_snapshot("题干A asset://practice/a.webp 题干B",
                            [{"label": "A", "content": "x"}])
    types = _types(doc)
    assert types == ["paragraph", "image", "paragraph", "optionGroup"]
    assert doc["content"][1]["attrs"]["src"] == "asset://practice/a.webp"


def test_serialize_roundtrip():
    doc = doc_from_blocks([FakeBlock("text", "中文 $x$ 内容")])
    assert json.loads(serialize(doc)) == doc
