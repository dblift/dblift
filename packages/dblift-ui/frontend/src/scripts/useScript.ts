import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { readScript, saveScript } from "../api/scripts";
import type { ScriptFile } from "../api/types";

type Phase = "idle" | "loading" | "ready" | "missing" | "error";

interface State {
  phase: Phase;
  file: ScriptFile | null;
  content: string;
  saving: boolean;
  error: string | null;
}

const IDLE: State = { phase: "idle", file: null, content: "", saving: false, error: null };

/** Load one script, hold its edited text, and save it on demand. */
export function useScript(projectId: string, name: string | null) {
  const [state, setState] = useState<State>(IDLE);

  useEffect(() => {
    if (!name) {
      setState(IDLE);
      return;
    }
    let current = true;
    setState({ ...IDLE, phase: "loading" });
    readScript(projectId, name)
      .then((file) => {
        if (current) {
          setState({ ...IDLE, phase: "ready", file, content: file.content });
        }
      })
      .catch((failure: Error) => {
        if (current) {
          const missing = failure instanceof ApiError && failure.status === 404;
          setState({ ...IDLE, phase: missing ? "missing" : "error", error: failure.message });
        }
      });
    return () => {
      current = false;
    };
  }, [projectId, name]);

  const edit = useCallback((content: string) => setState((s) => ({ ...s, content })), []);

  const save = useCallback(async (): Promise<boolean> => {
    if (!state.file) {
      return false;
    }
    const { name: target } = state.file;
    const content = state.content;
    setState((s) => ({ ...s, saving: true, error: null }));
    try {
      await saveScript(projectId, target, content);
      setState((s) => (s.file ? { ...s, saving: false, file: { ...s.file, content } } : s));
      return true;
    } catch (failure) {
      setState((s) => ({ ...s, saving: false, error: (failure as Error).message }));
      return false;
    }
  }, [projectId, state.file, state.content]);

  const dirty = state.file !== null && state.content !== state.file.content;
  return { ...state, dirty, edit, save };
}
