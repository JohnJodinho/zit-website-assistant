/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ASSISTANT_API_URL: string;
  readonly VITE_ASSISTANT_WIDGET_URL: string;
  readonly VITE_PARENT_ORIGINS: string;
  readonly VITE_TURNSTILE_SITE_KEY: string;
  readonly VITE_PRIVACY_URL: string;
  readonly VITE_CONTACT_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
