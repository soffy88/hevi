export type HubAdapterMode = 'default' | 'idea2video' | 'explainer' | 'tongjian' | 'shortdrama';
export type HubExecutionPreset = 'economy' | 'balanced' | 'fast';

export interface DirectorPrefillPayload {
  prompt: string;
  adapterMode: HubAdapterMode;
  duration: string;
  aspectRatio: '9:16' | '16:9' | '1:1';
  characters: string[];
  presetLevel: HubExecutionPreset;
}

const KEY = 'hevi.director.prefill.v1';

export function prefillDirector(payload: DirectorPrefillPayload): void {
  if (typeof window !== 'undefined') window.sessionStorage.setItem(KEY, JSON.stringify(payload));
}

export function consumeDirectorPrefill(): DirectorPrefillPayload | null {
  if (typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(KEY);
  if (!raw) return null;
  window.sessionStorage.removeItem(KEY);
  try {
    const value = JSON.parse(raw) as Partial<DirectorPrefillPayload>;
    // prompt 必须非空、duration 必须存在(空串对带参带入无意义,视为脏数据)
    if (typeof value.prompt !== 'string' || !value.prompt.trim()) return null;
    if (typeof value.duration !== 'string') return null;
    return {
      prompt: value.prompt,
      adapterMode: value.adapterMode ?? 'default',
      duration: value.duration,
      aspectRatio: value.aspectRatio ?? '9:16',
      characters: Array.isArray(value.characters) ? value.characters.filter((id): id is string => typeof id === 'string') : [],
      presetLevel: value.presetLevel ?? 'balanced',
    };
  } catch {
    return null;
  }
}
