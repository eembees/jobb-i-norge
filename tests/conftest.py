"""
Shared pytest fixtures — load fixture JSON files once per session.
"""

import json
import os
import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def occupations_raw():
    return load_fixture("occupations.json")


@pytest.fixture(scope="session")
def wages_raw():
    return load_fixture("wages.json")


@pytest.fixture(scope="session")
def education_raw():
    return load_fixture("education.json")


@pytest.fixture(scope="session")
def labels_raw():
    return load_fixture("labels_no.json")
