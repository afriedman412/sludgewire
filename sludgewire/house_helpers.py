from datetime import datetime as dt
from bs4 import BeautifulSoup
import requests
import urllib3
import io
import pdfquery
import pandas as pd
import regex as re
from lxml import etree
from .house_parser_helpers import (
    doc_ender,doc_trigger, table_trigger, entry_trigger, 
    header_check, translate_check, make_ltlh_dict
    )
from .house_parsers import process_ptr_entry
from typing import Union

class congressDoc:
    def __init__(self, input_: Union[bytes, str], spacer: str="||"):
        self.soup = self.make_soup(input_)
        self.spacer=spacer
        self.all_transactions = []
        self.table_transactions = []
        self.entry = []
        return

    def make_soup(self, input_: Union[bytes, str]):
        """
        Converts either a url (pointing to a .pdf) or the bytes of a .pdf file into BeautifulSoup.

        Input:
            input_ (bytes or str) - address or data for a .pdf document
        
        Output:
            soup - BeautifulSoup of input_
        """
        if isinstance(input_, str) and input_.startswith("http"):
            xml = load_xml(input_)
        elif isinstance(input_, bytes):
            xml = input_
        else:
            raise TypeError("input must be url or bytes!!")
        
        soup = BeautifulSoup(xml, "xml")
        return soup

    def reset_entry(self):
        if self.entry:
            self.table_transactions.append(self.entry)
        self.entry = []
        return
        
    def reset_table(self):
        self.reset_entry()
        if self.table_transactions:
            self.all_transactions.append(self.table_transactions)
        self.table_transactions = []
        return

    def full_parse(self):
        self.active = False
        for xpage in self.soup.find_all("LTPage"):
            
            # make_lthl_dict puts everything in correct order now!
            # index all lines
            ltlh_dict = make_ltlh_dict(xpage)
            
            # iterate through lines
            for k,v in ltlh_dict.items():
                
                # make line text
                t = self.spacer.join([t.text.lower().strip() for t in v])
                
                if doc_trigger(t):
                    self.active=True
                    continue
                    
                elif doc_ender(t):
                    self.reset_table()
                    self.active=False
                    continue
                
                elif self.active:
                    if table_trigger(t):
                        self.reset_table()
                    
                    else:  
                        if entry_trigger(t):
                            self.reset_entry()

                        if not header_check(t, self.spacer):
                            self.entry.append(translate_check(t, self.spacer))
    
    def make_dataframe(self) -> pd.DataFrame:
        """
        Makes dataframe from transactions and adds PTR document metadata (from "row").
        """
        df_ = pd.DataFrame([process_ptr_entry(c, self.spacer) for c in self.all_transactions[0]])
        return df_ 

def get_entry_data(row) -> tuple:
    """
    Extracts and formats data for one row of document search results.

    Input:
        row - one row of document search results

    Outputs:
        (tuple) - formatted document data
    """
    output = [t.text.strip() for t in row.find_all('td')]
    output.append(row.find_all('td')[0].a['href'])
    return tuple(output)

def get_doc_list(params=None) -> list:
    """
    Formats document search results.

    Input:
        params (None) - query params for document search ... only here for testing purposes, default is the entire current year.

    Output:
        doc_list (list) - list of formatted document search results
    """
    base_url = 'https://disclosures-clerk.house.gov/FinancialDisclosure/ViewMemberSearchResult'
    if not params:
        params = {
            "FilingYear":dt.now().year
        }
    r = requests.post(base_url, params=params)
    soup = BeautifulSoup(r.content, 'lxml')
    doc_list = [get_entry_data(row) for row in soup.find_all('tr')[1:]]
    return doc_list

def load_xml(url: str):
    """
    Extracts xml from a url pointing to a .pdf file.

    Input:
        url (str) - url pointing to a document in .pdf format

    Output:
        xml (str?) - extracted xml of .pdf file
    """
    http = urllib3.PoolManager()
    temp = io.BytesIO()
    temp.write(http.request("GET", url).data)
    pq = pdfquery.PDFQuery(temp)
    pq.load()
    xml = etree.tostring(pq.tree)
    return xml

def make_state(jurisdiction):
    try:
        return re.search(r"([A-Z]{2})(?:\d\d)", jurisdiction).group(1)
    except AttributeError:
        return None