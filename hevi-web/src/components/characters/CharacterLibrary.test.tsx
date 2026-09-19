/**
 * D6-A/B 角色库 component tests — canonical identityApi only.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CharacterLibrary } from './CharacterLibrary';

const hoisted = vi.hoisted(() => ({
  list: vi.fn(),
  inspect: vi.fn(),
  create: vi.fn(),
  bind: vi.fn(),
  upgrade: vi.fn(),
  archive: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  identityApi: {
    list: hoisted.list,
    inspect: hoisted.inspect,
    create: hoisted.create,
    bind: hoisted.bind,
    projectBindings: vi.fn(),
    upgrade: hoisted.upgrade,
    archive: hoisted.archive,
  },
}));

const identity = {
  identity_id: 'i1',
  canonical_name: 'Anna',
  aliases: [],
  kind: 'character',
  identity_version: 3,
  archived: false,
  upgrade_available: true,
  appearance_count: 2,
  appearances: [
    { appearance_id: 'default', kind: 'default', label: 'default', version: 1 },
    { appearance_id: 'winter', kind: 'outfit', label: 'winter', version: 1 },
  ],
  voice_id: 'v-anna',
  binding_count: 1,
  projects_using: ['proj-a'],
  linked_subjects: [],
};

describe('角色库', () => {
  it('渲染角色、版本与升级提示', async () => {
    hoisted.list.mockResolvedValue([identity]);
    render(<CharacterLibrary projectId="proj-a" />);
    expect(await screen.findByText('Anna')).toBeInTheDocument();
    expect(screen.getByText(/v3/)).toBeInTheDocument();
    expect(screen.getByTestId('upgrade-available-i1')).toBeInTheDocument();
    expect(screen.getByText(/proj-a/)).toBeInTheDocument();
  });

  it('空状态', async () => {
    hoisted.list.mockResolvedValue([]);
    render(<CharacterLibrary />);
    expect(await screen.findByTestId('library-empty')).toBeInTheDocument();
  });

  it('用于当前项目调用 bind', async () => {
    hoisted.list.mockResolvedValue([identity]);
    hoisted.bind.mockResolvedValue({});
    const user = (await import('@testing-library/user-event')).default;
    render(<CharacterLibrary projectId="proj-a" />);
    await screen.findByText('Anna');
    await user.setup().click(screen.getByRole('button', { name: '用于当前项目' }));
    expect(hoisted.bind).toHaveBeenCalledWith('proj-a', 'i1');
  });

  it('升级调用 inspect 后对过期 binding 调用 upgrade', async () => {
    hoisted.list.mockResolvedValue([identity]);
    hoisted.inspect.mockResolvedValue({
      ...identity,
      identity_version: 4,
      bindings: [{ binding_id: 'b1', pinned_identity_version: 3 }],
    });
    hoisted.upgrade.mockResolvedValue({});
    const user = (await import('@testing-library/user-event')).default;
    render(<CharacterLibrary />);
    await screen.findByText('Anna');
    await user.setup().click(screen.getByRole('button', { name: '升级到当前版本' }));
    expect(hoisted.upgrade).toHaveBeenCalledWith('b1');
  });

  it('搜索过滤', async () => {
    hoisted.list.mockResolvedValue([
      identity,
      { ...identity, identity_id: 'i2', canonical_name: 'Bob', upgrade_available: false },
    ]);
    const user = (await import('@testing-library/user-event')).default;
    render(<CharacterLibrary />);
    await screen.findByText('Anna');
    await user.setup().type(screen.getByLabelText('搜索角色'), 'bob');
    expect(screen.queryByText('Anna')).not.toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
  });
});
