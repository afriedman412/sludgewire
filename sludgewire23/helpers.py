from datetime import datetime as dt
from bs4 import BeautifulSoup
import requests
import urllib3
import io
import pdfquery
import pandas as pd
import regex as re
from lxml import etree
from .parse_helpers import (
    doc_ender,doc_trigger, table_trigger, entry_trigger, 
    header_check, translate_check, make_ltlh_dict
    )
from .entry_parsers import process_ptr_entry
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
    
    def make_dataframe(self, row: dict) -> pd.DataFrame:
        """
        Makes dataframe from transactions and adds PTR document metadata (from "row").
        """
        df_ = pd.DataFrame([process_ptr_entry(c, self.spacer) for c in self.all_transactions[0]])
        for k,v in row.to_dict().items():
            df_[k] = v
        return df_
                        

def get_entry_data(row) -> tuple:
    output = [t.text.strip() for t in row.find_all('td')]
    output.append(row.find_all('td')[0].a['href'])
    return tuple(output)

def get_doc_list(year: str=None) -> list:
    if not year:
        year = dt.now().year
    r = requests.post(
        'https://disclosures-clerk.house.gov/PublicDisclosure/FinancialDisclosure/ViewMemberSearchResult',
        params={'FilingYear':year}
    )
    soup = BeautifulSoup(r.content, 'lxml')
    doc_list = [get_entry_data(row) for row in soup.find_all('tr')[1:]]
    return doc_list

def load_xml(url):
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