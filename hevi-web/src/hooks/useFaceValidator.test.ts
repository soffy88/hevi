import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useFaceValidator } from './useFaceValidator';

// jsdom 的 Image 不真正解码 blob URL —— 用假 Image 设置 src 时异步触发 onload。
class FakeImage {
  naturalWidth = 800;
  naturalHeight = 1200;
  onload: (() => void) | null = null;
  onerror: ((reason?: unknown) => void) | null = null;
  private _src = '';
  set src(value: string) {
    this._src = value;
    // 模拟解码完成:onload 异步触发,让 fileToImage 的 Promise 在 jsdom 里 resolve。
    setTimeout(() => this.onload?.(), 0);
  }
  get src(): string {
    return this._src;
  }
}

// face-api 在 jsdom 里不可用:mock 掉动态 import,返回可控的检测结果。
const hoisted = vi.hoisted(() => ({
  detections: [] as Array<{ box: { width: number; height: number } }>,
  loadError: null as Error | null,
}));

vi.mock('@vladmandic/face-api', () => ({
  nets: {
    tinyFaceDetector: {
      loadFromUri: vi.fn().mockImplementation(async () => {
        if (hoisted.loadError) throw hoisted.loadError;
      }),
    },
  },
  TinyFaceDetectorOptions: class {
    constructor(_options: Record<string, unknown>) {}
  },
  detectAllFaces: vi.fn().mockImplementation(async () => hoisted.detections),
}));

beforeEach(() => {
  hoisted.detections = [];
  hoisted.loadError = null;
  // 只补 createObjectURL/revokeObjectURL,保留原生 URL 构造能力。
  vi.stubGlobal('URL', Object.assign(URL, {
    createObjectURL: vi.fn(() => 'blob:fake'),
    revokeObjectURL: vi.fn(),
  }));
  vi.stubGlobal('Image', FakeImage);
});

function jpegFile(): File {
  return new File(['fake-jpeg-bytes'], 'photo.jpg', { type: 'image/jpeg' });
}

/** 每个用例前重置模块单例(模型只加载一次的懒加载逻辑)并重新渲染 Hook。 */
async function renderValidator() {
  vi.resetModules();
  const { useFaceValidator: freshHook } = await import('./useFaceValidator');
  return renderHook(() => freshHook());
}

describe('useFaceValidator', () => {
  it('模型加载失败 → 报错而非崩溃', async () => {
    hoisted.loadError = new Error('weights 404');
    const { result } = await renderValidator();
    const verdict = await act(async () => result.current.validate(jpegFile()));
    expect(verdict.isValid).toBe(false);
    expect(verdict.errorMsg).toMatch(/AI 素材质检失败/);
  });

  it('拒绝非 JPG/PNG 文件,不触发模型加载', async () => {
    const { result } = await renderValidator();
    const verdict = await act(async () =>
      result.current.validate(new File(['x'], 'clip.mp4', { type: 'video/mp4' })),
    );
    expect(verdict.isValid).toBe(false);
    expect(verdict.errorMsg).toMatch(/仅支持 JPG\/PNG/);
    expect(verdict.isLoading).toBe(false);
  });

  it('拒绝超过 10MB 的图片', async () => {
    const { result } = await renderValidator();
    const big = new File([new Uint8Array(11 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' });
    const verdict = await act(async () => result.current.validate(big));
    expect(verdict.isValid).toBe(false);
    expect(verdict.errorMsg).toMatch(/10MB/);
  });

  it('恰好 1 张人脸且占比在 5%-60% → 通过', async () => {
    hoisted.detections = [{ box: { width: 320, height: 480 } }]; // 800×1200 → 16%
    const { result } = await renderValidator();
    let verdict = await act(async () => result.current.validate(jpegFile()));
    expect(verdict.isValid).toBe(true);
    expect(verdict.faceCount).toBe(1);
    expect(verdict.faceRatio).toBeCloseTo(0.16, 2);
    expect(verdict.isLoading).toBe(false);

    // 模型只加载一次(懒加载单例)。
    const { detectAllFaces } = await import('@vladmandic/face-api');
    expect(detectAllFaces).toHaveBeenCalledTimes(1);
    act(() => { void result.current.validate(jpegFile()); });
    await waitFor(() => expect(detectAllFaces).toHaveBeenCalledTimes(2));
  });

  it('多张人脸 → 拒绝并提示单人照', async () => {
    hoisted.detections = [
      { box: { width: 100, height: 100 } },
      { box: { width: 100, height: 100 } },
    ];
    const { result } = await renderValidator();
    const verdict = await act(async () => result.current.validate(jpegFile()));
    expect(verdict.isValid).toBe(false);
    expect(verdict.errorMsg).toMatch(/单人照/);
  });

  it('人脸占比过小(全身远景)→ 拒绝', async () => {
    hoisted.detections = [{ box: { width: 60, height: 80 } }]; // 800×1200 → 0.5%
    const { result } = await renderValidator();
    const verdict = await act(async () => result.current.validate(jpegFile()));
    expect(verdict.isValid).toBe(false);
    expect(verdict.errorMsg).toMatch(/半身照/);
  });

  it('模型加载失败后重试可恢复(失败不缓存)', async () => {
    hoisted.loadError = new Error('first try failed');
    const { result } = await renderValidator();
    const failed = await act(async () => result.current.validate(jpegFile()));
    expect(failed.isValid).toBe(false);
    // 第二次尝试时网络恢复 → 成功。
    hoisted.loadError = null;
    hoisted.detections = [{ box: { width: 320, height: 480 } }];
    const ok = await act(async () => result.current.validate(jpegFile()));
    expect(ok.isValid).toBe(true);
  });

  it('reset 回到空闲态', async () => {
    hoisted.detections = [{ box: { width: 320, height: 480 } }];
    const { result } = await renderValidator();
    await act(async () => result.current.validate(jpegFile()));
    expect(result.current.result.isValid).toBe(true);
    act(() => result.current.reset());
    expect(result.current.result.isValid).toBe(false);
    expect(result.current.result.faceCount).toBeNull();
  });
});
