import { describe, expect, it } from 'vitest';

import {
  PRODUCTION_API_BASE,
  resolveApiBase,
  resolveFrontendEnvironment,
} from './runtime-config';

describe('frontend API route isolation', () => {
  it('uses the canonical production origin when production has no override', () => {
    expect(resolveApiBase('production', undefined)).toBe(PRODUCTION_API_BASE);
  });

  it('accepts independent demo and staging origins', () => {
    const demo = resolveApiBase('demo', 'https://demo-api.example.test');
    const staging = resolveApiBase('staging', 'https://staging-api.example.test');
    expect(demo).toBe('https://demo-api.example.test');
    expect(staging).toBe('https://staging-api.example.test');
    expect(demo).not.toBe(staging);
    expect(demo).not.toBe(PRODUCTION_API_BASE);
  });

  it('fails closed when demo or staging has no explicit route', () => {
    expect(() => resolveApiBase('demo', undefined)).toThrow(/required/);
    expect(() => resolveApiBase('staging', undefined)).toThrow(/required/);
  });

  it('rejects the retired shared API origin and cross-environment production routes', () => {
    const retired = ['https://api', 'sxueji.com'].join('.');
    expect(() => resolveApiBase('production', retired)).toThrow(/forbidden/);
    expect(() => resolveApiBase('production', 'https://staging-api.example.test')).toThrow(
      /Production API/,
    );
  });

  it('resolves deployment environment before API selection', () => {
    expect(resolveFrontendEnvironment('development', 'production')).toBe('development');
    expect(resolveFrontendEnvironment('staging', 'production')).toBe('staging');
    expect(resolveFrontendEnvironment(undefined, 'production')).toBe('production');
    expect(resolveFrontendEnvironment('demo', 'development')).toBe('demo');
    expect(() => resolveFrontendEnvironment('qa', 'production')).toThrow(/Unsupported/);
  });
});
