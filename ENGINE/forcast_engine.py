from copy import deepcopy
import math


class ForecastEngine:

    def __init__(self):
        self.forecast_windows = {
            "t_plus_15m": 15,
            "t_plus_30m": 30,
            "t_plus_60m": 60,
            "t_plus_6h": 360
        }

    async def generate_forecasts(self, zone_packet):
        forecasts = {}
        for label, minutes in (self.forecast_windows.items()):
            forecasts[label] = (
                self.forecast_zone(
                    deepcopy(zone_packet),
                    minutes
                )
            )
        return forecasts
    
    def forecast_zone(self, zone, minutes):
        future_flood = (self.predict_flood(zone, minutes))
        future_traffic = (self.predict_traffic(zone, minutes))
        future_panic = (self.predict_panic(zone, future_flood, future_traffic, minutes))
        escalation = (self.calculate_escalation( future_flood, future_traffic, future_panic))
        return {"forecast_minutes": minutes, "predicted_flood_risk": round(future_flood, 2), "predicted_traffic": round(future_traffic, 2), "predicted_panic": round(future_panic, 2), "predicted_escalation": round(escalation, 2)}

    def predict_flood( self, zone, minutes ):
        rainfall = zone.get("rainfall", 0)
        current_water = zone.get("water_level", 0)
        infra = zone.get("infrastructure_quality", 50)
        drainage_rate = (infra / 100) * 0.7
        terrain_coefficient = 1.15
        rainfall_accumulation = (rainfall * (minutes / 60)) * terrain_coefficient
        flood = (current_water + rainfall_accumulation - (drainage_rate * minutes * 0.4))
        return max( 0.0, min(100.0, flood) )
    
    def predict_traffic(self, zone, minutes):
        current_traffic = zone.get("congestion_level", 0)
        rain = zone.get("rainfall", 0)
        human_density = zone.get("human_activity_density", 0)
        flood = zone.get("water_level", 0)
        rain_factor = (rain * 0.6)
        density_factor = (human_density * 0.18)
        flood_factor = (flood * 0.45)
        time_factor = (math.log1p(minutes))
        traffic = ( current_traffic + rain_factor + density_factor + flood_factor) * time_factor
        return max(0.0, min(100.0, traffic))

    def predict_panic(self, zone, flood, traffic, minutes):
        current_panic = zone.get("panic_index", 0)
        citizen_volume = zone.get("citizen_msg_volume", 0)
        flood_impact = (flood * 0.45)
        traffic_impact = (traffic * 0.20)
        message_impact = (citizen_volume * 0.12)
        time_growth = (math.sqrt(minutes))
        panic = (current_panic + flood_impact + traffic_impact + message_impact ) * (time_growth / 3)
        return max(0.0, min(100.0, panic))

    def calculate_escalation(self, flood, traffic, panic):
        escalation = (flood * 0.45 + traffic * 0.20 + panic * 0.35)
        return max(0.0, min(100.0, escalation))
    
forecast_engine = ForecastEngine()