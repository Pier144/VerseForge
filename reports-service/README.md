# VerseForge Reports service

Receives the reports sent from VerseForge (Feedback button) and opens them as public issues on
[Pier144/VerseForge](https://github.com/Pier144/VerseForge/issues?q=label%3Afrom-app) through the
**VerseForge Reports** GitHub App. Screenshots go to Vercel Blob. Hosted on Vercel (project `verseforge-reports`,
root directory `reports-service`).

The issue text is built by the app (`sc_explorer/reports.py`); this service only checks it, uploads the picture,
applies the limits and creates the issue.

## Environment variables

| name | value |
|---|---|
| `GH_APP_ID` | App ID of the VerseForge Reports GitHub App |
| `GH_APP_PRIVATE_KEY` | the app's private key (.pem content; one line with `\n` also works) |
| `GH_APP_INSTALLATION_ID` | optional: found automatically from the repository |
| `REPORTS_REPO` | `Pier144/VerseForge` |
| `REPORTS_ENABLED` | `1` to accept reports, anything else to switch them off |
| `REPORTS_PER_HOUR` | cap on reports per hour from everyone (default 20) |
| `BLOB_READ_WRITE_TOKEN` | set by Vercel when the Blob store is connected |

Firewall: rate limit rule on `/api/report`, 5 requests per 10 minutes per IP, action "rate limit" (answers 429, which the app shows as "too many reports"; "deny" would answer 403 and look like the service being down).

## Tests

```bash
node --test
```

## Emergency (spam or abuse)

1. Vercel, project settings, Environment Variables: `REPORTS_ENABLED=0`, then redeploy. The app then offers
   GitHub's own form instead.
2. Close the bad issues in bulk:
   `gh issue list -R Pier144/VerseForge -l from-app --search "created:>=YYYY-MM-DD" --json number -q ".[].number" | xargs -n1 gh issue close -R Pier144/VerseForge`
   (delete them from the GitHub page if their content must go).
3. Pictures: Vercel, Storage, the Blob store, delete the files. The function log has a line
   `issue #N picture reports/YYYY-MM/<id>.jpg` for each report with a picture.
