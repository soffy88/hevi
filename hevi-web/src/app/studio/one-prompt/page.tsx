'use client';

import { TopNav } from '@/components/TopNav';
import { RequireAuth } from '@/components/RequireAuth';
import { OnePromptEntry } from '@/components/workbench/OnePromptEntry';

export default function OnePromptPage() { return <><TopNav /><RequireAuth><OnePromptEntry /></RequireAuth></>; }
