import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { sql } from "@codemirror/lang-sql";
import { HighlightStyle, bracketMatching, indentOnInput, syntaxHighlighting } from "@codemirror/language";
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView, drawSelection, highlightActiveLine, keymap, lineNumbers } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";

interface Props {
  value: string;
  language: "sql" | "python";
  label: string;
  readOnly?: boolean;
  onChange: (value: string) => void;
}

// Colours come from the tokens in tokens.css, so the editor follows the theme.
const theme = EditorView.theme(
  {
    "&": { height: "100%", backgroundColor: "var(--surface-inset)", color: "var(--text-code)" },
    ".cm-content": { fontFamily: "var(--font-mono)", fontSize: "13px", caretColor: "var(--accent)" },
    ".cm-gutters": { backgroundColor: "var(--surface-inset)", color: "var(--text-faint)", border: "none" },
    ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "var(--accent-tint)" },
    "&.cm-focused": { outline: "none" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": { backgroundColor: "var(--info-tint)" },
    ".cm-cursor": { borderLeftColor: "var(--accent)" },
  },
  { dark: true },
);

const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.operatorKeyword], color: "var(--info)", fontWeight: "600" },
  { tag: [tags.string, tags.number], color: "var(--warn)" },
  { tag: [tags.typeName, tags.standard(tags.name)], color: "var(--accent)" },
  { tag: tags.comment, color: "var(--text-muted)", fontStyle: "italic" },
]);

const grammar = (language: Props["language"]) => (language === "python" ? python() : sql());
// The accessible name sits on the editable element, where assistive technology and tests find it.
const named = (label: string) => EditorView.contentAttributes.of({ "aria-label": label });

export default function CodeEditor({ value, language, label, readOnly = false, onChange }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const changed = useRef(onChange);
  changed.current = onChange;
  const languageSlot = useRef(new Compartment());
  const readOnlySlot = useRef(new Compartment());
  const labelSlot = useRef(new Compartment());

  useEffect(() => {
    const editor = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          history(),
          drawSelection(),
          indentOnInput(),
          bracketMatching(),
          highlightActiveLine(),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          languageSlot.current.of(grammar(language)),
          readOnlySlot.current.of(EditorState.readOnly.of(readOnly)),
          syntaxHighlighting(highlight),
          theme,
          labelSlot.current.of(named(label)),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              changed.current(update.state.doc.toString());
            }
          }),
        ],
      }),
    });
    view.current = editor;
    return () => editor.destroy();
    // The editor is created once; later changes are applied by the effects below.
  }, []);

  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({
      effects: [
        languageSlot.current.reconfigure(grammar(language)),
        readOnlySlot.current.reconfigure(EditorState.readOnly.of(readOnly)),
        labelSlot.current.reconfigure(named(label)),
      ],
    });
  }, [language, readOnly, label]);

  return <div className="code-editor" ref={host} />;
}
