from dotenv import load_dotenv 
from pathlib import Path 

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from drone_team import create_app  # import after .env is loaded
from drone_team.services import news as news_svc 

app = create_app()
# with app.app_context():
#     news_svc.add_article_by_url(current_app, url, "signal_bot")

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
