import { useEffect, useRef, useState } from "react";
import { Send, Square } from "lucide-react";
import { Button } from "./Button";
import { useStore } from "@/store";
import { cn } from "@/lib/utils";

const SLASH_COMMANDS: { name: string; description: string }[] = [
  { name: "/help", description: "Show available commands" },
  { name: "/clear", description: "Start a fresh chat in this workspace" },
  { name: "/cost", description: "Show token usage + cache hit rate" },
  { name: "/compact", description: "Summarize older turns to free up context" },
  { name: "/history", description: "List recent messages in this session" },
  { name: "/tools", description: "List registered tools" },
  { name: "/permissions", description: "Show the active permission rules" },
];

export function Composer() {
  const [text, setText] = useState("");
  const [showSlash, setShowSlash] = useState(false);
  const send = useStore((s) => s.send);
  const streaming = useStore((s) => s.streaming);
  const connected = useStore((s) => s.connected);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 240) + "px";
    }
  }, [text]);

  useEffect(() => {
    setShowSlash(text.startsWith("/") && !text.includes("\n") && text.length <= 16);
  }, [text]);

  const submit = () => {
    const t = text.trim();
    if (!t || streaming) return;
    send({ type: "submit", text: t });
    setText("");
    setShowSlash(false);
  };

  const cancel = () => {
    send({ type: "cancel" });
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape") {
      if (streaming) {
        e.preventDefault();
        cancel();
      } else if (showSlash) {
        e.preventDefault();
        setShowSlash(false);
      }
    }
  };

  const busy = streaming !== null && !streaming.done;
  const filteredSlash = SLASH_COMMANDS.filter((c) =>
    c.name.toLowerCase().startsWith(text.toLowerCase()),
  );

  return (
    <div className="border-t bg-card/60 px-4 pb-4 pt-3 backdrop-blur">
      <div className="relative mx-auto max-w-3xl">
        {showSlash && filteredSlash.length > 0 && (
          <div className="absolute -top-2 left-0 right-0 z-10 -translate-y-full animate-slide-up rounded-md border bg-popover p-1 shadow-lg">
            {filteredSlash.slice(0, 6).map((c) => (
              <button
                key={c.name}
                onMouseDown={(e) => {
                  // mousedown to fire before textarea blur
                  e.preventDefault();
                  setText(c.name + " ");
                  textareaRef.current?.focus();
                }}
                className="flex w-full items-center justify-between gap-3 rounded px-2 py-1.5 text-left hover:bg-accent"
              >
                <span className="font-mono text-xs text-foreground">{c.name}</span>
                <span className="truncate text-[11px] text-muted-foreground">
                  {c.description}
                </span>
              </button>
            ))}
          </div>
        )}
        <div
          className={cn(
            "flex items-end gap-2 rounded-xl border bg-background p-2 shadow-sm transition-shadow focus-within:border-brand-blue/40 focus-within:shadow-md",
            !connected && "opacity-60",
          )}
        >
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            rows={1}
            placeholder={
              connected
                ? busy
                  ? "Working… press Esc to cancel."
                  : "Message Coding Agent — type / for commands"
                : "Reconnecting…"
            }
            disabled={!connected}
            className="flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] leading-relaxed placeholder:text-muted-foreground focus:outline-none"
          />
          {busy ? (
            <Button size="icon" variant="destructive" onClick={cancel} title="Cancel (Esc)">
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={submit}
              disabled={!connected || !text.trim()}
              title="Send (⌘/Ctrl+Enter)"
              className="bg-gradient-to-br from-brand-blue to-brand-violet text-white hover:opacity-90"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <div className="mt-1.5 flex items-center justify-between px-1 text-[11px] text-muted-foreground">
          <span>
            <kbd className="rounded border bg-muted px-1 py-0 font-mono text-[10px]">⌘/Ctrl</kbd>
            +
            <kbd className="rounded border bg-muted px-1 py-0 font-mono text-[10px]">Enter</kbd>
            <span className="mx-1.5">to send</span>
            {busy && (
              <>
                ·{" "}
                <kbd className="rounded border bg-muted px-1 py-0 font-mono text-[10px]">Esc</kbd>{" "}
                to cancel
              </>
            )}
          </span>
          {text.length > 0 && (
            <span className="tabular-nums">{text.length.toLocaleString()} chars</span>
          )}
        </div>
      </div>
    </div>
  );
}
