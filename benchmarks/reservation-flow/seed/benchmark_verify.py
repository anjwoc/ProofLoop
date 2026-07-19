from __future__ import annotations

import importlib
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate(factory: Callable[[str], Any], conflict_type: type[BaseException]) -> dict[str, Any]:
    checks: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        database = str(Path(tmp) / "reservations.sqlite3")
        service = factory(database)
        service.create_resource("room-a", 2)
        first = service.reserve("room-a", 100, 200, 1, "idem-1")
        repeated = service.reserve("room-a", 100, 200, 1, "idem-1")
        require(first["id"] == repeated["id"], "same idempotency request must return the original reservation")
        checks.append("idempotency")

        try:
            service.reserve("room-a", 100, 201, 1, "idem-1")
        except conflict_type:
            pass
        else:
            raise AssertionError("idempotency key reuse with different parameters must fail")

        reopened = factory(database)
        require(reopened.get_reservation(first["id"])["status"] == "active", "reservation must persist across reopen")
        checks.append("persistence")

        reopened.create_resource("room-b", 2)

        def attempt(index: int) -> dict[str, Any] | None:
            try:
                return factory(database).reserve("room-b", 300, 400, 1, f"concurrent-{index}")
            except conflict_type:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        successful = [item for item in results if item is not None]
        require(len(successful) == 2, f"capacity 2 must allow exactly 2 overlapping reservations, got {len(successful)}")
        checks.append("concurrency-capacity")

        reopened.cancel(successful[0]["id"])
        reopened.cancel(successful[0]["id"])
        replacement = reopened.reserve("room-b", 300, 400, 1, "replacement")
        require(replacement["status"] == "active", "cancellation must release capacity")
        checks.append("idempotent-cancel")

        for invalid in ((400, 400), (500, 400)):
            try:
                reopened.reserve("room-b", invalid[0], invalid[1], 1, f"invalid-{invalid[0]}-{invalid[1]}")
            except Exception:
                pass
            else:
                raise AssertionError("invalid interval must fail")
        checks.append("validation")
    return {"verdict": "PASS", "checks": checks}


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("reservation_flow.service")
        service = getattr(module, "ReservationService")
        conflict = getattr(module, "ReservationConflict")
        report = validate(service, conflict)
    except Exception as exc:
        report = {"verdict": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
