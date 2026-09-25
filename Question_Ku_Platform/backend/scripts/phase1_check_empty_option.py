"""对比验证：空选项容错是否生效（8001 旧进程应 422，8002 新进程应 200）。
只构造最小合法文档并保存两次（第二次恢复原内容需要手动？——不会：保存的是真实题的文档，
因此先读出原文档、改出一个含空选项的文档、保存、再原样保存回去，最后断言恢复成功。"""

import asyncio
import sys

import httpx

BASE_8002 = "http://127.0.0.1:8002"


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        # 取化学基线练习第一题（含选项）
        lst = (await c.get(f"{BASE_8002}/api/practices")).json()
        chem = next(p for p in lst["practices"] if "化学" in p["title"] and p["is_baseline"])
        detail = (await c.get(f"{BASE_8002}/api/practices/{chem['id']}/detail")).json()
        q = next(x for s in detail["sections"] for x in s["questions"] if x["options"])
        pid, qid = chem["id"], q["id"]
        original = q["rich_document"]

        # 构造含一个无 content 字段空选项的文档
        doc = {"type": "doc", "schema_version": 1, "content": []}
        for node in original["content"]:
            if node["type"] == "optionGroup":
                group = {"type": "optionGroup", "content": []}
                for o in node["content"]:
                    group["content"].append(o)
                group["content"].append({"type": "option", "attrs": {"label": "?"}})  # 无 content
                doc["content"].append(group)
            else:
                doc["content"].append(node)

        url = f"{BASE_8002}/api/practices/{pid}/questions/{qid}/document"
        r = await c.put(url, json={"document": doc})
        print(f"8002 保存含空选项文档: {r.status_code}")
        assert r.status_code == 200, r.text
        # 验证落库：选项数 +1 且空选项 content 为空串
        q2 = next(x for s in (await c.get(f"{BASE_8002}/api/practices/{pid}")).json()["sections"]
                  for x in s["questions"] if x["id"] == qid)
        assert len(q2["options"]) == len(q["options"]) + 1
        assert q2["options"][-1]["content"] == ""
        print("8002 空选项落库正确:", q2["options"][-1])

        # 收尾：用 /restore 恢复题库原版（顺带清除 is_modified，不污染基线样本）
        r2 = await c.post(f"{BASE_8002}/api/practices/{pid}/questions/{qid}/restore")
        print(f"8002 恢复题库版本: {r2.status_code}")
        assert r2.status_code == 200, r2.text
        assert r2.json()["question"]["is_modified"] is False

        # 对比：8001 旧进程应拒绝
        r3 = await c.put(url.replace("8002", "8001"), json={"document": doc})
        print(f"8001(旧代码) 保存同样文档: {r3.status_code}（预期 422）")


if __name__ == "__main__":
    asyncio.run(main())
