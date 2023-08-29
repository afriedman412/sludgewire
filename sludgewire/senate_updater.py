import time
import datetime as dt
import pandas as pd
from urllib.parse import urljoin
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from typing import Literal
from .access import Access
from .senate_helpers import (
    load_senate_driver, disabled_check, get_all_search_row_data, extract_ptr_transactions, senate_url
    )

class SenatePTRUpdater(Access):
    def __init__(self, 
            chrome: bool=True, 
            headless: bool=True,
            start_date: bool=None
        ):
        self.chrome = chrome
        self.headless = headless
        self.start_date = start_date if start_date else (
            dt.datetime.today()-dt.timedelta(1)).strftime("%m/%d/%Y")
        print(f'starting senate scrape at {self.start_date}...')
        super().__init__(chamber='senate')
        self.load_driver()

    def full_ptr_updater(self):
        new_ptr_files_df = self.get_new_file_list()
        new_ptr_transactions_df = self.get_new_ptr_transactions(new_ptr_files_df)
        
        for data, db in zip(
            [new_ptr_files_df, new_ptr_transactions_df],
            ['ptr_files', 'transactions']
            ):
            self.update_db(data, db)

        self.driver.quit()
        return

    def load_driver(self):
        self.driver, self.wait = load_senate_driver(self.chrome, self.headless)
        return
    
    def acknowledge_TOS(self):
        """
        Clears the TOS check that automatically loads periodically on the senate data site.

        Inputs:
            None

        Outputs:
            None
        """
        print("acknowleding senate TOS...")
        self.wait.until(EC.element_to_be_clickable((By.XPATH, "//*[@id='agree_statement']"))).click()
        return
    
    def set_PTR_search_params(self):
        """
        Sets the params for the PTR search.

        Inputs:
            None

        Outputs:
            None
        """
        print("...selecting all states...")
        senate_check = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.senator_filer'))) # probably works better
        senate_check.click()

        print("...selecting doc types...")
        PTR_field = self.driver.find_element(By.ID, 'reportTypeLabelPtr')
        PTR_field.click()

        print("...selecting start date...")
        fromDatefield = self.driver.find_element(By.ID, 'fromDate')
        fromDatefield.clear()
        fromDatefield.send_keys(self.start_date)

        print('...submitting...')
        button = self.driver.find_element(By.XPATH, '/html/body/div[1]/main/div/div/div[5]/div/form/div/button')
        button.click()

        print('..adjusting pagination...')
        pages_menu = self.driver.find_element(By.NAME, 'filedReports_length')
        for option in pages_menu.find_elements(By.TAG_NAME, 'option'):
            if option.text == '100':
                option.click()

        self.wait.until(EC.element_to_be_clickable((By.ID, 'filedReports_next')))
        return
    
    def get_new_file_list(self):
        """
        Loads senate data page, accepts TOS, sets params for search.

        Inputs:
            None
        
        Outputs:
            None
        """
        if 'driver' not in self.__dir__():
            self.load_driver(self.chrome, self.headless)
        self.driver.get(senate_url)
        self.acknowledge_TOS()
        self.set_PTR_search_params()

        search_result_data = self.scrape_PTR_search()
        search_row_dicts = get_all_search_row_data(search_result_data)
        new_ptr_files_df = self.filter_new_files(search_row_dicts)
        return new_ptr_files_df

    def scrape_PTR_search(self):
        """
        Extracts results from senate PTR search.

        Input: Non

        Ouput:
            search_result_data (dict)
        """
        page_index = 1
        
        search_result_data = []
        while True:
            print(page_index)
            search_result_data.append(self.driver.page_source)
            next_button = self.driver.find_element(By.ID, 'filedReports_next')
            next_button.click()
            time.sleep(2)
            if disabled_check(self.driver.page_source):
                break
            page_index += 1

        # last row -- this is ugly and only necessary because "disabled_check" is clumsy
        # ("disabled_check" is clumsy due to weirdness on the senate side)
        # duplicates removed later
        if page_index > 1:
            print(page_index)
            search_result_data.append(self.driver.page_source)
        return search_result_data
        
    def filter_new_files(self, search_row_dicts: dict) -> pd.DataFrame:
        """
        Filters out already-processed PTR search results. Done in pandas for easier parsing.
        
        Input:
            search_row_dicts

        Output:
            new_ptr_files_df
        """
        search_row_df = pd.DataFrame(search_row_dicts).drop_duplicates()
        ptr_files_found = search_row_df['File_Key'].nunique()
        print(f"{ptr_files_found} senate PTR files found ...")
        if ptr_files_found > 0:
            old_keys = self.read_from_db("select distinct(File_Key) from ptr_files")['File_Key'].unique()
            new_ptr_files_df = search_row_df.query("~File_Key.isin(@old_keys)")
            print(f"{len(new_ptr_files_df)} new senate PTR files found ...")
            return new_ptr_files_df
        else:
            print("no new senate PTRs!")
            return
        
    def get_new_ptr_transactions(self, new_ptr_files_df: pd.DataFrame) -> pd.DataFrame:
        """
        Input:
            new_ptr_files_df (DataFrame) - df of search results for new ptrs

        Output:
            new_ptr_transactions_df (DataFrame) - df of transactions from new ptrs (excluding handwritten)
        """
        ptrs = []
        for ptr_row in new_ptr_files_df.query("Handwritten==False").to_dict('records'):
            self.driver.get(urljoin('https://efdsearch.senate.gov/', ptr_row['URL']))
            ptr_page_source = self.driver.page_source
            ptr_transactions_df = extract_ptr_transactions(ptr_row, ptr_page_source)
            ptrs.append(ptr_transactions_df)
        new_ptr_transactions_df = pd.concat(ptrs)
        return new_ptr_transactions_df
    
    def update_db(self, data: pd.DataFrame, db: Literal['ptr_files', 'transactions']):
        if db not in ['ptr_files', 'transactions']:
            raise ValueError("Invalid data_contents options")
        self.write_to_db(data, db)
        return
    
    def text_new_files(self, new_ptr_files_df):
        file_data = "\n".join(
            [
                " / ".join(v) for v in new_ptr_files_df[
                ['Name (Last)', 'Name (First)', 'Filing Type']].drop_duplicates().values
            ])
        payload = f"**NEW SENATE PTRs**\n\n{file_data}"
        self.send_text(payload)
        return
        
    
    
    