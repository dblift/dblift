import { useCallback, useEffect, useId, useRef, useState } from "react";

import type { Project } from "../../api/types";
import { useRepo } from "../../git/useRepo";
import { START, STEPS, type WizardContext, type WizardData, type WizardStep } from "../../wizard/steps";
import Dialog from "../Dialog";

interface Props {
  project: Project;
  onClose: () => void;
  /** Files or git state may have changed: the view behind reads them again. */
  onChanged: () => void;
  /** The steps to show; the shell knows none of them by name. */
  steps?: WizardStep[];
}

/** A guided change, step by step, in a wide dialog. */
export default function Wizard({ project, onClose, onChanged, steps = STEPS }: Props) {
  const ids = useId();
  const { repo } = useRepo(project.id, onChanged);
  const [data, setData] = useState<WizardData>(START);
  const [wanted, setWanted] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const update = useCallback((partial: Partial<WizardData>) => setData((current) => ({ ...current, ...partial })), []);
  const context: WizardContext = { ...data, project, repo, update, changed: onChanged };

  // A step opens only once every step before it is done: the furthest one reachable bounds the active one.
  const shown = steps.filter((step) => step.available(context));
  const undone = shown.findIndex((step) => !step.done(context));
  const furthest = undone === -1 ? shown.length - 1 : undone;
  const asked = shown.findIndex((step) => step.id === wanted);
  const index = wanted === null ? 0 : asked === -1 ? furthest : Math.min(asked, furthest);
  const active = shown[index];

  // A visited step stays in the page, hidden, so its edits and results survive going back and forth.
  const visited = useRef(new Set<string>());
  visited.current.add(active.id);

  // A step calls onNext after its own work: it acts on the wizard as it is then.
  const latest = useRef(shown);
  latest.current = shown;
  const now = useRef(data);
  now.current = data;
  const next = (id: string) => {
    const list = latest.current;
    const at = list.findIndex((step) => step.id === id);
    if (at === list.length - 1) {
      close();
    } else {
      setWanted(list[at + 1].id);
    }
  };
  const back = (id: string) => {
    const list = latest.current;
    const at = list.findIndex((step) => step.id === id);
    if (at > 0) {
      setWanted(list[at - 1].id);
    }
  };

  // Moving to a step puts focus on its heading.
  const headings = useRef<Record<string, HTMLHeadingElement | null>>({});
  const shownBefore = useRef(active.id);
  useEffect(() => {
    if (shownBefore.current !== active.id) {
      shownBefore.current = active.id;
      headings.current[active.id]?.focus();
    }
  }, [active.id]);

  // The files are on disk once created, so closing asks nothing about them; only unsaved edits are asked about.
  const asker = useRef<HTMLElement | null>(null);
  const finish = () => {
    if (now.current.scripts) {
      onChanged();
    }
    onClose();
  };
  function close() {
    if (asking) {
      keepEditing();
    } else if (now.current.unsaved) {
      asker.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setAsking(true);
    } else {
      finish();
    }
  }
  function keepEditing() {
    setAsking(false);
    asker.current?.focus();
  }

  return (
    <Dialog title="New change" wide onClose={close}>
      <div className="wizard">
        {asking && (
          <div className="wizard__guard">
            <span>Discard the unsaved edits?</span>
            <button className="button button--quiet" autoFocus onClick={keepEditing}>
              Keep editing
            </button>
            <button className="button button--danger" onClick={finish}>
              Discard and close
            </button>
          </div>
        )}

        <nav className="wizard__rail" aria-label="Steps">
          <ol>
            {shown.map((step, i) => {
              const done = step.done(context);
              return (
                <li key={step.id}>
                  <button
                    type="button"
                    className="wizard__stop"
                    aria-current={i === index ? "step" : undefined}
                    disabled={i > furthest}
                    onClick={() => setWanted(step.id)}
                  >
                    <span className={done ? "wizard__mark wizard__mark--done" : "wizard__mark"} aria-hidden="true">
                      {done ? "✓" : i + 1}
                    </span>
                    <span className="wizard__label">{step.title}</span>
                    {done && <span className="visually-hidden">, done</span>}
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>
        <p className="wizard__compact">{`Step ${index + 1} of ${shown.length} — ${active.title}`}</p>

        {shown.map(
          (step, i) =>
            visited.current.has(step.id) && (
              <section key={step.id} className="wizard__step" hidden={step.id !== active.id} aria-labelledby={`${ids}-${step.id}`}>
                <h3
                  id={`${ids}-${step.id}`}
                  className="wizard__title"
                  tabIndex={-1}
                  ref={(node) => {
                    headings.current[step.id] = node;
                  }}
                >
                  {step.title}
                </h3>
                <step.Component context={context} onNext={() => next(step.id)} onBack={() => back(step.id)} last={i === shown.length - 1} />
              </section>
            ),
        )}
      </div>
    </Dialog>
  );
}
