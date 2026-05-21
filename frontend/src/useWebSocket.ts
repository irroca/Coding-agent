import { useEffect, useRef } from "react";
import { useStore } from "./store";
import { getTabId } from "./lib/utils";
import type { ClientMessage, ServerMessage } from "./types";

const RECONNECT_DELAY_MS = 1500;

export function useWebSocket() {
  const setConnected = useStore((s) => s.setConnected);
  const ingest = useStore((s) => s.ingest);
  const setSendFn = useStore((s) => s.setSendFn);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;
    let retryTimer: number | null = null;

    const connect = () => {
      const tabId = getTabId();
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/${tabId}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setSendFn((m: ClientMessage) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(m));
          }
        });
        ws.send(JSON.stringify({ type: "list_sessions" }));
        ws.send(JSON.stringify({ type: "list_workspaces" }));
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as ServerMessage;
          ingest(msg);
        } catch (e) {
          console.error("Bad WS message", e, ev.data);
        }
      };

      ws.onerror = (e) => {
        console.warn("ws error", e);
      };

      ws.onclose = () => {
        setConnected(false);
        if (!stopped) {
          retryTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
    };

    connect();

    return () => {
      stopped = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, [setConnected, ingest, setSendFn]);
}
