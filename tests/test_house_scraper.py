import pytest
from sludgewire.house_updater import HousePTRUpdater
from sludgewire.house_helpers import get_doc_list

@pytest.fixture(scope="module")
def hpu():
    return HousePTRUpdater()

def test_house_ptr_request():
    # TODO: add "filter out existing" test after sorting out what is saved where
    test_doc_list = get_doc_list({"FilingYear":2021, "State":"AZ"})
    assert len(test_doc_list) == 23
    assert test_doc_list[-1][0] == 'Stanton, Hon.. Greg', "Bad doc list query"

def test_hpu(hpu):
    existing_files = hpu.get_existing_file_names(year=2019)
    assert len(existing_files) == 1709, "Bad exisiting file count"

    test_row_df = hpu.parse_one_url('public_disc/ptr-pdfs/2023/20022986.pdf')
    assert test_row_df['asset'][1].split()[0] == 'southstate', "Parser error"