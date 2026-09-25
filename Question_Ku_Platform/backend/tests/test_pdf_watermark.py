"""PDF 水印清洗。

两个要点：
1. 只中和**自述为水印**的 Form XObject（/PieceInfo/ADBE_CompoundType/Private
   /Watermark），别的对象一律不动；
2. 清洗副本**必须与原文件同名**（只换目录）—— run_extract 与 OCRAdapter 都用
   `pdf_path.stem` 推导输出目录，改名会让重跑生成新目录、题卡资产 URL 全部失配。
"""

from __future__ import annotations

import pathlib

import pymupdf

from app.utils.pdf_watermark import CLEAN_DIR_NAME, prepare_pdf, strip_watermarks


def _build_pdf(path: pathlib.Path, *, marked: bool = True) -> pathlib.Path:
    """造一份 PDF：正文一个黑方块，另加一个（可标记为水印的）Form XObject。

    分两阶段是必须的：
    - 页面创建后先落盘，让内容流固化；
    - 重开后先 clean_contents()，**再**写资源键 —— clean_contents() 会重建页面
      Resources，先写会被丢掉，渲染时报 "cannot find XObject resource"。
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(100, 100, 200, 200), fill=(0, 0, 0))
    doc.save(path)
    doc.close()

    doc = pymupdf.open(path)
    page = doc[0]
    page.clean_contents()

    xref = doc.get_new_xref()
    marker = (
        "/PieceInfo << /ADBE_CompoundType << /Private /Watermark >> >>" if marked else ""
    )
    doc.update_object(
        xref,
        f"<< /Type /XObject /Subtype /Form /BBox [0 0 50 50] /Resources <<>> {marker} >>",
    )
    doc.update_stream(xref, b"0 0 50 50 re f")
    doc.xref_set_key(page.xref, "Resources/XObject/Wm", f"{xref} 0 R")

    cont_xref = page.get_contents()[0]
    body = doc.xref_stream(cont_xref) or b""
    doc.update_stream(cont_xref, body + b"\nq 1 0 0 1 250 250 cm /Wm Do Q\n")

    stage = path.with_name(path.stem + ".stage.pdf")
    doc.save(stage, garbage=1)
    doc.close()
    stage.replace(path)

    # 自检：样本没造好就别让测试去猜（否则只会渲染出一堆无意义的错误）。
    with pymupdf.open(path) as check:
        names = [entry[1] for entry in check[0].get_xobjects() or []]
        assert "Wm" in names, f"样本 PDF 未引用 XObject：{names}"
    return path


def _ink(path: pathlib.Path) -> int:
    """渲染后非白像素数：用来证明对象「画了/没画」。

    注意先把样点取出来存成 bytes 再遍历 —— ``pix.samples`` 每访问一次都可能
    重建整个缓冲区，写成 ``pix.samples[i]`` 会退化成「每次循环复制 1.5MB」，
    实测把一个测试从 0.05 秒拖到 146 秒。
    """
    with pymupdf.open(path) as doc:
        pix = doc[0].get_pixmap(dpi=72)
        samples = bytes(pix.samples)
        stride = pix.n
    return sum(1 for value in samples[::stride] if value < 250)  # red 通道


def test_strip_neutralizes_declared_watermark(tmp_path):
    src = _build_pdf(tmp_path / "paper.pdf", marked=True)
    dst = tmp_path / "clean" / "paper.pdf"

    before = _ink(src)
    assert strip_watermarks(src, dst) == 1
    assert dst.exists()
    # 中和 = 不再绘制，而不是涂白：着色像素必须变少。
    assert _ink(dst) < before


def test_object_without_marker_is_left_alone(tmp_path):
    src = _build_pdf(tmp_path / "plain.pdf", marked=False)
    dst = tmp_path / "clean" / "plain.pdf"

    assert strip_watermarks(src, dst) == 0
    # 没有水印就不留副本，免得污染上传目录。
    assert not dst.exists()


def test_prepare_pdf_keeps_filename_but_moves_dir(tmp_path):
    src = _build_pdf(tmp_path / "试卷.pdf", marked=True)

    prepared = prepare_pdf(src)

    assert prepared != src
    assert prepared.name == src.name, "副本必须同名，否则输出目录会变"
    assert prepared.parent.name == CLEAN_DIR_NAME
    # 二次调用复用副本，不重复解析整份 PDF。
    assert prepare_pdf(src) == prepared


def test_prepare_pdf_returns_source_without_watermark(tmp_path):
    src = _build_pdf(tmp_path / "plain.pdf", marked=False)
    assert prepare_pdf(src) == src


def test_prepare_pdf_never_raises_on_broken_file(tmp_path):
    src = tmp_path / "broken.pdf"
    src.write_bytes(b"definitely not a pdf")

    # 清洗是加分项：坏文件必须回退原路径，让识别自己报错。
    assert prepare_pdf(src) == src


def test_prepare_pdf_missing_file(tmp_path):
    missing = tmp_path / "nope.pdf"
    assert prepare_pdf(missing) == missing
