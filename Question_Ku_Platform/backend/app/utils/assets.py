"""Asset URL helpers — pure functions, no DB / HTTP / router dependency.

原实现位于 `app/routers/upload.py`，被 `schemas/question.py` 与
`routers/extract.py` 反向引用，导致 schemas → routers 的层级倒挂。
这两个函数只做字符串/路径变换，与 FastAPI 无关，故下沉到 utils。
"""

import re
from pathlib import Path


def resolve_asset_urls(content: str | None, source_id: str) -> str | None:
    """Convert asset:// URLs to HTTP-servable /api/ocr-assets/{source_id}/... URLs.

    Handles:
    - asset://figures/figures/xxx.webp (old buggy double figures/)
    - asset://figures/xxx.webp (correct)
    - asset://questions/xxx.webp (card images)
    """
    if not content:
        return content

    def _replace(m):
        path = m.group(1)
        # Normalize double figures/figures/ → figures/
        path = re.sub(r'^figures/figures/', 'figures/', path)
        return f'/api/ocr-assets/{source_id}/{path}'

    return re.sub(r'asset://([^\s\)]+)', _replace, content)


def resolve_card_image_path(path: str | None, source_id: str) -> str | None:
    """Convert absolute filesystem card_image_path to HTTP URL."""
    if not path:
        return path
    # Extract relative path from the OCR output directory structure
    # e.g. D:\...\ocr_output\<doc>\questions\Q001.webp → questions/Q001.webp
    try:
        p = Path(path)
        # Find 'ocr_output' in the path parts and take everything after the doc dir
        parts = p.parts
        if 'ocr_output' in parts:
            idx = parts.index('ocr_output')
            # parts[idx] = 'ocr_output', parts[idx+1] = doc_dir, rest = relative path
            relative = '/'.join(parts[idx + 2:])
            return f'/api/ocr-assets/{source_id}/{relative}'
    except (ValueError, IndexError):
        pass
    return path
