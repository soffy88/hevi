import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductionCreatePanel } from './ProductionCreatePanel';

const hoisted = vi.hoisted(() => ({
  health: vi.fn(),
  create: vi.fn(),
  push: vi.fn(),
  created: vi.fn(),
}));

vi.mock('@/lib/backend-health', () => ({ checkBackendHealth: hoisted.health }));
vi.mock('@/lib/api-client', () => ({ productionApi: { create: hoisted.create } }));
vi.mock('@/lib/auth-store', () => ({ isAuthenticated: () => true }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: hoisted.push }) }));

describe('ProductionCreatePanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('submits the canonical production request and no internal workflow endpoint', async () => {
    hoisted.health.mockResolvedValue({ live: true, ready: true, state: 'healthy' });
    hoisted.create.mockResolvedValue({ task_id: 'task-1', status: 'queued', percent: 0, production_source: 'automatic' });
    const user = userEvent.setup();
    render(<ProductionCreatePanel onCreated={hoisted.created} />);
    await waitFor(() => expect(screen.getByTestId('production-readiness')).toHaveTextContent('READY'));
    await user.type(screen.getByLabelText('script/text'), 'A real production script');
    await user.click(screen.getByRole('button', { name: '创建 production' }));
    await waitFor(() => expect(hoisted.create).toHaveBeenCalledOnce());
    expect(hoisted.create).toHaveBeenCalledWith(expect.objectContaining({
      source: 'automatic',
      topic: 'A real production script',
      options: expect.objectContaining({ visual_mode: 'local_media', subtitles: true }),
    }));
    expect(hoisted.created).toHaveBeenCalledWith(expect.objectContaining({ task_id: 'task-1' }));
  });

  it('blocks submission when backend readiness says worker/dependencies are unavailable', async () => {
    hoisted.health.mockResolvedValue({ live: true, ready: false, state: 'degraded' });
    const user = userEvent.setup();
    render(<ProductionCreatePanel onCreated={hoisted.created} />);
    await waitFor(() => expect(screen.getByTestId('production-readiness')).toHaveTextContent('UNAVAILABLE'));
    await user.type(screen.getByLabelText('script/text'), 'must not submit');
    expect(screen.getByRole('button', { name: '创建 production' })).toBeDisabled();
    expect(hoisted.create).not.toHaveBeenCalled();
  });
});
