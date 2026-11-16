// Checks a report sent by VerseForge. The app builds the whole issue text (sc_explorer/reports.py): here it is only
// checked, never rewritten, apart from @mentions, which are broken again in case the request did not come from the app.
export const PICTURE = "<!-- screenshot -->";
const LIMITS = { title: [4, 130], body: [10, 20000], picture: 2 * 1024 * 1024 };
const PREFIX = /^\[(Bug|Idea)\] /;
const VERSION = /^\d+\.\d+\.\d+$/;
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

export function breakMentions(text) {
  return text.replace(/@(?=[A-Za-z0-9])/g, "@​");   // zero-width space: GitHub does not notify anyone
}

const length = (s, [min, max]) => typeof s === "string" && s.trim().length >= min && s.length <= max;

// The minimum counts the user's own words only (not the "[Bug] " the app puts in front); the maximum the whole title.
const titleOk = (s) => typeof s === "string" && s.length <= LIMITS.title[1] &&
  s.replace(PREFIX, "").replace(/\s/g, "").length >= LIMITS.title[0];

export function validate(input) {
  if (!input || typeof input !== "object") return { error: "The report is empty" };
  const { kind, title, body, version, screenshot } = input;
  if (kind !== "bug" && kind !== "idea") return { error: "Unknown report type" };
  if (!titleOk(title)) return { error: "The title must be 4 to 130 characters" };
  if (!length(body, LIMITS.body)) return { error: "The text must be 10 to 20000 characters" };
  if (typeof version !== "string" || !VERSION.test(version)) return { error: "Missing VerseForge version" };
  let picture = null;
  if (screenshot != null) {
    if (typeof screenshot !== "string" || !BASE64.test(screenshot)) return { error: "The picture is not valid" };
    picture = Buffer.from(screenshot, "base64");
    if (picture.length > LIMITS.picture) return { error: "The picture is larger than 2 MB" };
    if (picture.length < 3 || picture[0] !== 0xff || picture[1] !== 0xd8 || picture[2] !== 0xff) {
      return { error: "The picture must be a JPEG" };
    }
  }
  return { report: { kind, title: breakMentions(title.trim()), body: breakMentions(body), version, picture } };
}

export function placePicture(body, markdown) {
  const i = body.lastIndexOf(PICTURE);
  return i < 0 ? body : body.slice(0, i) + markdown + body.slice(i + PICTURE.length);
}
