from django.db import connection
from django.test import TestCase
from django.utils import timezone


class PrintJobTableTests(TestCase):
    """
    Lightweight integration tests that validate read/write operations for the
    user_print_jobs and vendor_print_jobs tables. The tables are created
    temporarily inside the Django test database so we can assert that data
    persistence works end-to-end without touching production data.
    """

    user_table = "user_print_jobs"
    vendor_table = "vendor_print_jobs"

    def setUp(self):
        self._create_tables()

    def tearDown(self):
        self._drop_tables()

    def _create_tables(self):
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.user_table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    copies INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.vendor_table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _drop_tables(self):
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {self.user_table}")
            cursor.execute(f"DROP TABLE IF EXISTS {self.vendor_table}")

    def test_user_print_jobs_accepts_new_rows(self):
        now = timezone.now().isoformat()
        sample = {
            "user_email": "demo@example.com",
            "file_name": "thesis.pdf",
            "copies": 2,
            "created_at": now,
        }

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {self.user_table} (user_email, file_name, copies, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [
                    sample["user_email"],
                    sample["file_name"],
                    sample["copies"],
                    sample["created_at"],
                ],
            )
            cursor.execute(
                f"""
                SELECT user_email, file_name, copies, created_at
                FROM {self.user_table}
                """
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], sample["user_email"])
        self.assertEqual(row[1], sample["file_name"])
        self.assertEqual(row[2], sample["copies"])
        self.assertEqual(row[3], sample["created_at"])

    def test_vendor_print_jobs_accepts_new_rows(self):
        now = timezone.now().isoformat()
        sample = {
            "vendor_id": "vendor-123",
            "file_name": "poster.pdf",
            "status": "pending",
            "created_at": now,
        }

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {self.vendor_table} (vendor_id, file_name, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [
                    sample["vendor_id"],
                    sample["file_name"],
                    sample["status"],
                    sample["created_at"],
                ],
            )
            cursor.execute(
                f"""
                SELECT vendor_id, file_name, status, created_at
                FROM {self.vendor_table}
                """
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], sample["vendor_id"])
        self.assertEqual(row[1], sample["file_name"])
        self.assertEqual(row[2], sample["status"])
        self.assertEqual(row[3], sample["created_at"])
