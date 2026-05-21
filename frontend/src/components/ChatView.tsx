import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, FileText, FolderTree, MessageSquare, Sparkles } from "lucide-react";
import { useStore } from "@/store";
import { Markdown } from "./Markdown";
import { ToolCard } from "./ToolCard";
import { CopyButton } from "./CopyButton";
import { AssistantAvatar, Logo } from "./Logo";
import { cn } from "@/lib/utils";
import type { ToolResult } from "@/types";

interface RenderItem {
  key: string;
  role: "user" | "assistant";
  text: string;
  toolCalls: { id: string; name: string; arguments: Record<string, unknown> }[];
  results: Record<string, ToolResult>;
  streaming?: boolean;
}

export function ChatView() {
  const messages = useStore((s) => s.messages);
  const streaming = useStore((s) => s.streaming);
  const send = useStore((s) => s.send);
  const connected = useStore((s) => s.connected);

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  const [newCount, setNewCount] = useState(0);
  const lastTotalRef = useRef(0);

  const items = useMemo<RenderItem[]>(() => {
    const out: RenderItem[] = [];
    for (let i = 0; i < messages.length; i++) {
      const m = messages[i];
      if (m.role === "system") continue;
      if (m.role === "user") {
        out.push({
          key: `u-${i}`,
          role: "user",
          text: m.content,
          toolCalls: [],
          results: {},
        });
      } else if (m.role === "assistant") {
        const next = messages[i + 1];
        const resultsByCallId: Record<string, ToolResult> = {};
        if (next?.role === "tool") {
          for (const r of next.tool_results) resultsByCallId[r.call_id] = r;
        }
        out.push({
          key: `a-${i}`,
          role: "assistant",
          text: m.content,
          toolCalls: m.tool_calls,
          results: resultsByCallId,
        });
      }
    }
    if (streaming) {
      const callsInOrder = streaming.callOrder
        .map((id) => streaming.toolCalls[id])
        .filter(Boolean);
      out.push({
        key: "streaming",
        role: "assistant",
        text: streaming.text,
        toolCalls: callsInOrder,
        results: streaming.toolResults,
        streaming: true,
      });
    }
    return out;
  }, [messages, streaming]);

  // Detect "did the user scroll up?" — pin/unpin auto-scroll accordingly.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.clientHeight - el.scrollTop;
      const atBottom = distance < 80;
      setPinnedToBottom(atBottom);
      if (atBottom) setNewCount(0);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Auto-scroll when pinned; otherwise increment "new messages" badge.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (pinnedToBottom) {
      // Use rAF to wait for content paint.
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ block: "end" });
      });
      lastTotalRef.current = items.length;
      return;
    }
    if (items.length > lastTotalRef.current) {
      setNewCount((c) => c + (items.length - lastTotalRef.current));
      lastTotalRef.current = items.length;
    }
  }, [items, pinnedToBottom, streaming?.text]);

  // Reset pinning whenever the session changes.
  useEffect(() => {
    setPinnedToBottom(true);
    setNewCount(0);
    lastTotalRef.current = 0;
  }, [messages.length === 0]);

  const empty = items.length === 0;

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-6 py-6">
          {empty ? (
            <EmptyState
              connected={connected}
              onPrompt={(text) => send({ type: "submit", text })}
            />
          ) : (
            items.map((item) =>
              item.role === "user" ? (
                <UserMessage key={item.key} text={item.text} />
              ) : (
                <AssistantMessage
                  key={item.key}
                  text={item.text}
                  toolCalls={item.toolCalls}
                  results={item.results}
                  streaming={item.streaming}
                />
              ),
            )
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {!pinnedToBottom && (
        <button
          onClick={() => {
            bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
            setNewCount(0);
            setPinnedToBottom(true);
          }}
          className="absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 animate-slide-up items-center gap-1.5 rounded-full border bg-card/90 px-3 py-1.5 text-xs shadow-md backdrop-blur transition-colors hover:bg-accent"
        >
          <ArrowDown className="h-3.5 w-3.5" />
          {newCount > 0 ? `${newCount} new` : "Jump to latest"}
        </button>
      )}
    </div>
  );
}

