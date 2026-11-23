/** SQLite from Node's own node:sqlite (Node 22.13 and later): nothing to install or build. Node marks it experimental and
 *  says so on stderr; that one warning is left out here, every other warning still shows. */
const emit = process.emitWarning.bind(process) as (...a: unknown[]) => void;
process.emitWarning = ((warning: unknown, ...rest: unknown[]) => {
  if (String((warning as Error)?.message ?? warning).includes("SQLite is an experimental feature")) return;
  emit(warning, ...rest);
}) as typeof process.emitWarning;
export const { DatabaseSync } = await import("node:sqlite");
export type Database = InstanceType<typeof DatabaseSync>;
