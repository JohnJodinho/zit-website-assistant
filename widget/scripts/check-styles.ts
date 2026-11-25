import { readdir, readFile } from "node:fs/promises";
import { basename, join, relative } from "node:path";

const sourceRoot = join(process.cwd(), "src");
const violations: string[] = [];
const requiredLayoutContent = [
  [join(sourceRoot, "styles", "tokens.css"), "--panel-width: 25rem", "--panel-height: 40rem", "--safe-top"],
  [join(sourceRoot, "loader", "loader.css"), "var(--panel-width)", "var(--panel-height)", "100dvh"],
  [join(sourceRoot, "styles", "components.css"), "100dvh", "var(--safe-top)", "var(--safe-bottom)"],
] as const;

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

function checkTypeScript(path: string, source: string): void {
  if (/(?:#[\da-f]{3,8}\b|(?:rgb|hsl)\s*\()/i.test(source)) {
    violations.push(`${relative(process.cwd(), path)} contains a hard-coded color.`);
  }
  if (/\b\d+(?:\.\d+)?(?:px|rem)\b/i.test(source)) {
    violations.push(`${relative(process.cwd(), path)} contains a CSS unit literal.`);
  }
  if (/\b[a-zA-Z_-]+-\[[^\]]+\]/.test(source)) {
    violations.push(`${relative(process.cwd(), path)} contains a Tailwind arbitrary value.`);
  }
  if (/\bstyle\s*=/.test(source)) {
    violations.push(`${relative(process.cwd(), path)} contains a style prop.`);
  }
}

function checkCss(path: string, source: string): void {
  if (path.endsWith("tokens.css")) return;
  if (/:root[^{}]*\{[^}]*--[\w-]+\s*:/s.test(source)) {
    violations.push(`${relative(process.cwd(), path)} defines root CSS variables outside tokens.css.`);
  }
}

function checkLayoutSafety(files: string[]): void {
  checkRequiredLayoutContent(files);
  checkPanelDimensions();
}

function checkRequiredLayoutContent(files: string[]): void {
  for (const [path, ...needles] of requiredLayoutContent) {
    const source = files.find((file) => file === path);
    if (!source) {
      violations.push(`${relative(process.cwd(), path)} is missing.`);
      continue;
    }
    const contents = readFileSyncCache.get(source);
    for (const needle of needles) {
      if (!contents?.includes(needle)) {
        violations.push(`${relative(process.cwd(), path)} must include ${needle}.`);
      }
    }
  }
}

function checkPanelDimensions(): void {
  const appStylesPath = join(sourceRoot, "styles", "components.css");
  const componentStyles = readFileSyncCache.get(appStylesPath) ?? "";
  const chatPanel = /\.chat-panel\s*\{([^}]*)\}/s.exec(componentStyles)?.[1] ?? "";
  if (!chatPanel || !/width:\s*100%/.test(chatPanel) || /(?:width|height):\s*[^;]*(?:px|rem)/.test(chatPanel)) {
    violations.push("The chat panel must size itself from its host, not fixed dimensions.");
  }
}

const readFileSyncCache = new Map<string, string>();
const files = await listFiles(sourceRoot);
for (const path of files) {
  const contents = await readFile(path, "utf8");
  readFileSyncCache.set(path, contents);
  if (/\.(?:ts|tsx)$/.test(path) && basename(path) !== "cssVariables.ts") {
    checkTypeScript(path, contents);
  }
  if (path.endsWith(".css")) checkCss(path, contents);
}
checkLayoutSafety(files);

if (violations.length > 0) {
  console.error("FAIL: style and layout rules");
  for (const violation of violations) console.error(`- ${violation}`);
  process.exitCode = 1;
} else {
  console.log("PASS: style and layout rules");
}
