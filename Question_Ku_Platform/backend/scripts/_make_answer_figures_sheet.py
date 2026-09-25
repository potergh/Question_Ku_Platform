"""把某份产物的答案区插图拼成一张对照图，方便人工核对「抓的是不是那张图」。

清单/报告里逐题看 9 张图很累；拼成一张带题号标注的网格，一眼就能比对。

用法：
    python -m scripts._make_answer_figures_sheet
    python -m scripts._make_answer_figures_sheet --dirname 2022年天津市和平区中考物理一模试卷__v9landing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.config import settings  # noqa: E402

DEFAULT_DIRNAME = "2022年天津市和平区中考物理一模试卷__v9landing"
OUT_PATH = BACKEND_DIR / "scripts" / "reports" / "answer_figures_contact_sheet.png"

CELL_W, CELL_H = 360, 280
CAPTION_H = 34
COLS = 4
TITLE_H = 64
BG = (248, 249, 251)
CELL_BG = (255, 255, 255)
BORDER = (214, 218, 224)
TITLE_FG = (32, 38, 48)
CAPTION_FG = (90, 98, 112)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _caption_for(name: str) -> str:
    """answer_Q020_01.webp → 第20题 · 图1"""
    stem = Path(name).stem  # answer_Q020_01
    parts = stem.split("_")
    if len(parts) >= 3 and parts[0] == "answer":
        number = parts[1].lstrip("Q0") or "0"
        index = parts[2].lstrip("0") or "0"
        return f"第 {number} 题 · 图 {index}"
    return stem


def collect(workdir: Path) -> list[Path]:
    figures_dir = workdir / "figures"
    if not figures_dir.is_dir():
        raise SystemExit(f"找不到 figures 目录：{figures_dir}")
    files = sorted(figures_dir.glob("answer_Q*.webp"))
    if not files:
        raise SystemExit(f"{figures_dir} 下没有 answer_Q*.webp")
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dirname", default=DEFAULT_DIRNAME)
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    workdir = settings.ocr_output_dir / args.dirname
    files = collect(workdir)

    rows = (len(files) + COLS - 1) // COLS
    sheet_w = CELL_W * COLS
    sheet_h = TITLE_H + rows * (CELL_H + CAPTION_H)
    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)

    title_font = _font(26)
    caption_font = _font(20)
    by_number: dict[str, int] = {}
    for path in files:
        stem = path.stem.split("_")
        if len(stem) >= 2:
            by_number[stem[1]] = by_number.get(stem[1], 0) + 1
    summary = " / ".join(f"{k.lstrip('Q0')}×{v}" for k, v in sorted(by_number.items()))
    draw.text(
        (18, 18),
        f"答案区插图 {len(files)} 张（题号×张数：{summary}）· {args.dirname}",
        font=title_font,
        fill=TITLE_FG,
    )

    for index, path in enumerate(files):
        row, col = divmod(index, COLS)
        x = col * CELL_W
        y = TITLE_H + row * (CELL_H + CAPTION_H)
        draw.rectangle(
            [x + 6, y + 6, x + CELL_W - 6, y + CELL_H - 6],
            fill=CELL_BG,
            outline=BORDER,
            width=1,
        )
        image = Image.open(path).convert("RGB")
        image.thumbnail((CELL_W - 24, CELL_H - 24), Image.LANCZOS)
        paste_x = x + (CELL_W - image.width) // 2
        paste_y = y + (CELL_H - image.height) // 2
        sheet.paste(image, (paste_x, paste_y))
        caption = _caption_for(path.name)
        text_w = draw.textlength(caption, font=caption_font)
        draw.text(
            (x + (CELL_W - text_w) / 2, y + CELL_H + 4),
            caption,
            font=caption_font,
            fill=CAPTION_FG,
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    print(f"已生成：{out_path}  ({sheet_w}x{sheet_h}, {len(files)} 张图)")
    for path in files:
        print(f"  - {_caption_for(path.name)}  ←  {path.name}  "
              f"{Image.open(path).size[0]}x{Image.open(path).size[1]}")


if __name__ == "__main__":
    main()
