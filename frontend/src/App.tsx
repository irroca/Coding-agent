import { useEffect } from "react";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { ChatView } from "@/components/ChatView";
import { Composer } from "@/components/Composer";
import { PermissionModal } from "@/components/PermissionModal";
import { Toaster } from "@/components/Toaster";
import { CommandPalette } from "@/components/CommandPalette";
import { ConfirmDialogHost } from "@/components/ConfirmDialog";
import { useTheme } from "@/lib/theme";
import { useStore } from "@/store";

export function App() {
  const setAppConfig = useStore((s) => s.setAppConfig);

  // Mount theme hook so it stays subscribed to system changes.
  useTheme();

  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then(setAppConfig)
      .catch(() => undefined);
  }, [setAppConfig]);

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <ChatView />
        <Composer />
      </div>
      <PermissionModal />
      <CommandPalette />
      <ConfirmDialogHost />
      <Toaster />
    </div>
  );
}
