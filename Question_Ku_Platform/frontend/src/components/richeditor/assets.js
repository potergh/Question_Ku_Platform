// 资产引用解析：存储统一为 asset:// 形式，渲染时转为真实 URL
export function resolveAssetSrc(src, practiceId) {
  if (!src) return ''
  if (src.startsWith('asset://practice/')) {
    return `/api/practices/${practiceId}/assets/${src.slice('asset://practice/'.length)}`
  }
  if (src.startsWith('asset://')) {
    // 不应出现的外部来源引用：兜底走 ocr 资产接口（渲染容错）
    return `/api/ocr-assets/${src.slice('asset://'.length)}`
  }
  return src  // 已是 http/绝对路径
}
