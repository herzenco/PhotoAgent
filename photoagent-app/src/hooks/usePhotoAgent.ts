import { useState, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

interface SidecarOutput {
  stdout: string;
  stderr: string;
  exit_code: number;
}

interface UsePhotoAgentReturn<T> {
  execute: (args: string[]) => Promise<T | null>;
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function usePhotoAgent<T = unknown>(): UsePhotoAgentReturn<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef(false);

  const execute = useCallback(async (args: string[]): Promise<T | null> => {
    setLoading(true);
    setError(null);
    abortRef.current = false;

    try {
      const result = await invoke<SidecarOutput>("run_photoagent", { args });

      if (abortRef.current) return null;

      if (result.exit_code !== 0) {
        const errMsg = result.stderr.trim() || `Process exited with code ${result.exit_code}`;
        setError(errMsg);
        setLoading(false);
        return null;
      }

      const stdout = result.stdout.trim();
      if (!stdout) {
        setError("No output from PhotoAgent");
        setLoading(false);
        return null;
      }
      const parsed = JSON.parse(stdout) as T;
      setData(parsed);
      setLoading(false);
      return parsed;
    } catch (e) {
      if (!abortRef.current) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        setLoading(false);
      }
      return null;
    }
  }, []);

  return { execute, data, loading, error };
}
