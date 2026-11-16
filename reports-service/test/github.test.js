import { test } from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync, createVerify } from "node:crypto";
import { appJwt, GitHub } from "../lib/github.js";

const { privateKey, publicKey } = generateKeyPairSync("rsa", {
  modulusLength: 2048,
  privateKeyEncoding: { type: "pkcs8", format: "pem" },
  publicKeyEncoding: { type: "spki", format: "pem" },
});
const NOW = Date.UTC(2026, 10, 16, 12, 0, 0);
const REPO = "Pier144/VerseForge";

// fetch stand-in: routes are "METHOD /path" -> [status, json] or (nth call of that route) => [status, json]
function fakeFetch(routes) {
  const calls = [];
  const fn = async (url, opts = {}) => {
    const key = `${opts.method || "GET"} ${new URL(url).pathname}`;
    calls.push({ url, key, ...opts });
    const route = routes[key];
    if (!route) throw new Error(`unexpected ${key}`);
    const [status, body] = typeof route === "function" ? route(calls.filter((c) => c.key === key).length) : route;
    return { ok: status < 300, status, statusText: String(status), json: async () => body };
  };
  fn.calls = calls;
  return fn;
}
const INSTALL = { [`GET /repos/${REPO}/installation`]: [200, { id: 99 }] };
const token = (t = "t1") => [201, { token: t, expires_at: "2026-11-16T13:00:00Z" }];
const client = (fetch) => new GitHub({ appId: 123, privateKey, repo: REPO, fetch, now: () => NOW });

test("app JWT is signed, short-lived and accepts a key pasted on one line", () => {
  const jwt = appJwt(123, privateKey.replace(/\n/g, "\n"), NOW);
  const [h, c, s] = jwt.split(".");
  assert.deepEqual(JSON.parse(Buffer.from(c, "base64url")), { iat: NOW / 1000 - 60, exp: NOW / 1000 + 540, iss: "123" });
  const v = createVerify("RSA-SHA256");
  v.update(`${h}.${c}`);
  assert.ok(v.verify(publicKey, s, "base64url"));
});

test("finds the installation, keeps the token and creates issues", async () => {
  const f = fakeFetch({ ...INSTALL, "POST /app/installations/99/access_tokens": token(),
    [`POST /repos/${REPO}/issues`]: [201, { number: 5, html_url: "u" }] });
  const g = client(f);
  assert.equal((await g.createIssue({ title: "t", body: "b", labels: ["from-app"] })).number, 5);
  await g.createIssue({ title: "t2", body: "b2", labels: [] });
  assert.equal(f.calls.filter((c) => c.key.endsWith("access_tokens")).length, 1);
  assert.equal(f.calls.at(-1).headers.Authorization, "Bearer t1");
  assert.deepEqual(JSON.parse(f.calls.at(-1).body), { title: "t2", body: "b2", labels: [] });
});

test("a 401 renews the token once and retries", async () => {
  let n = 0;
  const f = fakeFetch({ ...INSTALL, "POST /app/installations/99/access_tokens": () => token(`t${++n}`),
    [`POST /repos/${REPO}/issues`]: (k) => (k === 1 ? [401, { message: "Bad credentials" }] : [201, { number: 6 }]) });
  assert.equal((await client(f).createIssue({ title: "t", body: "b", labels: [] })).number, 6);
  assert.equal(f.calls.at(-1).headers.Authorization, "Bearer t2");
});

test("other errors carry the status", async () => {
  const f = fakeFetch({ ...INSTALL, "POST /app/installations/99/access_tokens": token(),
    [`POST /repos/${REPO}/issues`]: [422, { message: "Validation Failed" }] });
  await assert.rejects(client(f).createIssue({ title: "t", body: "b", labels: [] }), { status: 422 });
});

test("counts recent reports with search", async () => {
  const f = fakeFetch({ ...INSTALL, "POST /app/installations/99/access_tokens": token(),
    "GET /search/issues": [200, { total_count: 3 }] });
  assert.equal(await client(f).recentReports("2026-11-16T11:00:00Z"), 3);
  assert.equal(new URL(f.calls.at(-1).url).searchParams.get("q"),
    `repo:${REPO} is:issue label:from-app created:>=2026-11-16T11:00:00Z`);
});
