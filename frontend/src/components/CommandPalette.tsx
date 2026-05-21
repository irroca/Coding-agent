import { useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  FolderOpen,
  MessageSquare,
  Monitor,
  Moon,
  Plus,
  Search,
  Sun,
  Trash2,
} from "lucide-react";
import { useStore } from "@/store";
import { useTheme } from "@/lib/theme";
import { cn, shortTime } from "@/lib/utils";

interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
  group: "Actions" | "Sessions" | "Workspaces" | "Theme";
  run: () => void;
}

export function CommandPalette() {
  const open = useStore((s) => s.commandPaletteOpen);
  const setOpen = useStore((s) => s.setCommandPaletteOpen);
  const sessions = useStore((s) => s.sessions);
  const workspaces = useStore((s) => s.workspaces);
  const send = useStore((s) => s.send);
  const sessionId = useStore((s) => s.sessionId);
  const { setTheme } = useTheme();

  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  // Global ⌘K / Ctrl+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const close = () => setOpen(false);

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = [];
    list.push({
      id: "new-chat",
      group: "Actions",
      label: "New chat",
      hint: "Start a fresh session",
      icon: Plus,
      run: () => {
        send({ type: "attach_session", session_id: null, workspace: null });
        setTimeout(() => send({ type: "list_sessions" }), 200);
      },
    });
    if (sessionId) {
      list.push({
        id: "delete-current",
        group: "Actions",
        label: "Delete current session",
        icon: Trash2,
        run: () => {
          send({ type: "delete_session", session_id: sessionId });
        },
      });
    }
    for (const s of sessions.slice(0, 30)) {
      list.push({
        id: `session-${s.id}`,
        group: "Sessions",
        label: s.title || "(empty)",
        hint: shortTime(s.created_at),
        icon: MessageSquare,
        run: () => send({ type: "attach_session", session_id: s.id, workspace: null }),
      });
    }
    for (const w of workspaces.slice(0, 20)) {
      list.push({
        id: `ws-${w.path}`,
        group: "Workspaces",
        label: w.path,
        icon: FolderOpen,
        run: () => send({ type: "attach_session", session_id: null, workspace: w.path }),
      });
    }
    list.push(
      {
        id: "theme-light",
        group: "Theme",
        label: "Light theme",
        icon: Sun,
        run: () => setTheme("light"),
      },
      {
        id: "theme-dark",
        group: "Theme",
        label: "Dark theme",
        icon: Moon,
        run: () => setTheme("dark"),
      },
      {
        id: "theme-system",
        group: "Theme",
        label: "Follow system theme",
        icon: Monitor,
        run: () => setTheme("system"),
      },
    );
    return list;
  }, [sessions, workspaces, sessionId, send, setTheme]);

  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    const q = query.toLowerCase();
    return commands.filter(
      (c) => c.label.toLowerCase().includes(q) || c.group.toLowerCase().includes(q),
    );
  }, [commands, query]);

  useEffect(() => {
    if (activeIndex >= filtered.length) setActiveIndex(0);
  }, [filtered, activeIndex]);

  // group consecutive items by `group`
  const groupedItems = useMemo(() => {
    const blocks: { group: string; items: Command[] }[] = [];
    for (const c of filtered) {
      const last = blocks[blocks.length - 1];
      if (last && last.group === c.group) last.items.push(c);
      else blocks.push({ group: c.group, items: [c] });
    }
    return blocks;
  }, [filtered]);

  // flatten index → original entry in `filtered`
  const flatIndex = (entry: Command) => filtered.indexOf(entry);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(filtered.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const c = filtered[activeIndex];
      if (c) {
        c.run();
        close();
      }
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => setOpen(o)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 animate-overlay-in bg-black/50 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-[20%] z-50 w-[640px] max-w-[92vw] -translate-x-1/2 animate-slide-up overflow-hidden rounded-xl border bg-popover shadow-2xl focus:outline-none">
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={onKey}
              placeholder="Type a command, session, or workspace…"
              className="flex-1 bg-transparent py-1 text-sm placeholder:text-muted-foreground focus:outline-none"
            />
            <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              esc
            </kbd>
          </div>
          <div className="max-h-[55vh] overflow-y-auto p-1.5">
            {filtered.length === 0 ? (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                No matches.
              </div>
            ) : (
              groupedItems.map((block) => (
                <div key={block.group} className="mb-2 last:mb-0">
                  <div className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {block.group}
                  </div>
                  {block.items.map((c) => {
                    const idx = flatIndex(c);
                    const active = idx === activeIndex;
                    return (
                      <button
                        key={c.id}
                        onMouseEnter={() => setActiveIndex(idx)}
                        onClick={() => {
                          c.run();
                          close();
                        }}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left",
                          active && "bg-accent",
                        )}
                      >
                        <c.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="flex-1 truncate text-sm">{c.label}</span>
                        {c.hint && (
                          <span className="shrink-0 text-[11px] text-muted-foreground">
                            {c.hint}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
          <div className="flex items-center justify-between border-t bg-muted/40 px-3 py-1.5 text-[10px] text-muted-foreground">
            <span>
              <kbd className="rounded border bg-background px-1 font-mono">↑↓</kbd> navigate{" "}
              <kbd className="ml-1 rounded border bg-background px-1 font-mono">↵</kbd> select
            </span>
            <span>{filtered.length} results</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
