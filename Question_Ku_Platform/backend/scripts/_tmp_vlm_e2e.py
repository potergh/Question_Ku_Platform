"""临时：第二条路（api_extract/VLM）完整链路冒烟。

链路：起服务 → POST /api/upload(channel=api_extract) → 轮询 Source 状态
      → GET /extract 预览 → POST /extract/confirm 入库 → 汇总

用法（工作目录 backend/）：
    python scripts/_tmp_vlm_e2e.py <pdf> [--sandbox DIR] [--upload-name NAME]
                                   [--subject 物理] [--doc-kind paper]
                                   [--answer-doc <已上传的答案文档名>] [--port 8011]
                                   [--no-confirm] [--timeout 1800]

--sandbox DIR：把 DB / uploads / ocr_output 全部指向 DIR（先拷一份真实 DB 快照），
               完整跑通含入库，但**不碰真实题库**。环境变量必须在 import app.config
               之前设好，故本文件顶部先处理 --sandbox 再 import。

安全：非沙箱模式写库前自动备份；日志只输出结构化字段（见 LEARNING_LOG R3）。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# ── 沙箱必须在 import app.config 之前生效 ──────────────────────────────
if "--sandbox" in sys.argv:
    _sb = Path(sys.argv[sys.argv.index("--sandbox") + 1]).resolve()
    _sb.mkdir(parents=True, exist_ok=True)
    for _sub in ("uploads", "ocr_output"):
        (_sb / _sub).mkdir(exist_ok=True)
    _src_db = PROJECT_ROOT / "data" / "db.sqlite3"
    _dst_db = _sb / "db.sqlite3"
    if not _dst_db.exists() and _src_db.exists():
        shutil.copy2(_src_db, _dst_db)
    os.environ["DB_PATH"] = str(_dst_db)
    os.environ["DATA_DIR"] = str(_sb)
    os.environ["UPLOAD_DIR"] = str(_sb / "uploads")
    os.environ["OCR_OUTPUT_DIR"] = str(_sb / "ocr_output")

sys.path.insert(0, str(BACKEND_DIR))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.api_extract_adapter import CHANNEL_API_EXTRACT, STAGING_STATUS  # noqa: E402


def backup_db() -> Path | None:
    if not settings.db_path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = settings.data_dir / "backups" / f"vlm_e2e_{stamp}" / settings.db_path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings.db_path, dest)
    return dest


def wait_health(base: str, proc: subprocess.Popen, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"服务提前退出，returncode={proc.returncode}")
        try:
            if httpx.get(f"{base}/api/health", timeout=2.0).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError("服务未在超时内就绪")


def poll_source(client: httpx.Client, base: str, sid: str, timeout: float) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        src = client.get(f"{base}/api/sources/{sid}").json()
        status = src.get("ocr_status")
        if status != last:
            print(f"    [{time.strftime('%H:%M:%S')}] ocr_status = {status}", flush=True)
            last = status
        if status in (STAGING_STATUS, "done", "error"):
            return src
        time.sleep(5)
    raise TimeoutError(f"识别超时（最后状态 {last}）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--sandbox", default=None)
    ap.add_argument("--upload-name", default=None, help="上传时用的文件名（绕开同名校验）")
    ap.add_argument("--subject", default="物理")
    ap.add_argument("--doc-kind", default=None)
    ap.add_argument("--answer-doc", default=None)
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--no-confirm", action="store_true")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"[ERROR] 找不到文件：{pdf}", file=sys.stderr)
        return 1

    print(f"[cfg] db           = {settings.db_path}")
    print(f"[cfg] ocr_output   = {settings.ocr_output_dir}")
    print(f"[cfg] sandbox      = {args.sandbox or '（关：将写入真实库）'}")
    if not args.sandbox:
        backup = backup_db()
        print(f"[0] 数据库备份 → {backup}")

    base = f"http://127.0.0.1:{args.port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(args.port), "--log-level", "warning"],
        cwd=str(BACKEND_DIR),
    )
    try:
        print(f"[1] 启动服务 {base} ...", flush=True)
        wait_health(base, proc)
        print("[1] 服务就绪", flush=True)

        with httpx.Client(timeout=180.0) as client:
            data = {"channel": CHANNEL_API_EXTRACT, "subject": args.subject, "role": "paper"}
            if args.doc_kind:
                data["doc_kind"] = args.doc_kind
            if args.answer_doc:
                data["companion_filename"] = args.answer_doc
            upload_name = args.upload_name or pdf.name
            print(f"[2] 上传 {upload_name}（channel={CHANNEL_API_EXTRACT}）...", flush=True)
            with pdf.open("rb") as fh:
                resp = client.post(f"{base}/api/upload", data=data,
                                   files={"file": (upload_name, fh, "application/pdf")})
            if resp.status_code >= 400:
                print(f"[ERROR] 上传失败 {resp.status_code}: {resp.text[:400]}", file=sys.stderr)
                return 1
            src = resp.json()
            sid = src["id"]
            print(f"[2] 来源 {sid[:8]} status={src.get('ocr_status')}")

            print("[3] 等待识别（VLM 逐页划界+转写）...", flush=True)
            src = poll_source(client, base, sid, args.timeout)
            print(f"[3] ocr_status={src.get('ocr_status')} "
                  f"question_count={src.get('question_count')} review_count={src.get('review_count')}")
            if src.get("ocr_status") == "error":
                jobs = client.get(f"{base}/api/jobs").json()
                bad = [j for j in jobs if j.get("source_id") == sid]
                print(f"[ERROR] 识别失败：{[j.get('error_message') for j in bad]}", file=sys.stderr)
                return 1

            print("[4] 读取暂存区预览 ...", flush=True)
            ext = client.get(f"{base}/api/sources/{sid}/extract").json()
            items = ext.get("items") or []
            audit = ext.get("audit") or {}
            print(f"    题数={len(items)} 待复核={ext.get('review_count')} "
                  f"覆盖率={audit.get('coverage_ratio')} 阻断={ext.get('blocked')}")
            print(f"    题号={[i.get('question_number') for i in items]}")
            print(f"    待复核题号={[i.get('question_number') for i in items if i.get('needs_review')]}")
            print(f"    剔除题号={[i.get('question_number') for i in items if i.get('excluded')]}")

            if args.no_confirm:
                print("[5] --no-confirm：跳过入库")
                return 0

            print("[5] 确认入库 ...", flush=True)
            r = client.post(f"{base}/api/sources/{sid}/extract/confirm")
            if r.status_code == 409:
                print("    409 审计闸门未通过，带 force 重试 ...")
                r = client.post(f"{base}/api/sources/{sid}/extract/confirm?force=true")
            print(f"[5] 入库 {r.status_code}: {json.dumps(r.json(), ensure_ascii=False)[:300]}")
            if r.status_code < 400:
                qs = client.get(f"{base}/api/questions", params={"limit": 1}).json()
                total = qs.get("total")
                print(f"[6] 入库后题库总数 = {total}")
            return 0 if r.status_code < 400 else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
