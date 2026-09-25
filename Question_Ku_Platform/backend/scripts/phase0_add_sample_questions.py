"""阶段 0 验收补丁：手工补录样题进题库，补齐覆盖缺口（幂等）。

缺口（见验收清单）：题库 195 题几乎无 LaTeX 公式、无选项图。
补录 4 题到来源"手动补录样题（公式+选项图）"：
- 数学选择：选项含图（/api/ocr-assets 形式，走真实引用迁移管线）
- 数学综合：行内 $…$ + 行间 $$…$$ 公式
- 物理填空：公式计算（$…$ 行内 + $$…$$ 行间）
- 物理综合：题干图（/api/ocr-assets）+ 公式
图片由 PIL 现场生成（几何图形/斜面示意图），存到该来源的 figures/ 目录。
"""

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from PIL import Image, ImageDraw  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models import Question, Source  # noqa: E402

SOURCE_FILENAME = "手动补录样题（公式+选项图）"
OCR_DIR = settings.data_dir / "ocr_output" / "manual_samples"


def _draw_figures() -> None:
    """生成几何图形选项图与斜面示意图（无中文，避免字体依赖）。"""
    fig = OCR_DIR / "figures"
    fig.mkdir(parents=True, exist_ok=True)

    def canvas():
        return Image.new("RGB", (240, 180), "white"), None

    # A 三角形（轴对称、非中心对称）
    img, _ = canvas()
    d = ImageDraw.Draw(img)
    d.polygon([(120, 20), (40, 160), (200, 160)], outline="black", width=3)
    img.save(fig / "opt_A.webp")
    # B 平行四边形（中心对称、非轴对称）
    img, _ = canvas()
    d = ImageDraw.Draw(img)
    d.polygon([(70, 40), (220, 40), (170, 140), (20, 140)], outline="black", width=3)
    img.save(fig / "opt_B.webp")
    # C 正方形（既轴对称又中心对称）
    img, _ = canvas()
    d = ImageDraw.Draw(img)
    d.rectangle([50, 25, 190, 165], outline="black", width=3)
    img.save(fig / "opt_C.webp")
    # D 梯形（都对称也谈不上——普通等腰梯形只轴对称→改为不规则四边形：都不对称）
    img, _ = canvas()
    d = ImageDraw.Draw(img)
    d.polygon([(40, 50), (190, 30), (210, 150), (80, 130)], outline="black", width=3)
    img.save(fig / "opt_D.webp")
    # 斜面示意图：直角三角形 + 木箱 + 推力 F
    img = Image.new("RGB", (420, 260), "white")
    d = ImageDraw.Draw(img)
    d.polygon([(30, 230), (390, 230), (390, 60)], outline="black", width=3)
    d.rectangle([200, 128, 250, 168], outline="black", width=3)   # 木箱（近似沿斜面）
    d.line([(255, 140), (320, 108)], fill="black", width=3)        # 推力方向
    d.text((322, 96), "F", fill="black")
    img.save(fig / "Q_incline_01.webp")


def _ref(source_id: str, name: str) -> str:
    return f"![figure](/api/ocr-assets/{source_id}/figures/{name})"


