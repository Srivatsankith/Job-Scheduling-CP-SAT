"""MongoDB persistence for the DynamiQ dashboard."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@lru_cache(maxsize=1)
def client() -> MongoClient:
    uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017").strip()
    if not uri:
        raise RuntimeError("MONGODB_URI is empty. Set it in backend/.env.")
    return MongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True)


def database():
    name = os.getenv("MONGODB_DATABASE", "dynamiq").strip()
    if not name:
        raise RuntimeError("MONGODB_DATABASE is empty. Set it in backend/.env.")
    return client()[name]


def initialize() -> None:
    client().admin.command("ping")
    db = database()
    db.resources.create_index([("kind", ASCENDING), ("active", ASCENDING)])
    db.tasks.create_index([("batch_id", ASCENDING), ("position", ASCENDING)])
    db.archived_tasks.create_index([("batch_id", ASCENDING), ("position", ASCENDING)])


def check_connection() -> None:
    client().admin.command("ping")


def _rows_collection(model: str) -> Collection:
    if model not in {"tasks", "archived_tasks"}:
        raise ValueError("Unsupported dashboard collection.")
    return database()[model]


def get_resources(kind: str | None = None, include_inactive: bool = True) -> list[dict]:
    query: dict = {}
    if kind is not None:
        query["kind"] = kind
    if not include_inactive:
        query["active"] = True
    rows = database().resources.find(query).sort([("kind", ASCENDING), ("id", ASCENDING)])
    return [
        {"kind": row["kind"], "id": row["id"], "name": row["name"], "active": row["active"], "data": row.get("data", {})}
        for row in rows
    ]


def save_resource(kind: str, row: dict, *, create_only: bool = False) -> bool:
    collection = database().resources
    resource_id = f"resource:{kind}:{row['id']}"
    document = {
        "_id": resource_id,
        "kind": kind,
        "id": row["id"],
        "name": row["name"],
        "active": row.get("active", True),
        "data": row.get("data", {}),
    }
    if create_only:
        try:
            collection.insert_one(document)
            return True
        except DuplicateKeyError:
            return False
    result = collection.replace_one({"_id": resource_id}, document, upsert=False)
    return result.matched_count > 0


def set_resource_active(kind: str, resource_id: str, active: bool) -> bool:
    result = database().resources.update_one(
        {"_id": f"resource:{kind}:{resource_id}"}, {"$set": {"active": active}}
    )
    return result.matched_count > 0


def remove_resource(kind: str, resource_id: str) -> bool:
    result = database().resources.delete_one({"_id": f"resource:{kind}:{resource_id}"})
    return result.deleted_count > 0


def get_rows(collection_name: str) -> list[dict]:
    collection = _rows_collection(collection_name)
    state = collection.find_one({"_id": "__state__"})
    if not state or not state.get("active_batch"):
        return []
    documents = collection.find({"batch_id": state["active_batch"]}).sort("position", ASCENDING)
    return [document["data"] for document in documents]


def replace_rows(collection_name: str, id_field: str, rows: list[dict]) -> None:
    ids = [str(row.get(id_field, "")).strip() for row in rows]
    if any(not value for value in ids) or len({value.casefold() for value in ids}) != len(ids):
        raise ValueError(f"{id_field} values must be non-empty and unique.")

    collection = _rows_collection(collection_name)
    previous = collection.find_one({"_id": "__state__"})
    batch_id = uuid4().hex
    try:
        if rows:
            collection.insert_many([
                {"_id": f"{batch_id}:item:{row[id_field]}", "batch_id": batch_id, "position": index, "data": row}
                for index, row in enumerate(rows)
            ])
        collection.replace_one(
            {"_id": "__state__"}, {"_id": "__state__", "active_batch": batch_id}, upsert=True
        )
    except Exception:
        collection.delete_many({"batch_id": batch_id})
        raise

    previous_batch = previous.get("active_batch") if previous else None
    if previous_batch and previous_batch != batch_id:
        collection.delete_many({"batch_id": previous_batch})


def get_latest_schedule() -> dict | None:
    row = database().schedule_state.find_one({"_id": "latest"})
    return row.get("data") if row else None


def save_latest_schedule(data: dict) -> None:
    database().schedule_state.replace_one({"_id": "latest"}, {"_id": "latest", "data": data}, upsert=True)
