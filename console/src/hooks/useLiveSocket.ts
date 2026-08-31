import { useEffect, useRef } from "react";
import { useStore } from "../store";

/**
 * WebSocket with capped exponential backoff.
 *
 * Connection state is surfaced in the header. If the socket drops mid-demo and
 * the screen silently freezes, the system looks broken; if it says
 * "reconnecting" and then recovers, it looks robust.
 */
export function useLiveSocket(sessionId: string | null) {
  const retry = useRef(0);
  const apply = useStore((s) => s.applyMessage);
  const setConn = useStore((s) => s.setConnection);

  useEffect(() => {
    if (!sessionId) {
      setConn("offline");
      return;
    }
    let cancelled = false;
    let sock: WebSocket | null = null;
    let timer: number | undefined;

    const connect = () => {
      if (cancelled) return;
      setConn(retry.current === 0 ? "connecting" : "reconnecting");
      const proto = location.protocol === "https:" ? "wss" : "ws";
      sock = new WebSocket(`${proto}://${location.host}/v1/live?session_id=${sessionId}`);

      sock.onopen = () => {
        retry.current = 0;
        setConn("live");
      };
      sock.onmessage = (e) => {
        try {
          apply(JSON.parse(e.data));
        } catch {
          /* malformed frame; drop it rather than tearing down the socket */
        }
      };
      sock.onclose = () => {
        if (cancelled) return;
        setConn("reconnecting");
        // Capped backoff. A tight reconnect loop during a network blip is worse
        // than a visible "reconnecting" badge.
        const delay = Math.min(700 * 2 ** retry.current++, 12000);
        timer = window.setTimeout(connect, delay);
      };
      sock.onerror = () => sock?.close();
    };

    connect();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      sock?.close();
    };
  }, [sessionId, apply, setConn]);
}
