from tests.conftest import ADMIN_EMAIL


def test_list_admins_includes_current_user(client):
    response = client.get("/api/v1/users")
    assert response.status_code == 200
    assert [u["email"] for u in response.json()] == [ADMIN_EMAIL]
    assert "password_hash" not in response.json()[0]


def test_new_admin_can_sign_in(client, anon_client):
    response = client.post("/api/v1/users", json={"email": "Second@Example.com", "password": "another long password"})
    assert response.status_code == 201, response.text
    assert response.json()["email"] == "second@example.com"

    login = anon_client.post("/api/v1/auth/login", json={"email": "second@example.com", "password": "another long password"})
    assert login.status_code == 200


def test_rejects_duplicate_email_and_short_password(client):
    duplicate = client.post("/api/v1/users", json={"email": ADMIN_EMAIL.upper(), "password": "another long password"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["details"][0]["field"] == "email"

    short = client.post("/api/v1/users", json={"email": "x@example.com", "password": "short"})
    assert short.status_code == 422


def test_remove_admin_but_not_yourself(client):
    me = client.get("/api/v1/auth/me").json()
    assert client.delete(f"/api/v1/users/{me['id']}").status_code == 400

    other = client.post("/api/v1/users", json={"email": "gone@example.com", "password": "another long password"}).json()
    assert client.delete(f"/api/v1/users/{other['id']}").status_code == 204
    assert [u["email"] for u in client.get("/api/v1/users").json()] == [ADMIN_EMAIL]


def test_requires_sign_in_and_csrf(client, anon_client):
    assert anon_client.get("/api/v1/users").status_code == 401
    del client.headers["X-CSRF-Token"]
    assert client.post("/api/v1/users", json={"email": "x@example.com", "password": "another long password"}).status_code == 403
