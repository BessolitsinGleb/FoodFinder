"""Сценарий целиком, как его пройдёт фронт: корзина -> адрес -> поиск -> подборка -> письма."""
from decimal import Decimal

from tests.conftest import API, create_category, make_admin, make_user


def _setup_order(client, mailer, top_k=2, email="ivan@test.ru"):
    admin = make_admin(client, mailer, email=f"admin-{email}")
    headers = make_user(client, mailer, email)
    dairy = create_category(client, admin, "Молочная продукция", f"dairy-{abs(hash(email)) % 1000}", is_featured=True)
    order = client.post(f"{API}/orders", json={"top_k": top_k}, headers=headers).json()
    client.post(f"{API}/orders/{order['id']}/items", headers=headers,
                json={"category_id": dairy["id"], "details": "26%", "quantity": 2, "unit": "т"})
    client.post(f"{API}/orders/{order['id']}/items", headers=headers,
                json={"custom_title": "Крафт-пакеты", "quantity": 1000, "unit": "шт"})
    return headers, order


def _run_search(client, headers, order_id):
    assert client.put(f"{API}/orders/{order_id}/delivery", json={}, headers=headers).status_code == 200
    res = client.post(f"{API}/orders/{order_id}/search", headers=headers)
    assert res.status_code == 202, res.text
    # TestClient выполняет фоновые задачи до возврата ответа — поиск уже закончился
    return client.get(f"{API}/orders/{order_id}/results", headers=headers).json()


def test_profile_region_is_normalized(client, mailer):
    headers = make_user(client, mailer)
    me = client.get(f"{API}/users/me", headers=headers).json()
    assert (me["city"], me["region"]) == ("Казань", "Республика Татарстан")

    res = client.patch(f"{API}/users/me", json={"region": "Нарния"}, headers=headers)
    assert res.status_code == 422
    res = client.patch(f"{API}/users/me", json={"region": "мск", "city": "москва"}, headers=headers)
    assert (res.json()["city"], res.json()["region"]) == ("Москва", "Москва")


def test_popular_categories(client, mailer):
    admin = make_admin(client, mailer)
    root = create_category(client, admin, "Ингредиенты", "ingredients")
    create_category(client, admin, "Сахар", "sugar", parent_id=root["id"])
    create_category(client, admin, "Мука", "flour", parent_id=root["id"], is_featured=True)

    # Корневой раздел не предлагаем; пока заказов нет — featured первым; "Другое" всегда последним
    options = client.get(f"{API}/categories/popular").json()
    assert [o["slug"] for o in options] == ["flour", "sugar", "other"]
    assert options[-1] == {"id": None, "name": "Другое", "slug": "other", "is_other": True}

    # Сахар начали заказывать — он поднимается наверх
    headers = make_user(client, mailer)
    order = client.post(f"{API}/orders", json={}, headers=headers).json()
    client.post(f"{API}/orders/{order['id']}/items", json={"category_id": options[1]["id"]}, headers=headers)
    options = client.get(f"{API}/categories/popular").json()
    assert [o["slug"] for o in options] == ["sugar", "flour", "other"]


def test_only_admin_edits_categories(client, mailer):
    headers = make_user(client, mailer)
    res = client.post(f"{API}/categories", json={"name": "Соль", "slug": "salt"}, headers=headers)
    assert res.status_code == 403
    assert client.post(f"{API}/categories", json={"name": "Соль", "slug": "salt"}).status_code == 401


def test_cart_validation_and_delivery_question(client, mailer):
    headers = make_user(client, mailer)
    order = client.post(f"{API}/orders", json={}, headers=headers).json()
    assert order["status"] == "draft"
    assert order["delivery_question"].startswith("Доставка в г. Казань")

    url = f"{API}/orders/{order['id']}"
    # Либо категория, либо "Другое", но не оба сразу
    assert client.post(f"{url}/items", json={"category_id": 1, "custom_title": "X"}, headers=headers).status_code == 422
    assert client.post(f"{url}/items", json={"custom_title": "Соль", "quantity": 5, "unit": "мешок"},
                       headers=headers).status_code == 422

    # Пустая корзина -> 409; без подтверждённого адреса -> 409
    assert client.post(f"{url}/search", headers=headers).status_code == 409
    client.post(f"{url}/items", json={"custom_title": "Соль", "quantity": 5, "unit": "кг"}, headers=headers)
    res = client.post(f"{url}/search", headers=headers)
    assert res.status_code == 409 and "адрес" in res.json()["detail"]

    # Другой адрес доставки
    order = client.put(f"{url}/delivery", headers=headers,
                       json={"city": "самара", "region": "Самарская обл", "address": "ул. Ленина, 1"}).json()
    assert (order["delivery_city"], order["delivery_region"]) == ("Самара", "Самарская область")
    assert order["delivery_confirmed"] and order["delivery_question"] is None


