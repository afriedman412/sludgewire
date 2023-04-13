import os
import json
import pandas as pd
from datetime import datetime as dt
from sqlalchemy import create_engine, text as sql_text
from .helpers import get_doc_list, congressDoc, make_state
from urllib.parse import urljoin
from twilio.rest import Client
from tqdm import tqdm
from typing import Literal

pd.options.mode.chained_assignment = None

class Access:
    """
    Handles credentials and connections.
    """
    def __init__(self, chamber=Literal['house', 'senate', 'h', 's'], force_env=None):
        __location__ = os.path.realpath(
            os.path.join(os.getcwd(), os.path.dirname(__file__)))

        if any([
            "HEROKU" in os.environ, force_env
            ]):
            for k in [
                'db_host', 'db_port', 'db_user', 'db_password',
                'twilio_auth', 'twilio_sid', 'twilio_test_auth', 'twilio_test_sid', 
                'phone_numbers'
            ]:
                setattr(self, k, os.environ[k])
        
        else:
            config_ = json.load(open(os.path.join(__location__,'config.json'), 'rb'))
            for k in config_:
                setattr(self, k, config_[k])
        
        if chamber.startswith('h'):
            self.db_table='house_ptr'
        elif chamber.startswith('s'):
            self.db_table='senate_ptr'
        else:
            raise "bad chamber!"

    def make_sql_engine(self, echo=False):
        """
        Note: 
        - pd.read_sql needs engine.connect()
        - df.to_sql only needs engine

        """
        dbstr = """mysql+pymysql://{}:{}@{}:{}/{}"""
        return create_engine(
            dbstr.format(
                self.db_user, 
                self.db_password, 
                self.db_host, 
                str(self.db_port),
                self.db_table), echo=echo
        )
    
    def query(self, q):
        engine = self.make_sql_engine()
        with engine.connect() as conn:
            conn.execute(sql_text(q))
        engine.dispose()
        return
        
    def write_to_db(self, df, table, if_exists='append', index=False):
        engine = self.make_sql_engine()
        df.to_sql(table, con=engine, if_exists=if_exists, index=index) # to_sql needs a "engine" object
        engine.dispose()
        return

    def read_from_db(self, q):
        engine = self.make_sql_engine()
        df = pd.read_sql(sql_text(q), engine.connect()) # read_sql needs a "connect" object
        engine.dispose()
        return df
    
    def send_text(self, payload):
        client = Client(self.twilio_sid, self.twilio_auth)

        # in case phone numbers is a stringified list...
        if isinstance(self.phone_numbers, str):
            self.phone_numbers=eval(self.phone_numbers)

        for n in self.phone_numbers:
            message = client.messages.create(
                body=payload,
                from_='+19179822265',
                to=n)

class HousePTRUpdater(Access):
    """
    Tables are:
    - ptr_files
    - ptr_transactions
    - test_files
    - test_transactions
    """
    def __init__(self, force_env=None):
        super().__init__(chamber='house', force_env=force_env)
        self.date_ = dt.strftime(dt.now(), "%Y-%m-%d")

    def update_ptrs(self, send_text=True, verify=False, debug=False):
        # load ptr docs that aren't in db yet
        new_ptr_docs_df, n_existing_ptrs = self.find_new_ptr_docs(debug=debug)
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

            if verify or debug:
                self.verify_new_ptrs(n_existing_ptrs, len(new_ptr_docs_df), debug=debug)

            # send text
            print("sending text...")
            self.send_ptr_text(new_ptr_docs_df)

        else:
            print("no new PTRs!")
        return

    def find_new_ptr_docs(self, debug=False):
        """
        Only PTRs for now, more later.
        """
        year = 2021 if debug else None
        file_table = "test_files" if debug else "ptr_files"

        print("finding new PTRs...")
        ptr_docs_df = pd.DataFrame(
            get_doc_list(year),
            columns=['name', 'jurisdiction', 'year', 'doc_type', 'url']
        ).query("doc_type.str.contains('PTR')")

        if not year:
            year = dt.now().year
        table_ptr_docs_df = self.read_from_db(f"""
            select * from {file_table} where year="{year}"
        """)
        
        new_ptr_docs_df = ptr_docs_df.query("url not in @table_ptr_docs_df['url']")
        new_ptr_docs_df = self.format_new_ptr_doc_df(new_ptr_docs_df)
        print(f"{len(new_ptr_docs_df)} new PTRs found")
        return new_ptr_docs_df, len(table_ptr_docs_df)
    
    def verify_new_ptrs(self, n_existing_ptrs, n_new_ptrs, debug=False):
        year = 2021 if debug else dt.now().year
        file_table = "test_files" if debug else "ptr_files"

        n_updated_ptrs = len(self.read_from_db(f"""
            select * from {file_table} where year="{year}"
        """))

        assert n_updated_ptrs == n_existing_ptrs + n_new_ptrs, f"n updated ({n_updated_ptrs}) is not equal to n old ({n_existing_ptrs}) + n new ({n_new_ptrs})"
    
    def format_new_ptr_doc_df(self, new_ptr_docs_df):
        new_ptr_docs_df['state'] = new_ptr_docs_df['jurisdiction'].map(make_state)
        new_ptr_docs_df['file_name'] = new_ptr_docs_df['url'].map(lambda r: r.split("/")[-1])
        new_ptr_docs_df['handwritten'] = new_ptr_docs_df['file_name'].str.startswith("8")
        return new_ptr_docs_df
    
    def parse_one_doc(self, row: dict) -> pd.DataFrame:
        url = urljoin('https://disclosures-clerk.house.gov', row['url'])
        cd = congressDoc(url)
        cd.full_parse()
        df = cd.make_dataframe(row)
        return df
    
    def parse_all_docs(self, new_ptr_docs: pd.DataFrame) -> list:
        print(f"parsing transactions from {len(new_ptr_docs)} new docs...")
        transaction_df_collector = []
        for row in tqdm(new_ptr_docs.query("doc_type.str.contains('PTR') and handwritten==False").iterrows()):
            new_transaction_df = self.parse_one_doc(row[1])
            transaction_df_collector.append(new_transaction_df)
        new_transactions_df = pd.concat(transaction_df_collector)
        return new_transactions_df
    
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
    
    def debug_reset(self):
        # this is for testing the updater
        # it usually locks up when I try to run this though, so don't use it
        self.q("delete from ptr_files where file_name='20022546.pdf';")
        return
    
    def send_ptr_text(self, new_ptr_docs_df: pd.DataFrame):
        file_data = "\n".join(
            [
                " / ".join(v) for v in new_ptr_docs_df[
                ['name', 'jurisdiction', 'file_name']].drop_duplicates().values
            ])

        payload = f"**NEW HOUSE PTRs**\n\n{file_data}"
        self.send_text(payload)
        return

