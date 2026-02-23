from sqlmodel import Session, SQLModel, create_engine

from app.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _run_sqlite_compat_migrations()


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _index_exists(conn, index_name: str) -> bool:
    row = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=:name",
        {"name": index_name},
    ).fetchone()
    return row is not None


def _run_sqlite_compat_migrations() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        user_additions = [
            ("weather_provider", "TEXT NOT NULL DEFAULT 'smhi'"),
            ("location_key", "TEXT NOT NULL DEFAULT ''"),
            ("country_code", "TEXT"),
            ("history_ready", "INTEGER NOT NULL DEFAULT 0"),
            ("history_last_refreshed_at", "TEXT"),
        ]
        for col, spec in user_additions:
            if not _column_exists(conn, "userprofile", col):
                conn.exec_driver_sql(f"ALTER TABLE userprofile ADD COLUMN {col} {spec}")

        obs_additions = [
            ("location_key", "TEXT NOT NULL DEFAULT ''"),
            ("provider", "TEXT NOT NULL DEFAULT 'smhi'"),
        ]
        for col, spec in obs_additions:
            if not _column_exists(conn, "obsdaily", col):
                conn.exec_driver_sql(f"ALTER TABLE obsdaily ADD COLUMN {col} {spec}")

        fc_additions = [
            ("location_key", "TEXT NOT NULL DEFAULT ''"),
            ("provider", "TEXT NOT NULL DEFAULT 'smhi'"),
        ]
        for col, spec in fc_additions:
            if not _column_exists(conn, "forecasthourly", col):
                conn.exec_driver_sql(f"ALTER TABLE forecasthourly ADD COLUMN {col} {spec}")

        if not _index_exists(conn, "ix_obsdaily_location_key_date"):
            conn.exec_driver_sql("CREATE INDEX ix_obsdaily_location_key_date ON obsdaily (location_key, date)")
        if not _index_exists(conn, "ix_forecasthourly_location_key_valid_time"):
            conn.exec_driver_sql(
                "CREATE INDEX ix_forecasthourly_location_key_valid_time ON forecasthourly (location_key, valid_time)"
            )

        conn.exec_driver_sql(
            "UPDATE userprofile SET weather_provider='smhi' WHERE weather_provider IS NULL OR weather_provider=''"
        )
        conn.exec_driver_sql("UPDATE userprofile SET location_key='' WHERE location_key IS NULL")
        conn.exec_driver_sql(
            "UPDATE userprofile SET location_key='smhi:station:' || station_id "
            "WHERE (location_key='' OR location_key IS NULL) AND station_id IS NOT NULL"
        )


def get_session():
    with Session(engine) as session:
        yield session
