import math
import asyncio
import json
import random
from typing import Dict, Any
from DATABASE.Database_management import db, cache
from RAG.Gemini_Api_connection import GeminiFunctions
from INPUTS.inputs import GANDHINAGAR_ZONES
from DATABASE.Database_management import cache
from CONTACTING.email_sender import send_escalation_email
from Security.Advance_Logger import logger
from ENGINE.panic_analysis import calculate_emergency_keyword_score, calculate_sentiment_score
from ENGINE.forcast_engine import forecast_engine

DECAY_RATE = 0.72
FLOOD_WEIGHT = 0.30
TRAFFIC_WEIGHT = 0.25
PANIC_WEIGHT = 0.45
ESCALATION_THRESHOLD = 65
AQI_WEIGHT = 0.15

CITY_RESOURCES_GANDHINAGAR = {
    "ambulances_available": 42,
    "fire_engines": 18,
    "police_units": 115,
    "ndrf_teams": 4, 
    "active_shelters": 6,
    "shelter_capacity": 4500
}

DETERMINISTIC_POLICIES = {
    "SAFE": {
        "close_roads": False,
        "activate_shelters": False,
        "deploy_rescue_units": False,
        "broadcast_interval_minutes": 60,
        "evacuation": False
    },
    "ELEVATED": {
        "close_roads": False,
        "activate_shelters": False,
        "deploy_rescue_units": False,
        "broadcast_interval_minutes": 30,
        "evacuation": False
    },
    "WARNING": {
        "close_roads": True,  
        "activate_shelters": True, 
        "deploy_rescue_units": True,
        "broadcast_interval_minutes": 15,
        "evacuation": False
    },
    "CRITICAL": {
        "close_roads": True,
        "activate_shelters": True,
        "deploy_rescue_units": True,
        "broadcast_interval_minutes": 5,
        "evacuation": True
    }
}

async def fetch_critical_city_state() -> dict:
    zone_names = list(GANDHINAGAR_ZONES.keys())
    tasks = [cache.get_zone_state(zone) for zone in zone_names]
    results = await asyncio.gather(*tasks)
    critical_zones = {}
    for zone, state in zip(zone_names, results):
        if state and state.get("escalation_score", 0) >= ESCALATION_THRESHOLD:
            critical_zones[zone] = state
    return critical_zones

def calculate_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2)**2)
    return 2 * r * math.asin(math.sqrt(a))

async def flood_agent(metrics: Dict[str, Any], prev_state: Dict[str, Any]) -> float:
    rain = metrics.get("rainfall", 0.0)
    water_level = metrics.get("water_level", 0.0)
    instant = (rain * 0.55 + water_level * 0.45) * 1.1
    decayed = prev_state.get("flood_risk", 0) * DECAY_RATE
    return min(100.0, max(0.0, decayed + instant))

async def sentiment_agent(metrics: Dict[str, Any], prev_state: Dict[str, Any]) -> float:
    current = metrics.get("citizen_msg_volume", 0)
    previous = metrics.get("prev_msg_volume", 0)
    messages = metrics.get("messages", [])
    if previous <= 0:
        message_velocity = min(current * 8, 100)
    else:
        growth = ((current - previous) / max(previous, 1))
        message_velocity = min(max(growth * 100, 0), 100)
    sentiment_score = (calculate_sentiment_score(messages))
    emergency_keywords = (calculate_emergency_keyword_score(messages))
    telecom_anomaly = min(current / 40, 1.0) * 100
    panic = (sentiment_score * 0.35 + message_velocity * 0.30 + emergency_keywords * 0.20 + telecom_anomaly * 0.15)
    previous_panic = prev_state.get("panic_index", 0)
    panic = (previous_panic * 0.35 + panic * 0.65)
    return round(max(0.0, min(100.0, panic)), 2)

