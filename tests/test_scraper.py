import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from sludgewire.senate_updater import SenatePTRUpdater
from sludgewire.senate_helpers import get_all_search_row_data, senate_url, extract_ptr_transactions

@pytest.fixture(scope="module")
def spu():
    return SenatePTRUpdater()

def test_senate_search(spu):
    spu.driver.get(senate_url)
    spu.acknowledge_TOS()

    spu.driver.find_element(By.ID, "filerTypeLabelSenator").click()
    senate_check = spu.wait.until(
            EC.presence_of_element_located((By.ID, 'senatorFilerState')))
    senate_check.click()
    state_dropdown = Select(senate_check)
    state_dropdown.select_by_visible_text("Alaska")
    senate_check.click()

    for id, date in zip(
        ['fromDate', 'toDate'], 
        ["01/01/2021", "01/01/2022"]
        ):
        field = spu.driver.find_element(By.ID, id)
        field.clear()
        field.send_keys(date)

    button = spu.driver.find_element(By.XPATH, '/html/body/div[1]/main/div/div/div[5]/div/form/div/button')
    button.click()

    spu.wait.until(EC.element_to_be_clickable((By.ID, 'filedReports_next')))
    
    search_result_data = spu.scrape_PTR_search()
    search_row_dicts = get_all_search_row_data(search_result_data)

    test_url = 'https://efdsearch.senate.gov/search/view/ptr/378080ec-6299-4274-a5e6-aa4f68577985/'
    spu.driver.get(test_url)
    ptr_page_source = spu.driver.page_source

    ptr_row = search_row_dicts[-1]
    ptr_transactions = extract_ptr_transactions(ptr_row, ptr_page_source)
    spu.driver.quit()

    assert len(search_row_dicts) == 6
    assert search_row_dicts[-1]['File_Key'] == '378080ec-6299-4274-a5e6-aa4f68577985'
    assert ptr_transactions.loc[0, 'Comment'].split()[4] == 'managed'

    










