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
SIGNAL_SENDER="+15555555555" \
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

### Dockerised Signal service runners

If you prefer to keep the Signal ingestion scripts in dedicated containers,
use the provided `docker-compose.signal.yml` file. It builds a lightweight
image (defined in `docker/Dockerfile.signal_service`) that ships the Flask
application code and executes `python -m scripts.signal_service` inside the
container.

1. Copy `.env.example` to `.env` (or create `.env` manually) and define:

   ```ini
   SIGNAL_PHONE_NUMBER=+15555555555
   SIGNAL_CLI_BIN=/usr/local/bin/signal-cli  # Optional override inside the container
   ```

   The default `SIGNAL_CLI_DATA` value mounts a local `./.signal-cli` folder
   into the container at `/root/.local/share/signal-cli`. Place the linked
   profile there (or update the variable to point to an existing directory).

   The Signal worker image now downloads the headless `signal-cli` release at
   build time (default version `0.13.20`). Override the version with
   `--build-arg SIGNAL_CLI_VERSION=0.13.25` when invoking `docker compose build`
   if you need a newer release.

   > The bundled binary lives only inside the container image, so it will not
   > conflict with any `signal-cli` you have already installed on your host.
   > You can keep the local installation (useful for registering or linking the
   > account) or remove it; the containerised workers run with their own copy.

2. Ensure the Signal profile directory contains the registration files for the
   same phone number you configured in `SIGNAL_PHONE_NUMBER`.

3. Ensure docker is running, give your user permission to talk to the daemon, and test.
   > Ensure Docker is running with `sudo systemctl status docker`
   > If it says inactive failed or dead run: `sudo systemctl start docker`
   > Enable auto-start on boot `sudo systemctl enable docker`
   > Give your user permission to talk to the daemon `sudo usermod -aG docker $USER`
   > Refresh session `newgrp docker`
   > Test with `docker run hello-world`
   
4. Start the three worker containers—one per Signal group—with:

   ```bash
   docker compose -f docker-compose.signal.yml up --build -d
   ```

   > **Note:** Some environments still ship the legacy `docker-compose`
   > standalone binary instead of the modern `docker compose` plugin. If you
   > see an error such as `unknown shorthand flag: 'f' in -f`, rerun the command
   > replacing `docker compose` with `docker-compose`.

5. Inspect the container logs to verify URL ingestion. Stop the workers with 
   `docker compose -f docker-compose.signal.yml down`
   (or `docker-compose ... down`) when needed.


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