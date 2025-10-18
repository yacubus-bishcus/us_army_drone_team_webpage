#scripts/load_user_env.py

from pathlib import Path
from dotenv import load_dotenv

def load_environment() -> None:
    """Load environment variables from the project .env file if present."""

    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)


