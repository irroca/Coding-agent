import { create } from "zustand";
import type {
  ClientMessage,
  ServerMessage,
  SessionMessageSnapshot,
  SessionSummary,
  ToolCall,
  ToolResult,
  Usage,
  WorkspaceInfo,
} from "./types";

// In-memory view of one streaming assistant turn that hasn't been committed
// to ``messages`` yet. The backend will eventually send a fresh
// ``session_state`` whose last message contains the same text, but we want
// the UI to render character-by-character while the stream is in progress.
export interface StreamingTurn {
  text: string;
  toolCalls: Record<string, ToolCall>; // by call_id, ordered insertion preserved
  toolResults: Record<string, ToolResult>; // by call_id
  callOrder: string[]; // preserved tool-call order
  done: boolean;
}

export interface PendingConfirm {
  request_id: string;
  tool_name: string;
  summary: string;
  diff_preview: string | null;
}

export interface Toast {
  id: string;
  kind: "info" | "success" | "warning" | "error";
  message: string;
  /** ms; undefined = sticky */
  duration?: number;
}

interface AppConfig {
  provider: string;
  model: string | null;
  workspace: string;
  supports_prompt_cache: boolean;
  version: string;
}

interface State {
  // connection
  connected: boolean;
  // session
  sessionId: string | null;
  workspace: string | null;
  provider: string | null;
  model: string | null;
  messages: SessionMessageSnapshot[];
  usage: Usage;
  autoApproved: string[];
  // streaming
  streaming: StreamingTurn | null;
  // sidebar
  sessions: SessionSummary[];
  workspaces: WorkspaceInfo[];
  currentWorkspace: string | null;
  // modal
  pendingConfirm: PendingConfirm | null;
  // toasts
  toasts: Toast[];
  // config
  appConfig: AppConfig | null;
  // command palette
  commandPaletteOpen: boolean;

  // actions
  setConnected: (b: boolean) => void;
  ingest: (msg: ServerMessage) => void;
  setSendFn: (send: (m: ClientMessage) => void) => void;
  setAppConfig: (c: AppConfig) => void;
  dismissConfirm: () => void;
  toast: (t: Omit<Toast, "id">) => void;
  dismissToast: (id: string) => void;
  setCommandPaletteOpen: (b: boolean) => void;
  send: (m: ClientMessage) => void;
}

const emptyUsage: Usage = {
  prompt_tokens: 0,
  completion_tokens: 0,
  cached_prompt_tokens: 0,
  cache_creation_tokens: 0,
};

let toastSeq = 0;
const nextToastId = () => {
  toastSeq += 1;
  return `t${Date.now()}-${toastSeq}`;
};

export const useStore = create<State>((set, get) => ({
  connected: false,
  sessionId: null,
  workspace: null,
  provider: null,
  model: null,
  messages: [],
  usage: emptyUsage,
  autoApproved: [],
  streaming: null,
  sessions: [],
  workspaces: [],
  currentWorkspace: null,
  pendingConfirm: null,
  toasts: [],
  appConfig: null,
  commandPaletteOpen: false,

  setConnected: (b) => set({ connected: b }),

  setSendFn: (fn) => set({ send: fn }),

  setAppConfig: (c) => set({ appConfig: c }),

  dismissConfirm: () => set({ pendingConfirm: null }),

  setCommandPaletteOpen: (b) => set({ commandPaletteOpen: b }),

  toast: (t) => {
    const id = nextToastId();
    const toast: Toast = { id, duration: 4500, ...t };
    set({ toasts: [...get().toasts, toast] });
    if (toast.duration) {
      const d = toast.duration;
      setTimeout(() => get().dismissToast(id), d);
    }
  },

  dismissToast: (id) =>
    set({ toasts: get().toasts.filter((t) => t.id !== id) }),

  // Default no-op send; overwritten once WebSocket connects.
  send: (_m) => {
    /* not yet connected */
  },

  ingest: (msg) => {
    const s = get();
    switch (msg.type) {
      case "text_delta": {
        const cur =
          s.streaming ?? {
            text: "",
            toolCalls: {},
            toolResults: {},
            callOrder: [],
            done: false,
          };
        set({ streaming: { ...cur, text: cur.text + msg.text } });
        break;
      }
      case "tool_start": {
        const cur =
          s.streaming ?? {
            text: "",
            toolCalls: {},
            toolResults: {},
            callOrder: [],
            done: false,
          };
        if (!cur.toolCalls[msg.tool_call.id]) {
          cur.callOrder.push(msg.tool_call.id);
        }
        set({
          streaming: {
            ...cur,
            toolCalls: { ...cur.toolCalls, [msg.tool_call.id]: msg.tool_call },
          },
        });
        break;
      }
      case "tool_result": {
        const cur =
          s.streaming ?? {
            text: "",
            toolCalls: {},
            toolResults: {},
            callOrder: [],
            done: false,
          };
        set({
          streaming: {
            ...cur,
            toolResults: { ...cur.toolResults, [msg.tool_result.call_id]: msg.tool_result },
          },
        });
        break;
      }
      case "usage": {
        set({ usage: msg.usage });
        break;
      }
      case "turn_end": {
        // Backend will follow with a fresh session_state; we just mark done.
        const cur = s.streaming;
        if (cur) set({ streaming: { ...cur, done: true } });
        break;
      }
      case "error": {
        get().toast({ kind: "error", message: msg.error, duration: 7000 });
        break;
      }
      case "confirm_request": {
        set({
          pendingConfirm: {
            request_id: msg.request_id,
            tool_name: msg.tool_name,
            summary: msg.summary,
            diff_preview: msg.diff_preview,
          },
        });
        break;
      }
      case "session_state": {
        set({
          sessionId: msg.session_id,
          workspace: msg.workspace,
          provider: msg.provider,
          model: msg.model,
          messages: msg.messages,
          usage: msg.usage,
          autoApproved: msg.auto_approved,
          // Clear streaming once the canonical snapshot arrives.
          streaming: null,
        });
        break;
      }
      case "session_list": {
        set({ sessions: msg.sessions });
        break;
      }
      case "workspace_list": {
        set({ workspaces: msg.recent, currentWorkspace: msg.current });
        break;
      }
      case "ack": {
        // No UI state change; could surface in dev console.
        break;
      }
      case "server_error": {
        get().toast({ kind: "warning", message: msg.message, duration: 6000 });
        break;
      }
    }
  },
}));
