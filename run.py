from dotenv import load_dotenv
from pathlib import Path
import os
import webbrowser
from threading import Timer


def _open_browser_once():
    webbrowser.open_new("http://127.0.0.1:5000")


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from drone_team import create_app  # import after .env is loaded

app = create_app()

def _maybe_open_browser():
    if os.getenv("RUN_LOCAL", "1") == "1" and not os.getenv("GUNICORN_CMD_ARGS"):
        Timer(1, _open_browser_once).start()

if __name__ == "__main__":
    _maybe_open_browser()
    app.run(debug=True, use_reloader=False)
