import { test } from "node:test";
import assert from "node:assert/strict";
import { handle } from "../lib/handle.js";

const JPEG = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]).toString("base64");
const report = { kind: "bug", title: "[Bug] Carrack", version: "1.14.0", screenshot: JPEG,
  body: "Grey everywhere\n\n<!-- screenshot -->\n\n<sub>Sent from VerseForge 1.14.0</sub>" };
const req = (body, ua = "VerseForge/1.14.0", method = "POST") => ({ method, headers: { "user-agent": ua }, body });
const ISSUE = { number: 42, html_url: "https://github.com/Pier144/VerseForge/issues/42" };

function deps({ count = 0, issue = ISSUE, put = async (name) => `https://blob.example/${name}`, env = {} } = {}) {
  const made = [], logs = [];
  return {
    made, logs, log: (m) => logs.push(m), now: () => Date.UTC(2026, 10, 16, 12),
    env: { REPORTS_ENABLED: "1", REPORTS_PER_HOUR: "20", ...env },
    putPicture: put,
    github: {
      recentReports: async () => { if (count instanceof Error) throw count; return count; },
      createIssue: async (i) => { if (issue instanceof Error) throw issue; made.push(i); return issue; },
    },
  };
}

test("creates the issue with the picture and the labels", async () => {
  const d = deps();
  assert.deepEqual(await handle(req(report), d), { status: 201, json: { number: 42, url: ISSUE.html_url } });
  assert.deepEqual(d.made[0].labels, ["from-app", "bug"]);
  assert.equal(d.made[0].title, "[Bug] Carrack");
  assert.match(d.made[0].body, /!\[3D view\]\(https:\/\/blob\.example\/reports\/2026-11\/[0-9a-f-]{36}\.jpg\)/);
  assert.ok(d.logs.some((l) => /^issue #42 picture reports\/2026-11\//.test(l)));
});

test("an idea gets the enhancement label", async () => {
  const d = deps();
  await handle(req({ ...report, kind: "idea", screenshot: undefined }), d);
  assert.deepEqual(d.made[0].labels, ["from-app", "enhancement"]);
  assert.ok(!d.made[0].body.includes("<!-- screenshot -->"));
});

test("the issue still goes out when the picture upload fails", async () => {
  const d = deps({ put: async () => { throw new Error("blob down"); } });
  assert.equal((await handle(req(report), d)).status, 201);
  assert.match(d.made[0].body, /the picture could not be uploaded/);
});

test("switched off", async () => {
  assert.equal((await handle(req(report), deps({ env: { REPORTS_ENABLED: "0" } }))).status, 503);
});

test("only POST from VerseForge", async () => {
  assert.equal((await handle(req(report, "curl/8"), deps())).status, 403);
  assert.equal((await handle(req(report, undefined, "GET"), deps())).status, 405);
});

test("invalid content gets the reason", async () => {
  const out = await handle(req({ ...report, title: "abc" }), deps());
  assert.equal(out.status, 400);
  assert.match(out.json.error, /title/i);
});

test("hourly cap", async () => {
  const d = deps({ count: 20 });
  assert.equal((await handle(req(report), d)).status, 503);
  assert.equal(d.made.length, 0);
});

test("a failed count lets the report through", async () => {
  const d = deps({ count: Object.assign(new Error("search down"), { status: 500 }) });
  assert.equal((await handle(req(report), d)).status, 201);
  assert.ok(d.logs.some((l) => l.includes("search down")));
});

test("GitHub refusing the issue gives 503", async () => {
  const d = deps({ issue: Object.assign(new Error("Validation Failed"), { status: 422 }) });
  assert.equal((await handle(req(report), d)).status, 503);
});
