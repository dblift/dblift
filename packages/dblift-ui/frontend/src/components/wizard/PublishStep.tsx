import { useId, useState } from "react";

import { pullRequestLink, pushRepo } from "../../api/git";
import { useRepo } from "../../git/useRepo";
import { pullRequestText } from "../../wizard/pullRequestText";
import type { StepProps } from "../../wizard/steps";

// Only a web page of the repository's host may be linked: never another scheme.
const linkable = (url: string | null): url is string => url !== null && url.startsWith("https://");

/** Push the branch, then offer a pre-filled pull request, or its text to copy. */
export default function PublishStep({ context, onNext, onBack, last }: StepProps) {
  const { project, repo, update, changed } = context;
  const git = useRepo(project.id, changed);
  const ids = useId();
  const [text, setText] = useState<{ title: string; body: string } | null>(null);
  const [link, setLink] = useState<{ url: string | null; branch: string } | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [copied, setCopied] = useState("");
  const detached = !repo || repo.detached === true || !repo.branch;
  const branch = detached ? "" : (repo.branch ?? "");
  const upstream = repo?.upstream ?? "";

  const push = async () => {
    setLinkError(null);
    if (!(await git.act(() => pushRepo(project.id)))) {
      return;
    }
    update({ published: true });
    changed();
    const shown = pullRequestText(context);
    setText(shown);
    setCopied("");
    try {
      const found = await pullRequestLink(project.id, shown.title, shown.body);
      setLink({ url: linkable(found.url) ? found.url : null, branch: found.branch });
    } catch (failure) {
      setLinkError((failure as Error).message);
      setLink({ url: null, branch });
    }
  };

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied("Copied.");
    } catch {
      setCopied("Select the text and copy it with the keyboard.");
    }
  };

  const url = link?.url ?? null;
  return (
    <div className="wizard__publish">
      <p className="wizard__branch-line">
        Branch <span className="mono">{branch || "detached"}</span>
        {upstream && (
          <>
            {" "}
            → <span className="mono">{upstream}</span>
          </>
        )}
      </p>
      {detached ? (
        <p className="dialog__hint">Switch to a branch first.</p>
      ) : (
        !text && (
          <p className="dialog__hint">
            {upstream ? "Push sends this branch's new commits to origin." : "Publish branch creates this branch on origin and sends its commits there."}
          </p>
        )
      )}
      {git.error && (
        <p className="error-text" role="alert">
          {git.error}
        </p>
      )}
      {linkError && (
        <p className="error-text" role="alert">
          The pull request page could not be prepared: {linkError}
        </p>
      )}

      {text && link && (
        <div className="wizard__pr">
          {url ? (
            <>
              <p>
                <a className="button button--primary" href={url} target="_blank" rel="noopener noreferrer">
                  Open the pull request page
                </a>
              </p>
              <p className="dialog__hint">The page opens with this title and description filled in: review them there before creating the pull request.</p>
            </>
          ) : (
            <p>{`Open a pull request for ${link.branch || branch} on your git host, then paste the title and the description there.`}</p>
          )}
          <div className="field">
            <label htmlFor={`${ids}-title`}>Pull request title</label>
            <div className="wizard__copy">
              <input id={`${ids}-title`} readOnly value={text.title} />
              {!url && (
                <button type="button" className="button" aria-label="Copy the title" onClick={() => void copy(text.title)}>
                  Copy
                </button>
              )}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`${ids}-body`}>Pull request description</label>
            <div className="wizard__copy">
              <textarea id={`${ids}-body`} className="wizard__description mono" readOnly rows={10} value={text.body} />
              {!url && (
                <button type="button" className="button" aria-label="Copy the description" onClick={() => void copy(text.body)}>
                  Copy
                </button>
              )}
            </div>
          </div>
          {!url && (
            <p className="wizard__copied" role="status">
              {copied}
            </p>
          )}
        </div>
      )}

      <div className="wizard__actions">
        <button type="button" className="button button--quiet wizard__back" onClick={onBack}>
          Back
        </button>
        <button className={text ? "button" : "button button--primary"} disabled={detached || git.busy} onClick={() => void push()}>
          {upstream ? "Push" : "Publish branch"}
        </button>
        <button className={text && !url ? "button button--primary" : "button"} onClick={onNext}>
          {last ? "Finish" : "Next"}
        </button>
      </div>
    </div>
  );
}
