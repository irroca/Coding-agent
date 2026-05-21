import { useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ShieldAlert } from "lucide-react";
import { Button } from "./Button";
import { useStore } from "@/store";
import { cn } from "@/lib/utils";

interface DiffLine {
  kind: "add" | "del" | "hunk" | "ctx" | "meta";
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

function parseDiff(raw: string): { lines: DiffLine[]; added: number; removed: number } {
  const lines: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  let added = 0;
  let removed = 0;

  for (const line of raw.split("\n")) {
    if (line.startsWith("@@")) {
      // @@ -a,b +c,d @@
      const m = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      if (m) {
        oldNo = parseInt(m[1], 10);
        newNo = parseInt(m[2], 10);
      }
      lines.push({ kind: "hunk", text: line, oldNo: null, newNo: null });
    } else if (line.startsWith("+++") || line.startsWith("---")) {
      lines.push({ kind: "meta", text: line, oldNo: null, newNo: null });
    } else if (line.startsWith("+")) {
      lines.push({ kind: "add", text: line.slice(1), oldNo: null, newNo });
      newNo += 1;
      added += 1;
    } else if (line.startsWith("-")) {
      lines.push({ kind: "del", text: line.slice(1), oldNo, newNo: null });
      oldNo += 1;
      removed += 1;
    } else if (line.startsWith("\\")) {
      lines.push({ kind: "meta", text: line, oldNo: null, newNo: null });
    } else {
      lines.push({
        kind: "ctx",
        text: line.startsWith(" ") ? line.slice(1) : line,
        oldNo,
        newNo,
      });
      oldNo += 1;
      newNo += 1;
    }
  }
  return { lines, added, removed };
}

export function PermissionModal() {
  const pending = useStore((s) => s.pendingConfirm);
  const send = useStore((s) => s.send);
  const dismiss = useStore((s) => s.dismissConfirm);
  const toast = useStore((s) => s.toast);
  const [always, setAlways] = useState(false);

  const diff = useMemo(
    () => (pending?.diff_preview ? parseDiff(pending.diff_preview) : null),
    [pending?.diff_preview],
  );

  if (!pending) return null;

  const respond = (approved: boolean) => {
    send({
      type: "confirm_response",
      request_id: pending.request_id,
      approved,
      always: approved && always,
    });
    if (approved && always) {
      toast({
        kind: "info",
        message: `Will auto-approve ${pending.tool_name} for the rest of this session.`,
        duration: 4000,
      });
    }
    setAlways(false);
    dismiss();
  };

  return (
    <Dialog.Root open onOpenChange={(o) => !o && respond(false)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 animate-overlay-in bg-black/60 backdrop-blur-sm" />
        <Dialog.Content
          onEscapeKeyDown={(e) => {
            e.preventDefault();
            respond(false);
          }}
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[720px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 animate-slide-up flex-col rounded-xl border bg-card shadow-2xl focus:outline-none"
        >
          <div className="flex items-start gap-3 border-b px-5 py-4">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-amber/15 text-brand-amber">
              <ShieldAlert className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-base font-semibold">
                Allow{" "}
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">
                  {pending.tool_name}
                </code>
                ?
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-muted-foreground">
                The agent wants to run this action. Review the details before approving.
              </Dialog.Description>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4">
            <div className="rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs leading-snug">
              {pending.summary}
            </div>

            {diff && (
              <div className="mt-4 overflow-hidden rounded-md border bg-background">
                <div className="flex items-center justify-between border-b bg-muted/40 px-3 py-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                  <span>Diff preview</span>
                  <span className="flex items-center gap-2 font-mono">
                    <span className="text-brand-emerald">+{diff.added}</span>
                    <span className="text-brand-rose">−{diff.removed}</span>
                  </span>
                </div>
                <div className="max-h-72 overflow-auto font-mono text-xs">
                  <table className="w-full border-collapse">
                    <tbody>
                      {diff.lines.map((line, i) => (
                        <tr
                          key={i}
                          className={cn(
                            line.kind === "add" && "bg-brand-emerald/10",
                            line.kind === "del" && "bg-brand-rose/10",
                            line.kind === "hunk" && "bg-brand-blue/10 text-brand-blue",
                          )}
                        >
                          <td className="w-10 select-none border-r px-1.5 py-0 text-right text-[10px] text-muted-foreground/70">
                            {line.oldNo ?? ""}
                          </td>
                          <td className="w-10 select-none border-r px-1.5 py-0 text-right text-[10px] text-muted-foreground/70">
                            {line.newNo ?? ""}
                          </td>
                          <td
                            className={cn(
                              "w-5 select-none px-1 py-0 text-center text-[10px]",
                              line.kind === "add" && "text-brand-emerald",
                              line.kind === "del" && "text-brand-rose",
                              line.kind === "hunk" && "text-brand-blue",
                            )}
                          >
                            {line.kind === "add" ? "+" : line.kind === "del" ? "-" : ""}
                          </td>
                          <td
                            className={cn(
                              "whitespace-pre py-0 pr-2 leading-5",
                              line.kind === "add" && "text-brand-emerald",
                              line.kind === "del" && "text-brand-rose",
                              line.kind === "hunk" && "text-brand-blue",
                              line.kind === "meta" && "text-muted-foreground",
                            )}
                          >
                            {line.text || " "}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t bg-muted/30 px-5 py-3">
            <label className="flex select-none items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={always}
                onChange={(e) => setAlways(e.target.checked)}
                className="h-3.5 w-3.5 accent-brand-blue"
              />
              Always allow{" "}
              <code className="rounded bg-background px-1 font-mono">{pending.tool_name}</code>{" "}
              for this session
            </label>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => respond(false)}>
                Deny
              </Button>
              <Button onClick={() => respond(true)} autoFocus>
                {always ? "Always allow" : "Allow"}
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
