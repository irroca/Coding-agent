import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  text: string;
  className?: string;
  label?: string;
  /** Render compact icon-only style. */
  iconOnly?: boolean;
}

export function CopyButton({ text, className, label = "Copy", iconOnly = false }: Props) {
  const [copied, setCopied] = useState(false);

  const onClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // older browsers / non-HTTPS — fall back to a temporary textarea
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        /* ignore */
      }
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };

  return (
    <button
      type="button"
      onClick={onClick}
      title={copied ? "Copied" : label}
      aria-label={copied ? "Copied" : label}
      className={cn(
        "inline-flex items-center gap-1 rounded text-xs text-muted-foreground transition-colors hover:text-foreground",
        iconOnly ? "p-1" : "px-1.5 py-1",
        className,
      )}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-brand-emerald" /> : <Copy className="h-3.5 w-3.5" />}
      {!iconOnly && <span>{copied ? "Copied" : label}</span>}
    </button>
  );
}
