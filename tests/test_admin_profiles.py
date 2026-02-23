from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel import select

from app.models import ComfortModelMeta, ComfortRating, DailyDigestLog, UserProfile
from app.services.app_logic import AppLogic


def test_duplicate_user_profile_groups_case_insensitive_city():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    logic = AppLogic()

    with Session(engine) as session:
        session.add(UserProfile(telegram_id=1, city="Gothenburg", lat=1.0, lon=2.0, station_id=100))
        session.add(UserProfile(telegram_id=2, city=" gothenburg ", lat=1.1, lon=2.1, station_id=100))
        session.add(UserProfile(telegram_id=3, city="Stockholm", lat=3.0, lon=4.0, station_id=200))
        session.commit()

        groups = logic.duplicate_user_profile_groups(session)

    assert len(groups) == 1
    assert {row.telegram_id for row in groups[0]} == {1, 2}


def test_remove_duplicate_user_profile_keeps_primary_and_cleans_user_rows():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    logic = AppLogic()

    with Session(engine) as session:
        primary = UserProfile(telegram_id=10, city="Gothenburg", lat=1.0, lon=2.0, station_id=100)
        duplicate = UserProfile(telegram_id=20, city="Gothenburg", lat=1.1, lon=2.1, station_id=100)
        session.add(primary)
        session.add(duplicate)
        session.commit()
        session.refresh(primary)
        session.refresh(duplicate)

        session.add(
            ComfortRating(
                telegram_id=duplicate.telegram_id,
                rating=3,
                activity="walking",
                minutes_outside=30,
                weather_feature_snapshot={"t": 0.0},
            )
        )
        session.add(ComfortModelMeta(telegram_id=duplicate.telegram_id, sample_count=1, metrics={"ready": True}))
        session.add(DailyDigestLog(telegram_id=duplicate.telegram_id, date=date.today(), payload_hash="abc"))
        session.commit()

        removed = logic.remove_duplicate_user_profile(session, duplicate.id)
        assert removed.id == duplicate.id

        assert session.get(UserProfile, primary.id) is not None
        assert session.get(UserProfile, duplicate.id) is None
        assert not session.exec(
            select(ComfortRating).where(ComfortRating.telegram_id == duplicate.telegram_id)
        ).all()
        assert (
            session.exec(select(ComfortModelMeta).where(ComfortModelMeta.telegram_id == duplicate.telegram_id)).first()
            is None
        )
        assert not session.exec(
            select(DailyDigestLog).where(DailyDigestLog.telegram_id == duplicate.telegram_id)
        ).all()


def test_remove_duplicate_user_profile_rejects_primary():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    logic = AppLogic()

    with Session(engine) as session:
        primary = UserProfile(telegram_id=100, city="Gothenburg", lat=1.0, lon=2.0, station_id=100)
        duplicate = UserProfile(telegram_id=200, city="Gothenburg", lat=1.1, lon=2.1, station_id=100)
        session.add(primary)
        session.add(duplicate)
        session.commit()
        session.refresh(primary)

        with pytest.raises(ValueError, match="refusing to delete primary profile"):
            logic.remove_duplicate_user_profile(session, primary.id)
