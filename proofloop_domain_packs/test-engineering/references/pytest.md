# Pytest Testing Adapter

Use when the repository uses pytest. Verify with `grep -r "^import pytest\|^from pytest" tests/ | head -5`.

## Red-Green workflow — establish a failing test first

```bash
# Run a single test node before writing implementation
pytest tests/test_orders.py::test_create_order_returns_201 -v
# Expected: FAILED or ERROR (collection failure means syntax problem, not red)

# Run with output captured
pytest tests/test_orders.py -v -s 2>&1 | tail -30
```

**A red test that fails for the wrong reason is not a valid red.** Read the failure message before implementing.

## Fixture discipline

```python
# Confirm fixture scope before using — wrong scope causes contamination
@pytest.fixture(scope="function")  # default — safest, use unless slow
def db_session():
    session = create_test_session()
    yield session
    session.rollback()  # always clean up

@pytest.fixture(scope="module")  # only for expensive read-only setup
def read_only_catalog():
    return load_catalog_from_file()

# ❌ Never use scope="session" for mutable state
```

```python
# Check for autouse fixtures that silently affect your test
# grep -r "autouse=True" tests/conftest.py
@pytest.fixture(autouse=True)
def reset_cache():  # fires for every test — make sure yours is expected here
    cache.clear()
    yield
```

## Parametrize — control input space explicitly

```python
@pytest.mark.parametrize("price,qty,expected", [
    (10.0, 2, 20.0),    # happy path
    (0.0, 1, 0.0),       # boundary: zero price
    (-1.0, 1, None),     # invalid: negative price → None or exception
])
def test_order_total(price, qty, expected):
    if expected is None:
        with pytest.raises(ValueError):
            Order(price=price, quantity=qty)
    else:
        assert Order(price=price, quantity=qty).total == expected
```

## Nondeterminism control

```python
# Time — use freezegun
from freezegun import freeze_time

@freeze_time("2024-01-15 12:00:00")
def test_order_timestamp():
    order = create_order()
    assert order.created_at.date() == date(2024, 1, 15)

# Random — seed explicitly
import random
random.seed(42)

# Filesystem — use tmp_path (pytest built-in, no cleanup needed)
def test_writes_report(tmp_path):
    report_path = tmp_path / "report.json"
    write_report(report_path)
    assert report_path.exists()

# Network — use responses or httpretty or monkeypatch
def test_api_call(monkeypatch):
    monkeypatch.setattr("myapp.client.requests.get", lambda *a, **kw: MockResponse(200))
```

## Async tests

```python
# Confirm async test setup
# cat pyproject.toml | grep asyncio_mode  →  asyncio_mode = "auto" or require @pytest.mark.anyio

import pytest

@pytest.mark.asyncio  # or anyio if using anyio
async def test_fetch_orders():
    orders = await fetch_orders()
    assert len(orders) > 0

# For SQLAlchemy async
@pytest.fixture
async def db_session(engine):
    async with engine.begin() as conn:
        async with AsyncSession(conn) as session:
            yield session
            await session.rollback()
```

## Mutation testing — verify the test actually guards the behavior

```bash
# mutmut: check if tests detect mutations
pip install mutmut
mutmut run --paths-to-mutate=myapp/orders.py --tests-dir=tests/
mutmut results  # survivors = tests that didn't catch a mutation
```

If you can't run mutmut, manually verify: comment out the assertion or return a wrong value — the test must fail.

## Running patterns

```bash
# Focused — run only what changed
pytest tests/test_orders.py -v

# By marker
pytest -m "not slow" -v

# Last failed first
pytest --lf -v

# Stop on first failure
pytest -x tests/

# Coverage for a specific module
pytest tests/test_orders.py --cov=myapp.orders --cov-report=term-missing
```

## Anti-patterns

- Do not use `assert mock.called` — use `assert_called_once_with(expected_args)`
- Do not share mutable fixtures across test modules without `scope="function"`
- Do not test `assertEqual(mock.return_value, result)` — test the actual output, not the mock
- Do not use broad `monkeypatch.setattr("builtins.open", ...)` when `tmp_path` solves it
