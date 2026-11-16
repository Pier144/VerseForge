import { test } from "node:test";
import assert from "node:assert/strict";
import { validate, breakMentions, placePicture, PICTURE } from "../lib/validate.js";

const JPEG = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]).toString("base64");
const good = { kind: "bug", title: "[Bug] Carrack", body: "It is grey everywhere", version: "1.14.0" };

test("accepts a good report with a picture", () => {
  const { report, error } = validate({ ...good, screenshot: JPEG });
  assert.equal(error, undefined);
  assert.equal(report.kind, "bug");
  assert.equal(report.picture.length, 7);
});

test("accepts a report without a picture", () => {
  assert.equal(validate(good).report.picture, null);
});

test("rejects bad fields", () => {
  const bad = [null, "text", { ...good, kind: "spam" }, { ...good, title: "abc" }, { ...good, title: "x".repeat(131) },
    { ...good, body: "short" }, { ...good, body: "x".repeat(20001) }, { ...good, version: "" },
    { ...good, version: "1.14" }, { ...good, screenshot: "not base64!" },
    { ...good, screenshot: Buffer.from("GIF89a").toString("base64") }];
  for (const b of bad) assert.ok(validate(b).error, JSON.stringify(b)?.slice(0, 80));
});

test("rejects pictures over 2 MB", () => {
  const big = Buffer.alloc(2 * 1024 * 1024 + 1);
  big[0] = 0xff; big[1] = 0xd8; big[2] = 0xff;
  assert.match(validate({ ...good, screenshot: big.toString("base64") }).error, /2 MB/);
});

test("mentions are broken once", () => {
  const once = breakMentions("hi @bob and a@b");
  assert.equal(once, "hi @​bob and a@​b");
  assert.equal(breakMentions(once), once);
  assert.equal(validate({ ...good, body: "ping @octocat please" }).report.body, "ping @​octocat please");
});

test("the picture goes in the last placeholder only", () => {
  assert.equal(placePicture(`a ${PICTURE} b ${PICTURE} c`, "IMG"), `a ${PICTURE} b IMG c`);
  assert.equal(placePicture("no marker", "IMG"), "no marker");
});
