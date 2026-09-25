"""把管线产出的 warnings 分成「用户可行动」与「管线诊断」两类。

为什么需要分：一次识别实测能产出 20 条 warning，其中绝大多数带内部坐标
（``line 602..613``、``#99``）或只有管线内部才懂的术语（批次、裸数组、装饰图）。
这类文案读完整屏，复核老师也不知道该做什么；而另一些（某几页没有文字层、
答案区正文重印被剔除）确实需要他看。

分开之后前端只把用户级放进警告条，诊断级折叠成「开发者诊断（N 条）」。

**分类只影响展示，绝不参与审计闸门（blocked）判定**——闸门只看覆盖率审计。
"""

import re

# 命中任一即判为诊断级：带内部行号 / 行 id，或使用了管线内部术语。
_DIAGNOSTIC_PATTERNS = (
    re.compile(r"\bline\s*\d"),  # line 602..613 / line 136
    re.compile(r"#\d+"),  # #99 / #200 —— 行 id
    re.compile(r"批次"),
    re.compile(r"区间(?:重叠|被截断)"),
    re.compile(r"裸数组"),
    re.compile(r"行清单"),
    re.compile(r"装饰图"),
    re.compile(r"题号锚点校正"),
    re.compile(r"确定性(?:边界)?校验"),
)


def is_diagnostic(warning: str) -> bool:
    """这条 warning 是否只对写管线的人有意义。"""
    text = str(warning or "")
    return any(pattern.search(text) for pattern in _DIAGNOSTIC_PATTERNS)


def split_warnings(warnings) -> tuple[list[str], list[str]]:
    """返回 (用户级, 诊断级)，各自保持原有顺序。"""
    user: list[str] = []
    diagnostic: list[str] = []
    for warning in warnings or []:
        text = str(warning)
        (diagnostic if is_diagnostic(text) else user).append(text)
    return user, diagnostic
