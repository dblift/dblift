import type { Migration } from "../api/types";
import { railFill, stateInfo } from "../status/model";

export default function Rail({ migrations }: { migrations: Migration[] }) {
  const firstPending = migrations.findIndex((m) => m.status === "PENDING");
  return (
    <div className="rail-scroll">
      <div className="rail">
        <div className="rail__track" />
        <div className="rail__fill" style={{ width: `${railFill(migrations) * 100}%` }} />
        <ol className="rail__nodes" aria-label="Migration timeline">
          {migrations.map((migration, index) => {
            const { label, tone, applied } = stateInfo(migration.status);
            const classes = [
              "rail__node",
              `rail__node--${tone}`,
              applied ? "rail__node--applied" : "",
              migration.status === "RUNNING" ? "rail__node--running" : "",
              index === firstPending ? "rail__node--next" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <li key={migration.script} className={classes}>
                <span className="rail__dot" aria-hidden="true" />
                <span className="rail__version mono">{migration.version}</span>
                <span className="rail__state">{label}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
