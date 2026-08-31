"""阶段 2 排版令牌：字体白名单 / 字号 / 行距 / 段间距 / 练习级默认样式。

前端镜像文件：frontend/src/components/richeditor/typography.js（两侧值必须一致）。
"""

# 字体白名单（避免缺失字体造成导出失真）：显示名 → CSS font-family 链
# 中文用中文名 + 英文名双写（Chromium 与 Word 均可识别）；西文默认 Times New Roman 回退
CN_FONT_CHAIN = {
    "宋体": '"SimSun", "宋体", serif',
    "黑体": '"SimHei", "黑体", sans-serif',
    "楷体": '"KaiTi", "楷体", serif',
    "仿宋": '"FangSong", "仿宋", serif',
    "微软雅黑": '"Microsoft YaHei", "微软雅黑", sans-serif',
}
EN_FONT_CHAIN = {
    "Times New Roman": '"Times New Roman", serif',
    "Arial": '"Arial", sans-serif',
}
FONT_NAMES = list(CN_FONT_CHAIN) + list(EN_FONT_CHAIN)
CN_FONT_NAMES = list(CN_FONT_CHAIN)

DEFAULT_CN_FONT = "宋体"
# 默认英文/数字字体：最终模板未确认前回退 Times New Roman（计划 Task 2.2）
DEFAULT_EN_FONT = "Times New Roman"

# 字号：中文名称 → 磅值（菜单同时显示两者，如“小四（12 pt）”）
FONT_SIZES = [
    ("初号", 42), ("小初", 36), ("一号", 26), ("小一", 24),
    ("二号", 22), ("小二", 18), ("三号", 16), ("小三", 15),
    ("四号", 14), ("小四", 12), ("五号", 10.5), ("小五", 9),
]
SIZE_PTS = [pt for _, pt in FONT_SIZES]
_PT_TO_CN = {pt: cn for cn, pt in FONT_SIZES}

# 行距（倍）；1.7 为既有默认，保留以免基线跳变
LINE_HEIGHTS = [1, 1.25, 1.5, 1.7, 2]

# 段前/段后距离预设（pt）
SPACING_PTS = [0, 3, 6, 9, 12]

# 练习级默认正文样式（未局部覆盖的内容使用；存于 page_config.default_style）
DEFAULT_STYLE = {
    "font_family": DEFAULT_CN_FONT,
    "font_size": 10.5,     # 五号（与既有预览/导出基线一致）
    "line_height": 1.7,
}

# 文字颜色：默认黑色；允许任意选择（决策 2.16），常用色供快捷项
DEFAULT_COLOR = "#000000"
QUICK_COLORS = [
    "#000000", "#666666", "#999999",
    "#f56c6c", "#e6a23c", "#67c23a", "#409eff", "#9b59b6",
]


def size_label(pt) -> str:
    """12 → “小四（12 pt）”；非标准磅值只显示磅值。"""
    cn = _PT_TO_CN.get(float(pt))
    return f"{cn}（{pt:g} pt）" if cn else f"{pt:g} pt"


def css_font_family(name: str | None, default_en: str = DEFAULT_EN_FONT) -> str:
    """字体名 → CSS font-family 链（西文默认字体始终在最前，中英文混排各取所需）。"""
    en = EN_FONT_CHAIN.get(default_en, EN_FONT_CHAIN[DEFAULT_EN_FONT])
    if not name or name == default_en:
        return en
    cn = CN_FONT_CHAIN.get(name)
    return f"{en.split(',')[0]}, {cn}" if cn else en


def practice_default_style(practice) -> dict:
    """练习默认样式：page_config.default_style 覆盖令牌默认值（只接受白名单内的值）。"""
    cfg = (practice.page_config or {}).get("default_style") or {}
    out = dict(DEFAULT_STYLE)
    if cfg.get("font_family") in FONT_NAMES:
        out["font_family"] = cfg["font_family"]
    if isinstance(cfg.get("font_size"), (int, float)) and float(cfg["font_size"]) in SIZE_PTS:
        out["font_size"] = float(cfg["font_size"])
    if isinstance(cfg.get("line_height"), (int, float)) and 0 < float(cfg["line_height"]) <= 4:
        out["line_height"] = float(cfg["line_height"])
    return out
