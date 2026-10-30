"""Одноразовая авторизация Gmail API для отправки писем с кодом.

Запуск из папки backend (в .env уже должны быть SMTP__GMAIL_CLIENT_ID и SMTP__GMAIL_CLIENT_SECRET):
    python scripts/gmail_auth.py

Откроется браузер: войдите в Gmail-аккаунт, с которого пойдут письма, и разрешите отправку.
Скрипт сам запишет SMTP__GMAIL_REFRESH_TOKEN в .env — на экран токен не выводится.
Права запрашиваются только на отправку (gmail.send): читать почту приложение не сможет.
"""
import base64
import hashlib
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import PROJECT_DIR, get_settings  # noqa: E402

SCOPE = "https://www.googleapis.com/auth/gmail.send"
ENV_KEY = "SMTP__GMAIL_REFRESH_TOKEN"


def save_to_env(value: str) -> Path:
    env = PROJECT_DIR / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lines = [line for line in lines if not line.startswith(f"{ENV_KEY}=")]
    lines.append(f"{ENV_KEY}={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env


def main() -> None:
    settings = get_settings().smtp
    client_id = settings.gmail_client_id
    client_secret = settings.gmail_client_secret.get_secret_value()
    if not client_id or not client_secret:
        sys.exit("В .env нет SMTP__GMAIL_CLIENT_ID / SMTP__GMAIL_CLIENT_SECRET")

    # PKCE + state: перехваченный code без verifier бесполезен, а state защищает от подмены ответа
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if query.get("state") == state and "code" in query:
                result["code"] = query["code"]
                text = "Готово! Можно закрыть вкладку и вернуться в терминал."
            else:
                result["error"] = query.get("error", "неверный ответ")
                text = f"Ошибка авторизации: {result['error']}"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h2>{text}</h2>".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # иначе Google может не выдать refresh-токен повторно
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    print("Открываю браузер для входа в Google. Если не открылся — перейдите по ссылке:\n", url, flush=True)
    webbrowser.open(url)
    while not result:
        server.handle_request()

    if "error" in result:
        sys.exit(f"Авторизация не удалась: {result['error']}")

    body = urllib.parse.urlencode({
        "code": result["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body, timeout=30) as response:
        tokens = json.load(response)
    if "refresh_token" not in tokens:
        sys.exit("Google не вернул refresh-токен. Удалите доступ приложения в аккаунте Google и запустите снова.")

    env = save_to_env(tokens["refresh_token"])
    print(f"Refresh-токен сохранён в {env} ({ENV_KEY}). Права: только отправка писем.")


if __name__ == "__main__":
    main()
