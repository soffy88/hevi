/**
 * HEVI Frontend Runtime Configuration Type
 *
 * This file contains only the type definition to break circular imports.
 * Import this type from other modules.
 */

export type RuntimeConfig = {
  apiBase: string;
  useMock: boolean;
  environment: string;
};