async def mobility_agent(metrics: Dict[str, Any], flood_risk: float, panic_index: float) -> float:
    base_traffic = metrics.get("congestion_level", 0.0)
    flood_impact = (flood_risk / 100) ** 2.2 * 35
    panic_impact = (panic_index / 100) * 22
    def logistic_normalize(x: float, k: float = 0.08, x0: float = 50):
        return 100 / (1 + math.exp(-k * (x - x0)))
    raw_score = (base_traffic * 0.5) + flood_impact + panic_impact
    return logistic_normalize(raw_score)

async def dispatch_agent(zone: str, lat: float, lon: float, escalation_score: float, ai_decision: dict):
    try:
        if escalation_score < ESCALATION_THRESHOLD:
            return
        radius = 2.5 if escalation_score < 80 else 4.5
        citizens = await asyncio.get_running_loop().run_in_executor(None, db.fetch_all_citizens)
        alert_message = ai_decision.get("citizen_alert_broadcast", f"Emergency alert for {zone}")
        tasks = []
        for citizen in citizens:
            distance = calculate_haversine(lat, lon, citizen["latitude"], citizen["longitude"])
            if distance <= radius:
                tasks.append(send_escalation_email(alert_message, citizen["email"]))
        if tasks:
            await asyncio.gather(*tasks)
            logger.info(f"[DISPATCH] Sent alerts to {len(tasks)} citizens in {zone}")
    except Exception as e:
        logger.error("simulation_engine.dispatch_agent", e)
        return False

async def ai_governance_agent(zone: str, metrics: dict, current_state: dict, policy: dict, forecasts: dict) -> dict:
    try:
        ai = GeminiFunctions()
        
        prompt = f"""
        You are the UrbanOS AI Governance Layer for Gandhinagar. 
        Your primary function is tactical analysis and citizen communication for this specific zone.
        
        // 1. LIVE TELEMETRY
        ZONE: {zone}
        COMPUTED RISK STATE: {json.dumps(current_state, indent=2)}
        LIVE METRICS: {json.dumps(metrics, indent=2)}
        
        // 2. TEMPORAL FORECASTS (15m to 6h)
        {json.dumps(forecasts, indent=2)}
        
        // 3. DETERMINISTIC POLICY LIMITATIONS (HARD CONSTRAINTS)
        Current Enforced Policy: {json.dumps(policy, indent=2)}
        You MUST strictly align your recommendations with these hardcoded states. 
        If policy.evacuation is False, DO NOT mention evacuation.
        
        // 4. AVAILABLE CITY RESOURCES
        {json.dumps(CITY_RESOURCES_GANDHINAGAR, indent=2)}
        
        Return ONLY valid JSON matching this exact structure:
        {{
          "operational_constraints": "Identify physical, meteorological, or data constraints currently limiting response capabilities in this zone.",
          "available_resources": "List the subset of city resources that can realistically be routed to this zone.",
          "forecast_windows": "Summarize the critical threat vectors expected between T+15m and T+6h.",
          "policy_limitations": "Identify which actions are currently locked or mandated by the deterministic policy.",
          "approved_routes": ["List specific safe transit corridors"],
          "blocked_routes": ["List specific closed or hazardous roads"],
          "shelter_state": "Current operational status and capacity of nearest shelters.",
          "recommended_action": "Precise, numbered priority execution steps based on the constraints established above.",
          "traffic_reroute_plan": "Specific traffic flow adjustments. Must be null if roads are not closed.",
          "citizen_alert_broadcast": "Concise, actionable instruction for the public. Focus on immediate physical safety.",
          "confidence_score": 0.0
        }}
        """
        try:
            response = await ai.generate_response(prompt)
            clean = response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except Exception as e:
            print(f"Zone AI Failure [{zone}]: {e}")
            return {
                "operational_constraints": "Telemetry failure; operating blind.",
                "available_resources": "Unverified.",
                "forecast_windows": "Data unavailable.",
                "policy_limitations": "Default passive monitoring enforced.",
                "approved_routes": [],
                "blocked_routes": [],
                "shelter_state": "Status unverified.",
                "recommended_action": "1. Maintain passive monitoring.\n2. Await subsequent cycle.",
                "traffic_reroute_plan": None,
                "citizen_alert_broadcast": f"Stay alert in {zone}. Monitor official channels.",
                "confidence_score": 0.5
            }
    except Exception as e:
        logger.error("simulation_engine.ai_governance_agent", e)
        return False

