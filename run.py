from dotenv import load_dotenv 
from pathlib import Path 

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from drone_team import create_app  # import after .env is loaded

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
