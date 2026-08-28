"""Export Spike — Test PDF generation with Chinese + KaTeX formulas + images.

Uses Playwright (headless Chromium) to render HTML → PDF.
This approach natively supports:
- Chinese text (via system fonts)
- KaTeX math rendering (real browser JS execution)
- CSS layout, tables, page breaks
- Images (local file paths)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))


def create_test_html():
    """Create a test HTML page with all the challenging elements, including KaTeX."""
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<!-- KaTeX CSS + JS from CDN -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
    onload="renderMathInElement(document.body, {
        delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false}
        ]
    });"></script>
<style>
    @page {
        size: A4;
        margin: 2cm;
    }
    body {
        font-family: "Microsoft YaHei", "SimSun", sans-serif;
        font-size: 12pt;
        line-height: 1.8;
    }
    .header {
        text-align: center;
        border-bottom: 2px solid #333;
        padding-bottom: 10px;
        margin-bottom: 20px;
    }
    .header h1 { font-size: 20pt; margin: 0; }
    .header .subtitle { color: #666; font-size: 10pt; }
    h2 {
        font-size: 14pt;
        color: #2c3e50;
        border-left: 4px solid #3498db;
        padding-left: 10px;
        margin-top: 25px;
    }
    .question {
        margin: 15px 0;
        padding: 15px;
        background: #f8f9fa;
        border-radius: 5px;
        page-break-inside: avoid;
    }
    .question-number { font-weight: bold; color: #e74c3c; }
    .options { margin: 10px 0 10px 20px; }
    .options li { list-style: none; margin: 5px 0; }
    .formula-block {
        text-align: center;
        margin: 15px 0;
        font-size: 13pt;
    }
    table { border-collapse: collapse; width: 100%; margin: 15px 0; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: center; }
    th { background: #3498db; color: white; }
    .answer-section {
        margin-top: 30px;
        padding: 15px;
        background: #e8f5e9;
        border-radius: 5px;
        page-break-before: always;
    }
    .blank {
        display: inline-block;
        width: 80px;
        border-bottom: 1px solid #333;
    }
    .figure-box {
        width: 200px; height: 120px;
        border: 2px dashed #ccc;
        text-align: center;
        line-height: 120px;
        color: #999;
        margin: 10px auto;
        font-size: 10pt;
    }
</style>
</head>
<body>

<div class="header">
    <h1>高中物理 · 牛顿运动定律专题</h1>
    <div class="subtitle">家教讲义 · 学生版 &nbsp;|&nbsp; 2026年8月</div>
</div>

<h2>一、选择题（每题 5 分）</h2>

<div class="question">
    <p><span class="question-number">1.</span>
    如图所示，一个质量为 $m = 2\\,\\text{kg}$ 的物体放在光滑水平面上，
    受到水平方向的力 $F = 10\\,\\text{N}$ 作用，
    则物体的加速度为：</p>

    <div class="figure-box">[ 物理图：力的示意图 ]</div>

    <ul class="options">
        <li>A. $1\\,\\text{m/s}^2$</li>
        <li>B. $2\\,\\text{m/s}^2$</li>
        <li>C. $5\\,\\text{m/s}^2$</li>
        <li>D. $10\\,\\text{m/s}^2$</li>
    </ul>
</div>

<div class="question">
    <p><span class="question-number">2.</span>
    关于牛顿第二定律 $F = ma$，下列说法正确的是：</p>
    <ul class="options">
        <li>A. 力是产生加速度的原因</li>
        <li>B. 质量越大，加速度越小</li>
        <li>C. 加速度方向与合力方向相同</li>
        <li>D. 以上说法都正确</li>
    </ul>
</div>

<h2>二、填空题（每空 3 分）</h2>

<div class="question">
    <p><span class="question-number">3.</span>
    牛顿第二定律的数学表达式为 <span class="blank"></span>，
    其中力的单位是 <span class="blank"></span>，
    质量的单位是 <span class="blank"></span>。</p>
</div>

<div class="question">
    <p><span class="question-number">4.</span>
    一个物体做匀加速直线运动，初速度 $v_0 = 2\\,\\text{m/s}$，
    加速度 $a = 3\\,\\text{m/s}^2$，则第 $2\\,\\text{s}$ 末的速度为
    <span class="blank"></span> $\\text{m/s}$。</p>
</div>

<h2>三、计算题</h2>

<div class="question">
    <p><span class="question-number">5.</span>（15 分）
    一个物体从静止开始做匀加速直线运动，加速度 $a = 2\\,\\text{m/s}^2$。
    求：</p>
    <p>（1）第 $3\\,\\text{s}$ 末的速度；</p>
    <p>（2）前 $3\\,\\text{s}$ 内的位移。</p>
</div>

<div class="question">
    <p><span class="question-number">6.</span>（20 分）
    如图所示，斜面倾角 $\\theta = 30°$，物体质量 $m = 5\\,\\text{kg}$，
    与斜面间的动摩擦因数 $\\mu = 0.2$。求物体沿斜面下滑的加速度。</p>

    <div class="figure-box">[ 斜面受力分析图 ]</div>

    <p>（提示：$g = 10\\,\\text{m/s}^2$，$\\sin 30° = 0.5$，$\\cos 30° \\approx 0.866$）</p>
</div>

<h2>四、知识总结</h2>

<table>
    <tr>
        <th>物理量</th>
        <th>符号</th>
        <th>单位</th>
        <th>公式</th>
    </tr>
    <tr><td>力</td><td>$F$</td><td>$\\text{N}$</td><td>$F = ma$</td></tr>
    <tr><td>质量</td><td>$m$</td><td>$\\text{kg}$</td><td>—</td></tr>
    <tr><td>加速度</td><td>$a$</td><td>$\\text{m/s}^2$</td><td>$a = \\dfrac{F}{m}$</td></tr>
    <tr><td>速度</td><td>$v$</td><td>$\\text{m/s}$</td><td>$v = v_0 + at$</td></tr>
    <tr><td>位移</td><td>$s$</td><td>$\\text{m}$</td><td>$s = v_0 t + \\dfrac{1}{2}at^2$</td></tr>
</table>

<div class="answer-section">
    <h2>参考答案</h2>
    <p><strong>1.</strong> C &nbsp; $a = \\dfrac{F}{m} = \\dfrac{10}{2} = 5\\,\\text{m/s}^2$</p>
    <p><strong>2.</strong> D</p>
    <p><strong>3.</strong> $F = ma$；牛顿（$\\text{N}$）；千克（$\\text{kg}$）</p>
    <p><strong>4.</strong> $v = v_0 + at = 2 + 3 \\times 2 = 8\\,\\text{m/s}$</p>
    <p><strong>5.</strong> (1) $v = at = 2 \\times 3 = 6\\,\\text{m/s}$ &nbsp; (2) $s = \\frac{1}{2}at^2 = \\frac{1}{2} \\times 2 \\times 9 = 9\\,\\text{m}$</p>
    <p><strong>6.</strong> $a = g(\\sin\\theta - \\mu\\cos\\theta) = 10(0.5 - 0.2 \\times 0.866) = 3.27\\,\\text{m/s}^2$</p>
</div>

</body>
</html>"""


