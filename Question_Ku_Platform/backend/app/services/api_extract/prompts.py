"""api_extract 通道的提示词契约。

三条 prompt 的共同硬约束：
- 定死输出 JSON schema，字段缺失填 null，不允许自创字段；
- 严禁推测或编造答案（编造的答案会被组卷印出去，危害大于缺答案）；
- 图片只输出占位符，禁止描述或生成图片内容；
- 边界判定必须对每一行负责：要么归入某道题，要么归入非题目区域。
  这条规则是覆盖率审计能成立的前提。
"""

from __future__ import annotations

# ── 学科差异：公式严格度 ─────────────────────────────────────────────

# 需要严格 LaTeX 的学科
FORMULA_SUBJECTS = {"physics", "math", "chemistry", "物理", "数学", "化学"}

FORMULA_STRICT_CLAUSE = (
    "公式与符号要求：\n"
    "- 所有数学/物理/化学表达式必须转成 LaTeX，行内用 $...$，独立成行用 $$...$$。\n"
    "- 上下标必须正确：m/s² 写作 $\\mathrm{m/s^2}$，kg/m³ 写作 $\\mathrm{kg/m^3}$。\n"
    "- 单位与数字之间保留原文空格习惯，不要自行增删。\n"
    "- 化学方程式用 LaTeX 表示，反应条件写在 \\xrightarrow{} 上。\n"
    "- 无法确定的符号宁可保留原字符并在 warnings 中说明，禁止编造。"
)

FORMULA_PLAIN_CLAUSE = (
    "公式与符号要求：\n"
    "- 本文档以自然语言为主，保持原文文字，不要转 LaTeX。\n"
    "- 音标、特殊符号按原文 Unicode 字符保留。"
)


def formula_clause(subject: str | None) -> str:
    """按学科返回公式处理条款。学科为空时按严格处理（更安全）。"""
    if subject and subject.strip().lower() not in FORMULA_SUBJECTS:
        return FORMULA_PLAIN_CLAUSE
    return FORMULA_STRICT_CLAUSE


# ── 一、题目边界判定 ─────────────────────────────────────────────────

BOUNDARY_SYSTEM = """你是中文试卷与讲义的版面结构分析专家。你的唯一任务是：根据带行号与坐标的文字行清单，切分出每一道题目，并指出哪些行不属于任何题目。

输入格式说明：
- 每行形如 `#<line_id> [p<页码> y=<纵坐标>] <文字>`，line_id 在整个文档内唯一递增。
- 页码从 1 开始，y 是 PDF 坐标（自上而下增大），同一页内 y 小的在前。
- 清单已剔除页眉页脚与页码，你不需要再处理它们。

输出 JSON 结构（严格遵守，不要增加字段）：
{
  "doc_kind": "paper 或 handout",
  "questions": [
    {
      "label": "题目在原文中的编号原文，例如 1．、【例1】、5、",
      "section": "所属板块或章节标题原文，例如 一、单项选择题、例题解析、随堂检测；没有则填 null",
      "start_line": 该题第一行的 line_id（必须是含编号的那一行）,
      "end_line": 该题最后一行的 line_id,
      "type": "single_choice / multiple_choice / fill_blank / comprehensive / experiment / short_answer / unknown",
      "score": 分值数字，原文没有分值则填 null
    }
  ],
  "non_question_regions": [
    {
      "start_line": 起始 line_id,
      "end_line": 结束 line_id,
      "kind": "cover / section_header / instruction / answer_key / other"
    }
  ]
}

判定规则：
1. 编号体系可能在文档内重启。试卷通常是全篇连续 1..N；讲义常见形态是「例题解析」板块用【例1】【例2】…，「随堂检测」板块又从 1、2、3… 重新计数。遇到重启不要合并、不要跳过，按出现顺序各自作为一道题输出，label 保留原文编号。
2. doc_kind 判定：出现【例N】/【变式N】/知识点N/例题解析/随堂检测等教学板块结构 → handout；只有连续题号与选项 → paper。
3. 跨页题目照常输出一条，start_line 与 end_line 落在不同页即可，绝对不要把一道题拆成两条。
4. 答案紧跟题干的情况（如每题后面有【难度】★、【答案】A、【解析】…），这些行属于该题，必须包含在 end_line 之内。
5. 答案集中在文档末尾的情况（出现「参考答案」「答案与解析」等标题），从该标题起到文档结束的所有行归入 non_question_regions，kind 填 answer_key，绝对不要当作题目输出。
6. 卷首信息（标题、班级、教师、日期、学生、课程编号、考试说明、注意事项）归入 non_question_regions，kind 分别填 cover 或 instruction。
7. 章节标题行（一、单项选择题 等）归入 non_question_regions，kind 填 section_header。
8. 完整性硬要求：清单里的每一个 line_id 都必须被覆盖——要么落在某道题的 [start_line, end_line] 区间内，要么落在某个 non_question_regions 区间内。区间之间不得重叠。不允许遗漏任何行。
9. 只输出 JSON，不要输出解释、注释或 Markdown 代码块以外的文字。"""


