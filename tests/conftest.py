import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://tcc_test:tcc_test_only_password"
    "@127.0.0.1:55432/plataforma_tcc_test"
)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def _validate_test_database_url(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("Os testes exigem um PostgreSQL dedicado.")
    if url.database != "plataforma_tcc_test":
        raise RuntimeError(
            "TEST_DATABASE_URL deve apontar exatamente para "
            "o banco isolado 'plataforma_tcc_test'."
        )
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "O banco de testes deve estar no host local; "
            "hosts externos não são permitidos."
        )
    if url.port != 55432:
        raise RuntimeError(
            "Os testes aceitam somente a porta 55432 do PostgreSQL isolado."
        )
    if url.username != "tcc_test":
        raise RuntimeError(
            "Os testes aceitam somente o usuário descartável 'tcc_test'."
        )


_validate_test_database_url(TEST_DATABASE_URL)
test_url = make_url(TEST_DATABASE_URL)

# Prevent the application from loading development credentials or JWT secrets
# from .env when its settings module is imported below.
os.environ["POSTGRES_USER"] = test_url.username or "tcc_test"
os.environ["POSTGRES_PASSWORD"] = test_url.password or "tcc_test_only_password"
os.environ["POSTGRES_DB"] = test_url.database or "plataforma_tcc_test"
os.environ["POSTGRES_HOST"] = test_url.host or "127.0.0.1"
os.environ["POSTGRES_PORT"] = str(test_url.port or 55432)
os.environ["JWT_SECRET_KEY"] = "pytest-only-secret-never-use-outside-tests"

import app.models  # noqa: E402,F401  Ensure every model is registered.
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)


@pytest.fixture(scope="session", autouse=True)
def test_database_schema() -> Generator[None, None, None]:
    """Create/drop only schema in the guarded test database, never migrate."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def db_session(test_database_schema: None) -> Generator[Session, None, None]:
    """Rollback each test's work, including commits made by application code."""
    with test_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def create_user(client: TestClient):
    counter = 0

    def _create_user(
        *,
        username: str | None = None,
        email: str | None = None,
        password: str = "Teste-Seguro-123!",
    ) -> dict:
        nonlocal counter
        counter += 1
        chosen_username = username or f"tester_{counter}"
        chosen_email = email or f"{chosen_username}@example.com"
        response = client.post(
            "/users/",
            json={
                "username": chosen_username,
                "email": chosen_email,
                "password": password,
                "birth_date": "1995-04-12",
            },
        )
        assert response.status_code == 201, response.text
        return {
            "id": response.json()["id"],
            "username": chosen_username,
            "email": chosen_email,
            "password": password,
        }

    return _create_user


@pytest.fixture
def auth_headers(client: TestClient, create_user):
    def _auth_headers(user: dict) -> dict[str, str]:
        response = client.post(
            "/users/login",
            json={"login": user["username"], "password": user["password"]},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _auth_headers
