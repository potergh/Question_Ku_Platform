<template>
  <div class="flex h-screen bg-canvas">
    <!--
      侧栏：这是每天看几十次的地方，它廉价则整站廉价。
      只做三件事——品牌区、分组的导航、底部的环境状态。
      选中态不用"整块药丸变蓝"，而是浅色底 + 左缘一道 3px 指示条：
      蓝是稀缺资源，留给真正的主操作。
    -->
    <aside class="app-rail" v-show="!railCollapsed">
      <!-- 品牌区：与下方导航共用一条中轴。收起按钮绝对定位贴右缘，
           品牌本身保持居中、不被按钮挤偏。 -->
      <div class="brand-row">
        <span class="brand-mark">库</span>
        <span class="text-[15px] font-semibold text-ink">题库工作台</span>
        <button
          type="button"
          class="rail-collapse"
          title="收起侧栏"
          @click="setRailCollapsed(true)"
        >
          <el-icon :size="14"><ArrowLeftBold /></el-icon>
        </button>
      </div>

      <!-- 功能项平铺，不再分「备课 / 系统」两组：
           分组标题本身占一行，却只罩住一两个入口，反把一眼能扫完的列表切碎了。 -->
      <nav class="app-rail__nav">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="rail-item"
          :class="{ 'rail-item--active': isActive(item) }"
        >
          <el-icon :size="17"><component :is="item.icon" /></el-icon>
          <span class="truncate">{{ item.label }}</span>
        </router-link>
      </nav>

      <footer class="border-t border-line px-2.5 py-2.5">
        <!-- 系统设置钉在底部（原来装明暗模式的位置）：低频入口不该占导航列表的注意力。
             明暗模式搬进了设置页——设置项本就该住在设置页里。 -->
        <router-link
          to="/settings"
          class="rail-item"
          :class="{ 'rail-item--active': isActive(settingsNav) }"
        >
          <el-icon :size="17"><component :is="settingsNav.icon" /></el-icon>
          <span class="truncate">{{ settingsNav.label }}</span>
        </router-link>
      </footer>
    </aside>

    <!-- 收起后的拉出条：与练习编辑器左栏同一套交互，贴左缘一条窄边随时可点 -->
    <button
      v-show="railCollapsed"
      type="button"
      class="rail-pull"
      title="展开侧栏"
      @click="setRailCollapsed(false)"
    >
      <el-icon :size="14"><ArrowRightBold /></el-icon>
      <span class="rail-pull-label">菜单</span>
    </button>

    <!-- .app-main 负责"品牌色柔光晕 + 画布色"这层底：毛玻璃要透过它才有东西可透 -->
    <main class="app-main min-w-0 flex-1 overflow-y-auto">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

// 侧栏可收起：题库管理是两栏、编辑器是三栏，228px 的导航在这种页面是想让出来的空间。
// 状态记在本机 —— 每次进站都要重新收一遍太烦（与编辑器左栏的做法一致）。
const railCollapsed = ref(localStorage.getItem('railCollapsed') === '1')
const setRailCollapsed = (value) => {
  railCollapsed.value = value
  localStorage.setItem('railCollapsed', value ? '1' : '0')
}

// 信息架构按参考稿重组：上传=导入中心，练习=练习组卷。
// match 用于把子路由归到父入口（如 /practice/editor 归「练习组卷」）。
const navItems = [
  { to: '/dashboard', label: '工作台', icon: 'HomeFilled' },
  { to: '/upload', label: '导入中心', icon: 'Upload' },
  { to: '/library', label: '题库管理', icon: 'Files' },
  { to: '/basket', label: '选题池', icon: 'ShoppingCart' },
  { to: '/practices', label: '练习组卷', icon: 'Notebook', match: ['/practices', '/practice'] },
  // 标签管理不再占导航位：标签的增删改在题库管理 → 筛选条件 → 标签管理里，
  // 它本来就是题库的附属操作，不值得一个一级入口。/tags 路由保留（兼容旧链接）。
  // 试卷记录已并入练习组卷（导出 Word/PDF 就在练习卡片上），页面与路由一并移除。
]
// 系统设置单独渲染在底部，所以不进 navItems。
const settingsNav = { to: '/settings', label: '系统设置', icon: 'Setting' }

const isActive = (item) => {
  const targets = item.match || [item.to]
  return targets.some((to) => route.path === to || route.path.startsWith(to + '/'))
}
</script>

<style scoped>
.app-rail {
  display: flex;
  width: 228px;
  flex-shrink: 0;
  flex-direction: column;
  border-right: 1px solid var(--glass-border);
  /* 侧栏也用毛玻璃：它压在带光晕的底上，模糊后能透出那层蓝，整块"活"起来 */
  background: var(--glass-bg-strong);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
}

