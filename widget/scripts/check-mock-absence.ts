import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";

const marker = "ZIT_WIDGET_MOCK_BACKEND_MARKER_58978D21";
const forbidden = [marker, "mock_token_"];

async function listFiles(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map((entry) => {
      const path = join(directory, entry.name);
      return entry.isDirectory() ? listFiles(path) : [path];
    }),
  );
  return nested.flat();
}

const buildDirectory = join(process.cwd(), "dist");
const files = await listFiles(buildDirectory);
const failures: string[] = [];
for (const file of files) {
  const contents = await readFile(file);
  const text = contents.toString("utf8");
  if (forbidden.some((value) => text.includes(value))) failures.push(file);
}

if (failures.length > 0) {
  console.error("FAIL: development mock backend found in the production build.");
  for (const file of failures) console.error(`- ${file}`);
  process.exitCode = 1;
} else {
  console.log("PASS: development mock backend is absent from dist/.");
}
