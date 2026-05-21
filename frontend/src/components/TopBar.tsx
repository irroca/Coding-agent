import { useEffect, useRef, useState } from "react";
import { ChevronDown, FolderOpen, Monitor, Moon, Search, Sun } from "lucide-react";
import { useStore } from "@/store";
import { useTheme, type Theme } from "@/lib/theme";
import { Button } from "./Button";
import { cn, formatTokens } from "@/lib/utils";

function shortenPath(p: string | null | undefined, max = 38): string {
  if (!p) return "—";
  if (p.length <= max) return p;
  const parts = p.split("/").filter(Boolean);
  if (parts.length <= 2) return "…/" + parts.slice(-2).join("/");
  return "…/" + parts.slice(-2).join("/");
}

export function TopBar() {
  const provider = useStore((s) => s.provider);
  const model = useStore((s) => s.model);
  const workspace = useStore((s) => s.workspace);
  const usage = useStore((s) => s.usage);
  const send = useStore((s) => s.send);
  const workspaces = useStore((s) => s.workspaces);
  const connected = useStore((s) => s.connected);
  const setCommandPaletteOpen = useStore((s) => s.setCommandPaletteOpen);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [customPath, setCustomPath] = useState("");
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (connected) send({ type: "list_workspaces" });
  }, [connected, send]);

  // Close dropdown on outside click.
  useEffect(() => {
    if (!pickerOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (!pickerRef.current?.contains(e.target as Node)) setPickerOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [pickerOpen]);

  const cacheRate =
    usage.prompt_tokens > 0
      ? Math.round((usage.cached_prompt_tokens / usage.prompt_tokens) * 100)
      : 0;

  const choose = (path: string) => {
    send({ type: "attach_session", session_id: null, workspace: path });
    setPickerOpen(false);
    setCustomPath("");
  };

  return (
    <header className="flex h-12 items-center justify-between border-b bg-card/70 px-3 backdrop-blur">
      <div className="flex items-center gap-2">
        <div ref={pickerRef} className="relative">
          <button
            onClick={() => setPickerOpen((b) => !b)}
            className="group flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs transition-colors hover:bg-accent"
            title={workspace || ""}
          >
            <FolderOpen className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="font-mono">{shortenPath(workspace)}</span>
            <ChevronDown className="h-3 w-3 text-muted-foreground opacity-60 transition-transform group-hover:opacity-100" />
          </button>
          {pickerOpen && (
            <div className="absolute left-0 top-10 z-30 w-[420px] animate-slide-up rounded-md border bg-popover p-2 shadow-xl">
              <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Recent workspaces
              </div>
              <ul className="mb-2 max-h-60 overflow-y-auto">
                {workspaces.length === 0 && (
                  <li className="px-2 py-3 text-center text-xs text-muted-foreground">
                    No recent workspaces.
                  </li>
                )}
                {workspaces.map((w) => (
                  <li key={w.path}>
                    <button
                      className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left font-mono text-xs hover:bg-accent"
                      onClick={() => choose(w.path)}
                      title={w.path}
                    >
                      <span className="truncate">{w.path}</span>
                      {workspace === w.path && (
                        <span className="ml-2 shrink-0 rounded bg-brand-blue/15 px-1 text-[9px] uppercase text-brand-blue">
                          active
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
              <div className="border-t pt-2">
                <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Other path
                </div>
                <form
                  className="flex gap-2 px-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (customPath.trim()) choose(customPath.trim());
                  }}
                >
                  <input
                    type="text"
                    placeholder="/abs/path/to/repo"
                    value={customPath}
                    onChange={(e) => setCustomPath(e.target.value)}
                    className="flex-1 rounded border bg-background px-2 py-1 font-mono text-xs focus-visible:ring-1 focus-visible:ring-ring"
                  />
                  <Button size="sm" type="submit">
                    Go
                  </Button>
                </form>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1">
        <button
          onClick={() => setCommandPaletteOpen(true)}
          className="hidden items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent md:inline-flex"
          title="Command palette"
        >
          <Search className="h-3.5 w-3.5" />
          <span>Search…</span>
          <kbd className="rounded border bg-muted px-1 py-0 font-mono text-[10px]">⌘K</kbd>
        </button>

        <UsagePill
          provider={provider}
          model={model}
          prompt={usage.prompt_tokens}
          completion={usage.completion_tokens}
          cacheRate={cacheRate}
          hasCache={usage.cached_prompt_tokens > 0}
        />

        <ThemeToggle />

        <span
          className={cn(
            "ml-1 h-1.5 w-1.5 rounded-full transition-colors",
            connected ? "bg-brand-emerald" : "bg-brand-rose",
          )}
          title={connected ? "Connected" : "Disconnected"}
        />
      </div>
    </header>
  );
}

function UsagePill({
  provider,
  model,
  prompt,
  completion,
  cacheRate,
  hasCache,
}: {
  provider: string | null;
  model: string | null;
  prompt: number;
  completion: number;
  cacheRate: number;
  hasCache: boolean;
}) {
  return (
    <div
      className="hidden items-center gap-2 rounded-md border bg-background/60 px-2 py-1 text-[11px] text-muted-foreground sm:flex"
      title={`${prompt.toLocaleString()} prompt · ${completion.toLocaleString()} completion`}
    >
      <span className="font-mono text-foreground">
        {provider || "—"}
        <span className="opacity-60">:</span>
        {model || "—"}
      </span>
      <span className="h-3 w-px bg-border" />
      <span className="font-mono">
        ↑{formatTokens(prompt)} <span className="opacity-50">/</span> ↓{formatTokens(completion)}
      </span>
      {hasCache && (
        <>
          <span className="h-3 w-px bg-border" />
          <span className="font-mono text-brand-emerald" title="Prompt cache hit rate">
            cache {cacheRate}%
          </span>
        </>
      )}
    </div>
  );
}

function ThemeToggle() {
  const { theme, setTheme, resolved } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const Icon = resolved === "dark" ? Moon : Sun;

  const items: { id: Theme; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
    { id: "light", label: "Light", icon: Sun },
    { id: "dark", label: "Dark", icon: Moon },
    { id: "system", label: "System", icon: Monitor },
  ];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((b) => !b)}
        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        title="Theme"
      >
        <Icon className="h-3.5 w-3.5" />
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-30 w-32 animate-slide-up overflow-hidden rounded-md border bg-popover p-1 shadow-lg">
          {items.map(({ id, label, icon: I }) => (
            <button
              key={id}
              onClick={() => {
                setTheme(id);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-accent",
                theme === id && "bg-accent",
              )}
            >
              <I className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
