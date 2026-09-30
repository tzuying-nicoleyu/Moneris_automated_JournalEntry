
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
from typing import Literal, cast
from dotenv import load_dotenv
import os
load_dotenv(".env")

HTTPMethod = Literal["CONNECT", "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"]


# BEFORE RUNNING TODO:
# 1. Make sure to install required libraries
# 2. Create your own credentails in a .env file in your local environment. Do not push to git!!
# 3. Update the download folder path in Checkpoint class to your own path


# Checkpoint Class 
class Checkpoint:
    def __init__(self,test_file_path=None):
        """
        Initialize the Checkpoint with the and grab latest moneris sales CSV file and required columns.
        If test_file_path is passed, then read test file otherwise read latest file from the destined folder.
        """
        file_pattern= r"Sales Summary by Merchant_Download Date *"
        download_folder_path = r"C:\Users\Tzuying\OneDrive - smilesfirstcorp\Reporting & Business Intelligence\Moneris\Downloaded_Files" # TODO: Change to your download folder path
        full_path = os.path.join(download_folder_path, file_pattern ) 
        list_of_files = glob.glob(full_path)
        latest_file = max(list_of_files, key=os.path.getctime) #latest change time of the file

        
        if not test_file_path: # didn't put any test file path
            read_file = latest_file
        else: # did put test file path
            read_file = test_file_path   

        self.df = pd.read_csv(read_file) #change it to latest_file when running for real
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
        valid_card_types = [1,2,3,6,10,16]
        invalid_card_types =  [ct for ct in self.df["Card Type"].unique()  if ct not in valid_card_types]
        if invalid_card_types:
            raise ValueError(f"⛔️ New Card Types found: {invalid_card_types}")
        else:
            print("✅ All Card Types are valid.")

    def check_date(self):
        """
        Check that every 'Settlement Date' in the file is an expected date.
        If today is Monday, the file may contain last Friday's and/or Saturday's date.
        Otherwise, it must contain only yesterday's date.
        Works for both single-date and multi-date files.
        """
        file_dates = set(pd.to_datetime(self.df['Settlement Date'], format='%Y%m%d').dt.date.unique())
        today = datetime.date.today()
        if today.weekday() == 0:  # Monday -> last Friday and/or Saturday
            allowed = {today - timedelta(days=3), today - timedelta(days=2)}
        else:  # All other days -> yesterday
            allowed = {today - timedelta(days=1)}

        unexpected = file_dates - allowed
        if unexpected:
            raise ValueError(f"⛔️ Unexpected Settlement Date(s) {sorted(unexpected)}; expected {sorted(allowed)}.")
        print(f"✅ Settlement Date(s) {sorted(file_dates)} OK.")

    def run_all_checks(self, check_date: bool = True):
        """
        Run all checkpoint checks.
        Returns the moneris csv.file, "sales summary by merchant" as DataFrame and filters to required columns.
        Raises ValueError if any check fails.
        """
        self.check_required_columns()
        self.check_total_sameAs_deposit()
        self.check_cardType()

        if check_date:
            self.check_date() 

        print("******✅ All checks passed successfully.******")
        print("\n")
        return self.df[self.required_columns]



