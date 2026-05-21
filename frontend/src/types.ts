// Mirrors src/coding_agent/web/protocol.py. Keep in sync.

export type Role = "system" | "user" | "assistant" | "tool";

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  cached_prompt_tokens: number;
  cache_creation_tokens: number;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolResult {
  call_id: string;
  tool: string;
  ok: boolean;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface SessionMessageSnapshot {
  role: Role;
  content: string;
  reasoning_content: string | null;
  tool_calls: ToolCall[];
  tool_results: ToolResult[];
  created_at: string;
}

export interface SessionSummary {
  id: string;
  created_at: string;
  title: string;
  message_count: number;
}

export interface WorkspaceInfo {
  path: string;
  last_used: string | null;
}

// ── Server → Client ────────────────────────────────────────────

export type ServerMessage =
  | { type: "text_delta"; text: string }
  | { type: "tool_start"; tool_call: ToolCall }
  | { type: "tool_result"; tool_result: ToolResult }
  | { type: "usage"; usage: Usage }
  | { type: "turn_end"; finish_reason: string | null }
  | { type: "error"; error: string }
  | {
      type: "confirm_request";
      request_id: string;
      tool_name: string;
      summary: string;
      diff_preview: string | null;
    }
  | {
      type: "session_state";
      session_id: string;
      workspace: string;
      provider: string;
      model: string;
      messages: SessionMessageSnapshot[];
      usage: Usage;
      created_at: string;
      auto_approved: string[];
    }
  | { type: "session_list"; sessions: SessionSummary[] }
  | { type: "workspace_list"; current: string; recent: WorkspaceInfo[] }
  | { type: "ack"; of: string; detail: Record<string, unknown> }
  | { type: "server_error"; message: string; recoverable: boolean };

// ── Client → Server ────────────────────────────────────────────

export type ClientMessage =
  | { type: "submit"; text: string }
  | { type: "cancel" }
  | { type: "confirm_response"; request_id: string; approved: boolean; always: boolean }
  | { type: "attach_session"; session_id: string | null; workspace: string | null }
  | { type: "delete_session"; session_id: string }
  | { type: "list_sessions" }
  | { type: "list_workspaces" };
