import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// RTL 组件测试自动清理(vitest 未开 globals 时 RTL 不会自动 unmount)
afterEach(() => cleanup());
