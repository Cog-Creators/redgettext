import pytest
from freezegun import freeze_time


@pytest.fixture(autouse=True)
def _setup_driver():
    with freeze_time():
        yield
