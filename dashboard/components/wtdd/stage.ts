/** The team's status words. Anything depending on unmerged work shows one of these. */
export type Stage =
  | { kind: "exists" }                 // EXISTS on main
  | { kind: "built"; pr: number }      // BUILT, PR #n open, not merged
  | { kind: "building" }               // BUILDING (branch only)
  | { kind: "not_built" };             // NOT BUILT: controls are disabled, never faked

export function stageLabel(s: Stage): string {
  switch (s.kind) {
    case "exists": return "EXISTS on main";
    case "built": return `BUILT · PR #${s.pr}`;
    case "building": return "BUILDING";
    case "not_built": return "NOT BUILT";
  }
}
