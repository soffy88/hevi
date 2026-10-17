'use client';

import { TopNav } from '@/components/TopNav';
import { RequireAuth } from '@/components/RequireAuth';
import { ProjectHub } from '@/components/workbench/ProjectHub';

export default function CanonicalProjectsPage() { return <><TopNav /><RequireAuth><ProjectHub /></RequireAuth></>; }
