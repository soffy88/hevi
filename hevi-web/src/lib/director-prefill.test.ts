/**
 * §6.2 UX 回归 —— 首页 → 导演控制台带参传输契约(director-prefill 纯逻辑)。
 * 覆盖 §3.1 payload 字段全量往返、单次消费、损坏数据兜底与默认值。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import {
  consumeDirectorPrefill,
  prefillDirector,
  type DirectorPrefillPayload,
} from './director-prefill';

const PAYLOAD: DirectorPrefillPayload = {
  prompt: '三国长坂坡,赵云七进七出',
  adapterMode: 'tongjian',
  duration: '5-15min',
  aspectRatio: '16:9',
  characters: ['char-liubei', 'char-zhaoyun'],
  presetLevel: 'fast',
};

describe('director-prefill (§3.1 首页 → 导演控制台带参传输)', () => {
  beforeEach(() => window.sessionStorage.clear());

  it('payload 全字段往返无损(§3.2 映射所需字段都在)', () => {
    prefillDirector(PAYLOAD);
    expect(consumeDirectorPrefill()).toEqual(PAYLOAD);
  });

  it('一次消费即销毁(单次带参跳转,刷新后不残留)', () => {
    prefillDirector(PAYLOAD);
    expect(consumeDirectorPrefill()).toEqual(PAYLOAD);
    expect(consumeDirectorPrefill()).toBeNull();
  });

  it('prompt/duration 缺失 → 判定为脏数据返回 null', () => {
    window.sessionStorage.setItem(
      'hevi.director.prefill.v1',
      JSON.stringify({ prompt: '', duration: '' }),
    );
    expect(consumeDirectorPrefill()).toBeNull();
  });

  it('JSON 损坏 → 静默兜底 null', () => {
    window.sessionStorage.setItem('hevi.director.prefill.v1', '{broken');
    expect(consumeDirectorPrefill()).toBeNull();
  });

  it('部分字段缺失 → 应用合理默认值(adapterMode=default / 9:16 / balanced)', () => {
    prefillDirector({ prompt: '一句话', duration: 'short' } as DirectorPrefillPayload);
    const got = consumeDirectorPrefill();
    expect(got?.adapterMode).toBe('default');
    expect(got?.aspectRatio).toBe('9:16');
    expect(got?.presetLevel).toBe('balanced');
    expect(got?.characters).toEqual([]);
  });
});
