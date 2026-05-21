import { useEffect, useMemo, useState } from "react";
import { MessageSquare, Plus, Search, Trash2 } from "lucide-react";
import { useStore } from "@/store";
import { cn, groupSessionsByDate, shortTime } from "@/lib/utils";
import { Button } from "./Button";
import { Logo } from "./Logo";
import { confirmDialog } from "./ConfirmDialog";

export function Sidebar() {
  const sessions = useStore((s) => s.sessions);
  const currentSessionId = useStore((s) => s.sessionId);
  const send = useStore((s) => s.send);
  const connected = useStore((s) => s.connected);
  const toast = useStore((s) => s.toast);
  const setCommandPaletteOpen = useStore((s) => s.setCommandPaletteOpen);

  const [query, setQuery] = useState("");

  useEffect(() => {
    if (connected) send({ type: "list_sessions" });
  }, [connected, send]);

  const filtered = useMemo(() => {
    if (!query.trim()) return sessions;
    const q = query.toLowerCase();
    return sessions.filter(
      (s) =>
        (s.title || "").toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q),
    );
  }, [sessions, query]);

  const grouped = groupSessionsByDate(filtered);

  const handleNewChat = () => {
    send({ type: "attach_session", session_id: null, workspace: null });
    setTimeout(() => send({ type: "list_sessions" }), 200);
  };

  const handleDelete = async (id: string, title: string) => {
    const ok = await confirmDialog({
      title: "Delete this session?",
      description:
        (title ? `“${title}” will be removed permanently.` : "The session will be removed permanently.") +
        " This can't be undone.",
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    send({ type: "delete_session", session_id: id });
    toast({ kind: "success", message: "Session deleted." });
  };

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r bg-card/40">
      <div className="flex items-center justify-between px-3 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Logo size={22} />
          <span>Coding Agent</span>
        </div>
      </div>
      <div className="px-3">
        <Button
          className="w-full justify-start gap-2 bg-gradient-to-br from-brand-blue to-brand-violet text-white shadow-sm hover:opacity-90"
          onClick={handleNewChat}
        >
          <Plus className="h-4 w-4" />
          New chat
        </Button>
      </div>
      <div className="px-3 pt-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions…"
            className="w-full rounded-md border bg-background py-1.5 pl-7 pr-2 text-xs placeholder:text-muted-foreground focus:border-brand-blue/40 focus:outline-none focus:ring-1 focus:ring-brand-blue/30"
          />
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-1.5 py-3">
        {grouped.length === 0 && (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">
            {query ? "No matches." : "No sessions yet."}
          </div>
        )}
        {grouped.map((group) => (
          <div key={group.label} className="mb-3">
            <div className="px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {group.label}
            </div>
            <ul>
              {group.items.map((s) => {
                const active = s.id === currentSessionId;
                return (
                  <li key={s.id}>
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() =>
                        send({ type: "attach_session", session_id: s.id, workspace: null })
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          send({ type: "attach_session", session_id: s.id, workspace: null });
                        }
                      }}
                      className={cn(
                        "group flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors hover:bg-accent focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-blue/40",
                        active && "bg-accent",
                      )}
                      title={`${s.title || "(empty)"} · ${shortTime(s.created_at)}`}
                    >
                      <MessageSquare
                        className={cn(
                          "h-4 w-4 shrink-0",
                          active ? "text-brand-blue" : "text-muted-foreground",
                        )}
                      />
                      <span className="line-clamp-1 flex-1 text-[13px]">
                        {s.title || <span className="italic text-muted-foreground">(empty)</span>}
                      </span>
                      <button
                        type="button"
                        className="rounded p-1 opacity-0 transition-opacity hover:bg-background hover:text-brand-rose group-hover:opacity-60 hover:!opacity-100"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(s.id, s.title);
                        }}
                        title="Delete session"
                        aria-label="Delete session"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t px-3 py-2">
        <button
          onClick={() => setCommandPaletteOpen(true)}
          className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <span className="flex items-center gap-1.5">
            <Search className="h-3.5 w-3.5" />
            Command palette
          </span>
          <kbd className="rounded border bg-muted px-1 py-0 font-mono text-[10px]">⌘K</kbd>
        </button>
      </div>
    </aside>
  );
}
