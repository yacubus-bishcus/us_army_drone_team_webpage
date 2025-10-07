# US Army Drone Team Webpage Limited Distribution
Beta Release v1 will only include the Drone Team Page.

US Army Drone Team Page
==

The US Army Drone Team drives unmanned aerial systems (UAS) innovation to ensure technological and operational dominance in modern warfare through national and international competitions. By recruiting and training the next generation of drone operators, the Army Drone Team advances tactical and technical capabilities aligned with the Army's Continuous Transformation Initiative. 
Apply Now Option leads to another page where the user can apply to the US Army Drone Team with a standard application form. After inputing applicant details the user will be emailed a confirmation with details to access the Velocidrone Racetrack.

## Local data sandboxing

Set `SANDBOX_DATA_MODE=true` in your environment while debugging or running automated tests to ensure the production
Postgres database and Google Sheets remain untouched. When this flag is enabled the application uses a local SQLite
database (override the path with `SANDBOX_SQLITE_URL`) and all Google Sheets synchronisation is skipped.

## Scheduled Signal ingestion for UAS News

The `scripts/pull_signal_news.py` helper can be executed on a schedule (for example
with Render Cron) to ingest URLs posted to a Signal group chat into the UAS News
feed. The script expects a headless [`signal-cli`](https://github.com/AsamK/signal-cli)
installation that is already linked to the Signal account participating in the
target group.

### Running locally

```bash
SIGNAL_PHONE_NUMBER="+15555555555" \
SIGNAL_GROUP_ID="<group-id-from-signal-cli>" \
SIGNAL_CLI_BIN="/usr/local/bin/signal-cli" \
SIGNAL_ADDED_BY="signal_bot" \
python -m scripts.pull_signal_news
```

The script stores its checkpoint in `instance/data/signal_ingest_state.json`
so repeated runs only process new messages. URLs that already exist in the
CSV-backed news feed are skipped automatically.

To test the Signal connection without writing to the CSV, append `--dry-run`.
You can optionally point the checkpoint at a custom location with
`--state-file=/tmp/signal-state.json` when running in this mode:

```bash
SIGNAL_PHONE_NUMBER="+15555555555" python -m scripts.pull_signal_news --dry-run --state-file=/tmp/signal-state.json
```

### Understanding the Signal tooling

The Signal applications you may already use—**Signal for iOS/Android** (the
mobile app) and **Signal Desktop** (the graphical desktop client)—do not ship
with `signal-cli`. They all talk to the same Signal service, but `signal-cli`
is a separate, headless command-line utility that exposes automation-friendly
APIs. You must install and link `signal-cli` to the same phone number that is a
member of the target group chat before the ingestion script can read messages.

Once `signal-cli` is registered with your Signal account it can co-exist with
the regular mobile and desktop apps; you do not need a new phone number.

### Installing `signal-cli`
**Linux (Debian/Ubuntu)** – there is no official `apt` package for
  `signal-cli`. Download the latest release tarball and install it manually.
  Choose the option that matches your permissions:

  *System-wide install (requires sudo)*

  ```bash
  VERSION="0.12.0"  # Replace with the current version from the releases page
  curl -LO https://github.com/AsamK/signal-cli/releases/download/v${VERSION}/signal-cli-${VERSION}-Linux-native.tar.gz
  sudo mkdir -p /opt/signal-cli
  sudo tar -xzf signal-cli-${VERSION}-Linux-native.tar.gz -C /opt/signal-cli --strip-components=1
  sudo ln -sf /opt/signal-cli/bin/signal-cli /usr/local/bin/signal-cli
  ```

  *User install (no sudo required)*

  ```bash
  VERSION="0.12.0"  # Replace with the current version from the releases page
  curl -LO https://github.com/AsamK/signal-cli/releases/download/v${VERSION}/signal-cli-${VERSION}-Linux-native.tar.gz
  mkdir -p "$HOME/.local/lib/signal-cli"
  tar -xzf signal-cli-${VERSION}-Linux-native.tar.gz -C "$HOME/.local/lib/signal-cli" --strip-components=1
  mkdir -p "$HOME/.local/bin"
  ln -sf "$HOME/.local/lib/signal-cli/bin/signal-cli" "$HOME/.local/bin/signal-cli"
  ```

  Keeping the binary in a dedicated directory makes upgrades easy—just download
  the latest tarball and repeat the extraction step.

You can list all available groups to discover the group identifier needed
for the ingestion script:

```bash
signal-cli --username +15555555555 listGroups
```
The resulting group ID (a long base64-like string) is what you pass in the
`SIGNAL_GROUP_ID` environment variable.

### Render Cron setup

1. Deploy `signal-cli` in a background worker (e.g. Docker) and authenticate it
   with the Signal account that has access to the target group.
2. Add the environment variables described above to the worker service.
3. Configure a Render Cron job to execute `python -m scripts.pull_signal_news`
   on a schedule that suits your cadence (for example every 15 minutes).
4. Monitor the worker logs to confirm the ingestion count after each run.

The ingestion script reuses the existing metadata scraper in
`drone_team.services.news` so the UAS News cards continue to display the
OpenGraph titles, summaries, and thumbnails when available.