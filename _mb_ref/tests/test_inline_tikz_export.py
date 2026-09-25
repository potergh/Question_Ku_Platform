"""Pure export regressions: no application startup or real question database."""

import os
import shutil

import pytest

from mathbank.paper_helper import build_latex_document, compile_tex_to_pdf


TRIANGLE = r"""\begin{tikzpicture}
% Keep this newline: the next command must not become a comment.
\draw (0,0)--(3,0)--(1,2)--cycle;
\node[below] at (0,0) {$A$};
\node[below] at (3,0) {$B$};
\node[above] at (1,2) {$C$};
\end{tikzpicture}"""
CIRCLE = r"\begin{tikzpicture}\draw (0,0) circle (1);\end{tikzpicture}"
PLOT = r"""\begin{tikzpicture}
\begin{axis}[width=6cm,height=4cm,axis lines=middle,domain=-1:1]
\addplot[samples=30] {x^2};
\end{axis}
\end{tikzpicture}"""
PATTERN = r"""\begin{tikzpicture}
\fill[pattern=north east lines] (0,0) rectangle (2,1);
\draw (0,0) rectangle (2,1);
\end{tikzpicture}"""
CHOICES = r"""\begin{choices}
\item $1$
\item $2$
\item $3$
\item $4$
\end{choices}"""
IMAGE = "![几何图](/static/uploads/tikz_triangle.png)"
ASSET = {
    "id": "triangle",
    "image_path": "/static/uploads/tikz_triangle.png",
    "tikz_code": TRIANGLE,
    "reference_image_path": "/static/uploads/private_reference.png",
}


def make_tex(content, *, paper_type="quiz", include_answers=False, **overrides):
    question = {
        "id": 9100,
        "question_type": "single_choice",
        "content": content,
        "content_tikz_assets": [ASSET],
        "figure_align": "center",
        "figure_size": "large",
        **overrides,
    }
    return build_latex_document(
        "插图位置验证", "", paper_type,
        [{"question": question, "score": 5}],
        include_answers=include_answers, show_secret=False, show_notice=False,
    )


@pytest.mark.parametrize("paper_type", ["exam", "quiz", "exam_19"])
@pytest.mark.parametrize("q_type", ["single_choice", "multi_choice"])
@pytest.mark.parametrize("include_answers", [False, True])
def test_between_stem_and_choices_uses_source(paper_type, q_type, include_answers):
    tex = make_tex(
        "如图，求三角形的面积。\n\n" + IMAGE + "\n\n" + CHOICES,
        paper_type=paper_type, question_type=q_type, include_answers=include_answers,
    )
    assert tex.index("如图") < tex.index(TRIANGLE) < tex.index(CHOICES.splitlines()[0])
    assert tex.count(TRIANGLE) == 1
    assert "tikz_triangle.png" not in tex
    assert "private_reference" not in tex
    assert "MATHBANKTIKZ" not in tex


def test_plain_letter_choices_do_not_parse_drawing_source_as_prose():
    code = TRIANGLE.replace("% Keep this newline", "% A. comment with $ and \\paren: Keep this newline")
    tex = make_tex(
        "题干\n\n" + IMAGE + "\n\nA. 1\nB. 2\nC. 3\nD. 4",
        content_tikz_assets=[{**ASSET, "tikz_code": code}],
    )
    assert code in tex
    assert tex.index(code) < tex.index(r"\begin{choices}")
    assert tex.count(r"\item") == 4


@pytest.mark.parametrize("environment", [
    "tabular", "tabular*", "tabularx", "longtable", "tblr", "longtblr", "talltblr",
])
def test_mixed_table_images_keep_source_and_cell_anchor(environment):
    content = (
        "表格之前\n" + rf"\begin{{{environment}}}{{|c|c|c|}}" + "\n"
        + "图形 & " + IMAGE + r" & ![](/static/uploads/photo.png) \\" + "\n"
        + rf"\end{{{environment}}}" + "\n表格之后"
    )
    tex = make_tex(content, question_type="detailed_answer")
    exported_env = "tabularx" if environment == "tabular" else environment
    assert tex.index(rf"\begin{{{exported_env}}}") < tex.index(TRIANGLE)
    assert tex.index(TRIANGLE) < tex.index("photo.png") < tex.index(rf"\end{{{exported_env}}}")
    assert tex.index(rf"\end{{{exported_env}}}") < tex.index("表格之后")
    assert "tikz_triangle.png" not in tex
    assert r"\adjustbox{max width=\linewidth,max height=4.0cm,keepaspectratio}{" in tex
    assert r"\begin{center}" not in tex[tex.index("表格之前"):tex.index("表格之后")]