/*
 * 导航滚动区**必须显式写 overflow-x: hidden**。
 * 只写 overflow-y: auto 时，按 CSS 规则 overflow-x 的 visible 会被计算成 auto，
 * 于是只要有任何 1px 横向溢出（长文案、阴影、滚动条自身的宽度）就会冒出一条
 * 横向滚动条 —— 侧栏里那条一直在的灰条就是这么来的。
 */
.app-rail__nav {
  min-height: 0;
  flex: 1;
  padding: 0 10px 8px;
  overflow-y: auto;
  overflow-x: hidden;
}

/*
 * 品牌行：position:relative 是为了让收起按钮绝对定位贴右缘 ——
 * 品牌本体继续居中，加按钮不会把它挤偏。
 */
.brand-row {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px 8px 14px;
}

.rail-collapse {
  position: absolute;
  right: 6px;
  top: 50%;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 6px;
  color: var(--color-ink-muted);
  transition:
    background-color var(--dur-fast) var(--ease-out-quart),
    color var(--dur-fast) var(--ease-out-quart);
}

.rail-collapse:hover {
  background: color-mix(in oklab, var(--color-primary-500) 10%, transparent);
  color: var(--color-ink);
}

/* 收起后的拉出条：毛玻璃底与侧栏一致，视觉上是"侧栏缩成的一条边" */
.rail-pull {
  display: flex;
  width: 22px;
  flex-shrink: 0;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-right: 1px solid var(--glass-border);
  background: var(--glass-bg-strong);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  backdrop-filter: blur(var(--glass-blur)) saturate(180%);
  color: var(--color-ink-muted);
  transition:
    background-color var(--dur-fast) var(--ease-out-quart),
    color var(--dur-fast) var(--ease-out-quart);
}

.rail-pull:hover {
  background: var(--glass-bg);
  color: var(--color-primary-600);
}

.rail-pull-label {
  font-size: var(--text-2xs);
  letter-spacing: 0.08em;
  writing-mode: vertical-rl;
}

/* 品牌标记：主色实底 + 衬线字。
   方向 B 把品牌色从"深墨"换成"主蓝"——蓝色要主动出场，而不是等到按钮才出现。 */
.brand-mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  place-items: center;
  border-radius: 11px;
  background: var(--color-primary-500);
  color: white;
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 600;
  box-shadow: 0 2px 8px color-mix(in oklab, var(--color-primary-500) 32%, transparent);
}

.rail-item {
  position: relative;
  display: flex;
  align-items: center;
  /* 左对齐而不是整组居中：标签字数不一（工作台 3 字 / 导入中心 4 字）时，
     居中会让图标随文字左右漂移，竖向不成一列。左对齐 + 图标定宽后，
     所有图标永远落在同一条竖线上 —— 这也是导航列表的常规排法。 */
  justify-content: flex-start;
  gap: 8px;
  /*
   * 这里**刻意不写 width: 100%**。
   * 本项目的 box-sizing 全局是 content-box（main.css 有意不引 Tailwind preflight），
   * 于是 width:100% 会在内容宽度之外再加左右内边距：实测每条导航比侧栏内容区
   * 宽出整整 20px，右边缘被裁掉，还撑出一条横向滚动条（侧栏那条灰条的根因）。
   * display:flex 的 <a> 本身就是块级，默认按"可用宽度减内边距"铺满，正是想要的。
   */
  margin-bottom: 4px;
  /* 行高比原来高一档：侧栏是每天看几十次、点几十次的地方，
     8px 内边距在这个宽度下偏挤。 */
  /* 左内边距大于右：整组内容（图标+文字）在导航里大致居中，但左对齐的
     排法保住了图标竖向成列 —— 这是"居中观感"与"图标对齐"的折中。 */
  padding: 11px 10px 11px 48px;
  border-radius: 8px;
  font-size: var(--text-base);
  color: var(--color-ink-soft);
  transition:
    background-color var(--dur-fast) var(--ease-out-quart),
    color var(--dur-fast) var(--ease-out-quart);
}

/* 图标列定宽：不同图标的字形宽窄不一（↑ 与 🛒），不定宽的话即使左对齐，
   图标自身也会在槽位里左右错位。定宽 + 内部居中 = 严丝合缝的一条竖线。 */
.rail-item .el-icon {
  flex: none;
  width: 20px;
  justify-content: center;
}

.rail-item:hover {
  background: color-mix(in oklab, var(--color-primary-500) 8%, transparent);
  color: var(--color-ink);
}

/* 选中态：实心药丸（参考稿的做法），蓝色主动承担"你在哪"。
   方向 B 不再用左缘细条——那是上一版"安静"路线的零件。 */
.rail-item--active {
  background: var(--color-primary-500);
  color: white;
  font-weight: 600;
  box-shadow: 0 2px 8px color-mix(in oklab, var(--color-primary-500) 28%, transparent);
}

.rail-item--active:hover {
  background: var(--color-primary-600);
  color: white;
}
</style>
