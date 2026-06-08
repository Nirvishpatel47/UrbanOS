import asyncio
from INPUTS.inputs import compile_complete_gandhinagar_report
from ENGINE.simulation_engine import process_urban_state_step

async def test_full_pipeline():
    print("Fetching real city data...")
    city_data = await compile_complete_gandhinagar_report()

    for zone_data in city_data:
        if not zone_data:
            continue

        print(f"\n=== Processing: {zone_data['zone_name']} ===")
        result = await process_urban_state_step(zone_data['zone_name'], zone_data)
        print(result)

asyncio.run(test_full_pipeline())