async def main():
    from playwright.async_api import async_playwright

    output_dir = Path(__file__).parent / "data" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    html_content = create_test_html()
    output_path = output_dir / "spike_test.pdf"

    print("=" * 60)
    print("Export Spike: Playwright + KaTeX → PDF")
    print("=" * 60)
    print()
    print("Testing:")
    print("  [v] 中文 + 英文混排")
    print("  [v] KaTeX 数学公式（行内 + 行间）")
    print("  [v] 分数、根号、上下标")
    print("  [v] 表格")
    print("  [v] 选择题排版")
    print("  [v] 页面分隔（page-break）")
    print("  [v] 图占位框")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # Load HTML content
        await page.set_content(html_content, wait_until="networkidle")

        # Wait for KaTeX to finish rendering
        await page.wait_for_timeout(2000)

        # Generate PDF
        await page.pdf(
            path=str(output_path),
            format="A4",
            margin={"top": "2cm", "bottom": "2cm", "left": "2cm", "right": "2cm"},
            print_background=True,
        )

        await browser.close()

    file_size = output_path.stat().st_size / 1024
    print(f"[OK] PDF generated: {output_path}")
    print(f"   File size: {file_size:.1f} KB")
    print()
    print("请打开 PDF 检查：")
    print("  1. 中文是否正常显示")
    print("  2. KaTeX 公式是否正确渲染（分数、上下标、希腊字母）")
    print("  3. 表格是否正确")
    print("  4. 答案页是否在新页开始")
    print("  5. 整体排版质量")
    print()
    print("决策建议：")
    print("  如果 PDF 质量可接受 → 采用 Playwright 方案")
    print("  如果公式有问题 → 检查 KaTeX CDN 加载（离线需本地化）")


if __name__ == "__main__":
    asyncio.run(main())
