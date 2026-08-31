import base from './vite.config.js'

// 验收临时配置：代理指向 8009 新代码后端（验收后删除本文件）
export default {
  ...base,
  server: {
    port: 5174,
    proxy: { '/api': { target: 'http://localhost:8009', changeOrigin: true } },
  },
}
