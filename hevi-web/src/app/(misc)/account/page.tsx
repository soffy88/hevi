'use client';
import { AccountCenter } from '@/components/account/AccountCenter';
import { RequireAuth } from '@/components/RequireAuth';

export default function Page() {
  return (
    <RequireAuth>
      <AccountCenter />
    </RequireAuth>
  );
}
