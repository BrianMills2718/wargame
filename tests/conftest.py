import pytest
from wargame.scenario import load_scenario, init_db

SCENARIO = "scenarios/us_iran_2026.yaml"


@pytest.fixture
def spec():
    return load_scenario(SCENARIO)


@pytest.fixture
def conn(spec):
    c = init_db(spec)
    yield c
    c.close()
