'use client';
import { TopNav } from '@/components/TopNav';
import { TaskDashboard } from '@/components/dashboard/TaskDashboard';

export default function DashboardPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-dashboard-page">
        <TaskDashboard />
      </main>
    </>
  );
}
