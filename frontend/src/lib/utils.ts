import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getTabId(): string {
  const KEY = "coding-agent-tab-id";
  let id = sessionStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(KEY, id);
  }
  return id;
}

export function shortTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString();
}

export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return (n / 1000).toFixed(1) + "k";
  return (n / 1_000_000).toFixed(2) + "M";
}

export function groupSessionsByDate<T extends { created_at: string }>(
  sessions: T[]
): { label: string; items: T[] }[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const lastWeek = new Date(today);
  lastWeek.setDate(today.getDate() - 7);

  const buckets: Record<string, T[]> = {
    Today: [],
    Yesterday: [],
    "Past 7 days": [],
    Older: [],
  };
  for (const s of sessions) {
    const d = new Date(s.created_at);
    if (d >= today) buckets.Today.push(s);
    else if (d >= yesterday) buckets.Yesterday.push(s);
    else if (d >= lastWeek) buckets["Past 7 days"].push(s);
    else buckets.Older.push(s);
  }
  return Object.entries(buckets)
    .filter(([, v]) => v.length > 0)
    .map(([label, items]) => ({ label, items }));
}
