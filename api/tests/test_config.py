import pytest
from pydantic import ValidationError

from lms.config import Settings


def test_today_is_melbournes_unless_told_otherwise():
    assert Settings().timezone == "Australia/Melbourne"


def test_an_unknown_time_zone_refuses_to_start():
    with pytest.raises(ValidationError, match="not a time zone"):
        Settings(timezone="Australia/Ballarat")


def test_another_real_time_zone_is_fine():
    assert Settings(timezone="Australia/Perth").timezone == "Australia/Perth"
