'use client';
import { TopNav } from '@/components/TopNav';
import { AccountCenter } from '@/components/account/AccountCenter';
import { RequireAuth } from '@/components/RequireAuth';
export default function Page() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <AccountCenter />
      </RequireAuth>
    </>
  );
}
