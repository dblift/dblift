const MAX = 40;

/** A branch-name word for *description*: lower-case ASCII letters and digits joined by "-", never empty. */
export function slug(description: string): string {
  const plain = description.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const words = plain.split(/[^a-z0-9]+/).filter(Boolean).join("-");
  const cut = words.slice(0, MAX).replace(/-+$/, "");
  return cut || "change";
}

/** The first line of *description*: the title of the change. */
export const firstLine = (description: string) => description.trim().split("\n")[0].trim();
