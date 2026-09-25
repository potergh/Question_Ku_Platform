"""MinerU 官方 API（mineru.net）客户端 —— MinerU 识别通道的唯一网络出口。

为什么不复用 vlm_client：
- vlm_client 打的是 chat/completions，一问一答，一次请求一次响应；
- MinerU 是「文件解析任务」：申请上传链接 → PUT 上传 → 轮询批次结果 → 下载 zip。
  四步、三种 HTTP 语义（POST/GET/PUT），状态机还有 waiting-file/pending/running/
  converting/done/failed 六个取值。硬塞进 call_vlm 只会把两边的重试策略与
  错误处理搅在一起，最后谁也改不动。

为什么不用单文件接口 POST /api/v4/extract/task：
那个接口只接受公网 URL，而平台的文件在本地磁盘（data/uploads/），
没有 MinerU 服务器能访问到的地址。所以本地文件必须走
/api/v4/file-urls/batch 这条「签名直传 + 上传完自动提交解析」的路。

与 vlm_client 同一定位：只做 HTTP 与「读自己那一个配置」（get_mineru_config），
不碰 Job / Source。想脱离 FastAPI 直接测调用链时把 token 直接传给 parse_pdf，
不需要数据库。

官方文档：https://mineru.net/apiManage/docs
"""

from __future__ import annotations

import asyncio
import logging
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Settings

logger = logging.getLogger(__name__)

MINERU_BASE_URL = "https://mineru.net"
UPLOAD_URLS_ENDPOINT = "/api/v4/file-urls/batch"
BATCH_RESULT_ENDPOINT = "/api/v4/extract-results/batch/{batch_id}"

# 默认解析后端。选 vlm 的依据是实测对比（和平卷 38 页，两个后端耗时与页数
# 消耗完全相同，都是 32.4 秒）：vlm 把选择题的 A/B/C/D 拆成各自独立的块，
# pipeline 把它们挤成一行（"…匀速直线运动B. 在0～40s…"，连分隔符都没有），
# 后者对下游逐题结构化不友好。
DEFAULT_MODEL_VERSION = "vlm"

# 文档语言。默认 ch（中英文）；手写体试卷用 ch_server，英文卷用 en 更准。
DEFAULT_LANGUAGE = "ch"

# 轮询节奏。单次查询很轻，3 秒足以让进度条（extracted_pages/total_pages）看起来连续；
# 总超时给 30 分钟 —— 200 页上限的文档解析耗时官方未给数字，宁可按住等。
DEFAULT_POLL_INTERVAL = 3.0
DEFAULT_DEADLINE = 1800.0
UPLOAD_TIMEOUT = 600.0
QUERY_TIMEOUT = 60.0
DOWNLOAD_TIMEOUT = 900.0

TERMINAL_OK = "done"
TERMINAL_FAIL = "failed"

# 错误码 → 用户该做什么。用户看到的必须是「怎么办」，不是「-60006」。
# 条目与官方文档「精准解析常见错误码」对齐，未列出的码原样透出 msg。
ERROR_HINTS = {
    "A0202": "Token 错误：检查是否填对，且不要漏掉 Bearer 前缀",
    "A0211": "Token 已过期，请重新申请",
    "-500": "传参错误：检查参数类型与 Content-Type",
    "-10001": "MinerU 服务异常，稍后重试",
    "-10002": "请求参数错误",
    "-60002": "无法识别文件格式：文件名与上传内容都要带正确后缀",
    "-60004": "空文件",
    "-60005": "文件超过 200MB 上限",
    "-60006": "文件超过 200 页上限，需拆分后再传",
    "-60008": "MinerU 读取文件超时",
    "-60012": "找不到该任务",
    "-60013": "无权访问该任务（task_id 不属于本 Token）",
    "-60015": "文件转换失败，建议先手动转成 PDF 再传",
    "-60016": "文件转换失败",
    "-60018": "今日解析额度已用尽，请次日再试",
    "-60019": "HTML 解析额度不足，请次日再试",
    "-60022": "MinerU 读取文件失败，可能限频，稍后重试",
}

# 这两个码是「配置问题」，不是「任务问题」，必须让用户去改设置而不是重试。
TOKEN_ERROR_CODES = {"A0202", "A0211"}


