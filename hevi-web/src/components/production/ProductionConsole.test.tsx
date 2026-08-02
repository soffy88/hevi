/**
 * §6.2 UX 回归 —— Production 页面纯粹化校验(§4)。
 * 校验点:/production 页面无任何输入框/文本域/生成提交按钮,
 * 正确渲染顶部指标概览、任务列表(含模式标签/进度/状态)与媒体交付库。
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { push, listMock, TASKS } = vi.hoisted(() => ({
  push: vi.fn(),
  listMock: vi.fn(),
  TASKS: [
    {
      task_id: 'tk-1024a9c1',
      status: 'running',
      percent: 75,
      stage: 'L6 画面渲染',
      production_source: 'tongjian',
      created_at: '2026-08-02T10:00:00Z',
    },
    {
      task_id: 'tk-1023b8d2',
      status: 'completed',
      percent: 100,
      stage: 'L8 完成装配',
      production_source: 'automatic',
      created_at: '2026-08-02T09:00:00Z',
    },
  ],
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

vi.mock('@/lib/auth-store', () => ({ isAuthenticated: () => true }));

vi.mock('@/lib/api-client', () => ({
  USE_MOCK: false,
  taskApi: {
    list: listMock.mockResolvedValue(TASKS),
    videoUrl: (id: string) => `/api/tasks/${id}/video`,
  },
}));

import { ProductionConsole } from './ProductionConsole';

describe('生产看板 & 任务中心 · 纯粹化校验(§6.2 flow 3)', () => {
  beforeEach(() => push.mockClear());

  it('页面无任何输入框/文本域/生成提交按钮(§4.1 物理剥离表单)', async () => {
    render(<ProductionConsole />);
    await screen.findByText(/tk-1024/);

    expect(document.querySelector('input')).toBeNull();
    expect(document.querySelector('textarea')).toBeNull();
    expect(document.querySelector('form')).toBeNull();
    expect(screen.queryByRole('button', { name: /开始自动出片|生成|提交/ })).toBeNull();
  });

  it('顶部指标概览:运行中/队列/已交付/质检通过率(§4.2 Metric Bar)', async () => {
    render(<ProductionConsole />);
    await screen.findByText(/tk-1024/);

    expect(screen.getByText('运行中任务')).toBeInTheDocument();
    expect(screen.getByText('队列等待')).toBeInTheDocument();
    expect(screen.getByText('已交付成片')).toBeInTheDocument();
    expect(screen.getByText('质检通过率')).toBeInTheDocument();
  });

  it('任务列表:模式标签 + 进度 + 状态 + 下载(§4.2 Task List)', async () => {
    render(<ProductionConsole />);
    await screen.findByText(/tk-1024/);

    expect(screen.getByText('资治通鉴')).toBeInTheDocument();
    expect(screen.getByText('L6 画面渲染')).toBeInTheDocument();
    expect(screen.getByText('RUNNING')).toBeInTheDocument();
    const download = screen.getByRole('link', { name: '下载' });
    expect(download).toHaveAttribute('href', '/api/tasks/tk-1023b8d2/video');
  });

  it('媒体交付库:仅渲染已完成成片卡片(§4.2 Media Gallery)', async () => {
    render(<ProductionConsole />);
    await screen.findByText(/tk-1024/);

    // 完成任务的卡片有「下载 MP4」;任务列表与交付库均出现模式标签
    expect(screen.getByText('下载 MP4')).toBeInTheDocument();
    expect(screen.getAllByText('极简单片').length).toBeGreaterThanOrEqual(1);
  });
});
