import { useQuery } from "@tanstack/react-query";

import { commitFiles } from "../../api/git";
import { listScripts } from "../../api/scripts";
import { changedScriptFiles } from "../../git/changes";
import { useRepo } from "../../git/useRepo";
import { firstLine } from "../../wizard/slug";
import type { StepProps } from "../../wizard/steps";
import CommitForm from "../CommitForm";

/** Commit the change: the repository's changed files, with the wizard's two scripts ticked. */
export default function CommitStep({ context, onNext, onBack, last }: StepProps) {
  const { project, repo, scripts, test, committed, description, update, changed } = context;
  const git = useRepo(project.id, changed);
  const { data: listed, isSuccess } = useQuery({ queryKey: ["scripts", project.id], queryFn: () => listScripts(project.id) });
  const files = repo?.files ?? [];
  // The scripts list holds each migration's exact path and its undo script's, as the commit dialog uses them.
  const mine = (listed ?? []).filter((s) => s.name === scripts?.migration);
  const preselected = changedScriptFiles(files, mine);
  // Said only once the list knows the migration: an older list would not have it yet.
  const nothingLeft = isSuccess && mine.length > 0 && preselected.length === 0;
  const branch = repo?.branch ?? "";

  const commit = async (paths: string[], message: string) => {
    if (await git.act(() => commitFiles(project.id, paths, message))) {
      update({ committed: true });
      changed();
    }
  };

  const back = (
    <button type="button" className="button button--quiet wizard__back" onClick={onBack}>
      Back
    </button>
  );
  const goOn = (label: string, action: () => void) => (
    <div className="wizard__actions">
      {back}
      <button className="button button--primary" onClick={action}>
        {label}
      </button>
    </div>
  );
  const nextLabel = last ? "Finish" : "Next";

  return (
    <div className="wizard__commit">
      {test.outcome === "failed" && (
        <p className="wizard__warning" role="note">
          The scratch test failed.
        </p>
      )}
      {committed ? (
        <>
          <p className="wizard__done">
            <span className="wizard__done-icon" aria-hidden="true">
              ✓
            </span>
            <span>{`The scripts are committed on ${branch}.`}</span>
          </p>
          {goOn(nextLabel, onNext)}
        </>
      ) : nothingLeft ? (
        <>
          <p className="wizard__done">The two scripts have nothing left to commit.</p>
          {goOn(nextLabel, () => {
            update({ committed: true });
            onNext();
          })}
        </>
      ) : (
        // Opened again once the scripts list arrives, so that the two scripts are ticked.
        <CommitForm
          key={preselected.join("\n")}
          className="commit wizard__form"
          files={files}
          preselected={preselected}
          busy={git.busy}
          error={git.error}
          truncated={repo?.truncated}
          message={firstLine(description)}
          onCommit={(paths, message) => void commit(paths, message)}
          actions={back}
        />
      )}
    </div>
  );
}