def test_search_ranks_suppliers_per_item(client, mailer, fake_web):
    headers, order = _setup_order(client, mailer, top_k=2)
    results = _run_search(client, headers, order["id"])

    assert results["order"]["status"] == "ready"
    assert all(p["status"] == "done" for p in results["order"]["search_progress"].values())

    # География расширялась от города к России
    first_queries = [q for q in fake_web.queries if "поставщик оптом" in q][:4]
    assert [q.split("оптом ")[1] for q in first_queries] == [
        "Казань", "Республика Татарстан", "Приволжский федеральный округ", "Россия"]

    milk, bags = results["items"]
    names = [o["supplier"]["name"] for o in milk["offers"]]
    assert len(names) == 2  # top_k
    assert "Старый завод" not in names  # ликвидирован — выкинут
    assert [o["rank"] for o in milk["offers"]] == [1, 2]

    best = milk["offers"][0]
    assert best["supplier"]["name"] == "ООО «Агро-Молоко»"
    assert best["supplier"]["is_safe"] and best["supplier"]["is_popular"]
    assert Decimal(best["supplier"]["safety_rating"]) >= Decimal("4.0")
    assert Decimal(best["estimated_cost"]) == Decimal("900000.00")  # 450 000 ₽/т * 2 т
    assert set(best["score_breakdown"]) == {"match", "proximity", "safety", "price", "delivery_time", "completeness"}

    # Срок доставки с сайта сохранился и дал бонус в формуле
    moltorg = milk["offers"][1]
    assert moltorg["supplier"]["delivery_time"] == "2-3 рабочих дня"
    assert moltorg["score_breakdown"]["delivery_time"] == 1.0
    assert best["score_breakdown"]["delivery_time"] == 0.0

    # Один поставщик в двух категориях — это одна запись в справочнике
    assert best["supplier"]["id"] in {o["supplier"]["id"] for o in bags["offers"]}

    assert Decimal(results["estimated_total"]) == Decimal("900000.00")
    assert results["priced_items"] == 1


def test_one_active_search_per_user(client, mailer):
    headers, order = _setup_order(client, mailer)
    client.put(f"{API}/orders/{order['id']}/delivery", json={}, headers=headers)
    second = client.post(f"{API}/orders", json={}, headers=headers).json()
    client.post(f"{API}/orders/{second['id']}/items", json={"custom_title": "Соль"}, headers=headers)
    client.put(f"{API}/orders/{second['id']}/delivery", json={}, headers=headers)

    from app.db.session import SessionFactory
    from app.models import Order, OrderStatus

    async def mark_searching():
        async with SessionFactory() as session:
            (await session.get(Order, order["id"])).status = OrderStatus.SEARCHING
            await session.commit()

    client.portal.call(mark_searching)
    res = client.post(f"{API}/orders/{second['id']}/search", headers=headers)
    assert res.status_code == 409 and "уже идёт поиск" in res.json()["detail"]


def test_letters_one_per_supplier_without_personal_data(client, mailer, fake_llm):
    headers, order = _setup_order(client, mailer)
    results = _run_search(client, headers, order["id"])
    milk, bags = results["items"]
    agro_id = milk["offers"][0]["supplier"]["id"]

    chosen = [milk["offers"][0]["id"], milk["offers"][1]["id"]]
    chosen += [o["id"] for o in bags["offers"] if o["supplier"]["id"] == agro_id]

    res = client.post(f"{API}/orders/{order['id']}/letters", json={"offer_ids": chosen}, headers=headers)
    assert res.status_code == 201, res.text
    letters = res.json()
    assert len(letters) == 2  # Агро-Молоко (2 позиции в одном письме) + МолТорг

    agro_letter = next(l for l in letters if l["supplier_id"] == agro_id)
    assert "Молочная продукция" in agro_letter["body"] and "Крафт-пакеты" in agro_letter["body"]
    assert "[ФИО]" in agro_letter["body"]  # подпись с пустыми полями добавлена

    # Личные данные пользователя в LLM не уходили
    assert not any("ivan@test.ru" in p or "Иван" in p for p in fake_llm.prompts)

    download = client.get(f"{API}/letters/{agro_letter['id']}/download", headers=headers)
    assert download.headers["content-type"].startswith("text/plain")
    assert download.text.startswith("Тема: ")

    # Заказ завершён и менять его уже нельзя
    assert client.get(f"{API}/orders/{order['id']}", headers=headers).json()["status"] == "completed"
    assert client.post(f"{API}/orders/{order['id']}/items", json={"custom_title": "Соль"},
                       headers=headers).status_code == 409


def test_letters_reject_foreign_offers_and_bad_template(client, mailer):
    headers, order = _setup_order(client, mailer)
    results = _run_search(client, headers, order["id"])
    url = f"{API}/orders/{order['id']}/letters"
    assert client.post(url, json={"offer_ids": [99999]}, headers=headers).status_code == 404

    offer_id = results["items"][0]["offers"][0]["id"]
    for template in ["../../../etc/passwd", "../../core/config", "default.txt", "нет-такого"]:
        res = client.post(url, json={"offer_ids": [offer_id], "template": template}, headers=headers)
        assert res.status_code == 404, template


