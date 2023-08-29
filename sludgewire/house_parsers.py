"""
Functions to parse individual entries from docs.

TODO: generalize spacer across code
TODO: generalize table-specific data
TODO: check which tables are needed, finish coding
"""

import regex as re
from itertools import zip_longest

def process_ptr_entry(entry: list, spacer: str) -> dict:
    cols=["owner", "asset", 'transaction_type', 'date', 'notification_date', 'amount']
    output = []
    # remove ID if present
    e0 = re.sub(r"^\d{6,}\s", "", entry[0])

    # parse first line into data, splitting connected dates if needed
    for e in e0.split(spacer):
        if re.search(r"\d{2}\/\d{2}\/20\d{2}\s+\d{2}\/\d{2}\/20\d{2}", e):
            output += e.split()
        else:
            output.append(e)
    
    # add spacer if no owner present
    if len(output[0].strip()) > 2:
        output.insert(0, "")

    # split transaction type from asset if needed
    if re.search(r"(?:\s)([eps]|(s \(partial\)))$", output[1]):
        output = output[0:1] + re.split(r"(?:\s)([eps]|(s \(partial\)))$", output[1])[:2] + output[2:]
            
    output = dict(zip(cols, output))
    output['over_200'] = 'CHECK' in entry
    
    entry_ = []
    for e in entry[1:]:
        entry_+=e.split(spacer)
        
    for e in entry_:
        cat_map = {
            "f s:": "filing status:",
            "s o:": "subholding of:",
            "d:": "description:",
            "l:": "location:",
            "c:": "comments:"
        }

        for cat in [
            'filing status:', 'description:', 'subholding of:', "location:", "comments:"
            ] + list(cat_map.keys()):
            if e.startswith(cat):
                cat = cat_map[cat][:-1] if cat in cat_map else cat[:-1]
                output[cat] = e.split(": ")[1]
                break
        else:
            output['asset']+=' ' + e.replace("$50,000", "")
                
    return output

def process_sked_a_entry(entry: list, spacer: str) -> dict:
    cols=[
        "asset", 'owner', 'value_of_asset', 'income_type', 'income'
    ]
    income_types = [
        'capital gains', 'dividends', 'interest', 'tax-deferred'
    ]
    values = [
        '$50,001 -', '$15,001 - $50,000', '$250,001 -', '$1,001 - $15,000', '$100,001 -', 'none'
    ]
    incomes = [
        '$1 - $200', '$2,501 - $5,000', 
        '$1,001 - $2,500', '$5,001 - $15,000'
    ]
    
    output = entry[0].split(spacer)
    
    if len(output[0]) < 3:
        output = [" ".join(entry[1:])] + output
        
    output = dict(zip_longest(cols, output, fillvalue=""))
    
    if output['asset'] in values:
        output['value_of_asset'] = output['asset']
        output['asset'] = " ".join(entry[1:])
        
    if output['owner'] in income_types:
        output['income_type'] = output['owner']
        output['owner'] = ""

    if output['income_type'] in incomes:
        output['income'] = output['income_type']
        output['income_type'] = ""
    
    def income_type_fixer(e, output):
        income_type = None
        try:
            income_type = next(i for i in income_types if i in e)
            output['income_type'] = ", ".join([income_type, output['income_type'].replace(",", "").strip()])
        except StopIteration:
            pass
        return output, income_type
    
    for e in entry[1:]:
        output, income_type = income_type_fixer(e, output)
        
    output, income_type = income_type_fixer(output['value_of_asset'], output)
    if income_type:
        output['value_of_asset'] = output['value_of_asset'].replace(income_type, "").strip()
    
    if output['owner'] in values:
        output['value_of_asset'] = output['owner']
        output['owner'] = ""
                
    return output

def process_sked_b_entry(entry: list, spacer: str) -> dict:
    output = {}
    cols = [
        'asset', 'owner', 'date', 'transaction_type', 'amount'
    ]
    e = entry[0].split(spacer)
    if len(e) < len(cols):
        try:
            output['date'] = next(
                i for i in e if re.search(
                    r"[\d\/]{8,}", i
                )
            )
        except StopIteration:
            output['date'] = ""
            
        try:
            output['amount'] = next(
                i for i in e if re.search(
                    r"\$[\$\d,\s\-]+", i
                )
            )
        except StopIteration:
            output['amount'] = ""
            
        try:
            output['transaction_type'] = next(
                i for i in e if len(i) == 1
            )
        except StopIteration:
            output['transaction_type'] = ""
            
        if any([i for i in entry if 'partial' in i]):
            output['transaction_type'] = "s (partial)"
            
        output['asset'] = ' '.join([i for i in entry[1:] if 'partial' not in i])
            
    else:
        output = dict(zip(cols, e))
        
    return output