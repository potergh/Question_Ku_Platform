import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// 排在 element-plus 之后：工具类要能覆盖组件默认样式
import './styles/main.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'

// 主题先于挂载生效，避免首帧闪白（脚本在 body 末尾也能覆盖首屏之前的绘制）
const savedTheme = localStorage.getItem('theme')
if (savedTheme === 'dark') document.documentElement.dataset.theme = 'dark'

const app = createApp(App)

// Register all Element Plus icons
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(ElementPlus)
app.use(router)
app.mount('#app')
