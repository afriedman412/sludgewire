import pandas as pd
import os
from datetime import datetime as dt
from .house_helpers import get_doc_list, congressDoc, make_state
from urllib.parse import urljoin
from tqdm import tqdm
from .access import Access

pd.options.mode.chained_assignment = None

class HousePTRUpdater(Access):
    """
    Tables are:
    - ptr_files
    - ptr_transactions
    - test_files
    - test_transactions
    """
    def __init__(
            self, 
            start_date: bool=None
            ):
        super().__init__(chamber='house')
        if not start_date:
            self.start_date = dt.strftime(dt.now(), "%Y-%m-%d")
            self.year = dt.now().year

    def update_ptrs(self, verify=False):
        """
        Full process of checking for new PTRs, extracting transactions and uploading both to database.

        Inputs:
            verify (bool) - toggles verfification of new/old PTR counts

        Outputs:
            None
        """
        # load ptr docs that aren't in db yet
        new_ptr_docs_df = self.find_new_ptr_docs()
        if len(new_ptr_docs_df):
            # don't process any ptr files that are already in ptr_transactions table
            filtered_ptr_docs_df = self.filter_out_duplicate_transactions(new_ptr_docs_df)
            if len(filtered_ptr_docs_df):
                # parse new ptr docs
                new_transactions_df = self.parse_all_docs(filtered_ptr_docs_df)

                print("writing data...")
                # write new transactions to table
                self.write_to_db(new_transactions_df, "ptr_transactions")

            # write new files to table
            # (do this last so if something goes wrong with writing the transactions it can easily be re-run)
            self.write_to_db(new_ptr_docs_df, "ptr_files")

            # send text
            print("sending text...")
            self.send_ptr_text(new_ptr_docs_df)

        else:
            print("no new PTRs!")
        return
    
    def find_new_docs(self):
        """
        Only PTRs for now, more later.
        """
        new_ptr_docs_df = self.get_new_docs()
        existing_files = self.get_existing_file_names()
        new_ptr_docs_df = new_ptr_docs_df.query("file_name not in @existing_files")

        new_ptr_docs_df['state'] = new_ptr_docs_df['jurisdiction'].map(make_state)
        new_ptr_docs_df['handwritten'] = new_ptr_docs_df['file_name'].str.startswith("8")

        print(f"{len(new_ptr_docs_df)} new PTRs found")
        return new_ptr_docs_df

    def get_new_docs(self):
        """
        Only PTRs!! Adjust later.
        """
        print("finding new PTRs...")
        ptr_docs_df = pd.DataFrame(
            get_doc_list(),
            columns=['rep_name', 'jurisdiction', 'year', 'doc_type', 'url']
        ).query("doc_type.str.contains('PTR')")
        ptr_docs_df['file_name'] = ptr_docs_df['url'].map(os.path.basename)
        return ptr_docs_df
        
    def get_existing_file_names(self, file_table: str='doc_table', year=None):
        # mostly for testing flexibility
        if not year:
            year = self.year
        table_ptr_docs_df = self.read_from_db(f"""
            select * from {file_table} where year="{year}"
        """)
        existing_files = table_ptr_docs_df['url'].map(os.path.basename)
        return existing_files
    
    def parse_one_url(self, url):
        url = urljoin('https://disclosures-clerk.house.gov', url)
        cd = congressDoc(url)
        cd.full_parse()
        new_transactions_df = cd.make_dataframe()
        return new_transactions_df
    
    def parse_docs(self, new_ptr_docs: pd.DataFrame) -> list:
        print(f"parsing transactions from {len(new_ptr_docs)} new docs...")
        transaction_df_collector = []
        for row in tqdm(new_ptr_docs.query("doc_type.str.contains('PTR') and handwritten==False").iterrows()):
            new_transactions_df = self.parse_one_url(row['url'])
            for k,v in row.to_dict().items():
                new_transactions_df[k] = v
            transaction_df_collector.append(new_transactions_df)
        all_new_transactions_df = pd.concat(transaction_df_collector)
        return all_new_transactions_df
    
    def filter_out_duplicate_transactions(self, new_ptr_docs: pd.DataFrame) -> list:
        """
        Compares incoming new ptr docs to existing transactions and returns only file names that aren't already in the database.
        """
        dup_file_names = self.read_from_db(f"""
                select file_name
                from ptr_transactions 
                where file_name in ({str(new_ptr_docs['file_name'].unique())[1:-1]})
                """)
        filtered_ptr_docs_df = new_ptr_docs[~new_ptr_docs['file_name'].isin(dup_file_names)]
        return filtered_ptr_docs_df
    
    
    def send_ptr_text(self, new_ptr_docs_df: pd.DataFrame):
        file_data = "\n".join(
            [
                " / ".join(v) for v in new_ptr_docs_df[
                ['name', 'jurisdiction', 'file_name']].drop_duplicates().values
            ])

        payload = f"**NEW HOUSE PTRs**\n\n{file_data}"
        self.send_text(payload)
        return

