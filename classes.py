
# Libaries
from multiprocessing.reduction import duplicate
import os 
import glob
import sys
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

import requests
from requests_oauthlib import OAuth1
from oauthlib.oauth1 import SIGNATURE_HMAC_SHA256, Client

import aiohttp
import asyncio

import base64
import hashlib

from dotenv import load_dotenv
import os
load_dotenv(".env")


# BEFORE RUNNING TODO:
# 1. Make sure to install required libraries
# 2. Update your own credentails in the .env file
# 3. Update the download folder path in Checkpoint class to your own path


# Checkpoint Class 
class Checkpoint:
    def __init__(self):
        """
        Initialize the Checkpoint with the and grab latest moneris sales CSV file and required columns.
        """
        file_pattern= r"Sales Summary by Merchant_Download Date *"
        folder_path = r"C:\Users\Tzuying\OneDrive - smilesfirstcorp\Reporting & Business Intelligence\Moneris" # TODO: Change to your download folder path
        full_path = os.path.join(folder_path, file_pattern ) 
        list_of_files = glob.glob(full_path)
        latest_file = max(list_of_files, key=os.path.getctime)

        self.df = pd.read_csv(latest_file)
        self.required_columns = ["Settlement Date", "Merchant Number", "Card Type", "Net Deposit"]

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
    
    def check_total_sameAs_deposit(self):
        """ 
        Check if the sum of 'Net Total' column matches the sum of 'Net Deposit' column.
        Raises ValueError if there is a discrepancy.
        """
        if self.df["Net Total"].sum() == self.df["Net Deposit"].sum():
            print("✅ Net Total matches Net Deposit.")
        else:
            raise ValueError("⛔️ Discrepancy found between Net Total and Net Deposit.")

    def check_cardType(self):
        """         
        Check if 'Card Type' column contains only valid values.
        Raises ValueError if new card types are found.
        """
        valid_card_types = [1,2,3,10]
        invalid_card_types =  [ct for ct in self.df["Card Type"].unique()  if ct not in valid_card_types]
        if invalid_card_types:
            raise ValueError(f"⛔️ New Card Types found: {invalid_card_types}")
        else:
            print("✅ All Card Types are valid.")

    def check_date(self):
        """
        Check if the 'Settlement Date' corresponds to yesterday's date. 
        If today is monday, it checks for last Saturday's date.
        Otherwise, always checks for yesterday's date.
        """

        file_date = pd.to_datetime(self.df['Settlement Date'], format='%Y%m%d').dt.date
        file_date = file_date.unique()[0] 
        yesterday = datetime.today().date() - timedelta(days = 1)
        today = datetime.today().date()
        if today.weekday() == 0:  # Monday
            last_saturday = today - timedelta(days=2)
            last_friday = today - timedelta(days=3)
            if file_date == last_saturday or file_date == last_friday:
                print(f"✅ Settlement Date {file_date} is last Saturday's or Friday's date.")
            else:
                raise ValueError(f"⛔️ Settlement Date {file_date} does not match last Saturday's or Friday's date {last_saturday}.")
        else:
            if file_date == yesterday:
                print(f"✅ Settlement Date {file_date} is yesterday's date.")
            else:
                raise ValueError(f"⛔️ Settlement Date {file_date} does not match yesterday's date {yesterday}.")

    def run_all_checks(self):
        """
        Run all checkpoint checks.
        Returns the moneris csv.file, "sales summary by merchant" as DataFrame and filters to required columns.
        Raises ValueError if any check fails.
        """
        self.check_required_columns()
        self.check_total_sameAs_deposit()
        self.check_cardType()
        #self.check_date()
        print("******✅ All checks passed successfully.******")
        print("\n")
        return self.df[self.required_columns]



