// 阶段 2 排版令牌（前端镜像）：与后端 backend/app/services/typography.py 值一致。
// 修改任一侧必须同步另一侧。

// 字体白名单：显示名 → CSS font-family 链（西文默认字体始终在最前）
export const CN_FONTS = ['宋体', '黑体', '楷体', '仿宋', '微软雅黑']
export const EN_FONTS = ['Times New Roman', 'Arial']
export const FONT_NAMES = [...CN_FONTS, ...EN_FONTS]
export const DEFAULT_EN_FONT = 'Times New Roman'

const CN_CHAIN = {
  '宋体': '"SimSun", "宋体", serif',
  '黑体': '"SimHei", "黑体", sans-serif',
  '楷体': '"KaiTi", "楷体", serif',
  '仿宋': '"FangSong", "仿宋", serif',
  '微软雅黑': '"Microsoft YaHei", "微软雅黑", sans-serif',
}
const EN_CHAIN = {
  'Times New Roman': '"Times New Roman", serif',
  Arial: '"Arial", sans-serif',
}

export function cssFontFamily(name) {
  const en = EN_CHAIN[DEFAULT_EN_FONT]
  if (!name || name === DEFAULT_EN_FONT) return en
  const cn = CN_CHAIN[name]
  return cn ? `${en.split(',')[0]}, ${cn}` : en
}

// 字号：中文名称 + 磅值（菜单同时显示两者）
export const FONT_SIZES = [
  { label: '初号（42 pt）', value: 42 },
  { label: '小初（36 pt）', value: 36 },
  { label: '一号（26 pt）', value: 26 },
  { label: '小一（24 pt）', value: 24 },
  { label: '二号（22 pt）', value: 22 },
  { label: '小二（18 pt）', value: 18 },
  { label: '三号（16 pt）', value: 16 },
  { label: '小三（15 pt）', value: 15 },
  { label: '四号（14 pt）', value: 14 },
  { label: '小四（12 pt）', value: 12 },
  { label: '五号（10.5 pt）', value: 10.5 },
  { label: '小五（9 pt）', value: 9 },
]
export const sizeLabel = (pt) =>
  FONT_SIZES.find(s => s.value === pt)?.label || (pt ? `${pt} pt` : null)

// 行距（倍）；1.7 为既有默认
export const LINE_HEIGHTS = [1, 1.25, 1.5, 1.7, 2]

// 段前/段后距离预设（pt）
export const SPACING_PTS = [0, 3, 6, 9, 12]

// 练习级默认正文样式（未局部覆盖的内容跟随；存于 page_config.default_style）
export const DEFAULT_STYLE = { font_family: '宋体', font_size: 10.5, line_height: 1.7 }

// 常用颜色（任意色由取色器提供）
export const QUICK_COLORS = [
  '#000000', '#666666', '#999999',
  '#f56c6c', '#e6a23c', '#67c23a', '#409eff', '#9b59b6',
]