def boundary_user_text(
    line_text: str,
    *,
    total_lines: int,
    page_count: int,
    doc_kind_hint: str | None = None,
    subject: str | None = None,
) -> str:
    """构造边界判定的 user 文本。"""
    hint = ""
    if doc_kind_hint in ("paper", "handout"):
        hint = f"\n用户已指定文档形态为 {doc_kind_hint}，除非明显矛盾，请采用该形态判定。\n"
    subject_line = f"\n学科：{subject}。\n" if subject else ""
    return (
        f"文档共 {page_count} 页、{total_lines} 个文字行。{hint}{subject_line}\n"
        f"请切分题目并输出 JSON：\n\n{line_text}"
    )


# ── 二、逐题结构化 ───────────────────────────────────────────────────

# 表格怎么处理，按通道分岔 —— 这一条直接决定界面上的表格是完整的还是"只有一半"。
#
# 实测（2026 河东一模第 24 题）：原件是 7 行 16 格、含 colspan/rowspan 的 HTML，
# 模型按下面第一条规则转成 Markdown 后合并关系全丢 —— `<td rowspan="3">方案一</td>`
# 变成 `| 方案一 |  |`，方案一/方案二的分组消失，界面上就成了"表格只有一半"。
# Markdown 语法里根本没有合并单元格，这不是模型没抄好，是规则本身做不到。
#
# MinerU 通道把表格按版面渲染成图片（与插图候选一起给出，合并关系完整），所以那条
# 通道只需要占位符；其余通道没有表格图，只能继续用 Markdown 抄（抄一半好过没有）。
TABLE_CLAUSE_MARKDOWN = (
    "5. 表格：如果原文是表格，用 Markdown 表格语法原样保留在 stem_md 中，"
    "行列结构不得改变。"
)
TABLE_CLAUSE_FIGURE = (
    "5. 表格：表格已由系统按版面渲染成图片（见第 4 条的占位符规则），"
    "行清单里以 [表格] 标记。只需在该位置放占位符。"
    "无论从行清单还是从题卡图里看到表格，都不要用文字或 Markdown 重抄 —— "
    "Markdown 表达不了合并单元格，重抄必然丢行列结构，系统会把它删掉。"
)

