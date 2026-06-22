
from classes import *
import asyncio
import itertools
import sys
import time
import sqlite3


# ----------------- Helper Functions ------------------------#
async def spinner(message="Loading..."):
    for symbol in itertools.cycle(["-", "\\", "|", "/"]):
        print(f"\r{message} {symbol}", end="", flush=True)
        await asyncio.sleep(0.1)

def store_to_sql(df: pd.DataFrame, db_path: str = "Moneris.db") -> None:
    df_to_sql = df.copy()
    df_to_sql["externalID"] = df_to_sql["Settlement Date"].astype(str) + "-" + df_to_sql["Merchant Number"].astype(str) + "-" + df_to_sql["Card Type"].astype(str)
    df_to_sql["created_date"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(db_path) as conn:
        # Stage table (replace each run)
        df_to_sql.to_sql("_raw_data_stage", conn, if_exists="replace", index=False)

        cols = df_to_sql.columns.tolist()
        col_list = ", ".join([f'"{c}"' for c in cols])

        conn.execute(f"""
            INSERT OR IGNORE INTO Raw_Data ({col_list})
            SELECT {col_list}
            FROM _raw_data_stage;
        """)

        conn.execute("DROP TABLE IF EXISTS _raw_data_stage;")
        conn.commit()

def store_summary_to_sql(df: pd.DataFrame, db_path: str = "Moneris.db") -> None:
    df["created_date"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    df["Merchant Number"] = df["Merchant Number"].apply(lambda x: json.dumps(x) if isinstance(x, list) else x)
    print(df)


    # Stage table to avoid inserting duplicates
    with sqlite3.connect(db_path) as conn:
        df.to_sql("_je_summary_stage", conn, if_exists="replace", index=False)

        cols = df.columns.tolist()
        col_list = ", ".join([f'"{c}"' for c in cols])

        conn.execute(f"""
        INSERT OR IGNORE INTO JE_Summary ({col_list})
        SELECT {col_list}
        FROM _je_summary_stage;
        """)


        conn.execute("DROP TABLE IF EXISTS _je_summary_stage;")
        conn.commit()    

# --------------- Main Function ----------------------------#
async def main():
    # read and validate data

    # Do this while testing, uncomment test_file_path and pass through the Checkpoint() class
    #test_file_path = r"C:\Users\Tzuying\Project\Moneris\Adjustment_File\Financial_Adjustment_Template_File.csv"

    # Replace with the following, if you want to turn off the check date features.
    df = Checkpoint().run_all_checks(check_date=False)

    #df = Checkpoint(test_file_path=test_file_path).run_all_checks(check_date=False)

    #df = Checkpoint().run_all_checks()

    # store to database
    store_to_sql(df)

    # continue with transformationy
    payloads = Transformation(df).create_payloads()
    final_payloads = FinalCheckpoint(payloads).run_final_check()
    

    # async loading with spinner 
    loader = Loader(final_payloads)
    start_time = time.time()
    spinner_task = asyncio.create_task(spinner("Uploading payloads..."))
    results = await loader.load_payloads_async()
    spinner_task.cancel()
    elapsed = time.time() - start_time
    print("\rFinished!                      ")
    print(f"Time used: {elapsed:.2f} seconds")

    # generate summary and store into sqlite
    summary = Summary.generate(results, df)
    store_summary_to_sql(summary)

    # save summary to csv file
    Summary.save_to_csv(summary) 
    
    print("\n" + "😼 Done!")


if __name__ == "__main__":
    asyncio.run(main())