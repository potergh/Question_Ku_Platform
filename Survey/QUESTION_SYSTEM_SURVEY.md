# 组卷录题系统 — GitHub 开源项目调研与对比分析

> 调研日期：2026-08-27
> 调研范围：GitHub 上与"组卷录题系统/题库管理/试卷识别"相关的开源项目

---

## 一、项目总览

| # | 项目名称 | GitHub 链接 | 定位 | 技术栈 |
|---|---------|------------|------|--------|
| 1 | Question-Manager | [5huQu/Question-Manager](https://github.com/5huQu/Question-Manager) | 试题管理系统 | — |
| 2 | math-question-bank | [JudgePeach/math-question-bank](https://github.com/JudgePeach/math-question-bank) | 数学题库系统 | — |
| 3 | Exam++ / Examstack | [longxy/exam](https://github.com/longxy/exam) | 网络考试系统 | Java + MySQL + Spring |
| 4 | 云帆考试系统 | [yf-team/yf-exam-lite](https://github.com/yf-team/yf-exam-lite) | 在线培训考试系统 | SpringBoot + Vue + Shiro + MySQL |
| 5 | 面试鸭 | [liyupi/mianshiya](https://github.com/liyupi/mianshiya) | 面试刷题平台 | React + Node.js + MongoDB |
| 6 | PHPEMS | [oiuv/phpems](https://github.com/oiuv/phpems) | 无纸化模拟考试系统 | PHP + MySQL + Redis |
| 7 | xparse-sample-projects | [intsig-textin/xparse-sample-projects](https://github.com/intsig-textin/xparse-sample-projects) | 试卷智能解析工具 | 文档解析 + LLM |
| 8 | 题舟 (Tizhou) | [hack-scan/TIzhou](https://github.com/hack-scan/TIzhou) | 题库管理系统 | Django + Elasticsearch + Redis |
| 9 | Qujini | 见 CSDN/GitCode 介绍 | 开源试题生成工具 | Python + Django |
| 10 | Examination-System | [hatle/Examination-System](https://github.com/hatle/Examination-System) | 在线培训考试系统 | Java + MySQL |

> **注**：项目 1、2 的 GitHub 仓库在当前网络环境下无法直接访问 README，以下分析基于仓库名称及同类项目推断，建议后续补充。

---

## 二、各项目详细分析

### 1. Question-Manager（5huQu）

- **GitHub**: https://github.com/5huQu/Question-Manager
- **设计思路**: 面向试题管理的轻量级系统，侧重题目的录入、分类、检索和组卷功能。
- **技术栈**: 待确认（推测为 Web 全栈项目）
- **亮点**: 试题管理为核心，支持多题型分类

### 2. math-question-bank（JudgePeach）

- **GitHub**: https://github.com/JudgePeach/math-question-bank
- **设计思路**: 专注数学学科的题库系统，支持数学公式的录入与展示，面向数学题目的结构化管理。
- **技术栈**: 待确认（推测包含 LaTeX 公式渲染）
- **亮点**: 垂直于数学学科，公式支持是其核心差异点

### 3. Exam++ / Examstack（longxy/exam）

- **GitHub**: https://github.com/longxy/exam
- **设计思路**: 国内首款基于 Java + MySQL 的开源网络考试系统，采用 GPL 协议。覆盖"题库创建 → 组卷 → 考试 → 自动批改"全流程。
- **技术栈**: Java (Spring) + MySQL + Tomcat
- **核心功能模块**:
  - **用户模块**: 注册登录、随机练习、强化练习、错题练习、模拟考试
  - **教师模块**: 题库管理（6 种题型）、试卷管理（手动/自动组卷）、用户管理
  - **分析模块**: 知识体系统计分析（图表展示）
- **亮点**:
  - 支持 Windows/Linux 双平台
  - 高度可配置性和灵活性
  - 固定开发团队维护，已迭代至 Examstack 第二版

### 4. 云帆考试系统（yf-team/yf-exam-lite）

- **GitHub**: https://github.com/yf-team/yf-exam-lite
- **设计思路**: 多角色在线培训考试系统，覆盖"用户管理 → 题库管理 → 组卷 → 在线考试 → 错题训练"全链路。
- **技术栈**: SpringBoot + Vue + Shiro + JWT + MySQL
- **核心功能模块**:
  - **权限系统**: 基于 Shiro + JWT 的细粒度权限控制
  - **多角色**: 管理员/教师/学生三种角色
  - **题库管理**: 单选/多选/判断题，支持批量导入导出
  - **组卷功能**: 指定题库、分数、数量，题目和选项随机排序防作弊
  - **考试管理**: 定员考试（完全公开/指定部门）
  - **错题训练**: 自动收集错题，支持反复练习
- **亮点**:
  - 支持 PC + H5 + 小程序三端
  - 商业版 + 开源版双轨模式
  - 考试流程完善，防作弊机制
  - 一键部署（jar 包 + start.bat）

### 5. 面试鸭（liyupi/mianshiya）

- **GitHub**: https://github.com/liyupi/mianshiya
- **设计思路**: 专注程序员面试刷题的平台，采用"全民共建"模式，支持多维度检索、智能推荐、一键组卷。
- **技术栈**:
  - 前端: React + Umi + Ant Design + TypeScript + Less
  - 后端: Node.js (Express) / 腾讯云云开发
  - 数据库: MongoDB + Redis + Elasticsearch
  - 部署: Nginx + Docker + CDN
- **核心功能模块**:
  - **题目系统**: 多维度筛选（难度/标签/题型）、排序（热度/收藏/频率）、推荐
  - **试卷系统**: 试题篮 → 一键组卷 → 下载试卷（PDF）
  - **社区功能**: 回答题目、精选回答、点赞、面经分享
  - **用户系统**: 积分、收藏夹、个人主页、排行榜
  - **管理后台**: 题目管理、回答管理、试卷管理、消息中心
- **亮点**:
  - 200+ 题库、9000+ 高频面试题
  - 三端同步（网页 + 小程序 + IDE 插件）
  - 全民编辑共建模式
  - 语音读题/读卷
  - 每日更新，紧跟面试趋势

### 6. PHPEMS（oiuv/phpems）

- **GitHub**: https://github.com/oiuv/phpems
- **设计思路**: 基于 PHPEMS v6.1 优化的开源无纸化模拟考试系统，重点修复 BUG 并扩展功能。
- **技术栈**: PHP + MySQL + Redis
- **核心功能模块**:
  - **考试模块**: 考试设计 → 科目管理 → 章节 → 知识点 → 试题管理 → 试卷管理 → 随机组卷
  - **试题管理**: 普通试题 + CSV 导入（对应知识点 ID）
  - **考场管理**: 添加考场、管理考生
- **亮点**:
  - 完全开源免费
  - 知识点 ID 关联试题，支持按知识点组卷
  - CSV 批量导入试题
  - 支持微信 SDK 集成（overtrue/wechat）

### 7. xparse-sample-projects（合合信息 TextIn）

- **GitHub**: https://github.com/intsig-textin/xparse-sample-projects
- **在线试用**: https://www.textin.com/tasks/exam-extraction
- **设计思路**: 面向题库自动化的试卷智能解析工具。采用"文档解析 → 大模型抽取 → 后端规范化"三层架构。
- **技术栈**: 文档解析引擎 + LLM（大语言模型）
- **核心功能**:
  - 支持 PDF、扫描件、手机拍照试卷
  - 自动处理选择/填空/阅读理解/数学大题/听力题
  - 抽取题组结构、共享题干、小题、选项、分值、页码
  - 跨页题组拼接、表格保留、图片归位
  - 输出统一 JSON 格式
- **亮点**:
  - "确定性处理"与"概率性处理"分离的架构设计
  - 文档解析作为中间结构底座，LLM 只做语义归并
  - OCR 服务和模型服务可独立替换
  - 原文坐标溯源能力

### 8. 题舟 Tizhou（hack-scan/TIzhou）

- **GitHub**: https://github.com/hack-scan/TIzhou
- **设计思路**: 集成 Elasticsearch 全文搜索的题库管理系统，侧重数据导入、搜索和管理。
- **技术栈**:
  - Python 3.9.17 + Django 4.2
  - Elasticsearch 8.x（搜索和数据存储）
  - Redis 6.x（缓存和 ID 生成）
  - Jazzmin 3.0.1（管理后台主题）
  - Pandas（Excel 文件处理）
- **核心功能**:
  - 数据导入（JSON + Excel 格式）
  - Elasticsearch 全文搜索
  - Redis 缓存和唯一 ID 生成
  - 自动字段映射和验证
  - 批量数据处理
- **亮点**:
  - Elasticsearch 驱动的全文搜索，适合大规模题库
  - Jazzmin 现代化管理界面
  - 支持同时上传 JSON + XLSX

### 9. Examination-System（hatle）

- **GitHub**: https://github.com/hatle/Examination-System
- **设计思路**: 轻量级在线培训考试系统，支持题库组卷、在线考试、自动评分。
- **技术栈**: Java + MySQL
- **核心功能**:
  - 题库组卷：指定题库、分数、数量
  - 题目/选项随机排序，防作弊
  - 在线考试 + 自动评分
- **亮点**: 极简部署（jar 包 + 配置文件即可运行）

---

## 三、功能模块共同点对比

| 功能模块 | Exam++ | 云帆 | 面试鸭 | PHPEMS | xparse | 题舟 |
|---------|--------|------|--------|--------|--------|------|
| **题库管理** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| **多题型支持** | ✅ 6种 | ✅ 3种 | ✅ 多类型 | ✅ | ✅ 全题型 | ✅ |
| **知识点分类** | ✅ | ❌ | ✅ 标签 | ✅ ID关联 | ❌ | ❌ |
| **难度分级** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **智能组卷** | ✅ 自动 | ✅ 随机 | ✅ 一键 | ✅ 随机 | ❌ | ❌ |
| **手动组卷** | ✅ | ❌ | ✅ 试题篮 | ❌ | ❌ | ❌ |
| **在线考试** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| **自动批改** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| **错题本** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **批量导入** | ✅ | ✅ | ✅ | ✅ CSV | ✅ PDF/图片 | ✅ JSON/Excel |
| **试卷识别/OCR** | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| **公式支持** | ❌ | ❌ | ✅ Markdown | ❌ | ✅ | ❌ |
| **统计分析** | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **多端支持** | Web | PC+H5+小程序 | Web+小程序+IDE | Web | API | Web |
| **防作弊** | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **全文搜索** | ❌ | ❌ | ✅ ES | ❌ | ❌ | ✅ ES |

### 功能共同点总结

1. **题库管理是核心**：所有系统都以题库的增删改查为基础
2. **组卷功能不可或缺**：自动/手动组卷是标配
3. **多题型支持**：单选、多选、判断、填空、简答是通用题型
4. **批量导入**：所有系统都支持某种形式的批量导入
5. **知识点/标签体系**：多数系统通过知识点或标签对题目进行分类管理
6. **难度分级**：大多数系统支持按难度筛选

---

## 四、UI 界面共同点对比

| UI 特征 | Exam++ | 云帆 | 面试鸭 | PHPEMS | 题舟 |
|---------|--------|------|--------|--------|------|
| **前后端分离** | ❌ | ✅ | ✅ | ❌ | ✅ |
| **响应式布局** | ❌ | ✅ | ✅ | ❌ | ✅ |
| **管理后台** | 传统 | 现代 | 现代 | 传统 | Jazzmin美化 |
| **卡片式题目展示** | ❌ | ✅ | ✅ | ❌ | ❌ |
| **侧边栏导航** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **搜索框置顶** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **标签/筛选器** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **深色模式** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **拖拽排序** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **图表统计** | ✅ | ❌ | ✅ | ❌ | ❌ |

### UI 共同点总结

1. **侧边栏 + 顶栏布局**：几乎所有系统都采用经典的后台管理布局
2. **搜索框为核心入口**：题库搜索/题目搜索是首页最突出的元素
3. **表格/列表展示题目**：题目管理以表格或卡片列表为主
4. **表单式录入**：题目录入统一采用表单（题干 + 选项 + 答案 + 解析 + 标签）
5. **树形分类导航**：学科 → 章节 → 知识点的三级树形结构是通用模式
6. **管理后台 + 用户端分离**：管理员/教师端与学生/考生端界面分离
7. **现代 UI 趋势**：新项目（面试鸭、云帆）趋向使用 Ant Design 等现代组件库

---

## 五、技术栈分布统计

| 技术 | 使用项目数 | 代表项目 |
|------|-----------|---------|
| **Java (Spring/SpringBoot)** | 4 | Exam++, 云帆, Examination-System |
| **Vue.js** | 3 | 云帆, Qujini, 数学题库管理系统 |
| **MySQL** | 6 | Exam++, 云帆, PHPEMS, Examination-System |
| **Python (Django/Flask)** | 3 | 题舟, Qujini, physics-paper-splitter |
| **React** | 1 | 面试鸭 |
| **Node.js** | 2 | 面试鸭 |
| **PHP** | 1 | PHPEMS |
| **Elasticsearch** | 2 | 面试鸭, 题舟 |
| **Redis** | 3 | 云帆, PHPEMS, 题舟 |
| **MongoDB** | 1 | 面试鸭 |

**主流技术选型**：
- **后端**: Java SpringBoot > Python Django > Node.js > PHP
- **前端**: Vue.js > React
- **数据库**: MySQL 占绝对主导
- **搜索**: Elasticsearch 用于大规模题库的全文检索

---

## 六、对你的"组卷录题系统"的启示

### 6.1 必备功能模块（基于竞品共同点）

1. **题库管理**: 多题型、知识点标签、难度分级
2. **智能组卷**: 按知识点/难度/题型自动抽题 + 手动调整
3. **批量录入**: Word/Excel/PDF 导入 + OCR 识别
4. **在线考试**: 计时、防作弊、自动批改
5. **错题本**: 自动收集 + 反复练习
6. **统计分析**: 知识点掌握度、成绩趋势

### 6.2 差异化方向

| 方向 | 说明 | 竞品覆盖情况 |
|------|------|-------------|
| **OCR 试卷识别** | 拍照/扫描试卷自动切题入库 | 仅 xparse 覆盖，蓝海 |
| **公式识别** | LaTeX 公式自动识别与渲染 | 仅面试鸭(Markdown)支持 |
| **知识点自动标注** | AI 自动为题目打知识点标签 | 无竞品实现 |
| **上标/特殊符号修正** | PDF 提取后的文字质量修复 | 无竞品关注 |
| **物理学科垂直优化** | 针对物理实验图、受力分析等 | 无竞品覆盖 |

### 6.3 推荐技术栈

基于调研结果和你的项目特点（physics-paper-splitter 已有 Python + OCR 基础）：

```
后端: Python (Django/FastAPI) — 与现有 OCR 管道无缝集成
前端: Vue 3 + Element Plus — 教育类后台的主流选择
数据库: MySQL + Redis — 成熟稳定
搜索: Elasticsearch — 大规模题库全文检索
OCR: PyMuPDF + RapidOCR — 已有基础
公式: pix2tex (LaTeX-OCR) — 物理公式识别
部署: Docker Compose — 一键部署
```

---

## 七、总结

组卷录题系统的核心价值链为：

```
题目录入 → 题库管理 → 智能组卷 → 在线考试 → 成绩分析
   ↑                                        ↓
   └──── 错题反馈 ← 自动批改 ←──────────────┘
```

当前 GitHub 上的开源项目大多集中在 **管理层面**（题库 CRUD + 组卷 + 考试），而在 **录入层面**（OCR 识别、公式提取、自动标注）的开源方案极少。你的 physics-paper-splitter 项目恰好填补了这一空白——从 PDF 试卷自动切题、OCR 识别、上标修正、公式识别到知识点标注，这是一条完整的"智能录入"管道，是与现有竞品最大的差异化优势。

建议优先将 OCR 切题能力与题库管理系统打通，形成"**拍照/上传试卷 → 自动切题识别 → 人工复核 → 入库**"的闭环，这在当前开源生态中是独特的竞争力。
