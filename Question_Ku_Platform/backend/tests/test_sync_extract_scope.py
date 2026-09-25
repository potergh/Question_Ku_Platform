"""``scripts/_sync_extract_to_db.py`` 的回归测试：产物必须锁进单卷作用域。

补的是一个**真实存在过、只是还没暴露**的漏洞：脚本早期按 ``question_number``
全库匹配，而题号只在**卷内**唯一（和平卷 1~26、河东卷 1~25）。
库里只有一份卷时毫无症状；第二份卷的产物一进同步，就会拿它的 Q1~Q25
覆盖第一份卷的 Q1~Q25，``--update-source-dir`` 还会把第一份卷的入口
改指到第二份卷的产物目录 —— 双重静默毁数据。

实测过：用河东卷产物跑 dry-run，脚本报「题库现有 26 题 | 需要更新 25 题」，
而那 26 题是和平卷的；河东卷是扫描件、当时 answer 全是空串，真跑就会
把和平卷的答案清空。

这里把三条边界钉住：
1. 卷 B 的产物只能改卷 B 的题，卷 A 一字不动；
2. ``--update-source-dir`` 只改本卷入口，不改别人的；
3. 目录名锚不到唯一 source 时拒绝执行，且不写库。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(BACKEND_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import _sync_extract_to_db as s  # noqa: E402


SCHEMA = """
create table sources (
    id text primary key,
    filename text,
    question_count integer,
    ocr_result_path text
);
create table questions (
    id integer primary key,
    source_id text,
    question_number integer,
    content text,
    options text,
    answer text,
    explanation text,
    card_image_path text,
    answer_image_paths text,
    is_deleted integer default 0,
    updated_at text
);
"""

VOL_A = "2022年天津市和平区中考物理一模试卷"
VOL_B = "2026河东区一模物理试卷"


def _write_extract(root: Path, name: str, items: list[dict], *, confirmed=True) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "extract.json").write_text(
        json.dumps(
            {
                "confirmed": confirmed,
                "audit": {"blocked": False, "reasons": []},
                "items": items,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return d


def _question(number: int, answer: str, content: str = "") -> dict:
    return {
        "question_number": number,
        "content": content or f"第{number}题题干",
        "options": None,
        "answer": answer,
        "explanation": None,
        "card_image": None,
        "answer_figures": [],
    }


def _setup(tmp_path, monkeypatch, *, vol_b_items=None, b_deleted=False):
    """库里有 A、B 两份卷；返回 (db 路径, ocr 根, 便于断言的读取器)。"""
    db = tmp_path / "db.sqlite3"
    ocr = tmp_path / "ocr_output"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.executemany(
        "insert into sources values (?,?,?,?)",
        [
            ("a" * 32, f"{VOL_A}.pdf", 2, str(ocr / f"{VOL_A}__golden")),
            ("b" * 32, f"{VOL_B}.pdf", 1, str(ocr / f"{VOL_B}__old")),
        ],
    )
    conn.executemany(
        "insert into questions (id, source_id, question_number, content, options, "
        "answer, explanation, card_image_path, answer_image_paths, is_deleted) "
        "values (?,?,?,?,?,?,?,?,?,?)",
        [
            # content 用 _question() 的默认值：库里与产物只差 answer 一列，
            # 这样断言读出来的变化恰好是「正确的更新」，不是任何附带改动。
            (1, "a" * 32, 1, "第1题题干", None, "A1", None, None, None, 0),
            (2, "a" * 32, 2, "第2题题干", None, "A2", None, None, None, 0),
            (3, "b" * 32, 1, "第1题题干", None, "B1", None, None, None, 1 if b_deleted else 0),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(s, "DB", db)
    monkeypatch.setattr(s, "OCR", ocr)

    _write_extract(ocr, f"{VOL_A}__golden", [_question(1, "A1"), _question(2, "A2")])
    _write_extract(
        ocr,
        f"{VOL_B}__golden",
        vol_b_items if vol_b_items is not None else [_question(1, "B1-NEW")],
    )
    _write_extract(ocr, f"{VOL_B}__old", [_question(1, "B1")])

    def read(number: int, source_id: str) -> tuple:
        c = sqlite3.connect(db)
        row = c.execute(
            "select content, answer, is_deleted from questions "
            "where source_id=? and question_number=?",
            (source_id, number),
        ).fetchone()
        c.close()
        return row

    def source_path(source_id: str) -> str:
        c = sqlite3.connect(db)
        row = c.execute("select ocr_result_path from sources where id=?", (source_id,)).fetchone()
        c.close()
        return row[0]

    return db, ocr, read, source_path


def _run(monkeypatch, document: str, *extra: str) -> int:
    monkeypatch.setattr(sys, "argv", ["_sync_extract_to_db.py", document, *extra])
    return s.main()


# --------------------------------------------------------------------------- 核心隔离


def test_volume_b_does_not_touch_volume_a(tmp_path, monkeypatch):
    """这是漏洞本体：拿 B 的产物跑同步，A 的题必须一个字都不变。"""
    _, _, read, source_path = _setup(tmp_path, monkeypatch)

    code = _run(monkeypatch, f"{VOL_B}__golden")

    assert code == 0
    assert read(1, "b" * 32) == ("第1题题干", "B1-NEW", 0), "B 自己的题没被更新"
    assert read(1, "a" * 32) == ("第1题题干", "A1", 0), "A 卷 Q1 被 B 卷串写"
    assert read(2, "a" * 32) == ("第2题题干", "A2", 0), "A 卷 Q2 被 B 卷串写"
    # 没加 --update-source-dir，入口一律不动
    assert source_path("a" * 32).endswith(f"{VOL_A}__golden")
    assert source_path("b" * 32).endswith(f"{VOL_B}__old")


def test_update_source_dir_only_touches_own_volume(tmp_path, monkeypatch):
    """--update-source-dir 只改本卷入口。改别人的 = 把那份卷的产物指到这份卷来。"""
    _, _, _, source_path = _setup(tmp_path, monkeypatch)

    code = _run(monkeypatch, f"{VOL_B}__golden", "--update-source-dir")

    assert code == 0
    assert source_path("b" * 32).endswith(f"{VOL_B}__golden"), "本卷入口应改指新产物"
    assert source_path("a" * 32).endswith(f"{VOL_A}__golden"), "A 卷入口被越权改动"


def test_unmatched_volume_is_rejected_without_writing(tmp_path, monkeypatch, capsys):
    """目录存在、但卷名锚不到任何 source → 拒绝执行，且一个字的库都不能改。"""
    _, ocr, read, source_path = _setup(tmp_path, monkeypatch)
    _write_extract(ocr, "2026南开区一模物理试卷__golden", [_question(1, "X")])

    code = _run(monkeypatch, "2026南开区一模物理试卷__golden", "--update-source-dir")

    assert code == 2
    out = capsys.readouterr().out
    assert "找不到对应的 source" in out
    assert "--source-id" in out
    assert read(1, "a" * 32) == ("第1题题干", "A1", 0)
    assert read(1, "b" * 32) == ("第1题题干", "B1", 0)
    assert source_path("a" * 32).endswith(f"{VOL_A}__golden")
    assert source_path("b" * 32).endswith(f"{VOL_B}__old")


def test_missing_product_dir_reports_missing_file(tmp_path, monkeypatch, capsys):
    """目录本身不存在 → 报「找不到产物」。两种错误要能区分，否则会把人带偏。"""
    _, _, read, _ = _setup(tmp_path, monkeypatch)

    assert _run(monkeypatch, "根本不存在__golden") == 2
    out = capsys.readouterr().out
    assert "找不到产物" in out
    assert "source" not in out
    assert read(1, "a" * 32) == ("第1题题干", "A1", 0)


def test_soft_deleted_question_in_own_volume_is_not_targeted(tmp_path, monkeypatch):
    """本卷下软删的题不参与同步：is_deleted=1 的行不该被复活。"""
    _, _, read, _ = _setup(tmp_path, monkeypatch, b_deleted=True)

    code = _run(monkeypatch, f"{VOL_B}__golden")

    assert code == 2
    assert read(1, "b" * 32) == ("第1题题干", "B1", 1), "软删的行被改了"


# --------------------------------------------------------------------------- 锚定规则


def test_directory_suffix_forms_all_anchor_to_same_volume(tmp_path, monkeypatch):
    """`卷名` / `卷名__golden` / `卷名__golden__v6` 都要锚到同一卷。

    双后缀不能靠 rsplit("__") 切 —— 那会把卷名切成 `卷名__golden`。
    这里用 `Path(filename).stem` 做前缀匹配，不猜切分规则。
    """
    db = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute("insert into sources values (?,?,?,?)", ("a" * 32, f"{VOL_A}.pdf", 0, ""))
    conn.commit()
    for name in (VOL_A, f"{VOL_A}__golden", f"{VOL_A}__golden__v6", f"{VOL_A}__v12"):
        got = s._resolve_source(conn, name, None)
        assert got == ("a" * 32, f"{VOL_A}.pdf"), name
    conn.close()


def test_explicit_source_id_wins(tmp_path, monkeypatch):
    """卷名反查不唯一时 --source-id 兜底。"""
    db = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute("insert into sources values (?,?,?,?)", ("a" * 32, f"{VOL_A}.pdf", 0, ""))
    conn.commit()

    assert s._resolve_source(conn, "别的卷__v1", "a" * 32) == ("a" * 32, f"{VOL_A}.pdf")
    assert s._resolve_source(conn, "别的卷__v1", "f" * 32) is None
    conn.close()


def test_ambiguous_filename_is_rejected(tmp_path, capsys):
    """同名文件上传过两次 → 匹配到两个 source → 必须拒绝而不是瞎猜。"""
    db = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.executemany(
        "insert into sources values (?,?,?,?)",
        [("a" * 32, f"{VOL_A}.pdf", 0, ""), ("b" * 32, f"{VOL_A}.pdf", 0, "")],
    )
    conn.commit()

    assert s._resolve_source(conn, f"{VOL_A}__golden", None) is None
    assert "匹配到 2 个 source" in capsys.readouterr().out
    conn.close()


def test_new_volume_hint_points_to_correct_entry(tmp_path, capsys):
    """锚不到时要提示「新卷不走这里」，否则用户会拿 --source-id 硬凑。"""
    db = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute("insert into sources values (?,?,?,?)", ("a" * 32, f"{VOL_A}.pdf", 0, ""))
    conn.commit()

    assert s._resolve_source(conn, "全新卷__golden", None) is None
    assert "只更新已有题、不新建" in capsys.readouterr().out
    conn.close()


# --------------------------------------------------------------------------- 题号护栏


def test_duplicate_question_number_in_volume_is_rejected(tmp_path):
    """同卷内题号重复 → 按题号定位会静默覆盖 → 拒绝。"""
    db = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.executemany(
        "insert into questions (id, source_id, question_number, is_deleted) values (?,?,?,0)",
        [(1, "a" * 32, 5), (2, "a" * 32, 5)],
    )
    conn.commit()

    rows, dups = s._load_questions(conn, "a" * 32)
    assert dups == [5]
    assert len(rows) == 1  # dict 天然吞掉后一条 —— 所以要靠 dups 拦
    conn.close()


def test_load_questions_is_scoped_and_skips_deleted(tmp_path):
    """作用域 + 软删过滤一起验。"""
    db = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.executemany(
        "insert into questions (id, source_id, question_number, answer, is_deleted) "
        "values (?,?,?,?,?)",
        [
            (1, "a" * 32, 1, "A1", 0),
            (2, "a" * 32, 2, "A2", 1),
            (3, "b" * 32, 1, "B1", 0),
        ],
    )
    conn.commit()

    rows_a, _ = s._load_questions(conn, "a" * 32)
    assert set(rows_a) == {1}, "软删题不该进，B 卷题更不该进"
    rows_b, _ = s._load_questions(conn, "b" * 32)
    assert set(rows_b) == {1}
    assert rows_b[1][4] == "B1"  # [4]=answer（select 顺序见 _load_questions）
    conn.close()


# --------------------------------------------------------------------------- 四条底线仍在


def test_blocked_product_is_refused(tmp_path, monkeypatch, capsys):
    """闸门阻断时拒绝同步（除非 --force）。"""
    db, ocr, _, _ = _setup(tmp_path, monkeypatch)
    d = ocr / f"{VOL_B}__golden"
    doc = json.loads((d / "extract.json").read_text(encoding="utf-8"))
    doc["audit"] = {"blocked": True, "reasons": ["覆盖率不足"]}
    (d / "extract.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    assert _run(monkeypatch, f"{VOL_B}__golden") == 2
    assert "阻断" in capsys.readouterr().out


def test_unconfirmed_product_only_dry_runs(tmp_path, monkeypatch, capsys):
    """confirmed=false 时默认不写库。"""
    db, ocr, read, _ = _setup(tmp_path, monkeypatch)
    _write_extract(ocr, f"{VOL_B}__golden", [_question(1, "B1-NEW")], confirmed=False)

    assert _run(monkeypatch, f"{VOL_B}__golden") == 2
    assert "confirmed=false" in capsys.readouterr().out
    assert read(1, "b" * 32) == ("第1题题干", "B1", 0)


def test_missing_image_aborts(tmp_path, monkeypatch, capsys):
    """图片路径不存在时中止，不写库。"""
    db, ocr, read, _ = _setup(tmp_path, monkeypatch)
    item = _question(1, "B1-NEW")
    item["card_image"] = "cards/Q001.webp"  # 不创建这个文件
    _write_extract(ocr, f"{VOL_B}__golden", [item])

    assert _run(monkeypatch, f"{VOL_B}__golden") == 2
    assert "不存在" in capsys.readouterr().out
    assert read(1, "b" * 32) == ("第1题题干", "B1", 0)


def test_no_diff_is_reported_as_noop(tmp_path, monkeypatch, capsys):
    """内容一致时不要制造噪音差异。"""
    db, ocr, _, _ = _setup(tmp_path, monkeypatch)

    assert _run(monkeypatch, f"{VOL_B}__old") == 0
    assert "无需同步" in capsys.readouterr().out
