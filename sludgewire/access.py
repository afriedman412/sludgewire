import os
import json
from typing import Literal
from twilio.rest import Client
from sqlalchemy import create_engine, text as sql_text
import pandas as pd

class Access:
    """
    Handles credentials and connections.

    Inputs:
        chamber (str) - house or senate
        force_env (bool) - forces use of environmental variables (for heroku prod or for testing) instead of config.json
    """
    def __init__(self, chamber=Literal['house', 'senate', 'h', 's'], force_env=None):
        if not "HEROKU" in os.environ and not force_env:
            from dotenv import load_dotenv
            load_dotenv()

        for k in [
            'DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD',
            'TWILIO_AUTH', 'TWILIO_SID', 'TWILIO_TEST_AUTH', 'TWILIO_TEST_SID', 
            'PHONE_NUMBERS'
        ]:
            setattr(self, k, os.environ.get(k))
        
        if chamber.startswith('h'):
            self.DB_TABLE='house_ptr'
        elif chamber.startswith('s'):
            self.DB_TABLE='senate_ptr'
        else:
            raise ValueError("bad chamber!")

    def make_sql_engine(self, echo=False):
        """
        Note: 
        - pd.read_sql needs engine.connect()
        - df.to_sql only needs engine

        """
        dbstr = """mysql+pymysql://{}:{}@{}:{}/{}"""
        return create_engine(
            dbstr.format(
                self.DB_USER, 
                self.DB_PASSWORD, 
                self.DB_HOST, 
                str(self.DB_PORT),
                self.DB_TABLE), echo=echo
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