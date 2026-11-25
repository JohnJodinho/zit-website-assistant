import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";

const root = process.cwd();
const excludedDirectories = new Set([".git", "coverage", "dist", "node_modules"]);
const excludedExtensions = new Set([".png", ".woff", ".woff2"]);
const secretPatterns = [
  /\bAIza[0-9A-Za-z_-]{35}\b/,
  /\bsk-[A-Za-z0-9]{32,}\b/,
  /\bgh[pousr]_[A-Za-z0-9_]{30,}\b/,
  /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/,
  /\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
];

async function listFiles(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map((entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        return excludedDirectories.has(entry.name) ? [] : listFiles(path);
      }
      return [path];
    }),
  );
  return nested.flat();
}

function hasSecretEnvironmentValue(path: string, contents: string): boolean {
  if (!/(?:^|[/\\])\.env(?:\.|$)/.test(path)) return false;
  return contents.split(/\r?\n/).some((line) => {
    const match = /^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)\s*$/.exec(line);
    if (!match) return false;
    const key = match[1];
    const value = match[2];
    return key !== undefined && value !== undefined && !key.startsWith("VITE_") && value.length > 0;
  });
}

const failures: string[] = [];
for (const path of await listFiles(root)) {
  if (excludedExtensions.has(extname(path))) continue;
  if (path.endsWith("package-lock.json")) continue;
  const contents = await readFile(path, "utf8");
  if (secretPatterns.some((pattern) => pattern.test(contents)) || hasSecretEnvironmentValue(path, contents)) {
    failures.push(relative(root, path));
  }
}

if (failures.length > 0) {
  console.error("FAIL: possible private credentials found. Values are intentionally not shown.");
  for (const path of failures) console.error(`- ${path}`);
  process.exitCode = 1;
} else {
  console.log("PASS: no known credentials or private environment values found.");
}
