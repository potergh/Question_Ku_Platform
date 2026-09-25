"""视觉大模型（qwen-vl-max）调用封装 —— api_extract 通道的唯一网络出口。

不复用 ai_service._call_llm 的原因：
- 它只发送纯文本 messages，不支持 content 数组中的 image_url；
- ai_mode == "local" 时会强制把 base_url 覆盖为 http://localhost:11434/v1，
  与视觉通道需要独立端点（DashScope compatible-mode）的诉求冲突。
因此这里独立读取配置：优先 ai_vision_base_url，留空回退 ai_base_url；
API Key 优先 ai_vision_api_key，留空回退 ai_api_key（两家共用同一供应商时
老配置行为不变）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Settings

from .usage import record_call

logger = logging.getLogger(__name__)

# DashScope OpenAI 兼容端点；前端设置页作为预置值提示。
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 单张图片编码后的字节上限，超出则逐步降分辨率重编码。
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_SIDE = 4096
JPEG_QUALITY = 88

# 重试策略：仅对超时、429、5xx 重试，4xx 参数错误立即失败。
MAX_RETRIES = 2
RETRY_BACKOFF = 2.0
RETRY_STATUS = {429, 500, 502, 503, 504}

# 输出上限。显式给比依赖端点默认值稳：默认值偏小会让长结构（表格题）的输出
# 被截断，而截断与「非法转义」在 finish_reason 上都表现为 stop，排查时极易混淆。
DEFAULT_MAX_TOKENS = 8192

# JSON 只允许这些转义；模型写出的 \* \_ 会让 json.loads 抛 Invalid \escape。
# 注意：合法的两字符转义必须整体保留，否则 ``\\approx`` 里的第二个反斜杠会被
# 单独删掉、把合法 JSON 改成非法 —— 这个坑真实发生过（见 repair_invalid_escapes）。
LEGAL_ESCAPE_CHARS = '"\\/bfnrt'
HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


class VLMError(Exception):
    """视觉模型调用失败。"""


class VLMConfigError(VLMError):
    """配置缺失或不可用（未开启 AI、未填 Key、未填端点）。"""


class VLMRateLimitError(VLMError):
    """触发限流，重试后仍失败。"""


async def get_vision_config(db: AsyncSession) -> dict:
    """读取视觉模型配置。缺 Key 时抛 VLMConfigError。

    可用与否**只看有没有配 API Key**，不再看 ``ai_mode``。原因：原来那三档
    （本地 / 大模型 / MinerU）是"识别模式"的总开关，但它与导入页的通道选择
    是同一件事的两处表达，会出现"导入页选了大模型、设置页却关着"的错位，
    而且设置页关掉后连"改回来"的按钮都不显示。现在通道只在导入页选一次，
    这里就退化为纯粹的配置校验。

    调用方应在并发调用前只读一次并把结果往下传：AsyncSession 不是
    并发安全的，逐题结构化阶段会在 Semaphore 下并发调模型，共享 session
    发请求会直接报错。配置里不包含 temperature：结构化抽取要求可重现，
    温度固定为 0，不跟随用户给生成场景设的 ai_temperature。
    """
    result = await db.execute(select(Settings).where(Settings.id == 1))
    s = result.scalar_one_or_none()
    if not s:
        raise VLMConfigError("AI 未配置，请先在设置页面配置")
    # Key 的取值顺序与 /api/settings/test 的 kind=vision 分支保持一致：
    # 视觉 Key 优先，留空回退文本 Key —— 两家用同一供应商的老配置行为不变。
    api_key = (s.ai_vision_api_key or "").strip() or (s.ai_api_key or "").strip()
    if not api_key:
        raise VLMConfigError(
            "未配置 API Key，无法调用视觉模型：请在设置页填写视觉模型 Key，"
            "或留空以共用文本模型的 Key"
        )

    base_url = (s.ai_vision_base_url or s.ai_base_url or "").rstrip("/")
    if not base_url:
        raise VLMConfigError("未配置视觉模型端点（ai_vision_base_url / ai_base_url 均为空）")

    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": s.ai_vision_model or "qwen-vl-max",
    }


def encode_image(image_path: Path) -> str:
    """把题卡/页面图片编码为 base64 data URL（统一转 JPEG 以兼容并压缩体积）。"""
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        max_side = MAX_IMAGE_SIDE
        while True:
            if max(rgb.width, rgb.height) > max_side:
                scale = max_side / max(rgb.width, rgb.height)
                rgb = rgb.resize(
                    (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))),
                    Image.LANCZOS,
                )
            buffer = BytesIO()
            rgb.save(buffer, "JPEG", quality=JPEG_QUALITY)
            payload = buffer.getvalue()
            if len(payload) <= MAX_IMAGE_BYTES or max_side <= 1024:
                break
            max_side //= 2
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def build_user_content(text: str, image_data_urls: list[str] | None = None) -> list[dict]:
    """构造 OpenAI 兼容的 content 数组：图片在前、文字在后。"""
    content: list[dict] = []
    for url in image_data_urls or []:
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": text})
    return content


# 进程内共享的连接池。原来是每次调用 `async with httpx.AsyncClient(...)`，
# 每个请求都要重做一次 TLS 握手：串行时只是零点几秒，但页转写并发 4、
# 逐题结构化并发 6 之后会叠成可观的排队开销，而连接池就是为这个场景存在的。
# 超时按请求传（各阶段不同），不用客户端级默认值。
_CLIENT: httpx.AsyncClient | None = None


def _shared_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(limits=httpx.Limits(max_connections=32))
    return _CLIENT


async def call_vlm(
    config: dict,
    *,
    system: str,
    user_text: str,
    image_paths: list[Path] | None = None,
    temperature: float = 0.0,
    timeout: float = 180.0,
    max_tokens: int | None = DEFAULT_MAX_TOKENS,
) -> str:
    """调用视觉模型，返回原始回复文本。

    config 由 get_vision_config 预先读出（理由见该函数 docstring）。
    图片在线程池里编码（PIL 是 CPU 密集），避免阻塞事件循环。
    仅对超时/429/5xx 做指数退避重试。

    `max_tokens` 显式给，不依赖端点默认值。注意：**截断与非法转义在
    finish_reason 上都表现为 stop**，别看到 stop 就以为输出完整 ——
    第 13 题那次 JSON 解析失败的真实原因是 ``Invalid \\escape``（见
    `repair_invalid_escapes`），不是撞输出上限。
    """
    data_urls: list[str] = []
    if image_paths:
        loop = asyncio.get_event_loop()
        for path in image_paths:
            data_urls.append(await loop.run_in_executor(None, encode_image, path))

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": build_user_content(user_text, data_urls)},
    ]
    url = f"{config['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    body = {
        "model": config["model"],
        "messages": messages,
        # 结构化抽取要求稳定输出，温度固定 0；调用方显式传入时才覆盖。
        "temperature": temperature,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens

    last_error: str = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await _shared_client().post(
                url, headers=headers, json=body, timeout=timeout
            )
        except httpx.TimeoutException:
            last_error = "视觉模型响应超时"
        except httpx.ConnectError as exc:
            # 连不上多半是端点写错，重试无意义。
            raise VLMConfigError(f"无法连接视觉模型端点 {config['base_url']}: {exc}") from exc
        except httpx.HTTPError as exc:
            last_error = f"网络错误: {exc}"
        else:
            if resp.status_code == 200:
                data = resp.json()
                # 记账：响应里的 usage 以前被直接丢弃，导致「这一卷花了多少 token」
                # 无从回答。没有任务级账本时 record_call 是空操作，不影响调用。
                record_call(config.get("model"), data.get("usage"))
                try:
                    return data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise VLMError(f"视觉模型返回结构异常: {str(data)[:300]}") from exc
            if resp.status_code == 429:
                last_error = f"触发限流 (HTTP 429): {resp.text[:200]}"
            elif resp.status_code in RETRY_STATUS:
                last_error = f"服务端错误 (HTTP {resp.status_code}): {resp.text[:200]}"
            else:
                raise VLMError(
                    f"视觉模型返回错误 (HTTP {resp.status_code}): {resp.text[:300]}"
                )

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_BACKOFF ** attempt)

    if "429" in last_error:
        raise VLMRateLimitError(last_error)
    raise VLMError(last_error or "视觉模型调用失败")


def repair_invalid_escapes(text: str) -> str:
    """去掉 JSON 里非法的反斜杠转义，保留被转义的那个字符本身。

    JSON 规范里的合法转义只有 ``" \\ / b f n r t`` 与 ``\\uXXXX``。模型会把
    markdown 的加粗星号写成 ``\\*``、把 LaTeX 的行内符号写成 ``\\_ \\ (`` ——
    这些都是「反斜杠 + 字面字符」，去掉反斜杠语义不变，却会让 ``json.loads``
    直接抛 ``Invalid \\escape``。

    实测和平卷第 13 题（铭牌表格）稳定复现：连着重试三次都栽在**同一个字符**
    （``| **\\*\\*牌电烤箱** |``），所以解析重试救不了这一类，只能在这里修。

    **必须按「两字符一对」消费合法转义。** 最初的实现用
    ``re.sub(r'\\\\(?!["\\\\/bfnrtu])', "", text)`` 逐字符判断，结果把
    ``\\\\approx`` 的第二个反斜杠也删了（``a`` 不在合法字符表里）→ 合法 JSON
    变成 ``\\a`` → 整段解析失败。和平卷第 29/30/38 页的扫描页转写就这样被这条
    正则判死，页面从行清单里消失，最后以「孤儿页」的形式阻断整份文档。

    正确性是**单向**的：函数只删「不构成合法转义」的反斜杠，因此
    ① 能解析的输入经过它还是能解析（合法转义原样保留，不改一个字节）；
    ② 不能解析的输入才可能被救回。绝不可能把一个好 JSON 改坏。

    不能反向补一个反斜杠（``\\*`` -> ``\\\\*``）：那会让正文字符串里凭空多出一个
    反斜杠，题目内容被改坏 —— 缺答案比错答案好，多一个反斜杠同理。

    已知局限：模型**漏写**第二个反斜杠时（``\\times`` 写成 ``\\t imes``）属于
    ``\\t`` 这个合法转义，本函数不碰它，``json.loads`` 会把 LaTeX 命令静默解成
    制表符。实测语料里模型一律写双反斜杠，未观察到这种情况；要修需要区分
    「模型本意是 LaTeX」与「模型本意是换行符」，判据不唯一，故不在此处猜。
    """
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char != "\\" or index + 1 >= length:
            out.append(char)
            index += 1
            continue
        following = text[index + 1]
        if following in LEGAL_ESCAPE_CHARS:
            # 合法两字符转义（含 ``\\``）：整体留下，否则会拆坏 ``\\approx``。
            out.append(text[index : index + 2])
            index += 2
            continue
        if (
            following == "u"
            and length - index >= 6
            and all(c in HEX_DIGITS for c in text[index + 2 : index + 6])
        ):
            out.append(text[index : index + 6])
            index += 6
            continue
        # 非法转义：丢掉反斜杠，被转义的字符留在原地交给下一轮。
        index += 1
    return "".join(out)


def parse_json(text: str) -> Any:
    """解析模型回复中的 JSON：剥离 ``` 围栏，失败时尝试截取最外层括号。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        stripped = stripped.rsplit("```", 1)[0].strip()

    repaired = repair_invalid_escapes(stripped)
    # 修过就先用修过的；修不动再退回原文试一次（原文里若本来就是合法转义，
    # repaired 与 stripped 相同，不会多跑）。
    candidates = [repaired] if repaired == stripped else [repaired, stripped]
    errors: list[str] = []
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            # 只报「前 300 字」会把出错位置（可能在 1800 字往后）完全藏起来。
            # 把 msg/pos 与附近原文一起报出来，才能分清截断 / 非法转义 / 围栏。
            near = candidate[max(0, exc.pos - 40) : exc.pos + 40]
            errors.append(f"{exc.msg} @字符 {exc.pos}，附近: {near!r}")
        # 模型偶尔在 JSON 前后夹带说明文字，退化为截取最外层括号。
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start = candidate.find(open_ch)
            end = candidate.rfind(close_ch)
            if start != -1 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except json.JSONDecodeError as exc:
                    near = candidate[max(0, exc.pos - 40) : exc.pos + 40]
                    errors.append(f"{exc.msg} @字符 {exc.pos}，附近: {near!r}")
                    continue
    detail = "；".join(dict.fromkeys(errors)) or "无可用候选"
    raise VLMError(f"视觉模型回复不是合法 JSON（{len(text)} 字）：{detail}")


async def call_vlm_json(
    config: dict,
    *,
    system: str,
    user_text: str,
    image_paths: list[Path] | None = None,
    temperature: float = 0.0,
    timeout: float = 180.0,
    max_tokens: int | None = DEFAULT_MAX_TOKENS,
) -> Any:
    """call_vlm + parse_json 的组合，解析失败也要重试。

    call_vlm 只在超时/429/5xx 上重试；而「HTTP 200 却给不出可用 JSON」只有到
    解析这一步才暴露。端点是聚合网关、同一输入两次输出不同，重试是低成本的补救。

    但重试只对**抖动**有效。实测第 13 题失败于 `Invalid \\escape`（模型把表格里
    的加粗写成 `\\*`），三次请求截在同一字符上 —— 那类问题在 `parse_json` 里修，
    重试救不了。
    """
    last_error: VLMError | None = None
    for attempt in range(MAX_RETRIES + 1):
        raw = await call_vlm(
            config,
            system=system,
            user_text=user_text,
            image_paths=image_paths,
            temperature=temperature,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        try:
            return parse_json(raw)
        except VLMError as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF ** attempt)

    assert last_error is not None
    raise last_error
