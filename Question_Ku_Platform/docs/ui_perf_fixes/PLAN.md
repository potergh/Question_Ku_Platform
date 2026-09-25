# 题库平台 · 两处交互问题修复计划（已执行）

> 状态：**已按计划实施完成**。决策：① 去掉题库滚动列表这处毛玻璃；② 行内图宽度用百分比（与块图一致）；③ PDF+Word 导出都同步尺寸。
> 验证：前端 `npm run build` 通过；后端 `pytest` 499 passed（含新增 3 条 inlineImage width 用例）。
> 分析基于当前代码，行号以 2026-09-25 仓库为准。

---

## 问题 1：题库管理界面（LibraryView）列表滚动/拖动卡顿

### 根因（已定位）
1. **毛玻璃叠加滚动**（主因）：列表外层 `<section class="panel bank-list">` 使用 `.panel`，
   带 `backdrop-filter: blur(20px) saturate(180%)`（`frontend/src/styles/main.css:702-711`）。
   实际滚动发生在其内部的 `.bank-list-body`（`LibraryView.vue:107`，`overflow-y:auto`）。
   在 backdrop-filter 容器内滚动，浏览器每帧都要重算整块模糊 → 掉帧。
2. **每页 50 张卡片全量渲染**：`v-for="q in questions"`（`LibraryView.vue:143`），
   每张卡片题干 + 最多 4 个选项各 `v-html` 内嵌 `<img loading="lazy">`（`utils/render.js:310`），
   滚动时大量图片边解码边布局。
3. **屏幕外卡片未跳过渲染**：卡片无 `content-visibility`，离屏卡片仍完整布局/绘制。
4. 次要：`.glass-item` 带 `transition: transform`（`main.css:855`），hover 时轻微抖动。

### 修复方案（推荐组合 A+B+C，D 视效果再加）
- **A. 摘掉滚动容器的模糊**：给题库列表这块 `.panel` 关闭 `backdrop-filter`
  （改为不透明/半透明实色背景），或把 `.bank-list-body` 提到模糊层之外。
  保留其它静态面板的毛玻璃，只处理"里面会滚长列表"的这一处。
- **B. 卡片离屏跳过渲染**：`.glass-item` 加 `content-visibility: auto; contain-intrinsic-size: 0 <估值高度>px;`
  （浏览器对屏外卡片跳过布局/绘制，滚到才渲染）。
- **C. 图片占位与解码**：列表缩略图统一给固定 `width/height`（或 aspect-ratio）避免解码回流；
  可保留 `loading="lazy"`，必要时加 `decoding="async"`。
- **D.（可选，改动最大）虚拟列表**：若单页题量会远超 50，再引入 `RecycleScroller`/自写窗口化。
  当前有分页，A+B+C 预计已足够，**默认不做 D**。

### 涉及文件
- `frontend/src/styles/main.css`（`.panel` / 新增列表专用类 / `.glass-item`）
- `frontend/src/views/LibraryView.vue`（列表 section 类名、卡片 img 尺寸约束）

### 风险
- 去掉毛玻璃后视觉与全站玻璃质感略有差异 → 仅对"滚动列表"这一处降级，其它不动；
  如介意可用"半透明实色 + 细边框"尽量贴近原观感。
- `content-visibility` 需目标浏览器支持（Chromium 已支持，本项目 Playwright/Chrome 无碍）。

---

## 问题 2：选题编辑界面，选项内的图片无法拖动缩放

### 根因（已定位）
1. 选项内容模型是 `content: 'inline*'`（`frontend/src/components/richeditor/optionNodes.js:65`），
   只能放**行内节点**；选项里的图因此是 `inlineImage`。
2. 前端 `InlineImage`（`imageNodes.js:37-50`）**只有 `renderHTML`，无 NodeView、无缩放手柄**，
   也没有宽度属性。能拖拽缩放的是块级图 `BlockImage → BlockImageView.vue`
   （手柄 `.qre-img-handle` + `startResize`，`BlockImageView.vue:11,252-279`）。
3. 后端 `inlineImage` 节点**只有 `src`**（`backend/app/services/rich_document.py:11,20,143`）。
4. 导出 IR 也只读 `src`、丢弃尺寸（`backend/app/services/render_ir.py:282-283`）
   → 即便前端拖出宽度，PDF/Word 也不会认。

### 修复方案（端到端，推荐）
让行内图具备"宽度属性 + 可拖拽缩放手柄"，并把宽度贯通到校验与导出：

1. **前端节点**（`imageNodes.js`）
   - `InlineImage` 增加属性 `width`（默认 null=原始/自适应；数字=像素或百分比，沿用块图约定）。
   - `renderHTML` 输出时按 `width` 设置 `style`（如 `max-width` / `width`）。
   - 用 `VueNodeViewRenderer` 挂一个新的轻量 `InlineImageView.vue`（带选中态 + 右下角缩放手柄），
     `stopEvent` 放行手柄事件（参照 `BlockImage.addNodeView`）。
