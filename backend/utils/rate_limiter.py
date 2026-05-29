import redis
import os
from fastapi import HTTPException

redis_client = redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True
)

def check_otp_rate_limit(phone: str) -> None:
    """
    Rate limit OTP requests:
    - Max 3 OTP requests per phone per hour
    - Max 5 OTP requests per phone per day
    - Blocks for 1 hour after 3 attempts
    """
    
    hour_key = f"otp_hour:{phone}"
    day_key = f"otp_day:{phone}"
    block_key = f"otp_blocked:{phone}"
    
    # Check if phone is blocked
    if redis_client.exists(block_key):
        ttl = redis_client.ttl(block_key)
        raise HTTPException(
            status_code=429,
            detail=f"Too many OTP requests. Try again in {ttl // 60} minutes."
        )
    
    # Check hourly limit
    hour_count = redis_client.get(hour_key)
    if hour_count and int(hour_count) >= 3:
        # Block this phone for 1 hour
        redis_client.setex(block_key, 3600, "blocked")
        raise HTTPException(
            status_code=429,
            detail="Too many OTP requests. Phone blocked for 1 hour."
        )
    
    # Check daily limit
    day_count = redis_client.get(day_key)
    if day_count and int(day_count) >= 5:
        raise HTTPException(
            status_code=429,
            detail="Daily OTP limit reached. Try again tomorrow."
        )
    
    # Increment counters
    pipe = redis_client.pipeline()
    pipe.incr(hour_key)
    pipe.expire(hour_key, 3600)   # 1 hour expiry
    pipe.incr(day_key)
    pipe.expire(day_key, 86400)   # 24 hour expiry
    pipe.execute()
    
def check_login_rate_limit(identifier: str) -> None:
    """
    Rate limit login attempts:
    - Max 5 failed attempts per identifier per 15 minutes
    """
    key = f"login_attempts:{identifier}"
    block_key = f"login_blocked:{identifier}"
    
    if redis_client.exists(block_key):
        ttl = redis_client.ttl(block_key)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {ttl // 60} minutes."
        )
    
    count = redis_client.get(key)
    if count and int(count) >= 5:
        redis_client.setex(block_key, 900, "blocked")  # 15 min block
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Blocked for 15 minutes."
        )

def record_failed_login(identifier: str) -> None:
    """Call this when login fails"""
    key = f"login_attempts:{identifier}"
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, 900)  # 15 minutes
    pipe.execute()

def clear_login_attempts(identifier: str) -> None:
    """Call this when login succeeds"""
    redis_client.delete(f"login_attempts:{identifier}")
    redis_client.delete(f"login_blocked:{identifier}")