STRUCTURE_SYSTEM_TEMPLATE = """你是中文试题结构化专家。给你一道题的文字内容（可能同时给出该题的原始题卡图片），请把它转成结构化 JSON。

输出 JSON 结构（严格遵守，不要增加字段）：
{{
  "stem_md": "题干正文，Markdown 格式；不包含题号、不包含选项、不包含答案与解析",
  "options": [{{"label": "A", "content": "选项内容"}}],
  "type": "single_choice / multiple_choice / fill_blank / comprehensive / experiment / short_answer / unknown",
  "score": 分值数字或 null,
  "has_formula": true 或 false,
  "figure_placeholders": ["[[FIGURE_1]]"],
  "answer_inline": "题干区域内直接给出的答案，例如 A、B、等于；2ρgl；没有则填 null",
  "explanation_inline": "题干区域内直接给出的解析文字；没有则填 null",
  "warnings": ["无法确定的内容说明"]
}}

规则：
1. stem_md 中不要保留题号（如「1．」「【例1】」），题号由系统另行保存。
2. 选择题的选项必须拆进 options 数组，label 用原文字母（A/B/C/D）；非选择题 options 填空数组。
3. 选项里如果有图片，content 填该位置的图片占位符，不要描述图片内容。
{formula_clause}
4. 图片处理：题目中的插图、图表、电路图、几何图一律用占位符 [[FIGURE_n]] 表示（n 从 1 递增），按其在题干中出现的顺序插入到 stem_md 或选项 content 的正确位置。系统会把真实图片文件替换进去。严禁描述图片内容、严禁编造图中数据。
{table_clause}
6. 答案与解析：只有当原文里明确写出时才填 answer_inline / explanation_inline（常见形态：【答案】A、故选：B、【解析】…）。原文没有就填 null。严禁根据题目内容推断或计算出答案后填入。
7. 给了题卡图片时，以图片为准校正文字（尤其是上下标、单位、图形位置）；只给文字时不要臆造图片里才有的信息。
8. 只输出 JSON。"""


def structure_system_prompt(
    subject: str | None, *, tables_as_figures: bool = False
) -> str:
    """按学科渲染结构化 system prompt。

    tables_as_figures=True 表示本次的表格已作为图片提供（MinerU 通道）。
    只有**每个**表格块都拿到了渲染图时才该置 True：否则那张表的 HTML 被禁止重抄、
    图又不存在，题目会整块丢掉内容 —— 宁可留一份残缺的 Markdown。调用方按
    build_figure_candidates 的 stats 判断（见 mineru_service）。
    """
    return STRUCTURE_SYSTEM_TEMPLATE.format(
        formula_clause=formula_clause(subject),
        table_clause=TABLE_CLAUSE_FIGURE if tables_as_figures else TABLE_CLAUSE_MARKDOWN,
    )


def structure_user_text(line_text: str, *, label: str, section: str | None, has_image: bool) -> str:
    """构造逐题结构化的 user 文本。"""
    parts = [f"题目编号原文：{label or '（无）'}"]
    if section:
        parts.append(f"所属板块：{section}")
    parts.append("是否附带题卡图片：" + ("是，请以图片校正文字" if has_image else "否，仅依据文字"))
    parts.append("\n该题的全部文字行：\n" + line_text)
    return "\n".join(parts)


# ── 三、答案区归一 ───────────────────────────────────────────────────

ANSWER_KEY_SYSTEM = """你是中文试卷答案区解析专家。给你一段「参考答案 / 答案与解析」区域的文字行清单，请把每道题的答案与解析拆出来。

输出 JSON 结构（严格遵守）：
{
  "answers": [
    {
      "label": "答案条目对应的题号原文，例如 1、【例1】、15．",
      "answer": "答案本体：选择题填选项字母（如 A、ABD），填空题/解答题填答案文字；无法确定填 null",
      "explanation": "解析全文；没有解析则填 null"
    }
  ]
}

规则：
1. 严格按原文题号输出 label，不要重新编号、不要合并、不要补全缺失题号。
   label 只填题号本身，严禁带分值、题干、选项或解析文字。
   正确："14．"　错误："14．（2 分）如图所示，此时天平的读数为"（这是题干，不是题号）。
2. 一个题号可能对应多个小问（如 (1)(2)(3)），此时 answer 填完整的多小问答案文字，保持原文顺序。
   answer 必须**逐字原样抄写**【答案】后的原文，保留「答：」「正常工作时，水吸收的热量是」这类
   完整表述 —— 严禁概括、精简、只抄数值（「（1）正常工作时，水吸收的热量是8.4×10⁵J」抄成
   「（1）8.4×10⁵J」是错误示范，复核老师需要完整句子才能对卷）。
3. 解析中的公式按 LaTeX 输出（行内 $...$）。
4. 原文没有答案就填 null，严禁根据题目推断答案。
5. 例外（常见）：若某题的【答案】写的是「见试题解答内容」「见解析」「略」这类**指代文字**，
   说明答案就在同一题的【解答】/【解析】段落里 —— 请到那里抄出结论（通常跟在「答：」后面，
   例如「（1）电源的电压为36V；（2）R2 的阻值为40Ω」）填进 answer，
   **不要**因为这一行是指代文字就填 null。确实找不到该题任何解答文字时，才填 null。
6. 答案区的章节标题（一、选择题 等）不要作为条目输出。
7. 只输出 JSON。"""


