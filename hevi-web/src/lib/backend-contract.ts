/**
 * The frontend's single translation boundary for the canonical backend
 * production contract.
 *
 * This module deliberately contains no lifecycle rules. It only recognizes
 * values emitted by the backend and fails closed for values it does not know.
 */

export const TASK_STATUSES = [
  'pending',
  'queued',
  'claimed',
  'running',
  'completed',
  'failed',
  'blocked',
  'cancelled',
  'paused',
  'interrupted',
] as const;

export type BackendTaskStatus = (typeof TASK_STATUSES)[number];
export type FrontendTaskStatus = BackendTaskStatus | 'unknown';

export const TASK_STATUS_LABELS: Record<FrontendTaskStatus, string> = {
  pending: '等待提交',
  queued: '队列中',
  claimed: '已领取',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  blocked: '已阻断',
  cancelled: '已取消',
  paused: '已暂停',
  interrupted: '已中断',
  unknown: '未知状态（已阻断）',
};

export function normalizeTaskStatus(value: unknown): FrontendTaskStatus {
  return typeof value === 'string' && (TASK_STATUSES as readonly string[]).includes(value)
    ? (value as BackendTaskStatus)
    : 'unknown';
}

export function isTaskTerminal(value: unknown): boolean {
  const status = normalizeTaskStatus(value);
  return status === 'completed' || status === 'failed' || status === 'blocked' || status === 'cancelled';
}

export function isTaskActive(value: unknown): boolean {
  const status = normalizeTaskStatus(value);
  return status === 'pending' || status === 'queued' || status === 'claimed' || status === 'running';
}

export function boundedBackendProgress(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
}

export type CapabilityQualification =
  | 'PRODUCTION_QUALIFIED'
  | 'WIRING_QUALIFIED_PROVIDER_BLOCKED'
  | 'INTERFACE_AVAILABLE'
  | 'UNQUALIFIED'
  | 'UNKNOWN';

export const CAPABILITY_QUALIFICATION_LABELS: Record<CapabilityQualification, string> = {
  PRODUCTION_QUALIFIED: 'PRODUCTION_QUALIFIED',
  WIRING_QUALIFIED_PROVIDER_BLOCKED: 'WIRING_QUALIFIED_PROVIDER_BLOCKED',
  INTERFACE_AVAILABLE: 'INTERFACE_AVAILABLE',
  UNQUALIFIED: 'UNQUALIFIED',
  UNKNOWN: 'UNKNOWN',
};

export function capabilityQualification(capability: {
  id: string;
  available?: boolean;
  production_ready?: boolean | null;
  execution_ready?: boolean | null;
  quality_gate_ready?: boolean | null;
  provider_ready?: boolean | null;
  status?: string;
}): CapabilityQualification {
  // V2V is intentionally never presented as available by the frontend. The
  // backend catalog remains the authority for its actual provider state.
  if (capability.id === 'v2v' || capability.id === 'streaming_v2v') {
    return 'WIRING_QUALIFIED_PROVIDER_BLOCKED';
  }
  if (capability.production_ready === true) return 'PRODUCTION_QUALIFIED';
  if (capability.provider_ready === false) return 'WIRING_QUALIFIED_PROVIDER_BLOCKED';
  if (capability.available === true && capability.production_ready == null) {
    return 'INTERFACE_AVAILABLE';
  }
  if (capability.available === false || capability.production_ready === false) {
    return 'UNQUALIFIED';
  }
  return 'UNKNOWN';
}

export const BACKEND_API_CONTRACT = {
  productionCreate: { method: 'POST', path: '/api/pipeline/productions', success: 201 },
  capabilities: { method: 'GET', path: '/api/pipeline/capabilities', success: 200 },
  taskList: { method: 'GET', path: '/api/tasks', success: 200 },
  taskRead: { method: 'GET', path: '/api/tasks/{task_id}', success: 200 },
  taskCheckpoint: { method: 'GET', path: '/api/tasks/{task_id}/checkpoint', success: 200 },
  artifactPresentation: { method: 'GET', path: '/api/authorities/tasks/{task_id}/presentation', success: 200 },
  artifactCurrency: { method: 'GET', path: '/api/authorities/tasks/{task_id}/currency', success: 200 },
  qualityEvidence: { source: 'task.config_json.quality_evaluation', authority: 'backend' },
  incidents: { method: 'GET', path: '/api/incidents?production_run_id={id}', success: 200 },
  healthLive: { method: 'GET', path: '/api/health/live', success: 200 },
  healthReady: { method: 'GET', path: '/api/health/ready', success: 200, notReady: 503 },
  realtime: { method: 'WEBSOCKET', path: '/api/ws/tasks', event: 'task_update' },
} as const;

export function isKnownCapabilityQualification(value: unknown): value is CapabilityQualification {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(CAPABILITY_QUALIFICATION_LABELS, value);
}
