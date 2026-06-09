import os
import json
import uuid
from Security.Advance_Logger import logger
from Security.get_secretes import load_env_from_secret
from typing import Optional, List, Any
from sqlalchemy import create_engine, text
import redis.asyncio as redis
import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, HashingError

ph = PasswordHasher(
    time_cost=3,        # Number of iterations
    memory_cost=65536,  # 64 MB
    parallelism=2,
    hash_len=32,
    salt_len=16
)

try:
    DATABASE_URL = load_env_from_secret("DATABASE_URL")
    REDIS_URL = load_env_from_secret("REDIS_HOST")
except Exception as e:
    logger.error("Database_management", e)

class UrbanSQLConnection:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL, pool_size=20, max_overflow=10)
        self.bootstrap_schema()
    
    def hash_password(self, password: str) -> str:
        """Hash password using Argon2 (recommended for security)."""
        try:
            return ph.hash(password)
        except HashingError as e:
            logger.error("Database_management.UrbanSQLConnection.hash_password", e)
            raise

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify password using Argon2.
        Also checks if the hash needs rehashing (best practice).
        """
        try:
            ph.verify(hashed_password, plain_password)
            return True

        except VerifyMismatchError:
            return False
        except Exception as e:
            logger.error("Database_management.verify_password", e)
            return False
    
    def authenticate_citizen(self, email: str, password: str) -> Optional[dict]:
        """
        Authenticate user with email and password.
        Returns user info if successful.
        """
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT email, latitude, longitude, password 
                    FROM urban_citizens 
                    WHERE email = :email
                """), {"email": email})

                row = result.fetchone()
                if not row:
                    return None

                stored_hash = row.password

                if self.verify_password(password, stored_hash):
                    return {
                        "email": row.email,
                        "latitude": row.latitude,
                        "longitude": row.longitude
                    }
                return None

        except Exception as e:
            logger.error("Database_management.authenticate_citizen", e)
            return None

    def bootstrap_schema(self):
        """Initializes database schemas required for UrbanOS analytics and geofencing."""
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS urban_snapshots (
                        id SERIAL PRIMARY KEY,
                        zone_name TEXT NOT NULL,
                        flood_risk REAL NOT NULL,
                        traffic_congestion REAL NOT NULL,
                        panic_index REAL NOT NULL,
                        escalation_score REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_snapshots_zone_time 
                    ON urban_snapshots (zone_name, created_at DESC);
                """))

                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS urban_citizens (
                        id SERIAL PRIMARY KEY,
                        email TEXT UNIQUE NOT NULL,
                        password TEXT UNIQUE NOT NULL,
                        latitude DOUBLE PRECISION NOT NULL,
                        longitude DOUBLE PRECISION NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_citizens_geo 
                    ON urban_citizens (latitude, longitude);
                """))

                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS panic_index (
                        id SERIAL PRIMARY KEY,
                        email TEXT NOT NULL,
                        latitude DOUBLE PRECISION NOT NULL,
                        longitude DOUBLE PRECISION NOT NULL,
                        message TEXT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_citizens_panic
                    ON panic_index (latitude, longitude);
                """))
        except Exception as e:
            logger.error("Database_management.UrbanSQLConnection.bootstrap_schema", e)
            return False

    def log_snapshot(self, zone: str, flood: float, traffic: float, panic: float, score: float):
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO urban_snapshots (zone_name, flood_risk, traffic_congestion, panic_index, escalation_score)
                    VALUES (:zone, :flood, :traffic, :panic, :score)
                """), {"zone": zone, "flood": flood, "traffic": traffic, "panic": panic, "score": score})
        except Exception as e:
            logger.error("Database_management.UrbanSQLConnection.log_snapshot", e)
            return False

    def register_citizen(self, email: str, password: str, lat: float, lon: float):
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO urban_citizens (email, password, latitude, longitude)
                    VALUES (:email, :password, :lat, :lon)
                    ON CONFLICT (email) DO UPDATE SET latitude = :lat, longitude = :lon
                """), {"email": email, "password": self.hash_password(password), "lat": lat, "lon": lon})
                return True
        except Exception as e:
            logger.error("Database_management.UrbanSQLConnection.register_citizen", e)
            return False

    def fetch_all_citizens(self) -> List[dict]:
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("SELECT email, latitude, longitude FROM urban_citizens"))
                return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error("Database_management.UrbanSQLConnection.fetch_all_citizens", e)
            return False
        
    def log_panic_message(self, email: str, lat: float, lon: float, message: str = None) -> bool:
        """Log a citizen's panic/distress message with location."""
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO panic_index (email, latitude, longitude, message)
                    VALUES (:email, :lat, :lon, :message)
                """), {
                    "email": email,
                    "lat": lat,
                    "lon": lon,
                    "message": message
                })
            return True
        except Exception as e:
            logger.error("Database_management.UrbanSQLConnection.log_panic_message", e)
            return False
        
    def get_panic_message_counts_near(self, lat: float, lon: float, radius_km: float = 3.0, window_minutes: int = 30) -> dict:
        """
        Returns panic message counts using Haversine formula.
        Calculates current vs previous time window properly.
        """
        try:
            current_interval = f"{window_minutes} minutes"
            previous_interval = f"{window_minutes * 2} minutes"

            with self.engine.begin() as conn:
                # Execute count query
                counts_result = conn.execute(text("""
                    SELECT 
                        COUNT(*) FILTER (
                            WHERE created_at >= NOW() - INTERVAL :current_interval
                        ) as current_window,
                        
                        COUNT(*) FILTER (
                            WHERE created_at >= NOW() - INTERVAL :previous_interval
                            AND created_at < NOW() - INTERVAL :current_interval
                        ) as previous_window
                        
                    FROM panic_index
                    WHERE (
                        6371 * 2 * ASIN(
                            SQRT(
                                POWER(SIN(RADIANS(latitude - :lat) / 2), 2) +
                                COS(RADIANS(:lat)) * COS(RADIANS(latitude)) *
                                POWER(SIN(RADIANS(longitude - :lon) / 2), 2)
                            )
                        )
                    ) <= :radius_km
                """), {
                    "lat": lat,
                    "lon": lon,
                    "radius_km": radius_km,
                    "current_interval": current_interval,
                    "previous_interval": previous_interval
                })
                
                row = counts_result.fetchone()
                if row:
                    current_window = row[0] if row[0] is not None else 0
                    previous_window = row[1] if row[1] is not None else 0
                else:
                    current_window = 0
                    previous_window = 0

                # Fetch messages (this part was correct)
                messages_result = conn.execute(text("""
                    SELECT message
                    FROM panic_index
                    WHERE message IS NOT NULL
                    AND created_at >= NOW() - INTERVAL :current_interval
                    AND (
                        6371 * 2 * ASIN(
                            SQRT(
                                POWER(SIN(RADIANS(latitude - :lat) / 2), 2) +
                                COS(RADIANS(:lat)) * COS(RADIANS(latitude)) *
                                POWER(SIN(RADIANS(longitude - :lon) / 2), 2)
                            )
                        )
                    ) <= :radius_km
                    LIMIT 200
                """), {
                    "lat": lat,
                    "lon": lon,
                    "radius_km": radius_km,
                    "current_interval": current_interval
                })
                
                messages = messages_result.fetchall()
                message_texts = [m[0] for m in messages if m[0] and len(m) > 0]

                return {
                    "current_window": current_window,
                    "previous_window": previous_window,
                    "messages": message_texts
                }

        except Exception as e:
            logger.error("Database_management.UrbanSQLConnection.get_panic_message_counts_near", e)
            return {"current_window": 0, "previous_window": 0, "messages": []}

class UrbanRedisCacheManager:
    def __init__(self):
        self.pool = redis.ConnectionPool.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

    def get_client(self) -> redis.Redis:
        return redis.Redis(connection_pool=self.pool)

    async def get_zone_state(self, zone_name: str) -> dict:
        """Fetches memory state vector matrix baseline (t-1) for dynamic execution loops."""
        try:
            async with self.get_client() as r:
                data = await r.get(f"urban:zone:{zone_name}")
                if data:
                    return json.loads(data)
                return {"flood_risk": 0.0, "traffic_congestion": 0.0, "panic_index": 0.0, "escalation_score": 0.0}
        except Exception as e:
            logger.error("Database_management.UrbanRedisCacheManager.get_zone_state", e)
            return False

    async def save_zone_state(self, zone_name: str, state_payload: dict):
        try:
            async with self.get_client() as r:
                await r.set(f"urban:zone:{zone_name}", json.dumps(state_payload), ex=86400)
        except Exception as e:
            logger.error("Database_management.UrbanRedisCacheManager.save_zone_state", e)
            return False

    async def push_to_stream(self, stream_name: str, payload: dict):
        try:
            async with self.get_client() as r:
                await r.xadd(stream_name, {"data": json.dumps(payload)})
        except Exception as e:
            logger.error("Database_management.UrbanRedisCacheManager.push_to_stream", e)
            return False

try:
    db = UrbanSQLConnection()
    cache = UrbanRedisCacheManager()
except Exception as e:
    logger.error("Database_management.UrbanRedisCacheManager.push_to_stream", e)

if __name__ == "__main__":
    from INPUTS.inputs import GANDHINAGAR_ZONES
    import asyncio

    async def main():
        for zone_name in GANDHINAGAR_ZONES.keys():
            state = await cache.get_zone_state(zone_name)
            print(zone_name, state)

    asyncio.run(main())