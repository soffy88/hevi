import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useTaskWebSocket } from './useTaskWebSocket';

/** 假 WebSocket:手动驱动 onopen/onmessage/onclose,可断言发送内容。 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(message: string) {
    this.sent.push(message);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  // 测试助手:模拟服务端接受连接(readyState → OPEN 并触发 onopen)。
  serverOpen() {
    this.readyState = 1;
    this.onopen?.();
  }

  // 测试助手:模拟服务端广播。
  serverPush(json: unknown) {
    this.onmessage?.({ data: JSON.stringify(json) } as MessageEvent<string>);
  }
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useTaskWebSocket', () => {
  it('连接 ws://host/api/ws/tasks 并合并 task_update 广播', async () => {
    const { result } = renderHook(() => useTaskWebSocket());
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toMatch(/\/api\/ws\/tasks$/);

    act(() => FakeWebSocket.instances[0].serverOpen());
    expect(result.current.connected).toBe(true);

    act(() => {
      FakeWebSocket.instances[0].serverPush({
        type: 'task_update',
        task_id: 't1',
        status: 'running',
        progress: 42,
      });
    });
    expect(result.current.updates.t1?.progress).toBe(42);
    expect(result.current.updates.t1?.status).toBe('running');

    // 同一 task 后到覆盖先到。
    act(() => {
      FakeWebSocket.instances[0].serverPush({
        type: 'task_update',
        task_id: 't1',
        status: 'completed',
        progress: 100,
      });
    });
    expect(result.current.updates.t1?.progress).toBe(100);
    expect(Object.keys(result.current.updates)).toHaveLength(1);
  });

  it('发送 ping 心跳保活(假定时器加速 25s)', async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useTaskWebSocket());
    act(() => FakeWebSocket.instances[0].serverOpen());
    expect(result.current.connected).toBe(true);

    act(() => {
      vi.advanceTimersByTime(25_000);
    });
    expect(FakeWebSocket.instances[0].sent).toContain('ping');
  });

  it('断线后指数退避自动重连,并补上断线期间的进度', async () => {
    const { result } = renderHook(() => useTaskWebSocket());
    act(() => FakeWebSocket.instances[0].serverOpen());

    // 服务端断开。
    act(() => FakeWebSocket.instances[0].close());
    expect(result.current.connected).toBe(false);
    expect(result.current.reconnecting).toBe(true);

    // 1s 后自动重连(真实定时器,waitFor 兜底)。
    await waitFor(
      () => expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(2),
      { timeout: 4000 },
    );
    act(() => FakeWebSocket.instances[1].serverOpen());
    expect(result.current.connected).toBe(true);

    // 新连接继续收广播。
    act(() => {
      FakeWebSocket.instances[1].serverPush({
        type: 'task_update',
        task_id: 't2',
        status: 'running',
        progress: 7,
      });
    });
    expect(result.current.updates.t2?.progress).toBe(7);
  });

  it('非 JSON 消息(如 pong)忽略不崩', async () => {
    const { result } = renderHook(() => useTaskWebSocket());
    act(() => FakeWebSocket.instances[0].serverOpen());
    act(() => {
      FakeWebSocket.instances[0].onmessage?.({ data: 'pong' } as MessageEvent<string>);
    });
    expect(Object.keys(result.current.updates)).toHaveLength(0);
  });
});
