import { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Edit3,
  FileText,
  FolderTree,
  Loader2,
  Search,
  Terminal,
  Workflow,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CopyButton } from "./CopyButton";
import type { ToolCall, ToolResult } from "@/types";

interface Props {
  call: ToolCall;
  result?: ToolResult;
  defaultOpen?: boolean;
}

// Per-tool metadata: icon, accent color (CSS var), short label
const TOOL_META: Record<
  string,
  { icon: React.ComponentType<{ className?: string }>; tone: string; label: string }
> = {
  read: { icon: FileText, tone: "brand-blue", label: "Read" },
  write: { icon: FileText, tone: "brand-emerald", label: "Write" },
  edit: { icon: Edit3, tone: "brand-amber", label: "Edit" },
  ls: { icon: FolderTree, tone: "brand-blue", label: "List" },
  glob: { icon: Search, tone: "brand-blue", label: "Glob" },
  grep: { icon: Search, tone: "brand-blue", label: "Grep" },
  bash: { icon: Terminal, tone: "brand-violet", label: "Bash" },
  task: { icon: Workflow, tone: "brand-violet", label: "Sub-agent" },
  todo_write: { icon: Workflow, tone: "brand-emerald", label: "Todo" },
};

function metaFor(name: string) {
  return (
    TOOL_META[name] ?? {
      icon: Wrench,
      tone: "muted-foreground",
      label: name,
    }
  );
}

function summarizeArgs(name: string, args: Record<string, unknown>): string {
  if (name === "bash" && typeof args.command === "string") return args.command;
  if (name === "edit" && typeof args.file_path === "string") return args.file_path as string;
  if (name === "write" && typeof args.file_path === "string") return args.file_path as string;
  if (name === "read" && typeof args.file_path === "string") return args.file_path as string;
  if ((name === "ls" || name === "glob" || name === "grep") && typeof args.path === "string")
    return args.path as string;
  if (name === "grep" && typeof args.pattern === "string") return args.pattern as string;
  if (name === "task" && typeof args.subject === "string") return args.subject as string;
  const interesting = ["command", "file_path", "path", "pattern", "subject"];
  for (const k of interesting) {
    if (k in args && typeof args[k] === "string") return args[k] as string;
  }
  return JSON.stringify(args);
}

export function ToolCard({ call, result, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const running = result === undefined;
  const ok = result?.ok ?? null;
  const meta = metaFor(call.name);
  const Icon = meta.icon;

  const subtitle = summarizeArgs(call.name, call.arguments);
  const subtitleShort = subtitle.length > 140 ? subtitle.slice(0, 140) + "…" : subtitle;

  const stateColor = running
    ? "text-brand-amber"
    : ok
      ? "text-brand-emerald"
      : "text-brand-rose";
  const barColor = running
    ? "bg-brand-amber"
    : ok
      ? "bg-brand-emerald"
      : "bg-brand-rose";

  return (
    <div className="group/tool overflow-hidden rounded-md border bg-card/60 text-xs transition-colors hover:bg-card">
      <div className="flex">
        <div className={cn("w-0.5 shrink-0", barColor)} />
        <button
          type="button"
          onClick={() => setOpen((b) => !b)}
          className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
        >
          <ChevronRight
            className={cn(
              "h-3 w-3 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-90",
            )}
          />
          <Icon className={cn("h-3.5 w-3.5 shrink-0", `text-${meta.tone}`)} />
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            {meta.label}
          </span>
          <span className="min-w-0 flex-1 truncate font-mono text-muted-foreground">
            {subtitleShort || <em className="not-italic opacity-60">(no args)</em>}
          </span>
          <span className={cn("flex shrink-0 items-center gap-1 font-medium", stateColor)}>
            {running ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : ok ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <AlertCircle className="h-3 w-3" />
            )}
            {running ? "running" : ok ? "done" : "failed"}
          </span>
        </button>
      </div>
      {open && (
        <div className="grid gap-3 border-t border-border/60 px-3 py-2 sm:grid-cols-2">
          <Pane label="Arguments" copy={JSON.stringify(call.arguments, null, 2)}>
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words text-xs leading-snug">
              {JSON.stringify(call.arguments, null, 2)}
            </pre>
          </Pane>
          <Pane
            label={running ? "Pending…" : result?.ok ? "Result" : "Error"}
            copy={result?.content ?? ""}
            disabled={running}
          >
            {running ? (
              <div className="flex items-center gap-1.5 text-xs italic text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                streaming…
              </div>
            ) : (
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs leading-snug">
                {result?.content}
              </pre>
            )}
          </Pane>
        </div>
      )}
    </div>
  );
}

function Pane({
  label,
  copy,
  disabled = false,
  children,
}: {
  label: string;
  copy: string;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0 rounded border bg-background/50 p-2">
      <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
        <span>{label}</span>
        {!disabled && copy && <CopyButton text={copy} iconOnly />}
      </div>
      {children}
    </div>
  );
}
