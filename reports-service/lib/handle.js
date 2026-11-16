// One report from VerseForge -> one GitHub issue. Pure function of the request and its dependencies (GitHub
// client, picture upload, environment, clock, log), so it is tested without the network.
import { randomUUID } from "node:crypto";
import { validate, placePicture } from "./validate.js";

const reply = (status, json) => ({ status, json });

export async function handle(req, { env, github, putPicture, log = console.log, now = Date.now }) {
  if (req.method !== "POST") return reply(405, { error: "Use POST" });
  if (env.REPORTS_ENABLED !== "1") return reply(503, { error: "Reports are switched off for now" });
  if (!String(req.headers?.["user-agent"] || "").startsWith("VerseForge/")) {
    return reply(403, { error: "Reports are sent from VerseForge" });
  }
  const { error, report } = validate(req.body);
  if (error) return reply(400, { error });

  try {
    // hourly cap over all senders (approximate: GitHub's search index can lag a few minutes)
    try {
      const since = new Date(now() - 3_600_000).toISOString().replace(/\.\d+Z$/, "Z");
      if ((await github.recentReports(since)) >= Number(env.REPORTS_PER_HOUR || 20)) {
        log("hourly cap reached");
        return reply(503, { error: "Too many reports right now, try again later" });
      }
    } catch (e) {
      log(`count failed, report let through: ${e.message}`);   // the per-IP firewall limit still applies
    }

    let markdown = "", pictureName = "";
    if (report.picture) {
      pictureName = `reports/${new Date(now()).toISOString().slice(0, 7)}/${randomUUID()}.jpg`;
      try {
        markdown = `![3D view](${await putPicture(pictureName, report.picture)})`;
        log(`picture uploaded ${pictureName}`);   // logged now: creating the issue may still fail below
      } catch (e) {
        log(`picture upload failed: ${e.message}`);
        markdown = "_(the picture could not be uploaded)_";
        pictureName = "";
      }
    }
    const issue = await github.createIssue({
      title: report.title,
      body: placePicture(report.body, markdown),
      labels: ["from-app", report.kind === "bug" ? "bug" : "enhancement"],
    });
    log(`issue #${issue.number}${pictureName ? ` picture ${pictureName}` : ""}`);
    return reply(201, { number: issue.number, url: issue.html_url });
  } catch (e) {
    log(`GitHub refused the report (${e.status || "no status"}): ${e.message}`);
    return reply(503, { error: "GitHub did not accept the report, try again later" });
  }
}
