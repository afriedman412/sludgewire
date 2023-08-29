"""
Helper functions for parsing document xml. 
"""

import regex as re

def make_ltlh_dict(xpage) -> dict:
    ltlh_dict = {}
    for l in xpage.find_all('LTTextLineHorizontal'):
        x0, y0, x1, y1 = tuple([float(i) for i in eval(l['bbox'])])
        if y0 in ltlh_dict:
            ltlh_dict[y0].append(l)
        else:
            ltlh_dict[y0] = [l]
    sorted_dict = {
        k:sorted(v, key=lambda i: float(i['x0'])) for k,v in ltlh_dict.items()
        }
    return dict(sorted(sorted_dict.items(), reverse=True))

def translate_check(t: str, spacer: str=" ") -> str:
    t_ = t.replace(spacer, " ")
    if set(t_) == {' ', 'b', 'c', 'd', 'e', 'f', 'g'}:
        return "CHECK"
    if set(t_) == {' ', 'c', 'd', 'e', 'f', 'g'}:
        return "NULL"
    else:
        return t

def doc_trigger(t: str) -> bool:
    doc_starters = [
        "t",
        "transactions", 
        's a: a "a" i',
        'S A: A "U" I'
    ]
    return t.strip() in [doc_starter.lower() for doc_starter in doc_starters]

def doc_ender(t: str) -> bool:
    doc_enders = [
        "* for the complete list",
        'S A B A C D'
    ]
    return any([t.startswith(doc_ender.lower()) for doc_ender in doc_enders])

def table_trigger(t: str) -> bool:
    table_starters = [
        's a: a "a" i',
        'S A: A "U" I',
        'S B: T',
        'S C: E I',
        "S D: L",
        "S E: P",
        "S F: A", 
        "S G: G",
        "S H: T P R",
        "S I: P M C L H"
    ]
    return any([t.startswith(table_starter.lower()) for table_starter in table_starters])

def table_ender(t: str) -> bool:
    table_enders = [
        '* asset class details available',
        "* Asset class details available at the bottom of this form. For the complete list of asset type abbreviations, please visit"
    ]
    return any([t.startswith(table_ender.lower()) for table_ender in table_enders])
    
def entry_trigger(t: str) -> bool:
    entry_triggers = [
        r"(?:\w{3})\d{2}\/\d{2}\/20\d{2}",
        r"\$[\d,]+\s\-"
    ]
    return any([re.search(entry_trigger, t, flags=re.I) for entry_trigger in entry_triggers])

def header_check(t: str, spacer: str=" ") -> bool:
    header_strings = [
        'id transaction date notification amount cap. owner asset',
        'asset  owner  value of asset  income type(s)  income tx. >',
        'Owner Value of Asset  Income Type(s) Income  Asset  Tx. >',
        '$1,000?',
        'Owner Date  Asset  Tx.  Amount  Cap.',
        'asset  owner date tx.  amount  cap.',
        'Type Gains >',
        '$200?',
        'Source  Type  Amount',
        'owner creditor  date incurred  type  amount of',
        'liability',
        'owner asset  id  transaction  date  notification  amount  cap.',
        'transaction id date notification amount cap. owner asset',
        'type date gains >',
        '$200?',
        'owner asset cap. id transaction date  notification  amount',
        'owner asset cap. amount notification date transaction id',
        'gains >  type  date',
        'gains > type date',
        '* asset class details available at the bottom of this form. for the complete list of asset type abbreviations, please visit',
        'https://fd.house.gov/reference/asset-type-codes.aspx.'
        ]
    
    # will combine these eventually, this is overkill rn
    header_regex = r"(owner|asset|cap\.|amount|notification|date|transaction|id|type|gains\s\>|\s){5,}"
    
    return any([
        t.replace(spacer, " ") in [re.sub(r"\s+", " ", h.lower()) for h in header_strings],
        re.search(header_regex, t.replace(spacer, " "), flags=re.I)
    ])