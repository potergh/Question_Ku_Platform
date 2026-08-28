<template>
  <el-container class="app-container">
    <el-aside width="200px" class="sidebar">
      <div class="logo">
        <el-icon><Reading /></el-icon>
        <span>智能题库</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="sidebar-menu"
      >
        <el-menu-item index="/upload">
          <el-icon><Upload /></el-icon>
          <span>上传试卷</span>
        </el-menu-item>
        <el-menu-item index="/library">
          <el-icon><Files /></el-icon>
          <span>题库管理</span>
        </el-menu-item>
        <el-menu-item index="/handout">
          <el-icon><Document /></el-icon>
          <span>讲义编辑</span>
        </el-menu-item>
        <el-menu-item index="/tags">
          <el-icon><PriceTag /></el-icon>
          <span>标签管理</span>
        </el-menu-item>
        <el-menu-item index="/ai">
          <el-icon><MagicStick /></el-icon>
          <span>AI 助手</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>设置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-main class="main-content">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
}

.app-container {
  height: 100vh;
}

.sidebar {
  background: #304156;
  color: #fff;
}

.logo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 60px;
  font-size: 18px;
  font-weight: bold;
  color: #fff;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.sidebar-menu {
  border-right: none;
  background: #304156;
}

.sidebar-menu .el-menu-item {
  color: #bfcbd9;
}

.sidebar-menu .el-menu-item:hover,
.sidebar-menu .el-menu-item.is-active {
  background: #263445;
  color: #409eff;
}

.main-content {
  background: #f5f7fa;
  padding: 20px;
  overflow-y: auto;
}
</style>
