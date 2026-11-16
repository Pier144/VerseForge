import { put } from "@vercel/blob";
import { GitHub } from "../lib/github.js";
import { handle } from "../lib/handle.js";

let github;   // kept between requests while the instance is warm (the installation token is cached inside)

export default async function handler(req, res) {
  github ??= new GitHub({
    appId: process.env.GH_APP_ID,
    privateKey: process.env.GH_APP_PRIVATE_KEY || "",
    installationId: process.env.GH_APP_INSTALLATION_ID || undefined,
    repo: process.env.REPORTS_REPO || "Pier144/VerseForge",
  });
  let body;
  try {
    body = req.body;   // parsed by Vercel for application/json; reading it throws on broken JSON
  } catch {
    body = null;
  }
  const out = await handle({ method: req.method, headers: req.headers, body }, {
    env: process.env,
    github,
    putPicture: async (name, data) => (await put(name, data, { access: "public", contentType: "image/jpeg" })).url,
  });
  res.status(out.status).json(out.json);
}
