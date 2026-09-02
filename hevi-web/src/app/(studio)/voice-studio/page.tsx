'use client';

import { VoiceStudioConsole } from '@/components/studio/VoiceStudioConsole';
import { VoicePlatformPanel } from '@/components/studio/VoicePlatformPanel';

export default function VoiceStudioPage() {
  return (
    <main style={{ maxWidth: '1200px', margin: '0 auto', padding: '24px 16px' }}>
      <VoiceStudioConsole />
      <VoicePlatformPanel />
    </main>
  );
}