class MineruError(Exception):
    """MinerU 调用失败。"""


class MineruConfigError(MineruError):
    """配置不可用（Token 错/过期/未填），重试无意义。"""


class MineruTaskError(MineruError):
    """任务本身失败或超时。"""


class MineruCancelled(MineruError):
    """用户取消，等待轮询被主动打断。"""


# 进程内共享连接池，理由与 vlm_client._shared_client 相同：
# 轮询是每 3 秒一次的高频小请求，每次新建客户端都要重做 TLS 握手。
_CLIENT: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(limits=httpx.Limits(max_connections=8))
    return _CLIENT


async def aclose() -> None:
    """关闭共享连接池。脚本/测试收尾时显式调用，避免事件循环关闭时的告警。"""
    global _CLIENT
    if _CLIENT is not None and not _CLIENT.is_closed:
        await _CLIENT.aclose()
    _CLIENT = None


async def get_mineru_config(db: AsyncSession) -> dict:
    """读 MinerU 通道配置；Token 没配就抛 MineruConfigError。

    返回 {"token", "model_version", "language", "enable_formula", "enable_table"}，
    可以直接喂给 parse_pdf（token 之外都是它的关键字参数）。

    抛的是配置错误而不是普通错误：任务列表据此把失败原因写成「去设置页填 Token」，
    而不是一句让用户去猜的 HTTP 401。与 get_vision_config 同样的定位 ——
    本模块自己管自己的配置，调用方不必知道它存在哪张表的哪个字段。
    """
    result = await db.execute(select(Settings).where(Settings.id == 1))
    row = result.scalar_one_or_none()
    token = (row.mineru_api_token or "").strip() if row else ""
    if not token:
        raise MineruConfigError(
            "未配置 MinerU Token，请先在「系统设置」里填写后再用 MinerU 识别通道"
        )
    return {
        "token": token,
        # 这几列在迁移里带 server_default，正常不会为空；兜默认值是为了
        # 万一读到空串时不会把 None / "" 当参数发给 MinerU。
        "model_version": (row.mineru_model_version or "").strip() or DEFAULT_MODEL_VERSION,
        "language": (row.mineru_language or "").strip() or DEFAULT_LANGUAGE,
        "enable_formula": bool(row.mineru_enable_formula),
        "enable_table": bool(row.mineru_enable_table),
    }


def _api_error(payload: dict) -> MineruError:
    """把 code/msg 翻成带处置建议的异常。"""
    code = str(payload.get("code"))
    msg = str(payload.get("msg") or "")
    hint = ERROR_HINTS.get(code)
    text = f"MinerU 返回错误 code={code}：{msg}"
    if hint:
        text = f"{text}（{hint}）"
    return MineruConfigError(text) if code in TOKEN_ERROR_CODES else MineruError(text)


