#!/usr/bin/env bash
# 一轮全量回归：三份金标样本依次重跑（卡图边界 + 尾部插图修复后）。
# 旧产物先改名保留对照，避免脚本清理输出目录时触发沙箱批量删除拦截。
set -u

ROOT="D:/tiku_9.10/Question_Ku_Platform"
DATA="$ROOT/data/ocr_output"
cd "$DATA" || exit 1

stamp_dir() {
  local name="$1" suffix="$2"
  if [ -d "$name" ]; then
    mv "$name" "$name$suffix"
  fi
}

stamp_dir "2022年天津市和平区中考物理一模试卷__golden" "__v6"
stamp_dir "物-9暑-05-固体、液体压强选择-吴马倩__golden" "__v5"
stamp_dir "2026河东区一模物理试卷__golden" "__v5"

cd "$ROOT/backend" || exit 1
PY="../venv/Scripts/python.exe"

run() {
  local label="$1" file="$2" kind="$3" out="$4"
  echo "==================== $label ===================="
  "$PY" scripts/golden_extract.py -f "$ROOT/test_data/$file" --doc-kind "$kind" \
    --json "scripts/reports/$out" 2>&1 | tail -25
  echo "EXIT=$?"
}

run "和平卷 38 页混合形态" "2022年天津市和平区中考物理一模试卷.pdf" paper golden_tianjin_heping_v7.json
run "讲义 25 页有文字层"   "物-9暑-05-固体、液体压强选择-吴马倩.pdf" handout golden_wu_maqian_v7.json
run "河东卷 10 页纯扫描件" "2026河东区一模物理试卷.pdf" paper golden_hedong_v7.json

echo "全部完成"
