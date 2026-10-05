import type { Migration, Script } from "../api/types";
import { versionLabel } from "../status/model";
import StatePill from "./StatePill";

const readable = (description: string) => description.replaceAll("_", " ");

interface Props {
  migrations: Migration[];
  scripts: Script[];
  openScript: string | null;
  onOpen: (script: string) => void;
}

export default function MigrationGrid({ migrations, scripts, openScript, onOpen }: Props) {
  const withUndo = new Set(scripts.filter((s) => s.has_undo).map((s) => s.name));
  const onDisk = new Set(scripts.map((s) => s.name));
  // Which of a migration's files are not committed as they are, and their git state.
  const changes = new Map(
    scripts
      .filter((s) => s.change || s.undo_change)
      .map((s) => [
        s.name,
        [s.change && `Migration: ${s.change}`, s.undo_change && `Undo script: ${s.undo_change}`].filter(Boolean).join("; "),
      ]),
  );
  return (
    <div className="grid-scroll">
      <table className="grid" aria-label="Migrations">
        <thead>
          <tr>
            <th scope="col">Version</th>
            <th scope="col">Description</th>
            <th scope="col">State</th>
            <th scope="col">Undo</th>
            <th scope="col">Installed</th>
            <th scope="col">Duration</th>
          </tr>
        </thead>
        <tbody>
          {migrations.map((migration, index) => {
            const ran = migration.status !== "PENDING";
            return (
              <tr
                key={migration.script}
                className={migration.script === openScript ? "rise grid__row--open" : "rise"}
                style={{ "--order": index } as React.CSSProperties}
              >
                <td className="mono">
                  {onDisk.has(migration.script) ? (
                    <button className="grid__open" aria-label={`Open ${migration.script}`} onClick={() => onOpen(migration.script)}>
                      {versionLabel(migration)}
                    </button>
                  ) : (
                    versionLabel(migration)
                  )}
                </td>
                <td className="grid__description" title={migration.script}>
                  {readable(migration.description)}
                  {changes.has(migration.script) && (
                    <span className="chip grid__change" title={changes.get(migration.script)}>
                      Uncommitted
                    </span>
                  )}
                </td>
                <td>
                  <StatePill status={migration.status} />
                </td>
                <td>{withUndo.has(migration.script) ? "Yes" : "—"}</td>
                <td className="mono">{(ran && migration.installed_on) || "—"}</td>
                <td className="mono">{ran ? `${migration.execution_time} ms` : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
