from jose import jwt
from datetime import datetime, timedelta
from Security.get_secretes import load_env_from_secret

SECRET_KEY = load_env_from_secret("JWT_SECRETE")
ALGORITHM = load_env_from_secret("JWT_ALGORITHM")

def create_token(email: str):
    payload = {
        "email": email,
        "exp": datetime.utcnow() + timedelta(days=30)
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return payload["user_id"]