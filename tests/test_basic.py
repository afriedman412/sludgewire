import pytest
import os
from sqlalchemy.exc import OperationalError
from sludgewire.access import Access

@pytest.fixture(scope="module")
def access():
    access = Access('h')
    return access

def test_tester():
    x = 5
    assert x-5==0

def test_db_access(access):
    for t in ["house_ptr", "senate_ptr"]:
        access.DB_TABLE = t
        tables = access.read_from_db(f"SHOW TABLES")
        assert len(tables) >= 1
    return

def test_dotenv(access):
    assert os.environ['VAR_SOURCE'] == 'dotenv'