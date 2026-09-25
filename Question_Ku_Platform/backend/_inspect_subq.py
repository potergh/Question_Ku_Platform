import json, glob, os
cand = glob.glob(os.path.join('data', 'ocr_output', '*英语*', 'extract.json'))
cand = [c for c in cand if os.path.exists(c)]
if not cand:
    print("NO extract.json under *英语*; dirs:", os.listdir('data/ocr_output'))
    raise SystemExit
path = max(cand, key=os.path.getmtime)
print("FILE:", path)
data = json.load(open(path, encoding='utf-8'))
items = data.get('items', [])
print("items:", len(items), "blocked:", data.get('audit', {}).get('blocked'))
print("audit:", json.dumps(data.get('audit', {}), ensure_ascii=False)[:400])
for it in items:
    subs = it.get('sub_questions') or []
    if subs:
        withopt = sum(1 for s in subs if (s.get('options') or []))
        withans = sum(1 for s in subs if str(s.get('answer') or '').strip())
        stem = (it.get('stem_md') or '')[:40].replace('\n', ' ')
        print(f"- qid={it.get('qid')} label={it.get('label')!r} type={it.get('question_type')} "
              f"subs={len(subs)} 有选项={withopt} 有答案={withans} stem='{stem}'")
# 两道结构化失败的题
print("--- 空/失败题 ---")
for it in items:
    if not (it.get('stem_md') or it.get('content') or it.get('raw_text')):
        print(f"  qid={it.get('qid')} label={it.get('label')!r} error={it.get('error')}")
