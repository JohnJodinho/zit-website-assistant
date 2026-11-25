import { spawn } from "node:child_process";

const checks = [
  ["typecheck", "Strict TypeScript check"],
  ["lint", "ESLint and accessibility rules"],
  ["stylecheck", "Style and layout rules"],
  ["test", "Vitest and jsdom tests"],
  ["secretcheck", "Secret scan"],
  ["build", "Production app and loader build"],
  ["sizecheck", "Gzip size budgets"],
  ["mockcheck", "Mock-code production exclusion"],
] as const;

async function runCheck(script: string, label: string): Promise<boolean> {
  console.log(`\n${label}:`);
  const executable = process.platform === "win32" ? "npm.cmd" : "npm";
  const child = spawn(executable, ["run", script], {
    cwd: process.cwd(),
    shell: process.platform === "win32",
    stdio: "inherit",
  });
  const code = await new Promise<number>((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (exitCode) => resolve(exitCode ?? 1));
  });
  console.log(`${code === 0 ? "PASS" : "FAIL"}: ${label}`);
  return code === 0;
}

let failed = false;
for (const [script, label] of checks) {
  const passed = await runCheck(script, label);
  if (!passed) failed = true;
}
if (failed) process.exitCode = 1;
