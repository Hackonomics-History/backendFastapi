from google_auth_oauthlib.flow import Flow

from app.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

def build_google_calendar_flow(state: str | None = None) -> Flow:
    config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_calendar_redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        config,
        scopes=SCOPES,
        state=state,
        redirect_uri=settings.google_calendar_redirect_uri,
    )
    return flow
