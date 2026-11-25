import type { ApiClient } from "../api/client";

export class SessionManager {
  private token: string | null = null;

  get currentToken(): string | null {
    return this.token;
  }

  async getToken(api: ApiClient, turnstileToken?: string): Promise<string> {
    if (this.token) return this.token;
    this.token = await api.createSession(turnstileToken);
    return this.token;
  }

  clear(): void {
    this.token = null;
  }
}
