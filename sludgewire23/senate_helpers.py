from bs4 import BeautifulSoup
import os
import json
import time
import pandas as pd

### SCRAPE HELPERS
def scrape_senate_row(row):
    """
    Takes a row from senate search data (as a BeautifulSoup object!)

    Returns row data.
    """
    row_text = [r.text for r in row.find_all('td')]
    
    if len(row_text) > 1:
        row_dict = dict(
            zip(['Name (First)', 'Name (Last)', 'Status', 'Filing Type', 'Filing Date'], 
                row_text))
        # row_dict['Filing Date'] = row_dict['Filing Date'].replace('/', '_')
        row_dict['URL'] = row.find_all('td')[3].a['href']
        filing_code = file_typer(row_dict['Filing Type'].lower())
        
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

def file_typer(file_):
    code = ''
    code = ''.join([v for k, v in f_types.items() if k in file_])

    if '(amendment' in file_:
        code += 'X'
    else:
        code += '_'

    if 'due date extension' in file_:
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

### PARSE HELPERS
def parse_ptr(v, sale_):
    v_out = ptr_code[v]
    if sale_ is True:
        v_out = [-i for i in v_out[::-1]]
    return v_out
    
def process_PTR_df(full_ptr_list):
    ptr_df = pd.DataFrame(full_ptr_list)
    ptr_df['Sale'] = ptr_df['Type'].map(lambda x: True if 'Sale' in x else False)
    ptr_df['Amount Min'] = ptr_df.apply(lambda r: parse_ptr(r['Amount'], r['Sale'])[0], 1)
    ptr_df['Amount Max'] = ptr_df.apply(lambda r: parse_ptr(r['Amount'], r['Sale'])[1], 1)
    return ptr_df
    
def get_all_search_row_data(search_source_data):
    search_row_dicts = []
    for s in search_source_data:
        soup = BeautifulSoup(s, 'lxml')
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

senate_url = 'https://efdsearch.senate.gov/search/home'

### PROBABLY FOR PARSING DATA, NOT IN USE RN
# def process_search_data(search_row_dicts):
#     if search_row_dicts:
#         row_df = pd.DataFrame(search_row_dicts)
#         row_df['Handwritten'] = row_df['Filing Code'].map(lambda c: True if 'H' in c else False)
#         row_df['Filing Date'] = pd.to_datetime(row_df['Filing Date'])
#         row_df['File Name'] = row_df.apply(
#             lambda r: "_".join([r['Name (Last)'], r['State'], r['Filing Code'], str(r['Filing Date'])]).split(' ')[0] + ".html", 1
#         )
#         return row_df.to_dict('records')
#     else:
#         print('no search results!')
#         return


# def read_PTR_row(ptr_row):
#     """
#     ptr_list = pd.read_html(ptr_data[5]['html'])
#     for p_ in ptr_list:
#         for p_ in p.to_dict('records'):
#             print(p_)
#     """
#     output_ptr_list = []
#     ptr_list = pd.read_html(ptr_row['html'])
#     for ptr in ptr_list:
#         # add addn data
#         for p in ptr.to_dict('records'):
#             p['Name_'] = ' '.join([ptr_row['Name (First)'], ptr_row['Name (Last)']])
#             p['File Name'] = ptr_row['File Name']
#             p['Filing Type_'] = ptr_row['Filing Type']
#             p['Filing Date_'] = ptr_row['Filing Date']
#             output_ptr_list.append(p)

    # return output_ptr_list