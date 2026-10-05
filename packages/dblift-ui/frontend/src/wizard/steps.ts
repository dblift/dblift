import type { JSX } from "react";

import type { Project, RepoStatus, ScratchResult } from "../api/types";
import CommitStep from "../components/wizard/CommitStep";
import DescribeStep from "../components/wizard/DescribeStep";
import PublishStep from "../components/wizard/PublishStep";
import TestStep from "../components/wizard/TestStep";
import WriteStep from "../components/wizard/WriteStep";

export type Outcome = "passed" | "failed" | "skipped";

/** What the steps fill in as the developer goes. */
export interface WizardData {
  description: string;
  branch: { create: boolean; name: string };
  /** The files created for this change, once they exist. */
  scripts: { migration: string; undo: string | null } | null;
  test: { outcome: Outcome | null; result: ScratchResult | null };
  committed: boolean;
  published: boolean;
  /** The developer went past the editors with both scripts saved. */
  written: boolean;
  /** The editors hold edits not saved yet. */
  unsaved: boolean;
  /** Work a step started that goes on even if the wizard closes, so it cannot close: what it says meanwhile. */
  busy: string | null;
}

export type Update = Partial<WizardData> | ((current: WizardData) => Partial<WizardData>);

/** Everything the steps share. */
export interface WizardContext extends WizardData {
  project: Project;
  repo: RepoStatus | undefined;
  /** Merge *partial* in; a function gets the data as it is then, for a change built on a part of it. */
  update(partial: Update): void;
  /** Files or git state may have changed: the view behind reads them again. */
  changed(): void;
}

export interface StepProps {
  context: WizardContext;
  onNext(): void;
  onBack(): void;
  /** The last step shown: its "Next" finishes the wizard. */
  last: boolean;
}

export interface WizardStep {
  id: string;
  title: string;
  Component: (props: StepProps) => JSX.Element;
  available(context: WizardContext): boolean;
  done(context: WizardContext): boolean;
}

export const START: WizardData = {
  description: "",
  branch: { create: false, name: "feature/change" },
  scripts: null,
  test: { outcome: null, result: null },
  committed: false,
  published: false,
  written: false,
  unsaved: false,
  busy: null,
};

const always = () => true;
// Outside a git repository the wizard ends after the test.
const inRepository = (context: WizardContext) => context.repo?.repository === true;

/** The wizard's steps, in order; the shell shows those available and knows none by name. */
export const STEPS: WizardStep[] = [
  { id: "describe", title: "Describe", Component: DescribeStep, available: always, done: (c) => c.scripts !== null },
  { id: "write", title: "Write", Component: WriteStep, available: always, done: (c) => c.written && !c.unsaved },
  { id: "test", title: "Test", Component: TestStep, available: always, done: (c) => c.test.outcome !== null },
  { id: "commit", title: "Commit", Component: CommitStep, available: inRepository, done: (c) => c.committed },
  { id: "publish", title: "Publish", Component: PublishStep, available: inRepository, done: (c) => c.published },
];
