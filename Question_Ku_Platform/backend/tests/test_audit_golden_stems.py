r"""题干首行自检脚本（backend/scripts/_audit_golden_stems.py）的行为契约。

测的不是脚本的每个分支，而是三条**决定它能不能用**的性质：

1. 反向：Q22 那种「首行是半句话」必须报出来（exit=2）—— 这是它存在的理由。
   漏报的代价是定版时把一个题干被切的基线封成 golden。
2. 正向：题干完整的题不能报（exit=0）—— 误报的代价是脚本没人再跑。
   和平卷 golden 26 题全过就是正向样本。
3. 「(多选) 13.（3 分）…」这类行首标注不能被判成异常 —— 扫 `__before_fix`
   时踩到的误报：标注占 5 个非数字字符，挤爆了 `\D{0,4}` 的前缀名额。

脚本在 scripts/ 下不是包，用 importlib 加载。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "_audit_golden_stems.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_golden_stems", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load()


def _item(number: int, label: str, raw_text: str) -> dict:
    return {"question_number": number, "label": label, "raw_text": raw_text}


def _run(tmp_path, monkeypatch, items: list[dict], name="doc__t") -> int:
    (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / name / "extract.json").write_text(
        json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(MOD, "OCR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["_audit_golden_stems.py", name])
    return MOD.main()


def test_strip_choice_mark_only_strips_choice_marks():
    assert MOD._strip_choice_mark("(多选) 13.（3 分）如表为…") == "13.（3 分）如表为…"
    assert MOD._strip_choice_mark("（单选）2．下列…") == "2．下列…"
    assert MOD._strip_choice_mark("(不定项)5、…") == "5、…"
    # 不带标注的原样返回，避免把正常题干削坏
    assert MOD._strip_choice_mark("21．（7 分）…") == "21．（7 分）…"
    assert MOD._strip_choice_mark("【例1】…") == "【例1】…"


def test_clean_product_passes(tmp_path, monkeypatch, capsys):
    items = [
        _item(1, "1．", "1．（3 分）下列估测最接近实际的是\nA．…\nB．…"),
        _item(21, "21．", "21．（7 分）如图所示，电源电压为 6V\n（1）…"),
    ]
    assert _run(tmp_path, monkeypatch, items) == 0
    assert "0 题" in capsys.readouterr().out


def test_cut_stem_is_reported(tmp_path, monkeypatch, capsys):
    """Q22 的形状：首行是上一题的最后半句话。"""
    items = [
        _item(21, "21．", "21．（7 分）…\n22．（6 分）…都闭合"),
        _item(22, "22．", "时，电流表示数为1.2A，这时小灯泡L 正常发光。求：\n（1）…"),
    ]
    assert _run(tmp_path, monkeypatch, items) == 2
    out = capsys.readouterr().out
    assert "Q22" in out
    assert "时，电流表示数为1.2A" in out


def test_sub_question_first_line_is_flagged(tmp_path, monkeypatch, capsys):
    """第 1 题题干被切成从「（1）…」开始时，不能因为数字刚好对上题号 1 就漏报。

    这条盲点是本测试跑出来的：照搬 audit.py 的 LEADING_NUMBER_RE（`）)` 也算题号
    分隔符）时，「（1）」会被认成题号 1，恰好等于本题号 → 静默漏过。
    """
    assert _run(tmp_path, monkeypatch, [_item(1, "1．", "（1）求电源电压\n（2）求电流")]) == 2
    assert "Q1" in capsys.readouterr().out


def test_choice_mark_prefix_is_not_flagged(tmp_path, monkeypatch, capsys):
    """`(多选) ` 占 5 个非数字字符；不剥掉就会被 `\D{0,4}` 判成不像题号。"""
    items = [_item(39, "13．", "(多选) 13.（3 分）如表为某电烤箱铭牌，以下说法正确的是")]
    assert _run(tmp_path, monkeypatch, items) == 0
    assert "0 题" in capsys.readouterr().out


def test_empty_raw_text_is_reported(tmp_path, monkeypatch, capsys):
    items = [_item(7, "7．", "   \n  ")]
    assert _run(tmp_path, monkeypatch, items) == 2
    assert "空 raw_text" in capsys.readouterr().out


def test_missing_product_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(MOD, "OCR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["_audit_golden_stems.py", "不存在__v99"])
    assert MOD.main() == 2
    assert "[FAIL]" in capsys.readouterr().out


def test_excluded_items_are_skipped(tmp_path, monkeypatch, capsys):
    items = [
        {**_item(1, "1．", "1．（3 分）…"), "excluded": True},
        _item(2, "2．", "2．（3 分）…"),
    ]
    assert _run(tmp_path, monkeypatch, items) == 0
    assert "题数 1" in capsys.readouterr().out


@pytest.mark.parametrize("raw", ["时，电流表示数为1.2A…", "（1）求电源电压"])
def test_report_limited_by_show(tmp_path, monkeypatch, capsys, raw):
    items = [_item(i, f"{i}．", raw) for i in range(1, 6)]
    (tmp_path / "doc__t").mkdir(parents=True, exist_ok=True)
    (tmp_path / "doc__t" / "extract.json").write_text(
        json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(MOD, "OCR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["_audit_golden_stems.py", "doc__t", "--show", "2"])
    assert MOD.main() == 2
    assert "另有 3 题" in capsys.readouterr().out
