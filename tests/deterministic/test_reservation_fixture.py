from __future__ import annotations

import importlib.util
import threading
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "reservation_benchmark_verify",
    ROOT / "benchmarks" / "reservation-flow" / "seed" / "benchmark_verify.py",
)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class Conflict(Exception):
    pass


class ReferenceService:
    stores: dict[str, dict] = {}
    locks: dict[str, threading.Lock] = {}

    def __init__(self, path: str):
        self.path = path
        self.store = self.stores.setdefault(path, {"resources": {}, "reservations": {}, "keys": {}})
        self.lock = self.locks.setdefault(path, threading.Lock())

    def create_resource(self, resource_id: str, capacity: int) -> None:
        with self.lock:
            self.store["resources"].setdefault(resource_id, capacity)

    def reserve(self, resource_id: str, start: int, end: int, seats: int, idempotency_key: str) -> dict:
        if end <= start:
            raise ValueError("invalid interval")
        request = (resource_id, start, end, seats)
        with self.lock:
            if idempotency_key in self.store["keys"]:
                previous_request, reservation_id = self.store["keys"][idempotency_key]
                if previous_request != request:
                    raise Conflict("idempotency conflict")
                return dict(self.store["reservations"][reservation_id])
            used = sum(
                item["seats"]
                for item in self.store["reservations"].values()
                if item["resource_id"] == resource_id
                and item["status"] == "active"
                and item["start"] < end
                and start < item["end"]
            )
            if used + seats > self.store["resources"][resource_id]:
                raise Conflict("capacity exceeded")
            reservation_id = uuid.uuid4().hex
            item = {
                "id": reservation_id,
                "resource_id": resource_id,
                "start": start,
                "end": end,
                "seats": seats,
                "status": "active",
                "idempotency_key": idempotency_key,
            }
            self.store["reservations"][reservation_id] = item
            self.store["keys"][idempotency_key] = (request, reservation_id)
            return dict(item)

    def get_reservation(self, reservation_id: str) -> dict:
        with self.lock:
            return dict(self.store["reservations"][reservation_id])

    def cancel(self, reservation_id: str) -> dict:
        with self.lock:
            self.store["reservations"][reservation_id]["status"] = "cancelled"
            return dict(self.store["reservations"][reservation_id])


class ReservationFixtureTest(unittest.TestCase):
    def test_external_contract_accepts_a_concurrent_persistent_reference(self) -> None:
        report = VERIFY.validate(ReferenceService, Conflict)

        self.assertEqual("PASS", report["verdict"])
        self.assertEqual(5, len(report["checks"]))


if __name__ == "__main__":
    unittest.main()
