import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useStore, type Toast } from "@/store";
import { cn } from "@/lib/utils";

const KIND_STYLES: Record<
  Toast["kind"],
  { ring: string; icon: React.ComponentType<{ className?: string }>; iconColor: string }
> = {
  info: { ring: "ring-brand-blue/30", icon: Info, iconColor: "text-brand-blue" },
  success: {
    ring: "ring-brand-emerald/30",
    icon: CheckCircle2,
    iconColor: "text-brand-emerald",
  },
  warning: {
    ring: "ring-brand-amber/40",
    icon: AlertTriangle,
    iconColor: "text-brand-amber",
  },
  error: {
    ring: "ring-brand-rose/40",
    icon: XCircle,
    iconColor: "text-brand-rose",
  },
};

export function Toaster() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismissToast);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2">
      {toasts.map((t) => {
        const { ring, icon: Icon, iconColor } = KIND_STYLES[t.kind];
        return (
          <div
            key={t.id}
            role="status"
            className={cn(
              "pointer-events-auto flex animate-slide-up items-start gap-3 rounded-lg border bg-card/95 p-3 shadow-lg backdrop-blur ring-1",
              ring,
            )}
          >
            <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", iconColor)} />
            <div className="min-w-0 flex-1 text-sm leading-snug">{t.message}</div>
            <button
              onClick={() => dismiss(t.id)}
              className="rounded text-muted-foreground opacity-60 transition-opacity hover:opacity-100"
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
