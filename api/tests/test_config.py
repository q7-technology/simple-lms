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


def test_email_waits_until_there_is_a_host():
    s = Settings()
    assert (s.smtp_host, s.smtp_port, s.smtp_security) == ("", 587, "starttls")


def test_smtp_security_is_one_of_three():
    with pytest.raises(ValidationError):
        Settings(smtp_security="tls")
    assert Settings(smtp_security="ssl").smtp_security == "ssl"


def test_the_daily_job_runs_from_an_hour_of_the_day():
    assert Settings().daily_hour == 6
    with pytest.raises(ValidationError):
        Settings(daily_hour=24)


def test_the_public_url_loses_its_trailing_slash():
    assert Settings(public_url="https://lms.example.com.au/").public_url == "https://lms.example.com.au"


def test_the_worker_waits_some_time_between_polls():
    assert Settings().worker_poll_seconds == 5.0
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            Settings(worker_poll_seconds=bad)


TENANT = "6f1c2a4e-7b3d-4e8f-9a01-2b3c4d5e6f70"
CLIENT = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


@pytest.mark.parametrize("tenant", ["common", "organizations", "example.com.au", "6f1c2a4e"])
def test_the_tenant_is_one_tenant_by_its_id(tenant):
    with pytest.raises(ValidationError, match="must be your Directory \\(tenant\\) ID"):
        Settings(entra_tenant_id=tenant)


def test_the_ids_are_kept_lower_case():
    s = Settings(entra_tenant_id=TENANT.upper(), entra_client_id=f" {CLIENT.upper()} ")
    assert (s.entra_tenant_id, s.entra_client_id) == (TENANT, CLIENT)
    with pytest.raises(ValidationError, match="Application \\(client\\) ID"):
        Settings(entra_client_id="simple-lms")


def test_microsofts_address_is_the_usual_one_unless_told():
    assert Settings().entra_authority == "https://login.microsoftonline.com"
    assert Settings(entra_authority="http://10.0.0.5:8099/").entra_authority == "http://10.0.0.5:8099"
