import os, json, base64, time
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _client_from_env():
    b64 = os.getenv("GOOGLE_SA_JSON_B64", "")
    if not b64:
        raise RuntimeError("GOOGLE_SA_JSON_B64 not set")
    info = json.loads(base64.b64decode(b64).decode("utf-8"))
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def append_application_row(app, row_dict):
    """Append a single row to the configured worksheet.
       row_dict is your application dict (fields below)."""
    if os.getenv("GOOGLE_SHEETS_ENABLED", "false").lower() != "true":
        app.logger.info("Sheets append skipped; GOOGLE_SHEETS_ENABLED != true")
        return

    ss_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    ws_name = os.getenv("GOOGLE_SHEETS_WORKSHEET_NAME", "Applications")
    if not ss_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID not set")

    gc = _client_from_env()
    sh = gc.open_by_key(ss_id)

    try:
        ws = sh.worksheet(ws_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=ws_name, rows=100, cols=40)
        # Write header row once
        headers = [
            "timestamp", "app_id", "username", "name", "grade", "unit", "email", "phone",
            "years_experience", "primary_platforms", "skills",
            "deploying_12mo", "parental_leave_12mo", "tdy_restrictions",
            "statement", "video_path"
        ]
        ws.append_row(headers, value_input_option="RAW")

    values = [
        time.strftime("%Y-%m-%d %H:%M:%S"),
        row_dict.get("app_id", ""),
        row_dict.get("username", ""),
        row_dict.get("name", ""),
        row_dict.get("grade", ""),
        row_dict.get("unit", ""),
        row_dict.get("email", ""),
        row_dict.get("phone", ""),
        row_dict.get("years_experience", ""),
        row_dict.get("primary_platforms", ""),
        row_dict.get("skills", ""),
        row_dict.get("deploying_12mo", ""),
        row_dict.get("parental_leave_12mo", ""),
        row_dict.get("tdy_restrictions", ""),
        row_dict.get("statement", ""),
        row_dict.get("video_path", ""),
    ]
    ws.append_row(values, value_input_option="RAW")
