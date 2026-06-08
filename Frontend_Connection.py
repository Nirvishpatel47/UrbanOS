from fastapi import FastAPI, Form, UploadFile, File, Depends, Request
from contextlib import asynccontextmanager
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi_limiter.depends import RateLimiter
from fastapi import Header, HTTPException
from fastapi.staticfiles import StaticFiles
from Security.Advance_Logger import logger
from Security.JWT_token import create_token, decode_token
from Security.get_secretes import load_env_from_secret
from fastapi_limiter import FastAPILimiter
from urllib.parse import urlparse
from DATABASE.Database_management import db, cache
from INPUTS.inputs import GANDHINAGAR_ZONES, compile_complete_gandhinagar_report
from ENGINE.simulation_engine import process_urban_state_step, global_apex_commander, fetch_critical_city_state
import random

from DATABASE.Database_management import cache  # Or your specific Redis manager instance

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = cache.get_client() 
    
    await FastAPILimiter.init(redis_client)
    yield
    
    await redis_client.close()

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static", html=True), name="static")

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_citizen_email(authorization: str = Header(...)):
    try:
        token = authorization.split(" ")[1]  # "Bearer <token>"
        return decode_token(token)
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
@app.get("/", response_class=HTMLResponse)
async def landing_page():
    with open("templates/landing.html", "r", encoding="utf-8") as file:
        return file.read()
    
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    with open("templates/login.html", "r", encoding="utf-8") as file:
        return file.read()

@app.get("/signin", response_class=HTMLResponse)
async def signin_page():
    with open("templates/signin.html", "r", encoding="utf-8") as file:
        return file.read()

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    with open("templates/dashboard.html", "r", encoding="utf-8") as file:
        return file.read()
    

