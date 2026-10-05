import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import { getRepo } from "../api/git";
import type { RepoStatus } from "../api/types";

/** A project's repository status, and its git verbs run one at a time. */
export function useRepo(projectId: string, onMoved: () => void) {
  const queryClient = useQueryClient();
  // Commits and switches made with another tool show when the user comes back to the window.
  const { data: repo } = useQuery({
    queryKey: ["git", projectId],
    queryFn: () => getRepo(projectId),
    refetchOnWindowFocus: true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = useRef(false);
  const moved = useRef(onMoved);
  moved.current = onMoved;

  /** Run *verb*; *movedFiles* when it may have changed the working tree. False when refused or ignored. */
  const act = useCallback(
    async (verb: () => Promise<RepoStatus>, movedFiles = false): Promise<boolean> => {
      if (running.current) {
        return false;
      }
      running.current = true;
      setBusy(true);
      setError(null);
      try {
        queryClient.setQueryData(["git", projectId], await verb());
        if (movedFiles) {
          moved.current();
        }
        return true;
      } catch (failure) {
        setError((failure as Error).message);
        return false;
      } finally {
        running.current = false;
        setBusy(false);
      }
    },
    [queryClient, projectId],
  );

  const refresh = useCallback(() => void queryClient.invalidateQueries({ queryKey: ["git", projectId] }), [queryClient, projectId]);
  const dismissError = useCallback(() => setError(null), []);

  return { repo, busy, error, act, refresh, dismissError };
}
