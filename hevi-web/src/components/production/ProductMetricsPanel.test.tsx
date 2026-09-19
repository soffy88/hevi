/**
 * D6-H 创作数据 panel test — reads the canonical metrics endpoint.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProductMetricsPanel } from './ProductMetricsPanel';

const hoisted = vi.hoisted(() => ({ metrics: vi.fn() }));

vi.mock('@/lib/api-client', () => ({
  productApi: { metrics: hoisted.metrics },
}));

describe('创作数据', () => {
  it('展示 canonical 指标', async () => {
    hoisted.metrics.mockResolvedValue({
      owner_id: 'o',
      metrics: {
        IDENTITY_REUSE_RATE: 2.5,
        CONTINUITY_BLOCKS_CAUGHT: 3,
        CONTINUITY_WARNINGS_OVERRIDDEN: 1,
        AUTO_SAFE_REPAIRS: 4,
        PAID_REPAIRS_CONFIRMED: 1,
        FAILED_REPAIRS: 0,
        REPAIR_MEAN_ATTEMPTS: 1.2,
        DUPLICATE_BILLING_PREVENTED: 5,
        ARTIFACTS_PRESERVED_BY_REPAIR: 2,
      },
    });
    render(<ProductMetricsPanel />);
    expect(await screen.findByTestId('product-metrics')).toBeInTheDocument();
    expect(screen.getByTestId('metric-CONTINUITY_BLOCKS_CAUGHT')).toHaveTextContent('3');
    expect(screen.getByTestId('metric-AUTO_SAFE_REPAIRS')).toHaveTextContent('4');
  });
});
