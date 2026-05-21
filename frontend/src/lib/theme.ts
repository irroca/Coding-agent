import { useEffect, useState, useCallback } from "react";

export type Theme = "dark" | "light" | "system";

const KEY = "coding-agent-theme";

function applyTheme(theme: Theme) {
  const dark =
    theme === "dark" ||
    (theme === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function useTheme(): {
  theme: Theme;
  setTheme: (t: Theme) => void;
  resolved: "dark" | "light";
} {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === "undefined") return "system";
    return (localStorage.getItem(KEY) as Theme | null) ?? "system";
  });
  const [resolved, setResolved] = useState<"dark" | "light">(() => {
    if (typeof document === "undefined") return "dark";
    return document.documentElement.classList.contains("dark") ? "dark" : "light";
  });

  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem(KEY, t);
    applyTheme(t);
    setThemeState(t);
    setResolved(
      document.documentElement.classList.contains("dark") ? "dark" : "light",
    );
  }, []);

  // Follow system changes when in "system" mode.
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      applyTheme("system");
      setResolved(mq.matches ? "dark" : "light");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  return { theme, setTheme, resolved };
}
