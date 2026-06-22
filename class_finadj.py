# Libaries
from multiprocessing.reduction import duplicate
import os 
import glob
import sys
import json
from datetime import  datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

import requests
from requests_oauthlib import OAuth1
from oauthlib.oauth1 import SIGNATURE_HMAC_SHA256, Client

import aiohttp
import asyncio

import base64
import hashlib
import datetime


from dotenv import load_dotenv
import os
load_dotenv(".env")




class LoadFinAdj:
    def __init__(self,test_file_path=None):
        """
        Initialize the Checkpoint with the and grab latest moneris sales CSV file and required columns.
        If test_file_path is passed, then read test file otherwise read latest file from the destined folder.
        """
        file_pattern= r"Financial Adjustment*"
        download_folder_path = r"C:\Users\Tzuying\OneDrive - smilesfirstcorp\Reporting & Business Intelligence\Moneris\Downloaded_Files" # TODO: Change to your download folder path
        full_path = os.path.join(download_folder_path, file_pattern ) 
        list_of_files = glob.glob(full_path)
        latest_file = max(list_of_files, key=os.path.getctime) #latest change time of the file

        
        if not test_file_path: # didn't put any test file path
            read_file = latest_file
        else: # did put test file path
            read_file = test_file_path   

        self.df = pd.read_csv(read_file) #change it to latest_file when running for real
        self.required_columns = ["Deposit Date", "Merchant Number", "Card Type","Reason" ,"Merchant Adj Amount"]

    def check_required_columns(self):
        """
        Check if all required columns are present in the DataFrame.
        Raises ValueError if any required column is missing.
        """
        missing_columns = [col for col in self.required_columns if col not in self.df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {missing_columns}")
        else:
            print("✅ All required columns are present.")
            return self.df[self.required_columns]


class TransformFinAdj:
    def __init__(self, df, mapping_path='moneris_practice_mapping.csv'):
        self.df = df.copy()  # safer to avoid modifying original df
        self.mapping = pd.read_csv(mapping_path, usecols=["Merchant Number", "Internal ID", "Name (no hierarchy)", "Is Practice Closed?"])
        file_date  = pd.to_datetime(self.df["Deposit Date"], format='%Y%m%d').dt.date.unique()[0]
        self.date = str(file_date).strip()
        self._merge_mapping()

    def _merge_mapping(self):
        self.df = pd.merge(self.df, self.mapping, how='left', on='Merchant Number' )

    def lines_maker(self,row):
        """ Create line dictionary from a DataFrame row. """
        
        amount = str(row["Merchant Adj Amount"]).strip()
        last_8_digits = str(row["Merchant Number"]).strip()[-8:]
    
        memo = f"MON REV{last_8_digits}"
        debit_account = 6617 #NEED TO CHANGE TO 6617 WHEN LIVE
        credit_account = 6667 # This is for financial adjustment
        
        debit_line = {"account": debit_account,"debit": amount, "memo": memo}
        credit_line = {"account": credit_account,"credit": amount, "memo": memo}

        return [debit_line, credit_line]

    def header_maker(self, row):
        """ Create header dictionary for a group. """
        practice_name = str(row['Name (no hierarchy)']).strip()
        id = str(row['Internal ID']).strip()
        date_raw = pd.to_datetime(row["Deposit Date"], format='%Y%m%d').date()
        date = str(date_raw).strip()
        merchant_number = str(row["Merchant Number"]).strip()
        header = {
                    "trandate":date, 
                    "memo": f"Moneris Financial Adjustment for {practice_name} at {date}", 
                    "subsidiary": id,
                    "externalid": f"moneris_{id}_{merchant_number}_{date}_adj"
                }
        return header
    
    def create_payloads(self):
        """ Create payloads in json form for each group in the DataFrame. 
        Returns a list of payload dictionaries.
        """
        payloads = []
    
        for row_index in range(self.df.shape[0]):
            row = self.df.iloc[row_index, : ]
            # header
            header = self.header_maker(row)
            # body lines
            lines = []
            
            line_entries = self.lines_maker(row)
            lines.extend(line_entries)
            payload = {
                **header,
                "lines": lines
            }
            payloads.append(payload)
    
    
        print(f"****** ✅ Created {len(payloads)} payloads successfully.******")
        print("\n")
        return payloads   


class UploadFinAdj:
    def __init__(self, payloads):
        self.payloads = payloads
        self.url = "https://4571901.restlets.api.netsuite.com/app/site/hosting/restlet.nl?script=3084&deploy=1"  #need to change when live
        self.auth = {
        "client_key": os.getenv("CLIENT_KEY"),
        "client_secret": os.getenv("CLIENT_SECRET"),
        "resource_owner_key": os.getenv("OWNER_KEY"),
        "resource_owner_secret": os.getenv("OWNER_SECRET"),
        "signature_method": SIGNATURE_HMAC_SHA256,
        "realm": os.getenv("REALM"),
        }
        self.concurrency = 5
        self.max_retries = 3
    
    def sign_oauth1(self, url, method="POST", body=""):
        body_hash = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode("utf-8")

        client = Client(
            client_key=self.auth["client_key"],
            client_secret=self.auth["client_secret"],
            resource_owner_key=self.auth["resource_owner_key"],
            resource_owner_secret=self.auth["resource_owner_secret"],
            signature_method="HMAC-SHA256",
            realm=self.auth["realm"],
        )

        _, headers, _ = client.sign(
            url,
            http_method=method,
            body=body,
            headers={
                "Content-Type": "application/json",
                "oauth_body_hash": body_hash,
            },
        )
        return headers

    async def post_je_async(self,session, payload, max_retries=3):

        # Simple retry for transient errors
        backoff = 0.3
        body_str = json.dumps(payload)

        for attempt in range(1, max_retries + 1):
            oauth_headers = self.sign_oauth1(self.url,"POST", body=body_str)
            try: 
                timeout = aiohttp.ClientTimeout(total=20)
                async with session.post(self.url, json=payload, headers =oauth_headers, timeout=20) as r:

                    if r.status in (429, 502, 503, 504):
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    try:
                        body = await r.json()
                    except:
                        body = await r.text()
                    
                    return {
                    "payloadExternalId": payload.get("externalid"),
                    "status": r.status,
                    "body": body
                    }
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # Network or timeout — retry unless out of attempts
                if attempt < self.max_retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                return {
                    "payloadExternalId": payload.get("externalid"),
                    "status": "network_error",
                    "body": str(e),
                }
        
        return {
            "payloadExternalId": payload.get("externalid"),
            "status": "failed",
            "body": "Exceeded max retries",
        }
    

    async def load_payloads_async(self) -> list[dict]:
        """
        Run all payloads in concurrent (up to self.concurrency).
        Returns a list of result dicts.
        """
        semaphore = asyncio.Semaphore(self.concurrency)

        async def _bounded_call(payload):
            async with semaphore:
                return await self.post_je_async(session, payload)

        async with aiohttp.ClientSession() as session:
            tasks = [_bounded_call(p) for p in self.payloads]
            results = await asyncio.gather(*tasks)
            return results


class SummaryFinAdj:
    @staticmethod
    def generate(results):
        # ----------- Counter and Print Summary ---------------- #
        nsuccess = 0
        nfailure = 0
        nduplicate = 0
        fail_raw = []
        for result in results:
            if result["status"] == 200 and result["body"].get("report") == "duplicate":
                nduplicate += 1
            elif result["status"] == 200:
                nsuccess += 1
            else:
                nfailure += 1
      
    
        print("\n"+ "Summary of Load Results:")
        print("===================================")
        print(f"🟢 Out of {len(results)} payloads, Successful: {nsuccess}, Failed: {nfailure}, Duplicated: {nduplicate}"+ "\n")
        
             # ----------- Failure DataFrame ---------------- #
        fails = []
        fail_raw = [r for r in results if r.get("status") != 200]
        if nfailure > 0:
            for fail in fail_raw: 
                body = fail.get("body") or {}
                err = body.get("error") or {}
                raw_msg = err.get("message") or {}
                try:
                    if isinstance(raw_msg, str):
                        cleaned = raw_msg.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
                        data = json.loads(cleaned)
                    else:
                        data = {"name": "Unknown Error", "message": str(raw_msg)}
                except:
                    data = {"name": "Unknown Error", "message": raw_msg}

                f = { 'payloadExternalId': fail["payloadExternalId"], 
                        'Internal ID': fail["payloadExternalId"].split("_")[1],
                        'status': fail["status"],
                        'Name': data["name"],
                        'Message': data["message"]}
                fails.append(f)
                
                print(f"- {f}", "\n")