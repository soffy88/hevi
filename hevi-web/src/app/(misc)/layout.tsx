import { TopNav } from '@/components/TopNav';

export default function MiscLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <TopNav />
      {children}
    </>
  );
}
