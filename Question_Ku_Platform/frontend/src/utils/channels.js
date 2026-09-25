// 识别通道元信息。与后端 app/services/channels.py 的 CHANNEL_LABELS / JOB_TYPES 对应。
//
// 为什么集中成一份：这些判断原本散在导入页的 6 处（单选项、拖拽提示、配对答案文档、
// 列表标签、预览按钮、上传后提示）。加通道时漏掉任何一处，表现都是「按钮不出现」
// 或「文案显示成另一个通道」——报错信息完全指不到根因。
//
// staged    : 走暂存区（识别完先进 extract.json，预览确认才入库）
// companion : 支持配对一个独立答案文档作为第三答案源
// hint      : 导入页拖拽区下方的说明文案 —— 回答"这个通道怎么用"
// pick      : 导入页通道单选项下方的选择建议 —— 回答"该选哪个"
// tagType   : 列表里通道标签的配色（Element Plus 的 tag type）
//
// hint 与 pick 刻意分成两条：它们回答的是不同问题，混成一句会两边都记不住。
// hint 在拖拽文件时才看（格式/流程/前置条件），pick 在选通道时就该看到。
//
// pick 的每一句都有实测依据（同一份讲义两条通道各跑一遍、逐题核对）：
//   local_ocr 不联网不耗额度、且没有暂存复核 —— 这是通道元信息里 staged:false 的直接后果；
//   api_extract 读 PDF 文字层，所以符号原样，但插图只认内嵌位图，讲义里的矢量图会漏；
//   mineru 恰好相反：实测插图 36 → 75 张、零丢失，代价是待复核 21 → 55。

export const CHANNEL_META = {
  // 已下线（不在 CHANNEL_ORDER 里，导入页不再提供），仅为历史 sources 数据显示而保留。
  local_ocr: {
    label: '本地OCR识别',
    staged: false,
    companion: false,
    tagType: 'info',
    hint: '支持 PDF / DOCX / PPTX / TXT，可一次拖入多份',
    pick: '不联网、不耗额度，文字层清晰的电子卷最快；识别完直接入库，没有暂存复核',
  },
  api_extract: {
    label: '大模型识别',
    staged: true,
    companion: true,
    tagType: 'success',
    hint: '只支持 PDF；识别完先进暂存区，预览确认才入库',
    pick: '读 PDF 文字层，公式符号原样保留；插图只认内嵌位图，讲义里的矢量图画不出来',
  },
  mineru: {
    label: 'MinerU识别',
    staged: true,
    companion: false,
    tagType: 'success',
    hint: '只支持 PDF；需先在「系统设置」填 MinerU Token，识别完先进暂存区',
    pick: '解析排版最强，讲义 / 学案（Word 导出、矢量图多）优先选它；代价是待复核更多',
  },
}

// 导入页单选项的顺序，也是加/下线通道时唯一需要动的地方。
//
// local_ocr 已从这里下线：只在导入页不再提供该选项。
// 但 CHANNEL_META 与 CHANNEL_REVIEW_LABELS 里**必须保留** local_ocr 条目 ——
// 历史 sources 表里还存着这个通道值，列表页与复核页要能正常显示它的名字。
// 删掉条目会让老数据的通道标签退化成"未知通道"，那是把可解释信息变成噪点。
export const CHANNEL_ORDER = ['api_extract', 'mineru']

export function channelMeta(channel) {
  const meta = CHANNEL_META[channel]
  if (meta) return meta
  // 历史数据里可能有已下线的通道值：给一个能显示、但绝不冒充某个真实通道的兜底。
  return {
    label: channel || '未知通道',
    staged: false,
    companion: false,
    tagType: 'info',
    hint: '',
  }
}

// 复核页顶部的通道名。与 CHANNEL_META.label 保持同一套叫法 —— 同一个通道在不同
// 页面叫不同名字，是复核老师最难自行发现的困惑（这条原本只是"略有差别"，实测确实
// 会让人对不上：导入页写「大模型」、复核页写「API 大模型」）。
export const CHANNEL_REVIEW_LABELS = {
  local_ocr: '本地OCR识别',
  api_extract: '大模型识别',
  mineru: 'MinerU识别',
}
