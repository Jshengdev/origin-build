/** The wtdd API this dashboard reads, read on every request (never at build time): WTDD_API, else the dry API on 7960,
 *  which can never reach the dog. The live API, the one that holds the dog, is on 7788. Server-side only. */
export const apiTarget = () => process.env.WTDD_API ?? "http://127.0.0.1:7960";
