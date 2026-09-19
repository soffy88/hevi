/**
 * D6-C 连续性检查 tests — PASS/WARN/BLOCK semantics.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ContinuityCheckPanel } from './ContinuityCheckPanel';

const hoisted = vi.hoisted(() => ({
  summary: vi.fn(),
  gate: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  continuityApi: {
    projectSummary: hoisted.summary,
    gate: hoisted.gate,
  },
}));

const base = { project_id: 'p', binding_count: 1, facts: [] };

describe('连续性检查', () => {
  it('PASS 可直接继续', async () => {
    hoisted.summary.mockResolvedValue({ ...base, verdict: 'pass', gate_ready: true, issues: [] });
    render(<ContinuityCheckPanel projectId="p" />);
    expect(await screen.findByTestId('continuity-pass')).toBeInTheDocument();
  });

  it('WARN 显示提醒并允许继续生成（记录 override）', async () => {
    hoisted.summary.mockResolvedValue({
      ...base,
      verdict: 'warn',
      gate_ready: true,
      issues: [{ severity: 'warn', code: 'IDENTITY_VOICE_MISMATCH', detail: 'voice differs' }],
    });
    hoisted.gate.mockResolvedValue({});
    const onProceed = vi.fn();
    const user = (await import('@testing-library/user-event')).default;
    render(<ContinuityCheckPanel projectId="p" bindingId="b1" onProceed={onProceed} />);
    expect(await screen.findByTestId('continuity-issues')).toBeInTheDocument();
    await user.setup().click(screen.getByRole('button', { name: '仍然继续生成' }));
    expect(hoisted.gate).toHaveBeenCalledWith('b1', 'video_generation', {}, 'studio-user');
    expect(onProceed).toHaveBeenCalled();
  });

  it('BLOCK 阻止生成且不出现继续按钮', async () => {
    hoisted.summary.mockResolvedValue({
      ...base,
      verdict: 'block',
      gate_ready: false,
      issues: [{ severity: 'block', code: 'IDENTITY_CANON_CONTRADICTION', detail: 'hard conflict' }],
    });
    const onProceed = vi.fn();
    render(<ContinuityCheckPanel projectId="p" onProceed={onProceed} />);
    expect(await screen.findByTestId('continuity-block-issues')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '仍然继续生成' })).not.toBeInTheDocument();
    expect(screen.getByTestId('continuity-blocked-note')).toBeInTheDocument();
    expect(onProceed).not.toHaveBeenCalled();
  });
});
