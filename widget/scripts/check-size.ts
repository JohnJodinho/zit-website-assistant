import { readdir, readFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { basename, join } from "node:path";

async function filesIn(directory: string): Promise<string[]> {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    throw new Error("The production build directory is missing. Run the build step first.");
  }
  const nested = await Promise.all(
    entries.map((entry) => {
      const path = join(directory, entry.name);
      return entry.isDirectory() ? filesIn(path) : [path];
    }),
  );
  return nested.flat();
}

const files = await filesIn(join(process.cwd(), "dist"));
const appJavaScript = files.filter((path) => path.endsWith(".js") && basename(path) !== "loader.js");
const stylesheets = files.filter((path) => path.endsWith(".css"));
const loader = files.find((path) => basename(path) === "loader.js");

async function compressedSize(paths: string[]): Promise<number> {
  const contents = await Promise.all(paths.map((path) => readFile(path)));
  return contents.reduce((total, content) => total + gzipSync(content).byteLength, 0);
}

async function checkBudget(name: string, paths: string[], maxBytes: number): Promise<boolean> {
  const bytes = await compressedSize(paths);
  const kilobytes = (bytes / 1024).toFixed(1);
  const passed = bytes <= maxBytes;
  console.log(`${passed ? "PASS" : "FAIL"}: ${name} gzip ${kilobytes} KB / ${(maxBytes / 1024).toFixed(0)} KB`);
  return passed;
}

if (!loader) throw new Error("dist/loader.js is missing.");

const outcomes = await Promise.all([
  checkBudget("Application JavaScript", appJavaScript, 150 * 1024),
  checkBudget("Application CSS", stylesheets, 25 * 1024),
  checkBudget("Loader JavaScript", [loader], 6 * 1024),
]);

if (outcomes.some((passed) => !passed)) process.exitCode = 1;
