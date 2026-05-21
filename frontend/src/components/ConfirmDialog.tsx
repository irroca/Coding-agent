import { useCallback, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "./Button";

interface State {
  title: string;
  description?: string;
  confirmLabel: string;
  cancelLabel: string;
  destructive: boolean;
  resolve: (ok: boolean) => void;
}

let openDialog: ((state: Omit<State, "resolve">) => Promise<boolean>) | null = null;

/** Imperative confirm helper. Returns a promise that resolves to user's choice. */
export function confirmDialog(opts: {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}): Promise<boolean> {
  if (!openDialog) return Promise.resolve(false);
  return openDialog({
    title: opts.title,
    description: opts.description,
    confirmLabel: opts.confirmLabel ?? "Confirm",
    cancelLabel: opts.cancelLabel ?? "Cancel",
    destructive: opts.destructive ?? false,
  });
}

export function ConfirmDialogHost() {
  const [state, setState] = useState<State | null>(null);

  const open = useCallback((s: Omit<State, "resolve">) => {
    return new Promise<boolean>((resolve) => {
      setState({ ...s, resolve });
    });
  }, []);

  openDialog = open;

  const close = (ok: boolean) => {
    state?.resolve(ok);
    setState(null);
  };

  if (!state) return null;

  return (
    <Dialog.Root open onOpenChange={(o) => !o && close(false)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 animate-overlay-in bg-black/60 backdrop-blur-sm" />
        <Dialog.Content
          onEscapeKeyDown={() => close(false)}
          className="fixed left-1/2 top-1/2 z-50 w-[420px] max-w-[90vw] -translate-x-1/2 -translate-y-1/2 animate-slide-up rounded-lg border bg-card p-5 shadow-2xl focus:outline-none"
        >
          <Dialog.Title className="text-base font-semibold">{state.title}</Dialog.Title>
          {state.description && (
            <Dialog.Description className="mt-1.5 text-sm text-muted-foreground">
              {state.description}
            </Dialog.Description>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => close(false)}>
              {state.cancelLabel}
            </Button>
            <Button
              variant={state.destructive ? "destructive" : "default"}
              onClick={() => close(true)}
              autoFocus
            >
              {state.confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
