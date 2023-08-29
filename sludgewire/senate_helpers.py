import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.firefox.options import Options
import pandas as pd
from typing import List

senate_url = 'https://efdsearch.senate.gov/search/home'

def load_senate_driver(
        chrome: bool=True,
        headless: bool=True
        ):
    """
    Opens a firefox browser, loads the senate search page and accepts the popup.

    Input:
        None

    Output:
        driver - chromedriver or firefox window
        wait - wait object (5 sec)
    """
    print('loading driver...')
    
    if chrome:
        print("Running Chrome Webdriver to pull Senator data...")
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless")

        
        if "HEROKU" in os.environ:
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.binary_location = os.environ.get("GOOGLE_CHROME_BIN")

            driver = webdriver.Chrome(
                executable_path = os.environ.get("CHROMEDRIVER_PATH"), options=chrome_options)
        else:
            driver = webdriver.Chrome(options=chrome_options)
    
    else:
        print("Running Firefox Webdriver to pull Senator data...")
        options = Options()
        if headless:
            options.add_argument('-headless')

        fp = webdriver.FirefoxProfile()
        fp.set_preference("browser.download.folderList", 2)
        fp.set_preference("browser.download.manager.showWhenStarting", False)
        driver = webdriver.Firefox(options=options, firefox_profile=fp)

    wait = WebDriverWait(driver, 5)
    return driver, wait

def scrape_senate_row(row) -> dict:
    """
    For parsing senate search results.

    Input:
        row (BeautifulSoup object) - one row of senate search results
    
    Output:
        row_dict (dict) - formatted search result data
    """
    row_text = [r.text for r in row.find_all('td')]
    
    if len(row_text) > 1:
        row_dict = dict(
            zip(['Name (First)', 'Name (Last)', 'Status', 'Filing Type', 'Filing Date'], 
                row_text))
        row_dict['URL'] = row.find_all('td')[3].a['href']
        filing_code = filing_typer(row_dict['Filing Type'].lower())
        
        if 'paper' in row_dict['URL']:
            filing_code += 'H'  # for 'Handwritten'
        else:
            filing_code += 'W'  # for 'web'
            
        row_dict['Filing Code'] = filing_code
        row_dict['State'] = 'UN' # how do i find state?
        row_dict['File Name'] = '_'.join(
            [row_dict[k] for k in ['Name (Last)', 'State', 'Filing Code', 'Filing Date']]
        ).replace(", ", "_") + '.html'
        row_dict['Handwritten'] = True if 'H' in row_dict['Filing Code'] else False
        row_dict['File_Key'] = row_dict['URL'].split("/")[-2]

        return row_dict

def filing_typer(filing_type: str) -> str:
    """
    Processes 'Filing Type' column from senate search result into text code.

    Input: 
        filing_type (str)

    Output:
        code (str)
    """
    code = ''
    code = ''.join([v for k, v in f_types.items() if k in filing_type])

    if '(amendment' in filing_type:
        code += 'X'
    else:
        code += '_'

    if 'due date extension' in filing_type:
        code += 'E'
    else:
        code += '_'

    return code

def disabled_check(source):
    """
    Ham-fisted check if "Next" button on senate search page is disabled.
    
    returns True if it IS DISABLED.
    """
    soup = BeautifulSoup(source, 'lxml')
    try:
        if 'disabled' in soup.find('a', attrs={'id':'filedReports_next'})['class']:
            return True
        else:
            return False
    except IndexError:
        print('error')
        return False

### PARSERS
def extract_ptr_transactions(ptr_row, ptr_page_source):
    ptr_list = pd.read_html(ptr_page_source)
    output_ptr_list = []
    for ptr in ptr_list:
        # add addn data
        for p in ptr.to_dict('records'):
            p['Name_'] = ' '.join([ptr_row['Name (First)'], ptr_row['Name (Last)']])
            p['File Name'] = ptr_row['File Name']
            p['Filing Type_'] = ptr_row['Filing Type']
            p['Filing Date_'] = ptr_row['Filing Date']
            output_ptr_list.append(p)
    ptr_df = pd.DataFrame(output_ptr_list)
    ptr_df['Sale'] = ptr_df['Type'].map(lambda x: True if 'Sale' in x else False)
    ptr_df['Amount Min'] = ptr_df.apply(lambda r: parse_ptr(r['Amount'], r['Sale'])[0], 1)
    ptr_df['Amount Max'] = ptr_df.apply(lambda r: parse_ptr(r['Amount'], r['Sale'])[1], 1)
    return ptr_df

def parse_ptr(v, sale_):
    v_out = ptr_code[v]
    if sale_ is True:
        v_out = [-i for i in v_out[::-1]]
    return v_out
    
def get_all_search_row_data(search_source_data: dict) -> List[dict]:
    search_row_dicts = []
    for source_data in search_source_data:
        soup = BeautifulSoup(source_data, 'lxml')
        search_rows = soup.find_all('tr')
        for search_row in search_rows:
            search_row_dict = scrape_senate_row(search_row)
            if search_row_dict is not None:
                search_row_dicts.append(search_row_dict)
    return search_row_dicts

def row_for_text(row):
    return ' '.join([
        row['Name (First)'].strip(), 
        row['Name (Last)'].strip(),
        row['Filing Date'].strftime("%Y-%m-%d"),
        row['Filing Code'][-1]
        ])


f_types = {
        'annual report': 'A',
        'periodic transaction report': 'P',
        'new filer report': 'N',
        'candidate report': 'C',
        'termination report': 'T'
    }

ptr_code = {
    '$1,001 - $15,000': [1001, 15000],
    '$15,001 - $50,000': [15001, 50000],
    '$1,000,001 - $5,000,000': [1000001, 5000000],
    '$100,001 - $250,000': [100001, 250000],
    '$250,001 - $500,000': [250001, 500000],
    '$500,001 - $1,000,000': [500001, 1000000],
    '$50,001 - $100,000': [50001, 100000],
    '$5,000,001 - $25,000,000': [5000001, 25000000]
    }