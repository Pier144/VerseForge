// GitHub REST calls as the "VerseForge Reports" GitHub App: a JWT signed with the app's private key buys an
// installation token (valid 1 hour), kept in memory while the function instance stays warm.
import { createSign } from "node:crypto";

const API = "https://api.github.com";
const b64url = (x) => Buffer.from(x).toString("base64url");

export class GitHubError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function appJwt(appId, privateKey, now = Date.now()) {
  const t = Math.floor(now / 1000);
  const head = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  // issued a minute in the past and valid 9 minutes: GitHub allows 10, and clocks drift
  const claims = b64url(JSON.stringify({ iat: t - 60, exp: t + 540, iss: String(appId) }));
  const sign = createSign("RSA-SHA256");
  sign.update(`${head}.${claims}`);
  return `${head}.${claims}.${sign.sign(privateKey.replace(/\n/g, "\n"), "base64url")}`;
}

export class GitHub {
  constructor({ appId, privateKey, installationId, repo, fetch = globalThis.fetch, now = Date.now }) {
    Object.assign(this, { appId, privateKey, installationId, repo, fetch, now });
    this.token = null;
    this.tokenExp = 0;
  }

  async call(method, path, { token, body } = {}) {
    const headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "verseforge-reports", Authorization: `Bearer ${token}` };
    if (body) headers["Content-Type"] = "application/json";
    const r = await this.fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new GitHubError(r.status, data.message || r.statusText);
    return data;
  }

  async installationToken(force = false) {
    if (!force && this.token && this.now() < this.tokenExp - 5 * 60_000) return this.token;
    const jwt = appJwt(this.appId, this.privateKey, this.now());
    if (!this.installationId) {
      this.installationId = (await this.call("GET", `/repos/${this.repo}/installation`, { token: jwt })).id;
    }
    const t = await this.call("POST", `/app/installations/${this.installationId}/access_tokens`, { token: jwt });
    this.token = t.token;
    this.tokenExp = Date.parse(t.expires_at) || this.now() + 3_600_000;
    return this.token;
  }

  // with the installation token; a 401 (token revoked or expired early) renews it once
  async request(method, path, body) {
    try {
      return await this.call(method, path, { token: await this.installationToken(), body });
    } catch (e) {
      if (e.status !== 401) throw e;
      return this.call(method, path, { token: await this.installationToken(true), body });
    }
  }

  async recentReports(sinceIso) {
    const q = encodeURIComponent(`repo:${this.repo} is:issue label:from-app created:>=${sinceIso}`);
    return (await this.request("GET", `/search/issues?q=${q}&per_page=1`)).total_count;
  }

  createIssue({ title, body, labels }) {
    return this.request("POST", `/repos/${this.repo}/issues`, { title, body, labels });
  }
}
