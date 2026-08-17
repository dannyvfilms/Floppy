---
name: Bug report
about: Create a report to help us improve
title: "[BUG] "
labels: bug
assignees: ''

---

**Before you file this: attach your logs**
Go to **Settings > Advanced** in Floppy and click **Download Sanitized Logs** (tokens, passwords,
and API keys are automatically redacted). Attach the downloaded file below — this is almost
always the fastest way for us to diagnose issues like webhook/integration bugs, and reports
without it are much harder to act on.

**If Floppy will not start**, you cannot reach that page. Run the startup check instead and
paste its output below. It redacts passwords and tokens, the same as the log download:

```bash
# The container runs, but it is unhealthy or idle.
docker exec floppy python manage.py floppy_preflight --json

# The container restarts or has exited.
docker compose run --rm floppy python manage.py floppy_preflight --json
```

**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:

**Expected behavior**
Description of what you expected to happen.

**Screenshots**
If applicable, add screenshots to help explain your problem.

**Logs**
Attach the file from Settings > Advanced > Download Sanitized Logs here:

**Floppy version**:
**Database**: SQLite (default) or PostgreSQL
