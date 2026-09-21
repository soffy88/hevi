import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductionCreatePanel } from './ProductionCreatePanel';

const hoisted = vi.hoisted(() => ({
  health: vi.fn(),
  capabilities: vi.fn(),
  create: vi.fn(),
  push: vi.fn(),
  created: vi.fn(),
}));

vi.mock('@/lib/backend-health', () => ({ checkBackendHealth: hoisted.health }));
vi.mock('@/lib/api-client', () => ({ productionApi: { capabilities: hoisted.capabilities, create: hoisted.create } }));
vi.mock('@/lib/auth-store', () => ({ isAuthenticated: () => true }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: hoisted.push }) }));

describe('ProductionCreatePanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('submits the canonical production request and no internal workflow endpoint', async () => {
    hoisted.health.mockResolvedValue({ live: true, ready: true, state: 'healthy' });
    hoisted.capabilities.mockResolvedValue({ capabilities: [
      { id: 'local_media', name: 'Local Media Golden Path', available: true, production_ready: true, routes: [], status: 'ready', message: '' },
      { id: 'motion_graphics', name: 'Remotion', available: true, production_ready: true, routes: [], status: 'ready', message: '' },
      { id: 'v2v', name: 'V2V', available: false, production_ready: false, routes: [], status: 'unavailable', message: '' },
    ] });
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
    hoisted.capabilities.mockResolvedValue({ capabilities: [
      { id: 'local_media', name: 'Local Media Golden Path', available: true, production_ready: true, routes: [], status: 'ready', message: '' },
    ] });
    const user = userEvent.setup();
    render(<ProductionCreatePanel onCreated={hoisted.created} />);
    await waitFor(() => expect(screen.getByTestId('production-readiness')).toHaveTextContent('UNAVAILABLE'));
    await user.type(screen.getByLabelText('script/text'), 'must not submit');
    expect(screen.getByRole('button', { name: '创建 production' })).toBeDisabled();
    expect(hoisted.create).not.toHaveBeenCalled();
  });

  it('renders V2V from the backend catalog as blocked and never selectable', async () => {
    hoisted.health.mockResolvedValue({ live: true, ready: true, state: 'healthy' });
    hoisted.capabilities.mockResolvedValue({ capabilities: [
      { id: 'local_media', name: 'Local Media Golden Path', available: true, production_ready: true, routes: [], status: 'ready', message: '' },
      { id: 'v2v', name: 'V2V', available: true, production_ready: false, routes: [], status: 'conditional', message: '' },
    ] });
    render(<ProductionCreatePanel onCreated={hoisted.created} />);
    await waitFor(() => expect(screen.getByTestId('v2v-capability-state')).toHaveTextContent('WIRING_QUALIFIED_PROVIDER_BLOCKED'));
    expect(screen.getByRole('option', { name: /V2V/ })).toBeDisabled();
  });
});