@app.post("/login", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def login( email: str = Form(...), password: str = Form(...) ):
    try:
        row = db.authenticate_citizen(email=email, password=password)
        if row:
            token = create_token(email=email)
            return JSONResponse(
                        {
                            "success": True,
                            "message": "Login successful",
                            "token": token,
                            "user": {
                                "email": row.email,
                                "latitude": row.latitude,
                                "longitude": row.longitude
                            }
                        }
                    )
        else:
            return JSONResponse(
                {
                    "success": False,
                    "message": "User not found"
                }
            )
    except Exception as e:
        logger.error("Frontend_Connection.login", e)

@app.post("/signin", dependencies=[Depends(RateLimiter(times=3, seconds=60))])
async def signin(email: str = Form(...), password: str = Form(...), lat: str = Form(...), lon: str = Form(...)):
    try:
        if db.register_citizen(email=email, password=password, lat=lat, lon=lon):
            token = create_token(email=email)
            return JSONResponse({
                    "success": True,
                    "message": "sign-in successful",
                    "token": token,
                    "user": {
                        "email": email
                    }
                })
        else:
            return JSONResponse({
                    "success": True,
                    "message": "Registration Failed"
                })
    except Exception as e:
        logger.error("Frontend_Connection.signin", e)
        return JSONResponse({
                        "success": True,
                        "message": "Registration Failed"
                    })

@app.post("/text", dependencies=[Depends(RateLimiter(times=3, seconds=60))])
async def text(email: str = Form(...), text: str = Form(...), lat: str = Form(...), lon: str = Form(...)):
    try:
        if db.log_panic_message(email=email, message=text, lat=lat, lon=lon):
            return JSONResponse({
                    "success": True,
                    "message": "Done",
                })
        else:
            return JSONResponse({
                    "success": True,
                    "message": "Failed"
                })
    except Exception as e:
        logger.error("Frontend_Connection.signin", e)
        return JSONResponse({
                        "success": True,
                        "message": "Failed"
                    })

@app.get("/report", response_class=HTMLResponse)
async def report_page():
    with open("templates/report.html", "r", encoding="utf-8") as file:
        return file.read()

from fastapi.responses import StreamingResponse
@app.get("/api/zones")
async def get_zones():
    real_zones = []
    
    for zone_name, coords in GANDHINAGAR_ZONES.items():
        state = await cache.get_zone_state(zone_name) or {}
        
        lat = state.get("latitude") or coords["lat"]
        lon = state.get("longitude") or coords["lon"]
        
        if state and state.get("flood_risk") is not None:
            zone_obj = {
                "id": zone_name,
                "name": zone_name.replace("_", " "),
                "latitude": lat,
                "longitude": lon,
                **state
            }
        else:
            zone_obj = {
                "id": zone_name,
                "name": zone_name.replace("_", " "),
                "latitude": lat,
                "longitude": lon,
                "flood_risk": 0.0,
                "traffic_congestion": 0.0,
                "panic_index": 0.0,
                "escalation_score": 0.0,
                "alert_level": "SAFE",
                "ai_governance": None
            }
        
        real_zones.append(zone_obj)
    
    return JSONResponse(content=real_zones)

@app.get("/api/stream")
async def pipeline_stream(request: Request):
    async def event_generator():
        client = cache.get_client()
        pubsub = client.pubsub()
        await pubsub.subscribe("urban_pipeline_stream")
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    raw_data = message.get("data")
                    if isinstance(raw_data, bytes):
                        data = raw_data.decode("utf-8")
                    else:
                        data = raw_data or ""
                    yield f"data: {data}\n\n"
        finally:
            await pubsub.unsubscribe("urban_pipeline_stream")
            await client.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/run-simulation-cycle")
async def run_simulation_cycle(mode: str = "test"):
    try:
        logger.info(f"Starting simulation cycle | Mode: {mode}")
        city_metrics = await compile_complete_gandhinagar_report()
        
        if not city_metrics or city_metrics is False:
            return JSONResponse({
                "success": False, 
                "message": "Failed to fetch metrics from external APIs"
            })

        if mode == "test":
            logger.warning("⚠️  TEST MODE ACTIVATED → Using fake high-risk data")
            for m in city_metrics:
                if m and isinstance(m, dict):
                    m["rainfall"] = random.randint(90, 110)        # Heavy rainfall
                    m["water_level"] = random.randint(25, 35)          # High water level
                    m["citizen_msg_volume"] = random.randint(20, 200) # High panic messages
                    m["congestion_level"] = random.randint(70, 90)     # High traffic
                    m["prev_msg_volume"] = random.randint(45, 65)

        metrics_map = {}
        for m in city_metrics:
            if m and isinstance(m, dict) and "zone_name" in m:
                metrics_map[m["zone_name"]] = m

        processed_zones = []
        logger.info(f"Processing {len(GANDHINAGAR_ZONES)} zones (mode={mode})...")

        for zone_name in GANDHINAGAR_ZONES.keys():
            if zone_name in metrics_map:
                metrics = metrics_map[zone_name]
                try:
                    state = await process_urban_state_step(zone_name, metrics)
                    processed_zones.append({
                        "zone": zone_name,
                        "escalation_score": state.get("escalation_score"),
                        "alert_level": state.get("alert_level")
                    })
                except Exception as zone_err:
                    logger.error(f"Error processing zone {zone_name}", zone_err)

        return JSONResponse({
            "success": True,
            "message": f"Simulation completed successfully ({mode} mode)",
            "mode": mode,
            "processed_zones": processed_zones
        })
        
    except Exception as e:
        logger.error("Frontend_Connection.run_simulation_cycle", e)
        return JSONResponse({
            "success": False,
            "message": f"Simulation failed: {str(e)}"
        })
    
@app.post("/api/apex-commander")
async def get_decision():
    try:
        critical_zones = await fetch_critical_city_state()
        
        if not critical_zones:
            return JSONResponse({
                "city_wide_priority_execution": ["No critical threats detected. System maintaining passive monitoring."],
                "global_resource_ledger": {},
                "approved_evacuation_routes": [],
                "blocked_routes": [],
                "citizen_broadcast": "City systems nominal. No emergency action required."
            })

        final_decisions = await global_apex_commander(critical_zones)
        return JSONResponse(final_decisions)
        
    except Exception as e:
        logger.error(f"Apex Commander Endpoint Error", e)
        return JSONResponse({
            "city_wide_priority_execution": ["System fault: Triage generation failed."],
            "citizen_broadcast": "Standby for manual instructions."
        }, status_code=500)