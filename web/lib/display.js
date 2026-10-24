/** Shared display helpers — keep horse names / printed words ALL CAPS app-wide. */

export function horseCaps(value) {
  if (value == null || value === "") return "";
  return String(value).trim().toUpperCase();
}

/** Mating / hypofoal title: `CURLIN × STORMY WELCOME (2006)`. */
export function matingCaps(sire, dam, foalName) {
  if (foalName) {
    return horseCaps(String(foalName).replace(/\s*[x×]\s*/i, " × "));
  }
  const left = horseCaps(sire);
  const right = horseCaps(dam);
  if (left && right) return `${left} × ${right}`;
  return left || right || "";
}
