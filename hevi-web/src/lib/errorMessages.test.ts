import { describe, expect, it } from 'vitest';

import { humanizeTaskError } from './errorMessages';

describe('humanizeTaskError', () => {
  it('空输入返回 undefined', () => {
    expect(humanizeTaskError(undefined)).toBeUndefined();
    expect(humanizeTaskError(null)).toBeUndefined();
    expect(humanizeTaskError('')).toBeUndefined();
    expect(humanizeTaskError('   ')).toBeUndefined();
  });

  it('配音/TTS 错误 → 配音文案', () => {
    expect(humanizeTaskError('vibevoice package not installed')).toContain('配音');
  });

  it('网络错误 → 网络文案', () => {
    expect(humanizeTaskError('[Errno 111] Connection refused')).toContain('网络');
  });

  it('LLM 脚本规划错误 → 脚本文案', () => {
    expect(humanizeTaskError('LLM returned invalid JSON for chapter script')).toContain('脚本');
  });

  it('积分不足 → 积分文案', () => {
    expect(humanizeTaskError('insufficient_credits')).toContain('积分');
  });

  it('未知错误 → 兜底文案且带原始尾巴', () => {
    const out = humanizeTaskError('some totally unknown weird error xyz');
    expect(out).toContain('生成失败');
    expect(out).toContain('xyz'); // 保留原始错误尾巴便于排查
  });
});
