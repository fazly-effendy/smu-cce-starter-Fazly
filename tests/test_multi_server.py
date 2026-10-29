"""Several app servers sharing one database (preparation for Feature 6, scaling).

With more than one app server behind a load balancer, two servers can save at the
same moment, and every server holds its own pool of database connections.
"""

from __future__ import annotations

import pytest

from storage import briefing_store, database
from test_storage import make_briefing, make_note


def test_two_servers_saving_a_new_client_at_once_both_succeed(monkeypatch):
    """Server B creates client C-2001 between server A's check and server A's insert.

    Before the fix, server A's save failed with a duplicate-key error and the RM saw an
    error, although nothing was wrong. Now server A retries and links to the existing client.
    """
    original = database._ensure_client
    calls = {"n": 0}

    def other_server_wins_the_race(connection, client_id, client_name, now):
        calls["n"] += 1
        if calls["n"] == 1:
            with database.get_engine().begin() as other_server:  # server B, its own connection
                other_server.execute(database.clients.insert().values(
                    client_id=client_id, client_name=None, created_at=now))
            # Server A had already looked and found no client, so it inserts too.
            connection.execute(database.clients.insert().values(
                client_id=client_id, client_name=client_name, created_at=now))
            return
        original(connection, client_id, client_name, now)

    monkeypatch.setattr(database, "_ensure_client", other_server_wins_the_race)
    briefing = make_briefing()
    result = briefing_store.save_discussion(briefing, make_note("C-2001", client_name="Beta Pte Ltd"))
    assert result.created
    assert calls["n"] == 2  # failed once, then succeeded on the retry
    assert database.count_rows() == {"clients": 1, "discussions": 1, "discussion_companies": 2}
    assert database.list_clients() == [{"client_id": "C-2001", "client_name": "Beta Pte Ltd", "discussions": 1}]


def test_a_real_error_is_not_hidden_by_the_retry(monkeypatch):
    def always_fails(connection, client_id, client_name, now):
        raise database.IntegrityError("INSERT", {}, Exception("broken"))

    monkeypatch.setattr(database, "_ensure_client", always_fails)
    with pytest.raises(database.IntegrityError):
        briefing_store.save_discussion(make_briefing(), make_note("C-2002"))
    assert database.count_rows()["discussions"] == 0


def test_mysql_connections_per_server_are_capped():
    """db.t3.micro allows roughly 60-80 connections. At most 10 per server keeps
    3 servers (the planned maximum) well under that; idle connections are recycled."""
    options = database.engine_options("mysql+pymysql://user:pw@db.example:3306/nimbus")
    assert options["pool_size"] + options["max_overflow"] == 10
    assert options["pool_recycle"] <= 3600 and options["pool_pre_ping"]
    assert "pool_size" not in database.engine_options("sqlite:///nimbus.db")
