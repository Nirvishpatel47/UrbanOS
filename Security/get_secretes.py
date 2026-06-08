import json
import os
import logging
import requests
from functools import lru_cache
from dotenv import load_dotenv

# -----------------------------
# Load local env (ONLY for DOPPLER_TOKEN fallback)
# -----------------------------
load_dotenv()

DOPPLER_TOKEN = os.getenv("DOPPLER_TOKEN")
project = os.getenv("DOPPLER_PROJECT")
config = os.getenv("DOPPLER_CONFIG")

# -----------------------------
# Core: unwrap utility (kept from your design)
# -----------------------------
def unwrap_secret(value):
    """
    Ensures final output is always plain string
    """
    try:
        if value is None:
            return None

        if isinstance(value, str):
            return value

        if hasattr(value, "get_secret_value"):
            return str(unwrap_secret(value.get_secret_value()))

        if hasattr(value, "_secret_value"):
            return str(value._secret_value)

        return str(value)

    except Exception as e:
        logging.error(f"unwrap_secret error: {e}")
        return str(value)


# -----------------------------
# Doppler API fetcher
# -----------------------------
def fetch_from_doppler():
    """
    Fetch ALL secrets from Doppler project config
    """
    try:
        if not DOPPLER_TOKEN:
            raise ValueError("DOPPLER_TOKEN not set in environment")

        url = "https://api.doppler.com/v3/configs/config/secrets"

        headers = {
            "Authorization": f"Bearer {DOPPLER_TOKEN}"
        }

        params = {
            "project": project,
            "config": config
        }

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        data = response.json()

        secrets = {}
        for key, value in data.get("secrets", {}).items():
            secrets[key] = value.get("computed")

        return secrets

    except Exception as e:
        #logging.error(f"Doppler fetch error: {e}")
        return {}


# -----------------------------
# Main loader (replacement for GCP + dotenv logic)
# -----------------------------
@lru_cache(maxsize=64)
def load_env_from_secret(key: str):
    """
    Priority:
    1. Doppler
    2. OS env fallback
    """

    try:
        # 1. Fetch from Doppler
        secrets = fetch_from_doppler()

        if key in secrets:
            value = unwrap_secret(secrets[key])
            return str(value)

        # 2. fallback to OS env
        env_value = os.getenv(key)
        if env_value is not None:
            return str(unwrap_secret(env_value))

        raise ValueError(f"Secret '{key}' not found in Doppler or env")

    except Exception as e:
        logging.error(f"load_env_from_secret error: {e}")
        raise


# -----------------------------
# JSON secret loader
# -----------------------------
def get_secret_json(key: str) -> dict:
    """
    Parse JSON stored in Doppler secret
    """
    try:
        value_str = load_env_from_secret(key)
        return json.loads(value_str)

    except Exception as e:
        logging.error(f"get_secret_json error: {e}")
        return None