const files = import.meta.glob<string>("../assets/engines/*.svg", {
  eager: true,
  query: "?url&no-inline",
  import: "default",
});

const LOGOS: Record<string, string> = Object.fromEntries(
  Object.entries(files).map(([path, url]) => [path.split("/").pop()!.replace(".svg", ""), url]),
);

const ALIASES: Record<string, string> = { postgres: "postgresql", mssql: "sqlserver", mongo: "mongodb" };

export function logoFor(engine: string): string {
  const key = engine.toLowerCase();
  return LOGOS[ALIASES[key] ?? key] ?? LOGOS.generic;
}

export default function EngineLogo({ engine, size = 20 }: { engine: string; size?: number }) {
  return <img className="engine-logo" src={logoFor(engine)} alt="" width={size} height={size} />;
}