def _check_http(resp: httpx.Response, what: str) -> dict:
    """校验 HTTP 状态与业务 code，返回 JSON 主体。"""
    if resp.status_code != 200:
        raise MineruError(f"{what} 失败 (HTTP {resp.status_code})：{resp.text[:300]}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise MineruError(f"{what} 的返回不是 JSON：{resp.text[:300]}") from exc
    if not isinstance(payload, dict):
        raise MineruError(f"{what} 的返回结构异常：{str(payload)[:300]}")
    code = payload.get("code")
    if code not in (0, None):
        raise _api_error(payload)
    return payload


async def _emit(progress, value: float, stage: str | None = None) -> None:
    """进度回调兼容同步/异步两种写法（与 api_extract/service._tick 一致）。"""
    if progress is None:
        return
    result = progress(value, stage)
    if asyncio.iscoroutine(result):
        await result


def _guess_code(text: str) -> str | None:
    """失败任务的 err_msg 里可能夹着错误码，能认出来就补一句处置建议。"""
    for code in ERROR_HINTS:
        if code in text:
            return code
    return None


def _progress_ratio(row: dict) -> float | None:
    """running 状态下按已解析页数/总页数给出 0~1 的比例。"""
    info = row.get("extract_progress") or {}
    if not isinstance(info, dict):
        return None
    total = info.get("total_pages")
    done = info.get("extracted_pages")
    if done is None or not total:
        return None
    try:
        return min(max(float(done) / float(total), 0.0), 1.0)
    except (TypeError, ValueError):
        return None


def _pick_result(data: dict, file_name: str | None) -> dict:
    """从批次查询结果里挑出本次文件对应的那一条。"""
    rows = data.get("extract_result")
    if not isinstance(rows, list) or not rows:
        raise MineruTaskError(f"批次结果为空：{str(data)[:300]}")
    if file_name:
        for row in rows:
            if isinstance(row, dict) and row.get("file_name") == file_name:
                return row
    row = rows[0]
    if not isinstance(row, dict):
        raise MineruTaskError(f"批次结果结构异常：{str(row)[:300]}")
    return row


async def request_upload_urls(
    token: str,
    *,
    filename: str,
    model_version: str = DEFAULT_MODEL_VERSION,
    language: str = "ch",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool | None = None,
    page_ranges: str | None = None,
    timeout: float = UPLOAD_TIMEOUT,
) -> tuple[str, str]:
    """第一步：申请上传链接。返回 (batch_id, upload_url)。

    is_ocr 用三态而不是 bool：官方默认 false，但纯扫描件往往需要 true。
    传 None 时**不下发这个字段**，把判断权留给 MinerU 自己 —— 我们本地
    猜错会白白牺牲速度或质量。
    """
    file_spec: dict = {"name": filename}
    if is_ocr is not None:
        file_spec["is_ocr"] = is_ocr
    if page_ranges:
        file_spec["page_ranges"] = page_ranges

    body = {
        "files": [file_spec],
        "model_version": model_version,
        "language": language,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }
    resp = await _client().post(
        MINERU_BASE_URL + UPLOAD_URLS_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    payload = _check_http(resp, "申请上传链接")
    data = payload.get("data") or {}
    batch_id = data.get("batch_id")
    urls = data.get("file_urls") or []
    if not batch_id or not urls:
        raise MineruError(
            f"申请上传链接的返回缺少 batch_id / file_urls：{str(payload)[:300]}"
        )
    return str(batch_id), str(urls[0])


async def upload_file(upload_url: str, pdf_path: Path, *, timeout: float = UPLOAD_TIMEOUT) -> int:
    """第二步：PUT 原始字节到 OSS 签名链接，返回上传字节数。

    两个必须守住的细节（官方文档明确要求）：
    1. **不要设 Content-Type**：签名 URL 对请求头敏感，多一个头会让 OSS 判签名不符；
    2. 用 content=bytes 而不是文件对象：httpx 传文件对象会退化成 chunked 上传，
       而官方示例的 `curl -T` 带的是确定的 Content-Length，两者对 OSS 不等价。
       代价是文件会整个读进内存 —— 上限 200MB，对单人使用的平台可接受。
    """
    data = Path(pdf_path).read_bytes()
    resp = await _client().put(upload_url, content=data, timeout=timeout)
    if resp.status_code not in (200, 201, 204):
        raise MineruError(f"上传文件失败 (HTTP {resp.status_code})：{resp.text[:300]}")
    return len(data)


async def wait_for_result(
    token: str,
    batch_id: str,
    *,
    file_name: str | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    deadline: float = DEFAULT_DEADLINE,
    progress=None,
    cancel_check=None,
    stats: dict | None = None,
) -> dict:
    """第三步：轮询直到 done，返回该文件的 extract_result 条目（含 full_zip_url）。

    进度回调给的是 0~1 的比例与原始 state 字符串，由调用方决定怎么映射到
    Job 的百分比区间 —— 本模块不该知道「进度条长什么样」。

    stats 传入时原地写入 queries / elapsed：查询次数只有这里知道，
    在别处按「耗时 ÷ 轮询间隔」倒推是编数，不如直接记。
    """
    url = MINERU_BASE_URL + BATCH_RESULT_ENDPOINT.format(batch_id=batch_id)
    headers = {"Authorization": f"Bearer {token}"}
    started = time.monotonic()
    last_state = ""
    queries = 0

    while True:
        if cancel_check is not None and await cancel_check():
            raise MineruCancelled("用户取消，已停止等待 MinerU 解析结果")

        resp = await _client().get(url, headers=headers, timeout=QUERY_TIMEOUT)
        payload = _check_http(resp, "查询解析进度")
        queries += 1
        row = _pick_result(payload.get("data") or {}, file_name)
        state = str(row.get("state") or "")

        if state != last_state:
            logger.info("mineru batch=%s state=%s", batch_id, state)
            last_state = state

        if state == TERMINAL_OK:
            if stats is not None:
                stats["queries"] = queries
                stats["elapsed"] = round(time.monotonic() - started, 1)
            return row
        if state == TERMINAL_FAIL:
            err = str(row.get("err_msg") or "未提供失败原因")
            code = _guess_code(err)
            hint = ERROR_HINTS.get(code or "")
            raise MineruTaskError(f"MinerU 解析失败：{err}" + (f"（{hint}）" if hint else ""))

        ratio = _progress_ratio(row)
        if ratio is not None:
            await _emit(progress, ratio, state)

        elapsed = time.monotonic() - started
        if elapsed > deadline:
            raise MineruTaskError(
                f"MinerU 解析超时（已等待 {deadline:.0f} 秒，查询 {queries} 次，"
                f"最后状态 {state or '未知'}）"
            )
        await asyncio.sleep(poll_interval)


async def download_zip(zip_url: str, dest_path: Path, *, timeout: float = DOWNLOAD_TIMEOUT) -> Path:
    """第四步之一：流式下载结果包。zip 可能几十 MB，不整包读进内存。

    full_zip_url 是 CDN 链接，不需要带 Authorization。
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    async with _client().stream("GET", zip_url, timeout=timeout) as resp:
        if resp.status_code != 200:
            raise MineruError(f"下载结果包失败 (HTTP {resp.status_code})")
        with dest_path.open("wb") as fh:
            async for chunk in resp.aiter_bytes(65536):
                fh.write(chunk)
    return dest_path


def extract_zip(zip_path: Path, dest_dir: Path) -> list[str]:
    """第四步之二：解压，返回成员名列表（posix 相对路径）。

    成员名**不做任何改名**：MinerU 可能平铺、也可能包一层目录，
    content_list 还带原文件名前缀。先把真实名字原样列出来给调用方看，
    比在这里猜一套命名规则安全得多。
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    root = dest_dir.resolve()
    names: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = (dest_dir / info.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                logger.warning("跳过越界的 zip 成员：%s", info.filename)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())
            names.append(Path(info.filename).as_posix())
    return names


def find_member(names: list[str], *suffixes: str) -> str | None:
    """按后缀找成员。MinerU 的 content_list 叫 `<原文件名>_content_list.json`，
    裸名 `content_list.json` 也可能出现，所以用后缀匹配而不是等值匹配。
    """
    lowered = [(name, name.lower()) for name in names]
    for suffix in suffixes:
        tail = suffix.lower()
        for name, low in lowered:
            if low == tail or low.endswith("/" + tail) or low.endswith(tail):
                return name
    return None


@dataclass(slots=True)
class MineruArtifacts:
    """一次 MinerU 解析的全部产物。"""

    batch_id: str
    zip_path: Path
    extract_dir: Path
    members: list[str] = field(default_factory=list)
    content_list_path: Path | None = None
    full_md_path: Path | None = None
    layout_path: Path | None = None
    # 各阶段耗时（秒）：申请链接 / 上传 / 轮询 / 下载 / 解压 / 合计。
    timings: dict[str, float] = field(default_factory=dict)
    # 轮询次数，用于判断「文档解析到底要多久」这类只能靠实测回答的问题。
    queries: int = 0
    zip_bytes: int = 0


def artifacts_from_zip(zip_path: Path, work_dir: Path) -> MineruArtifacts:
    """把已有的结果包还原成 MineruArtifacts（不调 API）。

    用途是离线重放：调 prompt、改适配层时反复重跑下游管线，不必再消耗 MinerU
    的每日页数额度。也正因如此，MINERU_SUBDIR 下的结果包要留档而不是用完即删。
    """
    extract_dir = Path(work_dir) / "extract"
    members = extract_zip(zip_path, extract_dir)
    content_name = find_member(members, "_content_list.json", "content_list.json")
    md_name = find_member(members, "full.md", ".md")
    layout_name = find_member(members, "layout.json")
    return MineruArtifacts(
        batch_id="(reuse)",
        zip_path=Path(zip_path),
        extract_dir=extract_dir,
        members=members,
        content_list_path=(extract_dir / content_name) if content_name else None,
        full_md_path=(extract_dir / md_name) if md_name else None,
        layout_path=(extract_dir / layout_name) if layout_name else None,
        timings={},
        zip_bytes=Path(zip_path).stat().st_size if Path(zip_path).exists() else 0,
    )


async def parse_pdf(
    token: str,
    pdf_path: Path,
    dest_dir: Path,
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    language: str = "ch",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool | None = None,
    page_ranges: str | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    deadline: float = DEFAULT_DEADLINE,
    progress=None,
    cancel_check=None,
) -> MineruArtifacts:
    """把四步串起来：申请链接 → 上传 → 轮询 → 下载解压。

    dest_dir 下产出：
        <pdf 名>.zip      原始结果包（留档，便于离线复盘坐标系）
        extract/          解压后的 full.md / content_list.json / images/
    """
    pdf_path = Path(pdf_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    timings: dict[str, float] = {}
    mark = time.monotonic()
    await _emit(progress, 0.0, "提交任务")

    batch_id, upload_url = await request_upload_urls(
        token,
        filename=pdf_path.name,
        model_version=model_version,
        language=language,
        enable_formula=enable_formula,
        enable_table=enable_table,
        is_ocr=is_ocr,
        page_ranges=page_ranges,
    )
    timings["申请链接"] = round(time.monotonic() - mark, 1)
    logger.info("mineru batch=%s 已创建，开始上传 %s", batch_id, pdf_path.name)

    mark = time.monotonic()
    size = await upload_file(upload_url, pdf_path)
    timings["上传"] = round(time.monotonic() - mark, 1)

    # 上传完成后 MinerU 会自动提交解析，这里不需要再调提交接口。
    mark = time.monotonic()
    poll_stats: dict = {}
    row = await wait_for_result(
        token,
        batch_id,
        file_name=pdf_path.name,
        poll_interval=poll_interval,
        deadline=deadline,
        progress=progress,
        cancel_check=cancel_check,
        stats=poll_stats,
    )
    timings["轮询"] = round(time.monotonic() - mark, 1)

    zip_url = row.get("full_zip_url")
    if not zip_url:
        raise MineruTaskError(f"解析完成但没有 full_zip_url：{str(row)[:300]}")
    await _emit(progress, 1.0, "下载结果")

    mark = time.monotonic()
    zip_path = await download_zip(str(zip_url), dest_dir / f"{pdf_path.stem}.zip")
    timings["下载"] = round(time.monotonic() - mark, 1)

    mark = time.monotonic()
    extract_dir = dest_dir / "extract"
    members = await asyncio.get_event_loop().run_in_executor(
        None, extract_zip, zip_path, extract_dir
    )
    timings["解压"] = round(time.monotonic() - mark, 1)
    timings["合计"] = round(sum(timings.values()), 1)

    content_name = find_member(members, "_content_list.json", "content_list.json")
    md_name = find_member(members, "full.md", ".md")
    layout_name = find_member(members, "layout.json")

    logger.info(
        "mineru done batch=%s：上传 %.1fMB，轮询 %.1fs，下载 %.1fs，成员 %d 个",
        batch_id, size / 1024 / 1024, timings["轮询"], timings["下载"], len(members),
    )
    return MineruArtifacts(
        batch_id=batch_id,
        zip_path=zip_path,
        extract_dir=extract_dir,
        members=members,
        content_list_path=(extract_dir / content_name) if content_name else None,
        full_md_path=(extract_dir / md_name) if md_name else None,
        layout_path=(extract_dir / layout_name) if layout_name else None,
        timings=timings,
        queries=int(poll_stats.get("queries", 0)),
        zip_bytes=zip_path.stat().st_size if zip_path.exists() else 0,
    )
