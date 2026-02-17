
from classes import *
import asyncio
import itertools
import sys
import time
import sqlite3


async def spinner(message="Loading..."):
    for symbol in itertools.cycle(["-", "\\", "|", "/"]):
        print(f"\r{message} {symbol}", end="", flush=True)
        await asyncio.sleep(0.1)

async def main():
    # read and validate data
    df = Checkpoint().run_all_checks()

    df_to_sql = df.copy()
    df_to_sql["externalID"] = df_to_sql["Settlement Date"].astype(str) + "-" + df_to_sql["Merchant Number"].astype(str) + "-" + df_to_sql["Card Type"].astype(str)
    # store raw data into sqlite
    df_to_sql["created_date"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect("Moneris.db")

 
    # stage table (replace each run)
    df_to_sql.to_sql("_raw_data_stage", conn, if_exists="replace", index=False)
    cols = df_to_sql.columns.tolist()
    col_list = ", ".join([f'"{c}"' for c in cols])

    # insert first-seen only
    conn.execute(f"""
    INSERT OR IGNORE INTO Raw_Data ({col_list})
    SELECT {col_list}
    FROM _raw_data_stage;
    """)
    conn.execute("DROP TABLE _raw_data_stage;")
    conn.commit()

    # continue with transformation
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
    #print(results)
    summary = Summary.generate(results, df)
    summary["created_date"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    summary["Merchant Number"] = summary["Merchant Number"].apply(lambda x: json.dumps(x) if isinstance(x, list) else x)
    print(summary)

    


    # Stage table to avoid inserting duplicates
    summary.to_sql("_je_summary_stage", conn, if_exists="replace", index=False)

    cols = summary.columns.tolist()
    col_list = ", ".join([f'"{c}"' for c in cols])

    conn.execute(f"""
    INSERT OR IGNORE INTO JE_Summary ({col_list})
    SELECT {col_list}
    FROM _je_summary_stage;
    """)


    conn.execute("DROP TABLE IF EXISTS _je_summary_stage;")
    conn.commit()    

    conn.close()

    # save summary to csv file
    Summary.save_to_csv(summary) 
    
    print("\n" + "😼 Done!")


if __name__ == "__main__":
    asyncio.run(main())