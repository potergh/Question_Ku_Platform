// 与后端 app/utils/question_types.py 的 QUESTION_TYPE_MAP 保持一致
export const QUESTION_TYPE_MAP = {
  single_choice: '选择题',
  multiple_choice: '多选题',
  fill_blank: '填空题',
  comprehensive: '综合题',
  experiment: '实验题',
  calculation: '计算题',
  short_answer: '简答题',
  essay: '论述题',
  unknown: '未知题型',
  // 英语专属题型
  listening: '听力题',
  grammar_choice: '单项填空',
  cloze: '完形填空',
  reading: '阅读理解',
  task_reading: '任务型阅读',
  use_of_english: '综合填空',
  sentence_completion: '完成句子',
  writing: '书面表达',
}

// 篇章题（一篇材料挂多小题）：单题模型下不再展示「第一小题的一套选项」，
// 复核/详情页对这类题型隐藏选项区，避免「阅读理解显示单选选项」的误导。
export const PASSAGE_TYPES = [
  'cloze', 'reading', 'task_reading', 'use_of_english', 'sentence_completion', 'writing',
]

export const isPassageType = (type) => PASSAGE_TYPES.includes(type)
