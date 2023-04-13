from selenium import webdriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
import os
import time
import datetime as dt
import pandas as pd
from .senate_helpers import (
    disabled_check, get_all_search_row_data, senate_url
    )
from .updater import Access

# 
class SenatePTRUpdater(Access):
    def __init__(self, 
            chrome=True, 
            headless=True,
            start_date=None
        ):
        self.chrome = chrome
        self.headless = headless
        self.start_date = start_date if start_date else (
            dt.datetime.today()-dt.timedelta(1)).strftime("%m/%d/%Y")
        print(f'starting senate scrape at {self.start_date}...')
        super().__init__(chamber='senate')

    def load_senate_driver(self):
        """
        Opens a firefox browser, loads the senate search page and accepts the popup.

        Input:
            None

        Output:
            self.driver - chromedriver window
            self.wait - wait object (5 sec)
        """
        print('loading driver...')
        if self.chrome:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--headless")

            if "HEROKU" in os.environ:
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--no-sandbox")
            
                chrome_options.binary_location = os.environ.get("GOOGLE_CHROME_BIN")

                print("Running Chrome Webdriver to pull Senator data...")
                self.driver = webdriver.Chrome(
                    executable_path = os.environ.get("CHROMEDRIVER_PATH"), chrome_options=chrome_options)
            else:
                print("Running Chrome Webdriver to pull Senator data...")
                self.driver = webdriver.Chrome(chrome_options=chrome_options)
        
        else:
            options = Options()
            if self.headless:
                options.add_argument('-headless')

            fp = webdriver.FirefoxProfile()
            fp.set_preference("browser.download.folderList", 2)
            fp.set_preference("browser.download.manager.showWhenStarting", False)

            print("Running Webdriver to pull Senator data...")
            self.driver = webdriver.Firefox(options=options, firefox_profile=fp)

        self.wait = WebDriverWait(self.driver, 5)
        return
    
    def acknowledge_TOS(self):
        """
        Clears the TOS check that automatically loads periodically on the senate data site.

        Inputs:
            None

        Outputs:
            None
        """
        print("acknowleding TOS...")
        self.wait.until(EC.element_to_be_clickable((By.XPATH, "//*[@id='agree_statement']"))).click()
        return
    
    def PTR_search_params(self):
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
    
    def full_search(self):
        """
        Loads senate data page, accepts TOS, sets params for search.
        """
        self.load_senate_driver()
        self.driver.get(senate_url)
        self.acknowledge_TOS()
        self.PTR_search_params()

        search_result_data = self.scrape_PTR_search()
        search_row_dicts = get_all_search_row_data(search_result_data)
        self.driver.quit()

        print("filtering new files...")
        new_files_df = self.filter_new_files(search_row_dicts)
        print('updating files table...')
        self.update_files(new_files_df)
        print('sending text...')
        self.text_new_files(new_files_df)
        print('done!')
        return

    def scrape_PTR_search(self):
        page_count = 1
        
        search_result_data = []
        while True:
            print(page_count)
            search_result_data.append(self.driver.page_source)
            next_button = self.driver.find_element(By.ID, 'filedReports_next')
            next_button.click()
            time.sleep(2)
            page_count += 1
            if disabled_check(self.driver.page_source):
                break

        # last row -- this is ugly and only necessary because "disabled_check" is clumsy
        # ("disabled_check" is clumsy due to weirdness on the senate side)
        # duplicates removed later
        if page_count > 1:
            print(page_count)
            search_result_data.append(self.driver.page_source)
        return search_result_data
            
    def get_PTR_data(self, row_dict):
        link = 'https://efdsearch.senate.gov' + row_dict['URL']
        if "/ptr/" in link:
            print(link)
            self.driver.get(link)
            time.sleep(1)
            row_dict['html'] = self.driver.page_source
            return row_dict # make a function to collect these
        
    def filter_new_files(self, search_row_dicts):
        search_row_df = pd.DataFrame(search_row_dicts).drop_duplicates()
        print(f"{len(search_row_df)} senate PTR files found ...")
        existing_keys = self.read_from_db("select distinct(File_Key) from ptr_files")
        new_files_df = search_row_df[~search_row_df['File_Key'].isin(existing_keys['File_Key'])]
        if len(new_files_df) > 0:
            print(f"{len(new_files_df)} new senate PTR files found ...")
            print(new_files_df['File_Key'])
        else:
            print("no new senate PTRs!")
        return new_files_df
    
    def update_files(self, new_files_df):
        self.write_to_db(new_files_df, "ptr_files")
        return
    
    def text_new_files(self, new_files_df):
        file_data = "\n".join(
            [
                " / ".join(v) for v in new_files_df[
                ['Name (Last)', 'Name (First)', 'Filing Type']].drop_duplicates().values
            ])

        payload = f"**NEW SENATE PTRs**\n\n{file_data}"
        self.send_text(payload)
        return
        
    
    
    