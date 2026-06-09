import httpx
import asyncio
import random
from typing import Dict, Any, List
from typing import Optional
from DATABASE.Database_management import db
from Security.get_secretes import load_env_from_secret
from Security.Advance_Logger import logger

GANDHINAGAR_ZONES = {
    # Core Sectors (Grid layout mapping)
    "Sector_1_Residential":  {"lat": 23.1999, "lon": 72.6446},
    "Sector_2_Residential":  {"lat": 23.2012, "lon": 72.6405},
    "Sector_3_Residential":  {"lat": 23.2039, "lon": 72.6289},
    "Sector_5_CivicHub":     {"lat": 23.2178, "lon": 72.6282},
    "Sector_6_Residential":  {"lat": 23.2185, "lon": 72.6391},
    "Sector_10_VidhanSabha": {"lat": 23.2233, "lon": 72.6492},
    "Sector_11_Commercial":  {"lat": 23.2251, "lon": 72.6410},
    "Sector_14_CapitalRwy":  {"lat": 23.2347, "lon": 72.6300},
    # "Sector_17_Commercial":  {"lat": 23.2272, "lon": 72.6525},
    # "Sector_21_Market":      {"lat": 23.2356, "lon": 72.6567},
    # "Sector_24_Residential": {"lat": 23.2450, "lon": 72.6530},
    # "Sector_28_GIDC":        {"lat": 23.2562, "lon": 72.6681},
    # "Sector_30_Periphery":   {"lat": 23.2625, "lon": 72.6710},
    
    # # # Outer Tech & Education Hubs
    # "Infocity_TechPark":     {"lat": 23.1915, "lon": 72.6308},
    # "GIFT_City_FinTech":     {"lat": 23.1675, "lon": 72.6792},
    # "PDPU_KnowledgeCorridor":{"lat": 23.1550, "lon": 72.6650},
    # "Koba_Institutional":    {"lat": 23.1365, "lon": 72.6280},

    #  # Peripheral / High-Density Suburbs
    # "Sargasan_Crossroad":    {"lat": 23.1932, "lon": 72.6138},
    # "Kudasan_Residential":   {"lat": 23.1850, "lon": 72.6250},
    # "Randesan_Development":  {"lat": 23.1720, "lon": 72.6350},
    # "Raysan_Corridor":       {"lat": 23.1780, "lon": 72.6450},
    # "Vavol_Residential":     {"lat": 23.2200, "lon": 72.6100},
    # "Adalaj_Heritage":       {"lat": 23.1667, "lon": 72.5800}
}

OPENWEATHER_KEY = load_env_from_secret("WEATHER_API_KEY")
TOMTOM_KEY = load_env_from_secret("TRAFFIC_API_KEY")
WAQI_KEY = load_env_from_secret("AQI_API_KEY")

async def get_zone_weather(client: httpx.AsyncClient, lat: float, lon: float) -> float:
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_KEY}&units=metric"
        res = await client.get(url, timeout=4.0)
        res.raise_for_status() 
        
        return float(res.json().get("rain", {}).get("1h", 0.0))
    except Exception as e:
        logger.error("inputs.get_zone_weather", e)
        return False

async def get_zone_traffic( client: httpx.AsyncClient, lat: float, lon: float ) -> Optional[float]:
    """
    Returns congestion level as percentage (0.0 = free flow, 100.0 = stopped).
    Returns None on failure.
    """
    try:
        url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/relative/10/json"
        params = {
            "point": f"{lat},{lon}",
            "key": TOMTOM_KEY,
            "unit": "kmph",          # or "mph"
        }
        res = await client.get(url, params=params, timeout=4.0)
        res.raise_for_status()
        data = res.json()
        
        flow = data.get("flowSegmentData")
        if not flow:
            return None
        
        curr_speed = flow.get("currentSpeed")
        free_speed = flow.get("freeFlowSpeed")
        
        if curr_speed is None or free_speed is None or free_speed == 0:
            return None
        
        congestion = (1.0 - (curr_speed / free_speed)) * 100.0
        return max(0.0, min(100.0, congestion))
    except Exception as e:
        logger.error("inputs.get_zone_traffic", e)
        return False


async def get_zone_pollution(client: httpx.AsyncClient, lat: float, lon: float) -> float:
    try:
        url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={WAQI_KEY}"
        res = await client.get(url, timeout=4.0)
        res.raise_for_status()
        
        data = res.json()
        if data["status"] != "ok":
            raise ValueError(f"WAQI API Error: {data.get('data')}")
            
        return float(data["data"]["aqi"])
    except Exception as e:
        logger.error("inputs.get_zone_pollution", e)
        return False

async def get_zone_panic_metrics(lat: float, lon: float, radius_km: float = 3.0) -> dict:
    """
    Fetches real panic message volume from database for a zone.
    Returns current and previous window counts for acceleration calculation.
    """
    loop = asyncio.get_running_loop()
    try:
        counts = await loop.run_in_executor(
            None,
            db.get_panic_message_counts_near,
            lat, lon, radius_km, 30 
        )
        return {
            "citizen_msg_volume": counts.get("current_window", 0),
            "prev_msg_volume": counts.get("previous_window", 0)
        }
    except Exception as e:
        logger.error("inputs.get_zone_panic_metrics", e)
        return {"citizen_msg_volume": 0, "prev_msg_volume": 0}
    
async def fetch_single_zone_packet(client: httpx.AsyncClient, name: str, lat: float, lon: float) -> Dict[str, Any]:
    try:
        results = await asyncio.gather(
            get_zone_weather(client, lat, lon),
            get_zone_traffic(client, lat, lon),
            get_zone_pollution(client, lat, lon),
            get_zone_panic_metrics(lat, lon)
        )
        
        panic_metrics = results[3]
        congestion_level = results[1]
        if congestion_level is None:
            congestion_level = 1.0

        return {
            "zone_name": name,
            "latitude": lat,
            "longitude": lon,
            "rainfall": results[0],
            "water_level": random.randint(0, 5),  
            "congestion_level": round(results[1], 2),
            "aqi": results[2],
            "citizen_msg_volume": panic_metrics["citizen_msg_volume"],
            "prev_msg_volume": panic_metrics["prev_msg_volume"]
        }

    except Exception as e:
        logger.error("inputs.fetch_single_zone_packet", e)
        return False


async def compile_complete_gandhinagar_report() -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient() as client:
            tasks = []
            for zone_name, coordinates in GANDHINAGAR_ZONES.items():
                tasks.append(fetch_single_zone_packet(client, zone_name, coordinates["lat"], coordinates["lon"]))
            
            master_report = await asyncio.gather(*tasks)
            return master_report
    except Exception as e:
        logger.error("inputs.compile_complete_gandhinagar_report", e)
        return False


if __name__ == "__main__":
    import json
    
    async def main():
        print("[RAW DEBUG MODE] Launching unshielded API calls...")
        city_metrics = await compile_complete_gandhinagar_report()
        print("\n=== SYSTEM COMPLETE GANDHINAGAR DATA ARRAY ===")
        print(json.dumps(city_metrics, indent=2))

    asyncio.run(main())