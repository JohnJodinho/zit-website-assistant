import { loadEnv, build as viteBuild } from "vite";

type PublicEnvironment = Record<string, string>;

const publicKeys = [
  "VITE_ASSISTANT_API_URL",
  "VITE_ASSISTANT_WIDGET_URL",
  "VITE_PARENT_ORIGINS",
  "VITE_TURNSTILE_SITE_KEY",
  "VITE_PRIVACY_URL",
  "VITE_CONTACT_URL",
] as const;

function getPublicEnvironment(mode: string): PublicEnvironment {
  const example = loadEnv("example", process.cwd(), "VITE_");
  const active = loadEnv(mode, process.cwd(), "VITE_");
  const environment: PublicEnvironment = { ...example, ...active };
  for (const key of publicKeys) {
    const processValue = process.env[key];
    if (processValue !== undefined) environment[key] = processValue;
  }
  return environment;
}

function validateEnvironment(environment: PublicEnvironment): void {
  const apiUrl = environment.VITE_ASSISTANT_API_URL;
  if (!apiUrl) throw new Error("VITE_ASSISTANT_API_URL is required to build the widget.");
  const parsedApiUrl = parseHttpUrl(apiUrl, "VITE_ASSISTANT_API_URL");
  if (parsedApiUrl.username || parsedApiUrl.password || parsedApiUrl.search || parsedApiUrl.hash) {
    throw new Error("VITE_ASSISTANT_API_URL must not contain credentials, a query, or a fragment.");
  }
  const origins = environment.VITE_PARENT_ORIGINS?.split(",").map((value) => value.trim()) ?? [];
  if (origins.length === 0 || origins.some((origin) => !isExactOrigin(origin))) {
    throw new Error("VITE_PARENT_ORIGINS must contain one or more exact HTTP(S) origins.");
  }
}

function parseHttpUrl(value: string, key: string): URL {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${key} must be a valid HTTP(S) URL.`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`${key} must use HTTP or HTTPS.`);
  }
  return url;
}

function isExactOrigin(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      url.origin === value &&
      url.username === "" &&
      url.password === ""
    );
  } catch {
    return false;
  }
}

async function buildWidget(): Promise<void> {
  const mode = process.env.NODE_ENV === "development" ? "development" : "production";
  const environment = getPublicEnvironment(mode);
  validateEnvironment(environment);
  for (const [key, value] of Object.entries(environment)) {
    process.env[key] ??= value;
  }
  await viteBuild({ configFile: "vite.loader.config.ts", mode });
  await viteBuild({ configFile: "vite.config.ts", mode });
}

await buildWidget();
