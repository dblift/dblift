import { type ReactNode, useEffect, useId, useRef, useState } from "react";

interface Props {
  title: string;
  onClose: () => void;
  /** A wider panel, for a form with a side pane. */
  wide?: boolean;
  /** While set, the dialog cannot be closed, and says why. */
  busy?: string | null;
  children: ReactNode;
}

const FOCUSABLE =
  "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex='-1'])";

export default function Dialog({ title, onClose, wide = false, busy = null, children }: Props) {
  const heading = useId();
  const box = useRef<HTMLDivElement>(null);
  // Read while rendering: a child may take focus before this dialog's effects run.
  const [opener] = useState(() => (document.activeElement instanceof HTMLElement ? document.activeElement : null));

  // The control marked data-autofocus takes focus on open, unless a child took it already;
  // focus goes back where it was on close.
  useEffect(() => {
    if (box.current && !box.current.contains(document.activeElement)) {
      (box.current.querySelector<HTMLElement>("[data-autofocus]") ?? box.current).focus();
    }
    return () => opener?.focus();
  }, [opener]);

  // Escape closes; Tab and Shift+Tab cycle through the dialog's controls only.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!busy) {
          onClose();
        }
        return;
      }
      if (event.key !== "Tab" || !box.current) {
        return;
      }
      // A control inside a hidden part (a step not shown) cannot take focus: it does not count.
      const controls = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((control) => !control.closest("[hidden]"));
      if (controls.length === 0) {
        return;
      }
      const head = controls[0];
      const tail = controls[controls.length - 1];
      const inside = box.current.contains(document.activeElement);
      if (event.shiftKey && (!inside || document.activeElement === head)) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && (!inside || document.activeElement === tail)) {
        event.preventDefault();
        head.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  return (
    <div className="dialog-scrim">
      <div
        ref={box}
        className={wide ? "dialog dialog--wide panel" : "dialog panel"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={heading}
        tabIndex={-1}
      >
        <header className="dialog__head">
          <h2 id={heading}>{title}</h2>
          {busy && <span className="dialog__busy">{busy}</span>}
          <button className="button button--quiet" disabled={busy !== null} onClick={onClose}>
            Close
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