QUESTIONS = [
    dict(
        sid="M001", number=1, qtype="single_choice", subject="math", grade="初三",
        content="下列图形中，既是轴对称图形又是中心对称图形的是（　　）",
        options=[{"label": "A", "content": "三角形 {OA}"},
                 {"label": "B", "content": "平行四边形 {OB}"},
                 {"label": "C", "content": "正方形 {OC}"},
                 {"label": "D", "content": "不规则四边形 {OD}"}],
        answer="C",
        explanation="正方形既有对称轴又有对称中心；三角形与等腰梯形类图形只轴对称，"
                    "平行四边形只中心对称，不规则四边形两者都不是。",
    ),
    dict(
        sid="M002", number=2, qtype="comprehensive", subject="math", grade="初三",
        content="已知关于 $x$ 的一元二次方程 $x^2-(2k+1)x+k^2+k=0$。\n"
                "（1）求证：方程总有两个不相等的实数根；\n"
                "（2）若方程的一个根为 $x=2$，求 $k$ 的值及方程的另一个根。",
        options=None,
        answer="（1）见解析；（2）k=1 或 k=2，另一个根为 1 或 3",
        explanation="（1）$$\\Delta=(2k+1)^2-4(k^2+k)=1>0$$ 故方程总有两个不相等的实数根。\n"
                    "（2）把 $x=2$ 代入得 $4-2(2k+1)+k^2+k=0$，即 $k^2-3k+2=0$，解得 $k=1$ 或 $k=2$。\n"
                    "由两根之和 $x_1+x_2=2k+1$：当 $k=1$ 时和为 $3$，另一根为 $1$；"
                    "当 $k=2$ 时和为 $5$，另一根为 $3$。",
    ),
    dict(
        sid="M003", number=3, qtype="fill_blank", subject="physics", grade="初三",
        content="一只小灯泡标有“6V 3W”字样。它正常发光时，通过灯丝的电流为 ______ A，"
                "灯丝的电阻为 ______ Ω；正常发光 1 分钟消耗的电能为 ______ J。",
        options=None,
        answer="0.5；12；180",
        explanation="$$I=\\frac{P}{U}=\\frac{3\\mathrm{W}}{6\\mathrm{V}}=0.5\\mathrm{A},\\quad "
                    "R=\\frac{U^2}{P}=\\frac{(6\\mathrm{V})^2}{3\\mathrm{W}}=12\\Omega$$ "
                    "$W=Pt=3\\times60=180\\mathrm{J}$。",
    ),
    dict(
        sid="M004", number=4, qtype="comprehensive", subject="physics", grade="初三",
        content="如图所示，工人用斜面将质量为 $60\\ \\ $ 的木箱匀速推上高 $1.5\\ \\ $ 的平台，"
                "斜面长 $5\\ \\ $，沿斜面向上的推力 $F=240\\ \\ $。（$g$ 取 $10\\ \\ $）\n"
                "（1）求把木箱举高所做的有用功；\n"
                "（2）求推力做的总功与斜面的机械效率。\n\n{INCLINE}",
        options=None,
        answer="（1）900 J；（2）1200 J，75%",
        explanation="（1）$$W_{有}=Gh=mgh=60\\times10\\times1.5=900\\mathrm{J}$$\n"
                    "（2）$$W_{总}=FL=240\\times5=1200\\mathrm{J},\\quad "
                    "\\eta=\\frac{W_{有}}{W_{总}}=\\frac{900}{1200}=75\\%$$",
    ),
]


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    async with async_session_factory() as db:
        existing = (await db.execute(
            select(Source).where(Source.filename == SOURCE_FILENAME))).scalar_one_or_none()
        if existing:
            n = (await db.execute(select(Question).where(
                Question.source_id == existing.id, Question.is_deleted == False))).scalars().all()  # noqa: E712
            print(f"已存在（{len(n)} 题），跳过补录。如需重建请先删除来源 {SOURCE_FILENAME}")
            return

        _draw_figures()
        source = Source(filename=SOURCE_FILENAME, file_path=str(OCR_DIR), file_type="pdf",
                        ocr_status="done", ocr_result_path=str(OCR_DIR))
        db.add(source)
        await db.flush()
        await db.refresh(source)

        for spec in QUESTIONS:
            options = None
            if spec["options"]:
                options = [{"label": o["label"],
                            "content": o["content"].replace(
                                "{O" + o["label"] + "}", _ref(source.id, f"opt_{o['label']}.webp"))}
                           for o in spec["options"]]
            content = spec["content"].replace("{INCLINE}", _ref(source.id, "Q_incline_01.webp"))
            db.add(Question(
                source_id=source.id, source_question_id=spec["sid"],
                question_number=spec["number"], question_type=spec["qtype"],
                subject=spec["subject"], grade=spec["grade"], difficulty=3,
                content=content, options=options,
                answer=spec["answer"], explanation=spec["explanation"],
                needs_review=False, review_status="approved", ocr_confidence=1.0,
            ))
        await db.commit()
        print(f"已补录 {len(QUESTIONS)} 道样题 → 来源 {SOURCE_FILENAME}")
        print(f"图片目录：{OCR_DIR / 'figures'}")


if __name__ == "__main__":
    asyncio.run(main())
