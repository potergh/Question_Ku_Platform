"""大模型识别通道（api_extract）。

与本地几何切题通道（OCRAdapter + physics_paper_splitter.pipeline）并行的第二条
识别路径，分工是：

    LLM 判题目边界（只出坐标，不出图）
    -> PyMuPDF 裁原图题卡（无损）
    -> 覆盖率审计（防静默丢内容）
    -> 逐题结构化 + 三源答案归一
    -> 磁盘暂存 extract.json
    -> 用户在预览页确认后入库

本包是唯一可以直接 import physics_paper_splitter 的服务层代码。平台其余部分
（routers 与其它 services）只通过 api_extract_adapter 交互，与 OCRAdapter 的定位
一致 —— 换掉底层解析实现时，改动面被锁在本包内。

sys.path 注入在这里做一次（与 ocr_adapter.py 同样的手法），子模块即可自由 import。
"""

from __future__ import annotations

import sys
from pathlib import Path

# backend/app/services/api_extract/__init__.py -> parents[4] 是项目根
_PACKAGES_DIR = Path(__file__).resolve().parents[4] / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))


class ExtractCancelled(Exception):
    """用户取消了识别任务；service 层据此把 Job 标为 failed / 用户取消。"""