async def broadcast_event(event_type: str, data: dict):
    """Pushes live execution state to Redis PubSub"""
    try:
        client = cache.get_client()
        payload = {"type": event_type, **data}
        await client.publish("urban_pipeline_stream", json.dumps(payload))
    except Exception as e:
        print(f"Broadcast error: {e}")

async def process_urban_state_step(zone: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    await broadcast_event("agent_step", {"agent": "data", "status": "processing"})
    await broadcast_event("agent_step", {"agent": "data", "status": "completed", "output": "Metrics received"})
    await broadcast_event("log", {"text": f"Starting analysis for {zone}", "level": "info"})
    
    rain = metrics.get("rainfall", 0.0)
    water = metrics.get("water_level", 0.0)
    traffic_base = metrics.get("congestion_level", 0.0)
    msgs = metrics.get("citizen_msg_volume", 0)
    aqi = metrics.get("aqi", 50.0)

    prev_state = await cache.get_zone_state(zone) or {"flood_risk": 0, "traffic_congestion": 0, "panic_index": 0}

    infra_quality = 1.0
    if rain > 5.0 or water > 5.0:
        infra_quality = max(0.5, min(1.5, (rain + 1.0) / (water + 1.0)))

    activity_load = (traffic_base / 100.0) * 0.6 + (min(msgs, 200) / 200.0) * 0.4
    density_multiplier = max(0.8, min(1.5, 0.8 + activity_load))
    
    # 1. Flood Agent
    await broadcast_event("agent_step", {"agent": "flood", "status": "processing"})
    flood_raw = await flood_agent(metrics, prev_state)
    flood = max(0.0, min(100.0, flood_raw / infra_quality))
    await broadcast_event("agent_step", {"agent": "flood", "status": "completed", "output": f"{round(flood, 1)}% risk"})
    
    # 2. Sentiment Agent
    await broadcast_event("agent_step", {"agent": "sentiment", "status": "processing"})
    panic_raw = await sentiment_agent(metrics, prev_state)
    panic = min(100.0, panic_raw * density_multiplier)
    await broadcast_event("agent_step", {"agent": "sentiment", "status": "completed", "output": f"{round(panic, 1)} idx"})

    # 3. Mobility Agent
    await broadcast_event("agent_step", {"agent": "mobility", "status": "processing"})
    traffic_raw = await mobility_agent(metrics, flood, panic)
    traffic = min(100.0, traffic_raw * density_multiplier)
    await broadcast_event("agent_step", {"agent": "mobility", "status": "completed", "output": f"{round(traffic, 1)}% cong"})

    aqi_risk = min(100.0, (aqi / 300.0) * 100.0)

    escalation_score = (flood * FLOOD_WEIGHT) + (traffic * TRAFFIC_WEIGHT) + (panic * PANIC_WEIGHT) + (aqi_risk * AQI_WEIGHT)
    
    if escalation_score >= 80: alert_level = "CRITICAL"
    elif escalation_score >= ESCALATION_THRESHOLD: alert_level = "WARNING"
    elif escalation_score >= 40: alert_level = "ELEVATED"
    else: alert_level = "SAFE"

    current_policy = DETERMINISTIC_POLICIES[alert_level]

    current_state = {
        "flood_risk": round(flood, 2),
        "traffic_congestion": round(traffic, 2),
        "panic_index": round(panic, 2),
        "aqi_risk": round(aqi_risk, 2),
        "escalation_score": round(escalation_score, 2),
        "alert_level": alert_level,
        "latitude": metrics.get("latitude"),
        "longitude": metrics.get("longitude"),
        "enforced_policy": current_policy
    }

    forecasts = await forecast_engine.generate_forecasts(current_state)

    current_state["forecasts"] = forecasts
    
    # 4. AI Agent
    await broadcast_event("agent_step", {"agent": "ai", "status": "processing"})
    if escalation_score >= ESCALATION_THRESHOLD:
        ai_decision = await ai_governance_agent(zone=zone, metrics=metrics, current_state=current_state, policy=current_policy, forecasts=forecasts)
        current_state["ai_governance"] = ai_decision
        
        await broadcast_event("agent_step", {"agent": "dispatch", "status": "processing"})
        await dispatch_agent(zone, metrics["latitude"], metrics["longitude"], escalation_score, ai_decision)
        await broadcast_event("agent_step", {"agent": "dispatch", "status": "completed", "output": "Alerts sent"})
    else:
        current_state["ai_governance"] = None
        await broadcast_event("agent_step", {"agent": "dispatch", "status": "completed", "output": "No dispatch"})

    await broadcast_event("agent_step", {"agent": "ai", "status": "completed", "output": "Done"})

    # Save AFTER setting ai_governance so dashboard can show AI recommendations
    await cache.save_zone_state(zone, current_state)


    await broadcast_event("cycle_complete", {"zone": zone})
    await broadcast_event("agent_step", {"agent": "final", "status": "completed", "output": alert_level})
    
    return current_state

async def global_apex_commander(active_zones_data: dict) -> dict:
    """
    Takes a dictionary of all zones currently at or above the ESCALATION_THRESHOLD.
    """
    ai = GeminiFunctions()
    
    prompt = f"""
    You are the Apex Command AI for Gandhinagar.
    
    // 1. SYSTEMIC CONSTRAINTS & AVAILABLE RESOURCES
    {json.dumps(CITY_RESOURCES_GANDHINAGAR, indent=2)}
    You operate under a strict resource cap. You cannot deploy more units than exist.
    
    // 2. ACTIVE THREAT ZONES (Telemetry & Forecasts)
    {json.dumps(active_zones_data, indent=2)}
    
    Analyze the escalation scores, forecasts, and deterministic policy states of all active zones.
    Determine the optimal deployment of finite resources to minimize total city-wide impact.
    
    Return ONLY valid JSON matching this exact structure:
    {{
      "city_wide_priority_execution": [
        "1. [Highest Priority] Deploy 10 NDRF to Sector 28 due to 85% flood forecast.",
        "2. [Secondary] Reroute traffic from Sargasan using SG Highway."
      ],
      "global_resource_ledger": {{
        "Zone_Name_1": {{"ambulances": 5, "fire_engines": 2, "police": 10}},
        "Zone_Name_2": {{"ambulances": 0, "fire_engines": 0, "police": 2}}
      }},
      "approved_evacuation_routes": ["List specific clear routes based on traffic telemetry"],
      "blocked_routes": ["List specific hazardous routes"],
      "citizen_broadcast": "A single, comprehensive set of instructions for the public. State exactly what to do and what not to do."
    }}
    """
    try:
        response = await ai.generate_response(prompt)
        clean = response.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"Apex Commander Failure: {e}")
        return {
            "city_wide_priority_execution": ["System fault: Manual triage required."],
            "global_resource_ledger": {},
            "approved_evacuation_routes": [],
            "blocked_routes": [],
            "citizen_broadcast": "Emergency declared. Await official instructions and remain indoors."
        }

if __name__ == "__main__":
    async def main():
        from INPUTS.inputs import fetch_single_zone_packet
        import httpx
        async with httpx.AsyncClient() as client:
            result = await fetch_single_zone_packet(client=client, name="Sector 1", lat=23.1999, lon=72.6446)
            return await process_urban_state_step("Sector 1", result)
    print(asyncio.run(main()))