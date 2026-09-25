"""识别通道注册表：通道标识 → Job 类型 / 后台任务入口 / 展示名。

为什么单独一个模块：upload 路由（上传触发 + 重试）与 extract 路由（重跑）
都要按 Source.extract_channel 分发，以前是四处 if/else 各写一遍 —— 加一个通道
要改四处，漏一处的表现是「某个按钮报 400」或「点重跑却跑了另一个通道」。

为什么不放进 api_extract_adapter：那是通道契约模块，被各 service 反向 import，
而注册表要引用 service 的函数，放进去就形成循环依赖。
"""

from __future__ import annotations

from app.services.api_extract_adapter import (
    CHANNEL_API_EXTRACT,
    CHANNEL_LOCAL_OCR,
    CHANNEL_MINERU,
)
from app.services.api_extract_service import process_pdf_async as process_api_extract_async
from app.services.mineru_service import process_pdf_async as process_mineru_async
from app.services.ocr_service import process_pdf_async as process_local_ocr_async

# 通道展示名，报错信息与前端文案共用一份 —— 同一个通道在两个地方叫不同名字
# 是复核老师最难自行发现的困惑。
# 与前端 utils/channels.js 的 CHANNEL_META.label / CHANNEL_REVIEW_LABELS 三份
# 叫法保持一致：本地OCR识别 / 大模型识别 / MinerU识别。
CHANNEL_LABELS = {
    CHANNEL_LOCAL_OCR: "本地OCR识别",
    CHANNEL_API_EXTRACT: "大模型识别",
    CHANNEL_MINERU: "MinerU识别",
}

# 通道 → Job.job_type。job_type 是自由字符串，新增取值不需要迁移。
JOB_TYPES = {
    CHANNEL_LOCAL_OCR: "ocr",
    CHANNEL_API_EXTRACT: CHANNEL_API_EXTRACT,
    CHANNEL_MINERU: CHANNEL_MINERU,
}

# 通道 → 后台任务入口。三者的 process_pdf_async 签名完全一致
# (source_id, file_path, job_id)，这是能统一分发的前提。
RUNNERS = {
    CHANNEL_LOCAL_OCR: process_local_ocr_async,
    CHANNEL_API_EXTRACT: process_api_extract_async,
    CHANNEL_MINERU: process_mineru_async,
}


def channel_label(channel: str | None) -> str:
    return CHANNEL_LABELS.get(channel or "", channel or "未知通道")


def job_type_for(channel: str | None) -> str:
    """未知通道退化为本地 OCR：历史数据里可能存在已下线的通道值。"""
    return JOB_TYPES.get(channel or "", "ocr")


def runner_for(channel: str | None):
    """返回 (source_id, file_path, job_id) 签名一致的异步任务入口。"""
    return RUNNERS.get(channel or "", process_local_ocr_async)
