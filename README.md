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
  
`docker compose -f docker-compose.signal.yml run --rm --no-deps   --entrypoint signal-cli signal_master_trainer link --name "CLI2"`
In another terminal:
`URI='PASTE_THE_EXACT_sgnl://linkdevice_LINE_HERE'`
`printf '%s' "$URI" | qrencode -t ansiutf8`
You can list all available groups to discover the group identifier needed
for the ingestion script:

```bash
signal-cli --username +15555555555 listGroups
```
**Note** sudo apt update && 
sudo apt install openjdk-21-jre-headless may be required. 

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
   SIGNAL_TARGET_COUNT=10                    # Stop after ingesting 10 new URLs
   # Optional: override the runtime limit (default 2 min in SANDBOX, 180 min otherwise)
   # SIGNAL_MAX_MINUTES=15
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

   Each worker stops automatically after discovering `SIGNAL_TARGET_COUNT`
   new URLs (default `10`) or once it has been running for the mode-specific
   runtime limit (2 minutes with `SANDBOX_DATA_MODE=true`, 180 minutes
   otherwise). Increase or decrease the URL threshold or provide
   `SIGNAL_MAX_MINUTES` to override the runtime cap before launching the
   stack.

6. Verify signal workers
   > List the containers that started `docker compose -f docker-compose.signal.yml ps`
   > Tail the logs to confirm activity `docker compose -f docker-compose.signal.yml logs -f signal_master_trainer`
   > Bring the stack down when finished `docker compose -f docker-compose.signal.yml down`

   **Note:**
   > Other useful commands:
   > Build by name: `docker compose -f docker-compose.signal.yml up --build signal_master_trainer`
   > Run once in foreground and remove the container afterward (useful for testing):
   `docker compose -f docker-compose.signal.yml run --rm signal_master_trainer`

7. Run the Signal worker locally (without Docker) with the same environment by invoking:

   ```bash
   python run.py static/logs/news_log_testing.log
   ```

   Replace the log file path with the destination you want to mirror. The command streams
   output to stdout and continuously appends the same content to the specified log file.


### Built-in lightweight scheduler

If you want the existing Render web service to handle Signal ingestion without
provisioning a separate Cron Job, enable the bundled background scheduler. Set
`ENABLE_SIGNAL_SCHEDULER=1` in the web service environment and configure the
Signal groups you want to poll.

* Polling cadence – override `SIGNAL_SCHEDULER_INTERVAL_SECONDS` to change the
  interval (defaults to four hours).
* Group configuration – define `SIGNAL_SCHEDULER_GROUPS` as JSON. Each entry may
  be a string (just the Signal group name) or an object with custom settings:

  ```json
  [
    {
      "name": "Master-Trainer/UAS/C-UAS",
      "log_file": "static/logs/news_log_master_trainer.log",
      "added_by": "Master-Trainer/UAS/C-UAS",
      "target_count": 10
    },
    "IrregularChat: Counter UxV",
    "IrregularChat: sUAS"
  ]
  ```

  Relative log paths are resolved inside the repository (for example
  `static/logs/...`). `added_by` defaults to the group name and `target_count`
  falls back to `SIGNAL_TARGET_COUNT` (default 10).
* Single-group shortcut – if you only have one Signal group, you can skip the
  JSON and set `SIGNAL_GROUP_NAME`, `SIGNAL_LOG_FILE`, and `SIGNAL_ADDED_BY`
  instead.

The scheduler reuses the same `scripts.signal_service` worker that the Docker
composition runs. The Flask app keeps the thread alive across requests, so the
Signal URLs continue to trickle into the news feed at the configured cadence.
