# Question_Ku_Platform 项目长期备忘

天津中考物理题库抽取管线。`D:/tiku_9.10/Question_Ku_Platform`，FastAPI + Vue3 + PyMuPDF。

## 环境

- Python：`venv/Scripts/python.exe`（项目根下的 venv，不是 managed runtime）
- DB：`data/db.sqlite3`
- 产物：`data/ocr_output/<卷名>__<后缀>/`
- pytest：必须 `--basetemp=../data/_pytest_tmp`；**不要放后台跑**（沙箱隔离会挡住 fixture 写路径，
  报大面积 fixture error 但单跑正常）
- git 提交身份：`-c user.name=potergh -c user.email=tmh200309@tju.edu.cn`
- `data/` 在 `.gitignore` —— **git tag 钉不住数据**，定版后必须手工备份

## 数据模型的两条硬约定

1. **`question_number` 是全卷连续编号 1..N，不是 PDF 里的原始题号。**
   讲义卷的原始题号板块内重启（【例1】+ 随堂 1、），落盘时已全局重编号
   （暑期卷 75 题 → 1..75）。三份卷编号都从 1 开始 → **跨卷题号必然重复**。
2. **因此任何按题号定位数据的操作必须带 `source_id` 作用域。** 这类 bug 在单卷库上
   **零症状**（曾让 `_sync_extract_to_db.py` 具备跨卷覆盖+改错入口的能力），
   测试 fixture 必须造**两卷库**才能暴露。

## 入库的两条路径（职责互补，别混）

| 场景 | 入口 | 语义 |
| --- | --- | --- |
| **新卷首次入库** | `POST /api/sources/{id}/extract/confirm` | 幂等重建：按 source_id 软删旧题 + `db.add` 新题。**insert**，天然有 source 作用域 |
| **换基线后刷新已有题** | `backend/scripts/_sync_extract_to_db.py` | 只 **update** 不 insert；按卷名锚定唯一 source，锚不唯一即拒绝 |

新卷入库前置：`sources` 表得先有一条记录（`confirm` 按 id 找 source）。
建 source 不必走 HTTP 上传——上传会额外排 OCR job 重跑管线，可能产出与现有
`__golden` 不同的结果。手工插一行 source、`ocr_result_path` 指向已有产物目录即可。

## 三份卷的状态

三份 PDF 都在 `test_data/`（**是产物的源头，也是和平卷 `sources.file_path` 的指向目标，别删**）：

| PDF | 形态 | 产物 | 状态 |
| --- | --- | --- | --- |
| `2022年天津市和平区中考物理一模试卷.pdf` | paper 26 题 | `__golden` | **已定版入库**，DB 唯一 source |
| `2026河东区一模物理试卷.pdf` | 纯扫描 10 页 25 题 | `__v13` | 未定版、未入库 |
| `物-9暑-05-固体、液体压强选择-吴马倩.pdf` | handout 75 题 | `__v12` | 未定版、未入库 |

`data/uploads/` 空、`jobs` 表 0 行 —— 说明现有产物是直接跑 `golden_extract.py`
得来的，没走 HTTP 上传 + job 队列。

## 校验层的形态适配（别拿一套规则套所有卷）

- paper：`boundary_audit` 四条规则全跑
- handout：题号板块内重启 + 章节标题 + 双栏 → **只跑 span_overlap**（`doc_kind="handout"`）
- 扫描件：行坐标来自 VLM 转写，与裁图几何不同源 → 几何类校验**不适用**，0 命中不等于准确

## 备份

`data/_backups/<日期>/`，纯手工 `cp`（无校验、无保留策略、db 与 golden 分开放易漏一边）。
`_sync_extract_to_db.py` 写库前会自动留 `db.sqlite3.bak_<时间戳>`。