def answer_key_user_text(line_text: str, *, origin: str) -> str:
    """构造答案区解析的 user 文本。origin 说明来源（文末答案区 / 独立答案文档）。"""
    return f"以下答案内容来自：{origin}。\n\n{line_text}"


# ── 四、答案冲突定向仲裁 ─────────────────────────────────────────────

ARBITRATION_SYSTEM = """你是试卷答案仲裁员。同一道题的两个独立来源给出了不一致的答案，请你依据原文证据裁定哪一路更可信。

输出 JSON 结构（严格遵守，不要增加字段）：
{
  "verdict": "A 或 B 或 unclear",
  "reason": "裁定理由，必须引用原文证据里的具体内容，50 字以内"
}

规则：
1. 只依据给出的题干文字与两路证据判断，严禁自己解题推导答案 —— 你的任务
   是鉴别哪一路更忠实于原文，不是替试卷做题。
2. 常见的判据：哪一路的答案在原文里能逐字找到；哪一路的文字有明显乱码
   （如 �、□）或错序痕迹；哪一路与题干类型（选择/填空/解答）匹配。
3. 两路证据各有道理、无法取舍时 verdict 填 unclear，不要强行二选一。
4. reason 里不要出现「我」「笔者」等人称。
5. 只输出 JSON。"""


def arbitration_user_text(
    *,
    label: str | None,
    stem_text: str,
    evidence_a: str,
    evidence_b: str,
) -> str:
    """构造答案仲裁的 user 文本。evidence_a 为优先级较高的一路。"""
    parts = [f"题目编号原文：{label or '（无）'}"]
    if stem_text:
        parts.append("\n该题的原文文字：\n" + stem_text)
    parts.append("\n证据 A（语义识别路）：\n" + evidence_a)
    parts.append("\n证据 B（确定性解析路）：\n" + evidence_b)
    parts.append("\n请裁定哪一路更可信，输出 JSON。")
    return "\n".join(parts)


# ── 五、扫描页整页转写（低置信降级分支）──────────────────────────────

PAGE_TRANSCRIBE_SYSTEM = """你是文档版面转写专家。给你一页试卷或讲义的图片，请按视觉阅读顺序逐行转写文字。

输出 JSON 结构（严格遵守）：
{
  "lines": [
    {"text": "该行的完整文字", "y_ratio": 该行顶部在页面高度中的相对位置，0 到 1 之间的小数}
  ]
}

规则：
1. 一行输出一条，不要把多行合并，也不要把一行拆成多条。
2. 阅读顺序：先上后下；同高度多栏时先左后右。
3. 公式转成 LaTeX 并用 $...$ 包裹。
4. 图片、图表、电路图不要转写成文字，输出一条 text 为 "[[IMAGE]]" 的行，y_ratio 填其顶部位置。
5. 页眉、页脚、页码不要输出。
6. 无法辨认的字用 □ 占位，严禁猜测替换。
7. 只输出 JSON。"""


def page_transcribe_user_text(page_no: int) -> str:
    return f"这是文档的第 {page_no} 页，请逐行转写。"
