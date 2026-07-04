/**
 * 后端原始错误 → 用户可读中文文案映射
 *
 * 后端任务失败时 progress.error 会带原始英文错误(如
 * "vibevoice package not installed"、"[Errno 111] Connection refused" 等),
 * 直接展示用户看不懂。这里用一组规则把已知错误翻成「原因+建议」式短句,
 * 未命中的返回兜底文案(保留原始错误尾巴便于排查)。
 */

// [匹配规则(不区分大小写) → 中文文案]
const ERROR_RULES: Array<[RegExp, string]> = [
  // 配音 / TTS
  [/vibevoice|tts|voice.*not installed|配音/i, '配音生成失败,请稍后重试或更换音色。'],
  // 网络 / 连接
  [/connection refused|errno 111|timed? ?out|timeout|network|connection reset|econnrefused/i, '网络连接失败,请检查网络后稍后重试。'],
  // 脚本规划 / LLM 返回异常
  [/invalid json|chapter script|llm returned|script.*plan|planning|parse.*script/i, '脚本规划失败,请稍后重试或简化输入内容。'],
  // GPU / worker 繁忙、被重启
  [/zombie|worker restarted|out of memory|oom|cuda|gpu|worker.*busy/i, '生成服务繁忙,请稍后重试。'],
  // 产出为空 / 占位符(pipeline 失败)
  [/placeholder|empty output|no output|produced.*placeholder/i, '生成失败,未能产出有效视频,请稍后重试。'],
  // 积分不足 / 结算失败
  [/insufficient_credits|insufficient credit|not enough credit|积分不足/i, '积分不足,请充值后重试。'],
  [/credit settlement|settlement failed|billing/i, '积分结算失败,请稍后重试或联系支持。'],
];

/**
 * 把后端原始错误映射成用户可读中文文案。
 * @param raw 后端 progress.error 原始字符串
 * @returns 中文文案;raw 为空时返回 undefined
 */
export function humanizeTaskError(raw?: string | null): string | undefined {
  if (!raw) return undefined;
  const text = raw.trim();
  if (!text) return undefined;

  for (const [pattern, message] of ERROR_RULES) {
    if (pattern.test(text)) return message;
  }

  // 兜底:保留原始错误的简短尾巴便于排查
  const tail = text.length > 60 ? `${text.slice(0, 60)}…` : text;
  return `生成失败,请稍后重试或联系支持(${tail})`;
}
