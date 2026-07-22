# FastAPI Backend Adapter

Use only when the repository fingerprint confirms FastAPI.

## Quick orientation

```bash
# Confirm FastAPI and async stack
grep -E "fastapi|uvicorn|pydantic|sqlalchemy|asyncpg|httpx" requirements*.txt pyproject.toml
python -c "import fastapi; print(fastapi.__version__)"

# Find routers and test setup
find . -name "*.py" | xargs grep -l "APIRouter\|@app\." | grep -v test | head -20
find . -name "conftest.py" | head -5
cat conftest.py 2>/dev/null
```

## Test client setup

FastAPI's `TestClient` uses `httpx` under the hood. For async endpoints use `AsyncClient`:

```python
# Sync (most common — wraps async in event loop)
from fastapi.testclient import TestClient
client = TestClient(app)

# Async (when you need to test async dependencies properly)
import pytest
import httpx

@pytest.fixture
async def async_client():
    async with httpx.AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.mark.anyio
async def test_create_order(async_client, db_session):
    response = await async_client.post("/orders/", json={"item": "widget"})
    assert response.status_code == 201
```

## Dependency injection overrides — the right way

```python
# Override a dependency for a test without modifying production code
from app.dependencies import get_db

def override_get_db():
    yield test_db_session

app.dependency_overrides[get_db] = override_get_db

# Clean up after test
def teardown():
    app.dependency_overrides.clear()
```

## Pydantic v2 validation checks

```python
from pydantic import ValidationError

# Test model validation directly
def test_rejects_negative_price():
    with pytest.raises(ValidationError) as exc_info:
        OrderRequest(price=-1.0, quantity=1)
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("price",) for e in errors)

# Check response model serialization
response = client.get("/orders/1")
# Confirm no extra fields leak (model_config = ConfigDict(extra="forbid"))
assert set(response.json().keys()) == {"id", "item", "price", "status"}
```

## Authorization pattern

```python
# OAuth2 / API key dependency test
from app.auth import get_current_user

async def mock_auth():
    return User(id=1, role="admin")

app.dependency_overrides[get_current_user] = mock_auth

# Test unauthorized path explicitly
def test_requires_auth():
    response = client.get("/admin/stats")  # no override
    assert response.status_code == 401
```

## Async DB checks (SQLAlchemy 2 async)

```bash
# Confirm async engine is used
grep -r "create_async_engine\|AsyncSession\|async_sessionmaker" app/ --include="*.py"
```

```python
# Test DB interaction with rollback isolation
@pytest.fixture
async def db_session(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(conn) as session:
            yield session
            await session.rollback()
```

## Common FastAPI failure paths

1. **Background tasks fire after response**: `BackgroundTasks` run after `return` — don't assert side effects synchronously
2. **422 vs 400**: Pydantic validation failures return 422 (Unprocessable Entity), not 400 — assert correctly
3. **Middleware order**: auth middleware runs before route — wrong order lets unauthenticated requests through
4. **OpenAPI schema drift**: adding a field to a Pydantic model changes the schema; check downstream clients
5. **CORS**: `CORSMiddleware` must be added before route declarations for correct ordering

## Commands

```bash
# Run tests
pytest tests/ -v

# Coverage
pytest --cov=app tests/

# Type checking (if mypy configured)
mypy app/

# API schema validation
python -c "from app.main import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
```
