import { type FormEvent, useEffect, useId, useRef, useState } from "react";

import type { Branch, RepoStatus } from "../api/types";

interface Props {
  repo: RepoStatus;
  /** True while a git action runs. */
  busy: boolean;
  /** Why the last git action was refused, until dismissed. */
  error: string | null;
  /** True while a database change or the SQL preview runs on the project. */
  locked: boolean;
  loadBranches: () => Promise<Branch[]>;
  onSwitch: (name: string) => void;
  onCreate: (name: string) => void;
  onFetch: () => void;
  onPull: () => void;
  onPush: () => void;
  onCommit: () => void;
  onDismissError: () => void;
}

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** The project's branch in the header, with a menu of the git actions. */
export default function BranchChip({
  repo, busy, error, locked, loadBranches, onSwitch, onCreate, onFetch, onPull, onPush, onCommit, onDismissError,
}: Props) {
  const menuId = useId();
  const countsId = useId();
  const [open, setOpen] = useState(false);
  const [branches, setBranches] = useState<Branch[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [newName, setNewName] = useState("");
  const chip = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);

  const detached = repo.detached || !repo.branch;
  const name = detached ? "detached" : (repo.branch ?? "");
  const files = repo.files ?? [];
  const ahead = repo.ahead ?? 0;
  const behind = repo.behind ?? 0;
  const upstream = repo.upstream ?? "";
  const blocked = busy || locked;

  // The menu closes as soon as the user clicks anywhere else.
  useEffect(() => {
    if (!open) {
      return;
    }
    const dismiss = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);

  const openMenu = () => {
    setOpen(true);
    setSearch("");
    setNewName("");
    setBranches(null);
    setFailure(null);
    loadBranches().then(setBranches, (reason: Error) => setFailure(reason.message));
  };
  const close = () => {
    setOpen(false);
    chip.current?.focus();
  };
  const run = (action: () => void) => {
    close();
    action();
  };
  const create = (event: FormEvent) => {
    event.preventDefault();
    if (!blocked && newName.trim()) {
      run(() => onCreate(newName.trim()));
    }
  };

  const needle = search.trim().toLowerCase();
  const shown = (branches ?? []).filter((b) => b.name.toLowerCase().includes(needle));
  const local = shown.filter((b) => !b.remote);
  const remote = shown.filter((b) => b.remote);
  const item = (branch: Branch) => (
    <li key={branch.name}>
      {branch.current ? (
        <span className="branch__item branch__item--current mono" aria-current="true">
          {branch.name}
          <span className="branch__tag">current</span>
        </span>
      ) : (
        <button className="branch__item mono" disabled={blocked} onClick={() => run(() => onSwitch(branch.name))}>
          {branch.name}
        </button>
      )}
    </li>
  );

  return (
    <>
      <div
        ref={box}
        className="branch"
        onKeyDown={(event) => {
          if (open && event.key === "Escape") {
            event.stopPropagation();
            close();
          }
        }}
        onBlur={(event) => {
          // Tabbing out of the menu closes it, as a click elsewhere does.
          if (open && event.relatedTarget && !box.current?.contains(event.relatedTarget as Node)) {
            setOpen(false);
          }
        }}
      >
        <button
          ref={chip}
          className="branch__chip"
          aria-label={`Branch ${name}`}
          aria-describedby={countsId}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          aria-busy={busy}
          onClick={() => (open ? setOpen(false) : openMenu())}
        >
          {/* Tells the chip apart from the environment tabs beside it. */}
          <svg className="branch__icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
            <circle cx="4.5" cy="3.5" r="1.75" />
            <circle cx="4.5" cy="12.5" r="1.75" />
            <circle cx="11.5" cy="5" r="1.75" />
            <path d="M4.5 5.25v5.5M11.5 6.75c0 3-7 2.25-7 4" />
          </svg>
          <span className="branch__name mono">{name}</span>
          <span id={countsId} className="branch__counts">
            {files.length > 0 && (
              <span className="branch__changed">
                <span className="branch__dot" aria-hidden="true" />
                {files.length} uncommitted
              </span>
            )}
            {ahead > 0 && <span title={`${plural(ahead, "commit")} to push`}>↑{ahead}</span>}
            {behind > 0 && <span title={`${plural(behind, "commit")} to pull`}>↓{behind}</span>}
            {busy && <span className="branch__working">working…</span>}
          </span>
        </button>

        {open && (
          <div id={menuId} className="branch__menu" role="dialog" aria-label="Branch">
            <input
              type="search"
              className="branch__search"
              aria-label="Search branches"
              placeholder="Search branches"
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {files.length > 0 && (
              <p className="branch__note">{plural(files.length, "uncommitted file")} will come along if git allows it.</p>
            )}
            {locked && <p className="branch__note">A database change is running.</p>}

            <div className="branch__lists">
              {branches === null && !failure && <p className="branch__note">Reading the branches…</p>}
              {failure && <p className="error-text branch__note">The branches could not be read: {failure}</p>}
              {local.length > 0 && (
                <>
                  <p className="branch__group" aria-hidden="true">
                    Local
                  </p>
                  <ul className="branch__list" aria-label="Local branches">
                    {local.map(item)}
                  </ul>
                </>
              )}
              {remote.length > 0 && (
                <>
                  <p className="branch__group" aria-hidden="true">
                    Remote
                  </p>
                  <ul className="branch__list" aria-label="Remote branches">
                    {remote.map(item)}
                  </ul>
                </>
              )}
              {branches !== null && shown.length === 0 && <p className="branch__note">No branch matches.</p>}
            </div>

            <form className="branch__create" onSubmit={create}>
              <label className="field">
                New branch
                <input className="mono" value={newName} onChange={(e) => setNewName(e.target.value)} />
              </label>
              <button className="button" disabled={blocked || !newName.trim()}>
                Create
              </button>
            </form>

            <div className="branch__actions">
              <button className="button" disabled={blocked} onClick={() => run(onFetch)}>
                Fetch
              </button>
              <button className="button" disabled={blocked || detached || !upstream} onClick={() => run(onPull)}>
                {behind > 0 ? `Pull ↓${behind}` : "Pull"}
              </button>
              <button className="button" disabled={blocked || detached || (upstream !== "" && ahead === 0)} onClick={() => run(onPush)}>
                {!upstream ? "Publish branch" : ahead > 0 ? `Push ↑${ahead}` : "Push"}
              </button>
              <button className="button" disabled={blocked || files.length === 0} onClick={() => run(onCommit)}>
                Commit…
              </button>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="branch__error notice notice--error" role="alert">
          <span>{error}</span>
          <button className="button button--quiet" onClick={onDismissError}>
            Dismiss
          </button>
        </div>
      )}
    </>
  );
}
