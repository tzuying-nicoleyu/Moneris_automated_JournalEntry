
from class_finadj import *
import asyncio

async def main():
    df = LoadFinAdj().check_required_columns()
    payloads = TransformFinAdj(df).create_payloads()

    results = await UploadFinAdj(payloads).load_payloads_async()

    SummaryFinAdj.generate(results)

if __name__ == "__main__":
    asyncio.run(main())