def test_offer_note_and_selection(client, mailer):
    headers, order = _setup_order(client, mailer)
    offer = _run_search(client, headers, order["id"])["items"][0]["offers"][1]
    res = client.patch(f"{API}/offers/{offer['id']}", json={"is_selected": True, "user_note": "Позвонить в пн"},
                       headers=headers)
    assert res.status_code == 200
    assert res.json()["user_note"] == "Позвонить в пн"

    # Выбранное предложение участвует в итоговой сумме вместо лучшего (у него цена за кг)
    results = client.get(f"{API}/orders/{order['id']}/results", headers=headers).json()
    assert Decimal(results["estimated_total"]) == Decimal("800000.00")  # 400 ₽/кг * 2000 кг


def test_editing_cart_requires_new_search(client, mailer):
    headers, order = _setup_order(client, mailer)
    results = _run_search(client, headers, order["id"])
    item_id = results["items"][0]["item"]["id"]
    res = client.patch(f"{API}/orders/{order['id']}/items/{item_id}", json={"quantity": 3}, headers=headers)
    assert res.json()["status"] == "draft"


def test_users_cannot_see_each_other(client, mailer):
    """Чужие заказы, предложения и письма выглядят как несуществующие."""
    owner, order = _setup_order(client, mailer)
    results = _run_search(client, owner, order["id"])
    offer_id = results["items"][0]["offers"][0]["id"]
    letter = client.post(f"{API}/orders/{order['id']}/letters", json={"offer_ids": [offer_id]}, headers=owner).json()[0]

    stranger = make_user(client, mailer, "stranger@test.ru")
    oid = order["id"]
    checks = [
        ("get", f"/orders/{oid}", None),
        ("get", f"/orders/{oid}/results", None),
        ("patch", f"/orders/{oid}", {"top_k": 1}),
        ("put", f"/orders/{oid}/delivery", {}),
        ("post", f"/orders/{oid}/items", {"custom_title": "Взлом"}),
        ("post", f"/orders/{oid}/search", None),
        ("patch", f"/offers/{offer_id}", {"user_note": "чужое"}),
        ("get", f"/orders/{oid}/letters", None),
        ("get", f"/letters/{letter['id']}", None),
        ("get", f"/letters/{letter['id']}/download", None),
    ]
    for method, path, body in checks:
        kwargs = {"headers": stranger} | ({"json": body} if body is not None else {})
        res = getattr(client, method)(f"{API}{path}", **kwargs)
        assert res.status_code == 404, (method, path, res.status_code)

    # И в своей истории чужих заказов нет
    assert client.get(f"{API}/orders", headers=stranger).json()["total"] == 0


def test_input_hardening(client, mailer):
    """Найдено ручным тестом: NUL-байт ронял запрос с 500, лишние поля молча игнорировались."""
    headers = make_user(client, mailer)
    order = client.post(f"{API}/orders", json={}, headers=headers).json()
    url = f"{API}/orders/{order['id']}/items"

    assert client.post(url, json={"custom_title": "Мука\u0000DROP"}, headers=headers).status_code == 422
    assert client.post(url, json={"custom_title": "Соль", "is_admin": True}, headers=headers).status_code == 422
    assert client.patch(f"{API}/users/me", json={"email": "evil@test.ru"}, headers=headers).status_code == 422
    assert client.post(f"{API}/auth/login", data={"username": "a\u0000b", "password": "x"}).status_code == 401

    # SQL и HTML хранятся как обычный текст (экранирование — забота фронта при выводе)
    res = client.post(url, json={"custom_title": "'; DROP TABLE users; --"}, headers=headers)
    assert res.status_code == 201
    assert client.get(f"{API}/users/me", headers=headers).status_code == 200


def test_llm_output_nul_is_stripped():
    from app.schemas.llm import ExtractedSupplier
    s = ExtractedSupplier.model_validate({"name": "Ромаш\u0000ка", "match": "exact", "phones": ["+7\u0000"]})
    assert s.name == "Ромашка" and s.phones == ["+7"]


def test_letters_do_not_hold_db_connection(client, mailer, fake_llm):
    from app.db.session import engine
    headers, order = _setup_order(client, mailer)
    results = _run_search(client, headers, order["id"])
    busy = []
    fake_llm.on_call = lambda: busy.append(engine.pool.checkedout())
    offer_ids = [results["items"][0]["offers"][0]["id"], results["items"][0]["offers"][1]["id"]]
    assert client.post(f"{API}/orders/{order['id']}/letters", json={"offer_ids": offer_ids}, headers=headers).status_code == 201
    assert busy and set(busy) == {0}, busy