def test_multiple_assets_follow_markdown_order_with_ordinary_images():
    second = {"id": "circle", "image_path": "/static/uploads/tikz_circle.png", "tikz_code": CIRCLE}
    tex = make_tex(
        "题干\n![](/static/uploads/tikz_circle.png)\n说明一\n"
        "![](/static/uploads/photo.png)\n说明二\n" + IMAGE + "\n" + CHOICES,
        content_tikz_assets=[ASSET, second],
    )
    assert tex.index(CIRCLE) < tex.index("说明一") < tex.index("photo.png")
    assert tex.index("photo.png") < tex.index("说明二") < tex.index(TRIANGLE)
    assert tex.count(TRIANGLE) == tex.count(CIRCLE) == 1


@pytest.mark.parametrize("prefix", ["/static/uploads/", "static/uploads/", "/uploads/", "uploads/", ""])
def test_upload_path_aliases_match(prefix):
    tex = make_tex("题干\n![](" + prefix + "tikz_triangle.png)\n" + CHOICES)
    assert TRIANGLE in tex
    assert "tikz_triangle.png" not in tex


def test_same_basename_in_another_folder_is_not_the_same_asset():
    tex = make_tex("题干\n![](/static/uploads/tmp/tikz_triangle.png)\n" + CHOICES)
    assert TRIANGLE not in tex
    assert "includegraphics" in tex and "tikz_triangle.png" in tex


def test_missing_source_keeps_png_and_does_not_inject_unreferenced_assets():
    tex = make_tex(
        "题干\n" + IMAGE + "\n" + CHOICES,
        content_tikz_assets=[{**ASSET, "tikz_code": ""}, {
            "id": "unused", "image_path": "/static/uploads/unused.png", "tikz_code": CIRCLE,
        }],
    )
    assert "tikz_triangle.png" in tex
    assert TRIANGLE not in tex and CIRCLE not in tex


def test_legacy_single_tikz_image_uses_source_but_ambiguous_images_do_not():
    tex = make_tex("题干\n" + IMAGE + "\n" + CHOICES, content_tikz_assets=[], tikz_code=TRIANGLE)
    assert TRIANGLE in tex
    ambiguous = make_tex(
        "题干\n" + IMAGE + "\n![](/static/uploads/tikz_other.png)\n" + CHOICES,
        content_tikz_assets=[], tikz_code=TRIANGLE,
    )
    assert TRIANGLE not in ambiguous
    assert "tikz_triangle.png" in ambiguous and "tikz_other.png" in ambiguous


def test_trailing_tikz_keeps_existing_vector_layout():
    tex = make_tex("题干\n" + CHOICES + "\n" + IMAGE)
    assert tex.count(TRIANGLE) == 1
    assert tex.index(TRIANGLE) < tex.index(r"\begin{choices}")
    assert "tikz_triangle.png" not in tex


def test_paper_without_tikz_does_not_require_additional_drawing_libraries():
    tex = make_tex("普通选择题\n" + CHOICES, content_tikz_assets=[])
    assert r"\usepackage{pgfplots}" not in tex
    assert r"\usetikzlibrary{patterns" not in tex


@pytest.mark.skipif(
    os.environ.get("MATHBANK_TEST_TIKZ_NATIVE") != "1" or not shutil.which("xelatex"),
    reason="Opt-in native XeLaTeX regression",
)
@pytest.mark.parametrize("scenario", ["choice", "table", "multiple", "plot", "pattern"])
def test_native_pdf_contains_vector_drawing_without_preview_png(scenario):
    import pymupdf as fitz

    content = "如图，求三角形的面积。\n\n" + IMAGE + "\n\n" + CHOICES
    overrides = {}
    if scenario == "table":
        content = (
            "如图，求三角形的面积。\n\n"
            r"\begin{tabular}{|c|c|c|}" "\n" r"\hline" "\n"
            + "图形 & " + IMAGE + r" & 对照说明 \\ \hline" "\n"
            r"\end{tabular}" "\n\n" + CHOICES
        )
    elif scenario == "multiple":
        content = "如图，求三角形的面积。\n\n" + IMAGE + "\n\n对照下图。\n\n" + IMAGE + "\n\n" + CHOICES
    elif scenario in {"plot", "pattern"}:
        overrides["content_tikz_assets"] = [{**ASSET, "tikz_code": PLOT if scenario == "plot" else PATTERN}]
    tex = make_tex(content, **overrides)
    # Deliberately provide no PNG: success must come from compiling the source.
    pdf, diagnostic = compile_tex_to_pdf(tex)
    assert pdf, diagnostic
    with fitz.open(stream=pdf, filetype="pdf") as document:
        assert len(document) == 1
        assert document[0].get_drawings()
        assert document[0].get_images(full=True) == []
        assert "求三角形" in document[0].get_text()
