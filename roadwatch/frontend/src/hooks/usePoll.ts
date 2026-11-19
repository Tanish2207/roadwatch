import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";

interface PollState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/** Polls an API endpoint on an interval; used for health/status in the top bar. */
export function usePoll<T>(path: string, intervalMs = 5000): PollState<T> & { refresh: () => void } {
  const [state, setState] = useState<PollState<T>>({ data: null, error: null, loading: true });
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get<T>(path);
      setState({ data, error: null, loading: false });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Unknown error";
      setState((prev) => ({ data: prev.data, error: message, loading: false }));
    }
  }, [path]);

  useEffect(() => {
    void load();
    timer.current = window.setInterval(() => void load(), intervalMs);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
  }, [load, intervalMs]);

  return { ...state, refresh: load };
}
