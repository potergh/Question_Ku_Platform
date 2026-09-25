#!/usr/bin/env bash
# 第二轮全量回归：下边界修复后重跑河东卷（扫描件）与和平卷（混合形态）。
# 讲义已核对为空操作（25 页末行均在 content_bottom 之上），不重跑。
set -u

ROOT="D:/tiku_9.10/Question_Ku_Platform"
cd "$ROOT/backend" || exit 1
PY="../venv/Scripts/python.exe"

run() {
  local label="$1" file="$2" kind="$3" out="$4"
  echo "==================== $label ===================="
  "$PY" scripts/golden_extract.py -f "$ROOT/test_data/$file" --doc-kind "$kind" \
    --json "scripts/reports/$out" 2>&1 | tail -26
}

run "河东卷 10 页纯扫描件" "2026河东区一模物理试卷.pdf" paper golden_hedong_v8.json
run "和平卷 38 页混合形态" "2022年天津市和平区中考物理一模试卷.pdf" paper golden_tianjin_heping_v8.json

echo "全部完成"
