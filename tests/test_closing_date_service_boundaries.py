from app.models.settings import Settings
from app.services.closing_date import get_closing_date


def test_get_closing_date_handles_missing_and_invalid_values(db_session):
    assert get_closing_date(db_session) is None
    db_session.add(Settings(key="closing_date", value="not-a-date"))
    db_session.commit()
    assert get_closing_date(db_session) is None