# Transformation Class
class Transformation:
    def __init__(self, df, mapping_path='moneris_practice_mapping.csv'):
        self.df = df.copy()  # safer to avoid modifying original df
        self.mapping = pd.read_csv(mapping_path, usecols=["Merchant Number", "Internal ID", "Name (no hierarchy)", "Is Practice Closed?"])
        # All settlement dates in the file (one or many)
        self.dates = sorted(pd.to_datetime(self.df['Settlement Date'], format='%Y%m%d').dt.date.unique())
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
                6: "DSC",
                10: "EF",
                16: "UnionPay"
            }
        cardtype = line["Card Type"]
        if cardtype == 1: # Visa
            prefix = card_type_mapping.get(1)
            #memo = f"REV DEP{last_8_digits}"
            memo = f"{prefix} DEP{last_8_digits}"
        elif cardtype == 2: # MasterCard
            prefix = card_type_mapping.get(2)
            memo = f"{prefix} DEP {last_8_digits}"
        elif cardtype == 3: # AMEX
            prefix = card_type_mapping.get(3)
            memo = f"{prefix} DEP{last_8_digits}"
        elif cardtype == 6: # Discover
            prefix = card_type_mapping.get(6)
            memo = f"{prefix} DEP{last_8_digits}"
        elif cardtype == 10: # Interac
            prefix = card_type_mapping.get(10)
            memo = f"{prefix}{mmdd} {last_8_digits}"
        elif cardtype == 16: # UnionPay
            prefix = card_type_mapping.get(16)
            memo = f"{prefix}{mmdd} {last_8_digits}"
        
        debit_account = 6617 #NEED TO CHANGE TO 6617 WHEN LIVE
        credit_account = 2608 # Collection Account - Practices
        #credit_account = 6667 # This is for financial adjustment
        
        debit_line = {"account": debit_account,"debit": amount, "memo": memo}
        credit_line = {"account": credit_account,"credit": amount, "memo": memo}

        return [debit_line, credit_line]

    def header_maker(self, group):
        """ Create header dictionary for a group (one practice on one settlement date). """
        practice_name = group['Name (no hierarchy)'].iloc[0]
        id = str(group['Internal ID'].iloc[0]).strip()
        date = str(pd.to_datetime(str(group['Settlement Date'].iloc[0]), format='%Y%m%d').date())
        header = {
                    "trandate": date,
                    "memo": f"Moneris Collection for {practice_name} at {date}",
                    "subsidiary": id,
                    "externalid": f"moneris_{id}_{date}" # Replace with f"moneris_{id}_{date}_adj" when doing adjustment
                }
        return header

    def create_payloads(self):
        """ Create payloads in json form, one per (Settlement Date, Internal ID) group.
        Works for both single-date and multi-date files.
        Returns a list of payload dictionaries.
        """
        payloads = []
        used = set()  # (settlement_date, internal_id)

        # Merchants not found in the mapping file are skipped by groupby (NaN key) -> warn
        unmapped = self.df[self.df["Internal ID"].isna()]
        if not unmapped.empty:
            print(f"****** ‼️ Unmapped merchants (skipped): {unmapped['Merchant Number'].unique().tolist()} ******")
            print("\n")

        for (settle_date, id), group in self.df.groupby(["Settlement Date", "Internal ID"]):
            # header
            header = self.header_maker(group)
            # body lines
            lines = []
            for _, row in group.iterrows():
                lines.extend(self.lines_maker(row))
            payloads.append({**header, "lines": lines})
            used.add((settle_date, id))

        active_practice = self.mapping[self.mapping["Is Practice Closed?"] == "No"]
        all_ids_dict = active_practice.set_index("Internal ID")["Name (no hierarchy)"].to_dict()
        all_ids = active_practice["Internal ID"].unique()

        print(f"****** ✅ Created {len(payloads)} payloads successfully for dates {[str(d) for d in self.dates]} ******")
        print("\n")
        for settle_date in sorted(self.df["Settlement Date"].unique()):
            missing_practice = [all_ids_dict.get(i) for i in all_ids if (settle_date, i) not in used]
            print(f"****** ‼️ {settle_date}: Missing payloads for {len(missing_practice)} Practices: {missing_practice} ******")
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
        self.url = "https://4571901.restlets.api.netsuite.com/app/site/hosting/restlet.nl?script=3084&deploy=1"  #need to change when live
        self.auth = {
        "client_key": os.getenv("CLIENT_KEY"),
        "client_secret": os.getenv("CLIENT_SECRET"),
        "resource_owner_key": os.getenv("OWNER_KEY"),
        "resource_owner_secret": os.getenv("OWNER_SECRET"),
        "signature_method": SIGNATURE_HMAC_SHA256,
        "realm": os.getenv("REALM"),
        }
        self.concurrency = 2
        self.max_retries = 3
    
    def sign_oauth1(self, url, method: str = "POST", body: str = ""):
        body_hash = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode("utf-8")

        client = Client(
            client_key=self.auth["client_key"],
            client_secret=self.auth["client_secret"],
            resource_owner_key=self.auth["resource_owner_key"],
            resource_owner_secret=self.auth["resource_owner_secret"],
            signature_method="HMAC-SHA256",
            realm=self.auth["realm"],
        )

        http_method = cast(HTTPMethod, method.upper())

        _, headers, _ = client.sign(
            url,
            http_method=http_method,
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
        
        
                    
        # The summary dataframe starts here
        print("\n" + "Summary")
        # Get the moneris file with mapping
        df_mapping = Transformation(df).df
        # One row per (Settlement Date, Internal ID) -> same grain as the payloads
        df_mapping = df_mapping.groupby(["Settlement Date", "Internal ID"]).agg({'Net Deposit': lambda x: round(x.sum(),2),
                                       "Merchant Number": lambda x: sorted(int(v) for v in x.dropna().unique()),
                                       "Name (no hierarchy)": 'first'}).reset_index()
        df_mapping["Internal ID"] = df_mapping["Internal ID"].astype(str).str.strip()
        # Build the same key as header_maker's externalid, so each result matches its own date
        settle = pd.to_datetime(df_mapping["Settlement Date"].astype(str), format='%Y%m%d').dt.strftime('%Y-%m-%d')
        df_mapping["payloadExternalId"] = "moneris_" + df_mapping["Internal ID"] + "_" + settle
        df_mapping.drop(columns="Settlement Date", inplace=True)

        # ------------- Successful dataframe ---------------- #
        success = [r for r in results if (r.get("status") == 200 and r.get("body").get("report")== "success")] 
        success_ = pd.DataFrame()
        if success:
            success_df = pd.json_normalize(success)
            success_ = pd.merge(df_mapping, success_df, on='payloadExternalId', how='right')
            success_.drop(columns= "body.subsidiary", inplace = True)
       
        #--------------- Duplicate dataframe ----------------- #
        duplicate = [result for result in results if result["body"].get("report")=="duplicate"]
        duplicate_ = pd.DataFrame()
        if duplicate:
            duplicate_df = pd.json_normalize(duplicate)
            duplicate_ = pd.merge(df_mapping, duplicate_df, on='payloadExternalId', how='right')
            duplicate_.drop(columns= "body.subsidiary", inplace = True)
            
        # --------------- Failed dataframe ----------------- #
        fail_df = pd.DataFrame(fails) if fails else None
        fail_ = pd.DataFrame()
        if fail_df is not None:
            fail_ = pd.merge(df_mapping, fail_df.drop(columns="Internal ID"), on='payloadExternalId', how='right')
            fail_.drop(columns="Message", inplace=True)
            fail_.rename(columns={"Name":"body.report"}, inplace=True)
        

        # Combine all dataframe summary 
        result_frames = []
        for df_ in (success_, duplicate_, fail_):
            if not df_.empty:
                result_frames.append(df_)



        combined = pd.concat(result_frames, ignore_index=True, sort=False) 

        return combined
    
    @staticmethod
    def save_to_csv(summary_df):
        """ Save the summary DataFrame to a CSV file. """
        today = datetime.date.today()
        today_str = today.strftime("%Y-%m-%d")
        output_file = f"JE_Summary_{today_str}.csv"
        full_path = os.path.join("Summary_Csv_Files", output_file)
        summary_df.to_csv(full_path, index=False, encoding="utf-8")
        print(f"✅ Summary saved to {full_path}")