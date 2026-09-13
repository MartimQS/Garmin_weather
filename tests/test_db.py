from advisor.db import get_connection, record_report, upsert, was_report_sent


def test_upsert_inserts_and_updates_without_duplicating(tmp_path):
    db_path = str(tmp_path / "test.db")
    with get_connection(db_path) as conn:
        upsert(conn, "daily_health", ["date"], {"date": "2024-05-10", "steps": 1000, "ingested_at": "t1"})
        upsert(conn, "daily_health", ["date"], {"date": "2024-05-10", "steps": 2000, "ingested_at": "t2"})
        rows = conn.execute("SELECT * FROM daily_health").fetchall()
        assert len(rows) == 1
        assert rows[0]["steps"] == 2000
        assert rows[0]["ingested_at"] == "t2"


def test_report_log_dedup(tmp_path):
    db_path = str(tmp_path / "test.db")
    with get_connection(db_path) as conn:
        assert was_report_sent(conn, "daily", "2024-05-10") is False
        record_report(conn, "daily", "2024-05-10", "sent")
        assert was_report_sent(conn, "daily", "2024-05-10") is True


def test_db_persists_across_connections(tmp_path):
    db_path = str(tmp_path / "test.db")
    with get_connection(db_path) as conn:
        upsert(conn, "daily_health", ["date"], {"date": "2024-05-10", "steps": 1000, "ingested_at": "t1"})
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM daily_health").fetchall()
        assert len(rows) == 1