2. **前端视图**（新增 `components/richeditor/InlineImageView.vue`）
   - 复用 `BlockImageView.vue` 的 `startResize` 思路，但**只改宽度、保持行内流式**（不接管并排/整行缩放）。
   - 手柄出现条件：选中该 inlineImage 时。
3. **后端校验/物化**（`rich_document.py`）
   - 迁移生成 inlineImage 时允许携带 `width`（若有默认值）；
   - `_check` 白名单放行 `width`（`rich_document.py:418` 附近）；
   - doc→markdown 快照回写：markdown 无法表达宽度，**以 doc JSON 为编辑真源**（编辑器已按
     `PUT .../document` 存 JSON，见 `QuestionRichEditor.vue:300-302`），快照仅兜底，宽度不强求进 md。
4. **后端导出**（`render_ir.py:282-283` + Word/PDF 渲染）
   - `InlineImage` IR 增加 `width` 字段并透传到 PDF/Word 的行内图渲染，
     使拖出来的尺寸在预览与导出一致。

### 涉及文件
- `frontend/src/components/richeditor/imageNodes.js`
- `frontend/src/components/richeditor/InlineImageView.vue`（新增）
- `frontend/src/components/richeditor/BlockImageView.vue`（可能抽公共缩放逻辑，或各自实现）
- `backend/app/services/rich_document.py`
- `backend/app/services/render_ir.py`
- 相关 Word/PDF 导出渲染处（`render_ir` 下游，执行时定位）

### 风险与取舍
- **方案取舍**：另一条路是"把选项图改成块级图"，但会破坏 `option: inline*` 模型、影响面更大，**不推荐**。
- inlineImage 加 NodeView 要防止拖拽手柄抢焦点导致重渲染（沿用块图 `stopEvent` 约定）。
- 宽度单位需与块图、导出端统一（建议百分比或 px 二选一并写清），避免导出缩放不一致。
- 老数据（无 width 的 inlineImage）默认走"自适应原始尺寸"，向后兼容。

### 测试
- 后端：补/改 `test_rich_document.py`（inlineImage 带 width 校验通过）、
  `test_render_service.py`（选项图缩放后预览/导出宽度生效）。
- 前端：编辑界面选中选项图 → 拖拽手柄改变宽度 → 保存重载宽度保留 → 预览与导出尺寸一致。

---

## 执行顺序建议
1. 先做**问题 1**（纯前端 CSS/模板，风险低、见效快，独立可验证）。
2. 再做**问题 2**（前后端联动，端到端改 + 补测试）。
3. 每步改完 `npm run build` 前端 + 跑 `pytest` 后端回归，确认无回退。

## 待你确认的决策点（已确认）
- [x] 问题1：仅题库滚动列表这一处去掉毛玻璃（方案 A）—— 已确认「可以」
- [x] 问题2：行内图宽度单位用 **百分比**（与块图一致）—— 已确认「可以」
- [x] 问题2：PDF 与 Word 导出都同步反映拖出尺寸 —— 已确认「是」

## 实际改动清单（执行记录）
**问题 1（纯前端）**
- `frontend/src/views/LibraryView.vue`：`.bank-list.panel` 关 backdrop-filter + 半透明实色；`.bank-list-body .glass-item` 加 `content-visibility:auto` + `contain-intrinsic-size`。
- `frontend/src/utils/render.js`：三处缩略图 `<img>` 补 `decoding="async"`。

**问题 2（端到端）**
- `frontend/src/components/richeditor/imageNodes.js`：`InlineImage` 加 `width` 属性 + `addNodeView`（挂 InlineImageView，stopEvent 放行手柄）+ renderHTML 应用宽度。
- `frontend/src/components/richeditor/InlineImageView.vue`（新增）：选中显示右下角手柄，拖拽改宽度百分比。
- `frontend/src/components/richeditor/QuestionRichEditor.vue`：加 `.qre-inline-img-wrap/-handle/[data-selected]` 样式。
- `backend/app/services/render_ir.py`：`InlineImage` IR 加 `width`；`inline_runs` 读取；`runs_html` 按百分比输出宽度（无 width 保持默认小图）。
- `backend/app/services/docx_export.py`：`_add_runs` 行内图按 `width%` 折算内容宽插入；新增 `_inline_img_pct` 辅助。
- `backend/app/services/rich_document.py`：`_check_inline` 校验 inlineImage `width` 取值；新增 `_is_valid_img_width`；更新节点契约注释。
- 测试：`test_rich_document.py`（width 合法/越界）、`test_render_service.py`（HTML 投影带 width）。
