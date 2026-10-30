"""Регистрация, подтверждение почты, вход. Главное: почта не подтверждается без верного кода."""
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import update

from app.core.config import MailSettings, get_settings
from app.db.session import engine
from app.integrations.mailer import Mailer
from app.models import EmailVerificationCode, User
from main import app
from tests.conftest import API, PASSWORD, login, make_user, register

EMAIL = "ivan@test.ru"


def _verify(client, code, email=EMAIL):
    return client.post(f"{API}/auth/verify-email", json={"email": email, "code": code})


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def _shift_code(client, **fields):
    async def run():
        async with engine.begin() as conn:
            await conn.execute(update(EmailVerificationCode).values(**fields))
    client.portal.call(run)


def test_full_flow(client, mailer):
    assert register(client).status_code == 201
    code = mailer.codes[EMAIL]
    assert len(code) == 6 and code.isdigit()

    # До подтверждения войти нельзя
    res = login(client)
    assert res.status_code == 403 and "не подтверждена" in res.json()["detail"]

    res = _verify(client, code)
    assert res.status_code == 200
    token = res.json()["access_token"]
    me = client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == EMAIL

    assert login(client).status_code == 200
    # Повторное подтверждение — явная ошибка, а не тихий успех
    assert _verify(client, code).status_code == 409


def test_wrong_code_never_verifies(client, mailer):
    register(client)
    code = mailer.codes[EMAIL]

    res = _verify(client, _wrong(code))
    assert res.status_code == 400
    assert res.json()["detail"] == "Неверный код. Осталось попыток: 4"
    assert login(client).status_code == 403  # всё ещё не подтверждена

    # Не 6 цифр — отсекается валидацией
    for bad in ["12345", "1234567", "abcdef", "12 456", ""]:
        assert _verify(client, bad).status_code == 422, bad


def test_attempts_exhausted_burns_code(client, mailer):
    register(client)
    code = mailer.codes[EMAIL]
    for left in [4, 3, 2, 1]:
        assert _verify(client, _wrong(code)).json()["detail"].endswith(str(left))
    last = _verify(client, _wrong(code))
    assert last.status_code == 429

    # Даже верный код после исчерпания попыток не подтверждает почту
    res = _verify(client, code)
    assert res.status_code == 429
    assert login(client).status_code == 403


def test_expired_code_rejected_even_if_correct(client, mailer):
    register(client)
    _shift_code(client, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    res = _verify(client, mailer.codes[EMAIL])
    assert res.status_code == 410 and "истёк" in res.json()["detail"]
    assert login(client).status_code == 403


def test_resend_code(client, mailer):
    register(client)
    old_code = mailer.codes[EMAIL]

    # Сразу повторно — рано
    res = client.post(f"{API}/auth/resend-code", json={"email": EMAIL})
    assert res.status_code == 429 and "сек" in res.json()["detail"]

    _shift_code(client, created_at=datetime.now(UTC) - timedelta(minutes=2))
    assert client.post(f"{API}/auth/resend-code", json={"email": EMAIL}).status_code == 200
    new_code = mailer.codes[EMAIL]

    # Старый код больше не действует
    if old_code != new_code:
        assert _verify(client, old_code).status_code == 400
    assert _verify(client, new_code).status_code == 200

    assert client.post(f"{API}/auth/resend-code", json={"email": EMAIL}).status_code == 409
    assert client.post(f"{API}/auth/resend-code", json={"email": "nobody@test.ru"}).status_code == 404


def test_unknown_email_and_wrong_password(client, mailer):
    assert _verify(client, "123456", email="nobody@test.ru").status_code == 404
    make_user(client, mailer)
    res = login(client, password="wrong-password")
    assert res.status_code == 401 and res.headers["WWW-Authenticate"] == "Bearer"
    assert login(client, email="nobody@test.ru").status_code == 401
    # Email без учёта регистра
    assert login(client, email="IVAN@Test.ru").status_code == 200


def test_duplicate_registration(client, mailer):
    register(client)
    # Свежая неподтверждённая регистрация не перезаписывается (иначе можно подменить пароль)
    res = register(client, password="attacker-password")
    assert res.status_code == 409 and "не подтверждён" in res.json()["detail"]

    _verify(client, mailer.codes[EMAIL])
    res = register(client)
    assert res.status_code == 409 and "уже зарегистрирован" in res.json()["detail"]


def test_stale_unverified_registration_can_be_replaced(client, mailer):
    register(client)

    async def age_user():
        async with engine.begin() as conn:
            await conn.execute(update(User).values(created_at=datetime.now(UTC) - timedelta(days=2)))

    client.portal.call(age_user)
    assert register(client, name="Иван Новый").status_code == 201
    assert _verify(client, mailer.codes[EMAIL]).status_code == 200


def test_mail_failure_does_not_create_account(client, mailer):
    mailer.fail = True
    res = register(client)
    assert res.status_code == 502
    mailer.fail = False
    # Регистрация откатилась — можно пройти заново
    assert register(client).status_code == 201


def test_smtp_not_configured_means_503_not_autoverify(client):
    app.state.mailer = Mailer(MailSettings())  # пустой SMTP, dev_log_codes выключен
    res = register(client)
    assert res.status_code == 503 and "SMTP" in res.json()["detail"]
    assert login(client).status_code == 401  # пользователь не создан вовсе


def test_password_rules(client):
    assert register(client, password="short").status_code == 422
    assert register(client, region="Нарния").status_code == 422


def test_bad_tokens(client, mailer):
    headers = make_user(client, mailer)
    settings = get_settings().auth
    secret = settings.secret_key.get_secret_value()
    now = datetime.now(UTC)

    expired = jwt.encode({"sub": "1", "exp": now - timedelta(minutes=1), "type": "access"}, secret, "HS256")
    foreign = jwt.encode({"sub": "1", "exp": now + timedelta(hours=1), "type": "access"}, "x" * 40, "HS256")
    no_type = jwt.encode({"sub": "1", "exp": now + timedelta(hours=1)}, secret, "HS256")
    unsigned = jwt.encode({"sub": "1", "exp": now + timedelta(hours=1), "type": "access"}, None, "none")

    for token in [expired, foreign, no_type, unsigned, "garbage", ""]:
        res = client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401, token
    assert client.get(f"{API}/users/me").status_code == 401

    # Пользователь удалён — его токен больше не работает
    assert client.delete(f"{API}/users/me", headers=headers).status_code == 204
    assert client.get(f"{API}/users/me", headers=headers).status_code == 401


def test_code_is_stored_hashed(client, mailer):
    register(client)
    code = mailer.codes[EMAIL]

    async def stored_hash():
        async with engine.begin() as conn:
            from sqlalchemy import select
            return (await conn.execute(select(EmailVerificationCode.code_hash))).scalar_one()

    stored = client.portal.call(stored_hash)
    assert code not in stored and len(stored) == 64