# Transformation Class
class Transformation:
    def __init__(self, df, mapping_path='moneris_practice_mapping.csv'):
        self.df = df.copy()  # safer to avoid modifying original df
        self.mapping = pd.read_csv(mapping_path, usecols=["Merchant Number", "Internal ID", "Name (no hierarchy)", "Is Practice Closed?"])
        file_date  = pd.to_datetime(self.df['Settlement Date'], format='%Y%m%d').dt.date.unique()[0]
        self.date = str(file_date).strip()
        self._merge_mapping()

    def _merge_mapping(self):
        self.df = pd.merge( self.df, self.mapping, how='left', on='Merchant Number' )

    def lines_maker(self,line):
        """ Create line dictionary from a DataFrame row. """
        
        amount = line["Net Deposit"]
        last_8_digits = str(line["Merchant Number"]).strip()[-8:]
        mmdd = str(line["Settlement Date"]).strip()[-4:]
        card_type_mapping = {
                1: "VSA",
                2: "MC",
                3: "AMX",
                10: "EF"
            }
        cardtype = line["Card Type"]
        if cardtype == 1: # Visa
            prefix = card_type_mapping.get(1)
            memo = f"{prefix} DEP{last_8_digits}"
        elif cardtype == 2: # MasterCard
            prefix = card_type_mapping.get(2)
            memo = f"{prefix} DEP {last_8_digits}"
        elif cardtype == 3: # AMEX
            prefix = card_type_mapping.get(3)
            memo = f"{prefix} DEP{last_8_digits}"
        elif cardtype == 10: # Interac
            prefix = card_type_mapping.get(10)
            memo = f"{prefix}{mmdd} {last_8_digits}"
        
        debit_account = 1044 #NEED TO CHANGE TO 6617 WHEN LIVE
        credit_account = 2608 # Collection Account - Practices
        
        debit_line = {"account": debit_account,"debit": amount, "memo": memo}
        credit_line = {"account": credit_account,"credit": amount, "memo": memo}

        return [debit_line, credit_line]

    def header_maker(self, group):
        """ Create header dictionary for a group. """
        practice_name = group['Name (no hierarchy)'].unique()[0]
        id = str(group['Internal ID'].unique()[0]).strip()
        header = {
                    "trandate": self.date, 
                    "memo": f"Moneris Collection for {practice_name} at {self.date}", 
                    "subsidiary": id,
                    "externalid": f"moneris_{id}_{self.date}"
                }
        return header
    
    def create_payloads(self):
        """ Create payloads in json form for each group in the DataFrame. 
        Returns a list of payload dictionaries.
        """
        payloads = []
        used_ids = set()
        for id, group in self.df.groupby("Internal ID"):
            
            # header
            header = self.header_maker(group)
            # body lines
            lines = []
            for _, row in group.iterrows():
                line_entries = self.lines_maker(row)
                lines.extend(line_entries)
            payload = {
                **header,
                "lines": lines
            }
            payloads.append(payload)
            used_ids.add(id)
        
        active_practice  = self.mapping[self.mapping["Is Practice Closed?"] == "No"]
        all_ids_dict = active_practice.set_index("Internal ID")["Name (no hierarchy)"].to_dict()
        all_ids_set  = set(active_practice["Internal ID"].unique())
        missing_ids = all_ids_set - used_ids
        print(f"****** ✅ Created {len(payloads)} payloads successfully.******")
        print("\n")
        missing_practice = [all_ids_dict.get(id) for id in missing_ids]
        print(f"****** ‼️ Missing payloads for {len(missing_practice)} Practices: {missing_practice}******")
        print("\n")
        return payloads   



# Final Checkpoint Class
class FinalCheckpoint:
    def __init__(self, payloads):
        self.payloads = payloads
    def is_balanced(self):
        """ Check if each payload is balanced (total debits equal total credits). """
        for payload in self.payloads:
            total_debits = sum(line["debit"] for line in payload["lines"] if "debit" in line)
            total_credits = sum(line["credit"] for line in payload["lines"] if "credit" in line)
            if total_debits != total_credits:
                raise ValueError(f"Payload with external ID {payload['externalid']} is not balanced: Debits = {total_debits}, Credits = {total_credits}")
        print("All payloads are balanced.")


    def run_final_check(self):
        self.is_balanced()
        return self.payloads
    


