import { stateInfo } from "../status/model";

export default function StatePill({ status }: { status: string }) {
  const { label, tone, hint } = stateInfo(status);
  return (
    <span className={`pill pill--${tone}`} title={hint}>
      {label}
    </span>
  );
}
