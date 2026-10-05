interface Props {
  /** A unified diff, as git prints it. */
  diff: string;
}

interface Line {
  text: string;
  kind: "add" | "del" | "hunk" | "context";
}

/**
 * The hunks of a diff, without the file headers. A header line only comes before a file's first
 * hunk: inside a hunk, "--- note" is a removed SQL comment, not a header.
 */
function hunkLines(diff: string): Line[] {
  const lines: Line[] = [];
  let inHunk = false;
  for (const text of diff.replace(/\n$/, "").split("\n")) {
    if (text.startsWith("diff --git ")) {
      inHunk = false;
    } else if (text.startsWith("@@")) {
      inHunk = true;
      lines.push({ text, kind: "hunk" });
    } else if (inHunk) {
      lines.push({ text, kind: text.startsWith("+") ? "add" : text.startsWith("-") ? "del" : "context" });
    }
  }
  return lines;
}

export default function DiffView({ diff }: Props) {
  return (
    // Focusable, so that the keyboard can scroll a long line into view.
    <pre className="diff mono" role="region" aria-label="Changes since the last commit" tabIndex={0}>
      {hunkLines(diff).map((line, index) => (
        <span key={index} className={line.kind === "context" ? "diff-line" : `diff-line diff-${line.kind}`}>
          {line.text}
        </span>
      ))}
    </pre>
  );
}
