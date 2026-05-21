import { cn } from "@/lib/utils";

interface Props {
  size?: number;
  className?: string;
  /** When true, paints the hexagon with the brand gradient; otherwise inherits currentColor. */
  gradient?: boolean;
}

export function Logo({ size = 24, className, gradient = true }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={cn("shrink-0", className)}
      aria-hidden
    >
      <defs>
        <linearGradient id="cagentGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="hsl(213 94% 65%)" />
          <stop offset="100%" stopColor="hsl(262 83% 70%)" />
        </linearGradient>
      </defs>
      <path
        d="M16 2 L28 9 L28 23 L16 30 L4 23 L4 9 Z"
        fill={gradient ? "url(#cagentGrad)" : "currentColor"}
        opacity={gradient ? 1 : 0.95}
      />
      <path
        d="M11.5 13.5 L16 11 L20.5 13.5 L20.5 18.5 L16 21 L11.5 18.5 Z"
        fill="hsl(0 0% 100% / 0.92)"
      />
    </svg>
  );
}

export function AssistantAvatar({ size = 28 }: { size?: number }) {
  return (
    <div
      style={{ width: size, height: size }}
      className="flex shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-[hsl(213_94%_60%)] to-[hsl(262_83%_64%)] text-white shadow-sm"
    >
      <Logo size={Math.round(size * 0.62)} gradient={false} />
    </div>
  );
}
