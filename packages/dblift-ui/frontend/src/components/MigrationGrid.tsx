import type { Migration } from "../api/types";
import StatePill from "./StatePill";

const readable = (description: string) => description.replaceAll("_", " ");

export default function MigrationGrid({ migrations }: { migrations: Migration[] }) {
  return (
    <div className="grid-scroll">
      <table className="grid" aria-label="Migrations">
        <thead>
          <tr>
            <th scope="col">Version</th>
            <th scope="col">Description</th>
            <th scope="col">State</th>
            <th scope="col">Installed</th>
            <th scope="col">Duration</th>
          </tr>
        </thead>
        <tbody>
          {migrations.map((migration, index) => {
            const ran = migration.status !== "PENDING";
            return (
              <tr key={migration.script} className="rise" style={{ "--order": index } as React.CSSProperties}>
                <td className="mono">{migration.version}</td>
                <td className="grid__description" title={migration.script}>
                  {readable(migration.description)}
                </td>
                <td>
                  <StatePill status={migration.status} />
                </td>
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