function UserMessage({ text }: { text: string }) {
  return (
    <div className="group my-5 flex justify-end">
      <div className="relative max-w-[85%] rounded-2xl bg-accent px-4 py-2.5 text-sm leading-relaxed">
        <div className="whitespace-pre-wrap break-words">{text}</div>
        <CopyButton
          text={text}
          iconOnly
          className="absolute -left-8 top-1 opacity-0 transition-opacity group-hover:opacity-100"
        />
      </div>
    </div>
  );
}

function AssistantMessage({
  text,
  toolCalls,
  results,
  streaming = false,
}: {
  text: string;
  toolCalls: { id: string; name: string; arguments: Record<string, unknown> }[];
  results: Record<string, ToolResult>;
  streaming?: boolean;
}) {
  return (
    <div className="group relative my-6 flex gap-3">
      <AssistantAvatar size={28} />
      <div className="min-w-0 flex-1 pt-0.5">
        {text && (
          <div className={cn("text-[15px]", streaming && "streaming-cursor")}>
            <Markdown>{text}</Markdown>
          </div>
        )}
        {toolCalls.length > 0 && (
          <div className="mt-2 space-y-1.5">
            {toolCalls.map((c) => (
              <ToolCard key={c.id} call={c} result={results[c.id]} />
            ))}
          </div>
        )}
        {text && !streaming && (
          <div className="mt-1 flex h-5 items-center opacity-0 transition-opacity group-hover:opacity-100">
            <CopyButton text={text} />
          </div>
        )}
      </div>
    </div>
  );
}

interface QuickPrompt {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  prompt: string;
}

const QUICK_PROMPTS: QuickPrompt[] = [
  {
    icon: FolderTree,
    title: "Explore this codebase",
    prompt: "List the top-level structure of this workspace and explain what each directory contains.",
  },
  {
    icon: FileText,
    title: "Summarize README",
    prompt: "Read the README and summarize what this project is in three bullet points.",
  },
  {
    icon: Sparkles,
    title: "Find recent changes",
    prompt: "Show me the last five commits and explain what changed in each.",
  },
  {
    icon: MessageSquare,
    title: "Anything I should know?",
    prompt: "Take a quick look around this workspace and tell me anything noteworthy a new contributor should know.",
  },
];

function EmptyState({
  connected,
  onPrompt,
}: {
  connected: boolean;
  onPrompt: (text: string) => void;
}) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <Logo size={64} />
      <h1 className="mt-5 text-3xl font-semibold tracking-tight">
        <span className="gradient-text">Coding Agent</span>
      </h1>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        A terminal-grade coding agent, in your browser. Ask, build, refactor — the agent does the
        rest.
      </p>
      <div className="mt-8 grid w-full max-w-2xl grid-cols-1 gap-2 sm:grid-cols-2">
        {QUICK_PROMPTS.map((q) => (
          <button
            key={q.title}
            disabled={!connected}
            onClick={() => onPrompt(q.prompt)}
            className="group flex items-start gap-3 rounded-lg border bg-card px-4 py-3 text-left transition-colors hover:border-brand-blue/40 hover:bg-accent disabled:opacity-50"
          >
            <q.icon className="mt-0.5 h-4 w-4 shrink-0 text-brand-blue" />
            <div className="min-w-0">
              <div className="text-sm font-medium">{q.title}</div>
              <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                {q.prompt}
              </div>
            </div>
          </button>
        ))}
      </div>
      <div className="mt-6 text-xs text-muted-foreground">
        <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px]">⌘K</kbd>{" "}
        for the command palette ·{" "}
        <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
          ⌘/Ctrl + Enter
        </kbd>{" "}
        to send
      </div>
    </div>
  );
}
