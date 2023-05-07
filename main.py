import asyncio

import lib

async def main():
    api = lib.EggIncApi("https://www.auxbrain.com/ei/{}", "YOUR_USERID_HERE", 47)
    contracts = await api.get_current_contracts()

    print(contracts)

if __name__ == "__main__":
    asyncio.run(main())