class Loader:
    def __init__(self, payloads):
        self.payloads = payloads
        self.url = "https://4571901-sb1.restlets.api.netsuite.com/app/site/hosting/restlet.nl?script=2331&deploy=1"
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



class Summary:
    @staticmethod
    def generate(results, df):
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
       
        if nduplicate > 0:
            print(f"- {nduplicate} journal entries were duplicates and not posted again."+ "\n")
        else:
            print("- No duplicate journal entries found." + "\n")
        
        if nsuccess > 0:
            print(f"- Posted {nsuccess} journal entries successfully.", "\n")
        else:
            print("- No successful journal entries posted." + "\n")
        
        if nfailure > 0:
            print(f"- {nfailure} journal entries failed to post. See details below:" + "\n")
        else:
            print("- No failed journal entries." + "\n")

        # ----------- Failure DataFrame ---------------- #
        fails = []
        fail_raw = [r for r in results if r.get("status") != 200]
        if nfailure > 0:
            for fail in fail_raw:
                body = fail.get("body") or {}
                err = body.get("error") or {}
                raw_msg = err.get("message") or {}

                if isinstance(raw_msg, str):
                    cleaned = raw_msg.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
                    data = json.loads(cleaned)
                else:
                    data = {"name": "Unknown Error", "message": str(raw_msg)}

                f = { 'payloadExternalId': fail["payloadExternalId"], 
                        'Internal ID': fail["payloadExternalId"].split("_")[1],
                        'status': fail["status"],
                        'Name': data["name"],
                        'Message': data["message"]}
                fails.append(f)
                
                print(f"- {f}", "\n")
        
        
                    
        # The summary dataframe starts here
        print("\n" + "Summary")
        # Get the moneris file with mapping
        df_mapping = Transformation(df).df
        df_mapping = df_mapping.groupby("Internal ID").agg({'Net Deposit': lambda x: round(x.sum(),2),
                                       "Merchant Number": lambda x: sorted(int(v) for v in x.dropna().unique()),
                                       "Name (no hierarchy)": 'first'}).reset_index()
        df_mapping["Internal ID"] = df_mapping["Internal ID"].astype(str).str.strip()

        # ------------- Successful dataframe ---------------- #
        success = [r for r in results if (r.get("status") == 200 and r.get("body").get("report")== "success")] 
        success_ = pd.DataFrame()
        if success:
            success_df = pd.json_normalize(success)
            success_ = pd.merge(df_mapping, success_df, left_on='Internal ID', right_on='body.subsidiary', how='right')
            success_.drop(columns= "body.subsidiary", inplace = True)
       
        #--------------- Duplicate dataframe ----------------- #
        duplicate = [result for result in results if result["body"].get("report")=="duplicate"]
        duplicate_ = pd.DataFrame()
        if duplicate:
            duplicate_df = pd.json_normalize(duplicate)
            duplicate_ = pd.merge(df_mapping, duplicate_df, left_on='Internal ID', right_on='body.subsidiary', how='right')
            duplicate_.drop(columns= "body.subsidiary", inplace = True)
            
        # --------------- Failed dataframe ----------------- #
        fail_df = pd.DataFrame(fails) if fails else None
        fail_ = pd.DataFrame()
        if fail_df is not None:
            fail_ = pd.merge(df_mapping, fail_df, left_on='Internal ID', right_on='Internal ID', how='right')
            fail_.drop(columns="Message", inplace=True)
            fail_.rename(columns={"Name":"body.report"}, inplace=True)
        

        # Combine all dataframe summary 
        result_frames = []
        for df_ in (success_, duplicate_, fail_):
            if not df_.empty:
                result_frames.append(df_)



        combined = pd.concat(result_frames, ignore_index=True, sort=False) 

        return combined