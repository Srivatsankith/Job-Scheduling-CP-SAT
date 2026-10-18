import unittest
from unittest.mock import patch

from pymongo.errors import DuplicateKeyError

from src import mongo_store


class FakeCollection:
    def __init__(self):
        self.documents = {}

    def create_index(self, *_args, **_kwargs):
        return "fake-index"

    def find_one(self, query):
        return next((doc.copy() for doc in self.documents.values() if self._matches(doc, query)), None)

    def find(self, query=None):
        docs = [doc.copy() for doc in self.documents.values() if self._matches(doc, query or {})]
        return FakeCursor(docs)

    def insert_one(self, document):
        if document["_id"] in self.documents:
            raise DuplicateKeyError("duplicate _id")
        self.documents[document["_id"]] = document.copy()

    def insert_many(self, documents):
        for document in documents:
            self.insert_one(document)

    def replace_one(self, query, document, upsert=False):
        match = next((key for key, doc in self.documents.items() if self._matches(doc, query)), None)
        if match is None:
            if upsert:
                self.insert_one(document)
            return FakeResult(0)
        if match != document["_id"] and document["_id"] in self.documents:
            raise DuplicateKeyError("duplicate _id")
        del self.documents[match]
        self.documents[document["_id"]] = document.copy()
        return FakeResult(1)

    def update_one(self, query, update):
        doc = next((doc for doc in self.documents.values() if self._matches(doc, query)), None)
        if doc is None:
            return FakeResult(0)
        doc.update(update.get("$set", {}))
        return FakeResult(1)

    def delete_one(self, query):
        key = next((key for key, doc in self.documents.items() if self._matches(doc, query)), None)
        if key is None:
            return FakeResult(0, 0)
        del self.documents[key]
        return FakeResult(1, 1)

    def delete_many(self, query):
        keys = [key for key, doc in self.documents.items() if self._matches(doc, query)]
        for key in keys:
            del self.documents[key]
        return FakeResult(len(keys), len(keys))

    @staticmethod
    def _matches(document, query):
        return all(document.get(key) == value for key, value in query.items())


class FakeCursor(list):
    def sort(self, fields, direction=None):
        if isinstance(fields, str):
            fields = [(fields, direction or 1)]
        for key, order in reversed(fields):
            super().sort(key=lambda item: item.get(key), reverse=order < 0)
        return self


class FakeResult:
    def __init__(self, matched_count, deleted_count=0):
        self.matched_count = matched_count
        self.deleted_count = deleted_count


class FakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getattr__(self, name):
        return self.collections.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


class TestMongoStore(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.database_patch = patch.object(mongo_store, "database", return_value=self.db)
        self.database_patch.start()

    def tearDown(self):
        self.database_patch.stop()

    def test_task_replacements_keep_order_and_only_expose_active_batch(self):
        first = [{"Job ID": "A", "Task": "First"}, {"Job ID": "B", "Task": "Second"}]
        second = [{"Job ID": "A", "Task": "Updated"}]

        mongo_store.replace_rows("tasks", "Job ID", first)
        mongo_store.replace_rows("tasks", "Job ID", second)

        self.assertEqual(mongo_store.get_rows("tasks"), second)
        self.assertEqual(len(self.db.tasks.documents), 2)  # state pointer and active row

    def test_empty_task_replacement_clears_active_rows(self):
        mongo_store.replace_rows("archived_tasks", "Job ID", [{"Job ID": "A"}])
        mongo_store.replace_rows("archived_tasks", "Job ID", [])
        self.assertEqual(mongo_store.get_rows("archived_tasks"), [])

    def test_task_ids_must_be_nonempty_and_case_insensitively_unique(self):
        with self.assertRaises(ValueError):
            mongo_store.replace_rows("tasks", "Job ID", [{"Job ID": "A"}, {"Job ID": "a"}])

    def test_resource_create_update_deactivate_and_delete(self):
        resource = {"id": "M1", "name": "Mill", "active": True, "data": {"type": "CNC"}}
        self.assertTrue(mongo_store.save_resource("machines", resource, create_only=True))
        self.assertFalse(mongo_store.save_resource("machines", resource, create_only=True))
        self.assertEqual(mongo_store.get_resources("machines")[0]["data"], {"type": "CNC"})

        updated = {**resource, "name": "Updated mill"}
        self.assertTrue(mongo_store.save_resource("machines", updated))
        self.assertTrue(mongo_store.set_resource_active("machines", "M1", False))
        self.assertEqual(mongo_store.get_resources("machines")[0]["active"], False)
        self.assertEqual(mongo_store.get_resources("machines", include_inactive=False), [])
        self.assertTrue(mongo_store.remove_resource("machines", "M1"))
        self.assertEqual(mongo_store.get_resources("machines"), [])

    def test_latest_schedule_is_upserted(self):
        mongo_store.save_latest_schedule({"runs": 1})
        mongo_store.save_latest_schedule({"runs": 2})
        self.assertEqual(mongo_store.get_latest_schedule(), {"runs": 2})


if __name__ == "__main__":
    unittest.main()
