"""What this deployment of the sidecar is, read from the environment.

The variables below are the whole configuration surface the README publishes
to an operator, so this is what "the README is true" looks like as a test.
`load_settings` takes its mapping as an argument for exactly that reason:
nothing here touches os.environ.
"""

import pytest

from app.config import DEFAULT_CATALOG_IDS, DEFAULT_PORT, DEFAULT_SITES, load_settings


def test_an_empty_environment_serves_every_known_site_narrowed_to_games():
    settings = load_settings({})

    assert settings.sites == DEFAULT_SITES == ("uk", "fr", "de", "es", "ie")
    assert settings.port == DEFAULT_PORT
    assert settings.catalog_ids == DEFAULT_CATALOG_IDS == ("3002",)
    assert settings.per_page is None


def test_the_operator_can_pick_the_sites():
    assert load_settings({"VINTED_SITES": " UK, fr ,, "}).sites == ("uk", "fr")


def test_a_blank_value_falls_back_rather_than_configuring_nothing():
    settings = load_settings({"VINTED_SITES": "  ", "VINTED_CATALOG_IDS": ""})

    assert settings.sites == DEFAULT_SITES
    assert settings.catalog_ids == DEFAULT_CATALOG_IDS


def test_catalogue_ids_are_a_list_the_operator_verified():
    assert load_settings({"VINTED_CATALOG_IDS": " 2309 ,1131,, "}).catalog_ids == ("2309", "1131")


@pytest.mark.parametrize("value,expected", [("48", 48), ("", None), ("   ", None)])
def test_the_page_size_is_optional(value, expected):
    assert load_settings({"VINTED_PER_PAGE": value}).per_page == expected


def test_a_blank_port_is_the_default_rather_than_a_crash_loop():
    """An empty string is how a compose file passes "unset but present".

    int("") raises, and it would raise at startup, before the server binds:
    the container would crash-loop on a variable the operator meant to leave
    alone.
    """
    assert load_settings({"PORT": ""}).port == DEFAULT_PORT
    assert load_settings({"PORT": "9000"}).port == 9000
