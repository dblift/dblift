import { type FormEvent, useEffect, useId, useRef, useState } from "react";

import { createBranch } from "../../api/git";
import { createScripts } from "../../api/scripts";
import { useRepo } from "../../git/useRepo";
import { firstLine, slug } from "../../wizard/slug";
import type { StepProps } from "../../wizard/steps";

// On these, a change is usually made on a branch of its own.
const MAIN_LINES = new Set(["main", "master", "develop"]);

/** What the change does, an optional branch for it, then its migration and undo script. */
export default function DescribeStep({ context, onNext, last }: StepProps) {
  const { project, repo, description, branch, scripts, update, changed } = context;
  const git = useRepo(project.id, changed);
  const hint = useId();
  const inRepo = repo?.repository === true;
  // The branch name follows the description's first line, as the scripts do, until the developer types one.
  const [named, setNamed] = useState(false);
  // The branch this step created: a retry after a refused script does not create it again.
  const [made, setMade] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ticked by default on a main line, once the repository is known.
  const decided = useRef(false);
  useEffect(() => {
    if (decided.current || !repo) {
      return;
    }
    decided.current = true;
    if (repo.repository && !scripts) {
      const create = !repo.detached && MAIN_LINES.has(repo.branch ?? "");
      update((current) => ({ branch: { ...current.branch, create } }));
    }
  }, [repo]);

  const created = scripts !== null;
  const branchFixed = created || made !== null;
  const wantsBranch = inRepo && branch.create;
  const ready = description.trim() !== "" && (!wantsBranch || branch.name.trim() !== "") && !busy && !git.busy;

  // Built on the branch as it is when applied: a change of the box landing just before is kept.
  const describe = (text: string) =>
    update((current) => ({ description: text, ...(named ? {} : { branch: { ...current.branch, name: `feature/${slug(firstLine(text))}` } }) }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (created) {
      onNext();
      return;
    }
    if (!ready) {
      return;
    }
    setBusy(true);
    setError(null);
    git.dismissError();
    // The branch comes first, so that the new files are made on it.
    let branchMade = made;
    const name = branch.name.trim();
    if (wantsBranch && made === null && repo?.branch !== name) {
      if (!(await git.act(() => createBranch(project.id, name), true))) {
        setBusy(false);
        return;
      }
      branchMade = name;
      setMade(name);
    }
    try {
      const { created: names } = await createScripts(project.id, { kind: "versioned", language: "sql", description: firstLine(description) });
      update({ scripts: { migration: names[0], undo: names[1] ?? null } });
      changed();
      onNext();
    } catch (failure) {
      const reason = (failure as Error).message;
      setError(branchMade ? `The branch ${branchMade} was created, but the scripts were not: ${reason}` : reason);
    } finally {
      setBusy(false);
    }
  };

  const refusal = error ?? git.error;
  return (
    <form className="wizard__form" onSubmit={(e) => void submit(e)}>
      <label className="field">
        What does this change do?
        <textarea
          data-autofocus
          className="wizard__description"
          rows={3}
          required
          readOnly={created}
          aria-describedby={hint}
          placeholder="Add an invoices table"
          value={description}
          onChange={(e) => describe(e.target.value)}
        />
      </label>
      <p className="dialog__hint" id={hint}>
        {inRepo ? "The first line names the scripts, the commit and the pull request." : "The first line names the scripts."}
      </p>

      {inRepo && (
        <div className="wizard__branch">
          <label className="check">
            <input
              type="checkbox"
              checked={branch.create}
              disabled={branchFixed}
              onChange={(e) => {
                const create = e.target.checked;
                update((current) => ({ branch: { ...current.branch, create } }));
              }}
            />
            Create a branch
          </label>
          {branch.create && (
            <label className="field">
              Branch name
              <input
                className="mono"
                required
                readOnly={branchFixed}
                value={branch.name}
                onChange={(e) => {
                  setNamed(true);
                  const name = e.target.value;
                  update((current) => ({ branch: { ...current.branch, name } }));
                }}
              />
            </label>
          )}
        </div>
      )}

      {created && scripts && (
        <p className="wizard__created">
          Created <span className="mono">{scripts.migration}</span>
          {scripts.undo && (
            <>
              {" "}
              and <span className="mono">{scripts.undo}</span>
            </>
          )}
          .
        </p>
      )}
      {refusal && (
        <p className="error-text" role="alert">
          {refusal}
        </p>
      )}

      <div className="wizard__actions">
        <button className="button button--primary" disabled={!created && !ready}>
          {last ? "Finish" : "Next"}
        </button>
      </div>
    </form>
  );
}
