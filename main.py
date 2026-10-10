import re, os, requests
from pathlib import Path
from threading import Lock
from time import monotonic
from dotenv import load_dotenv
from pydantic import BaseModel
from fastapi.responses import FileResponse
from collections import defaultdict, deque
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Header
from helper import safe_load, clean_string, get_all_configs, fetch_and_display_offers
from helper import insert_config, delete_config, get_by_key, get_gpu_description, delete_older_configs

# Load the Env Secrets
load_dotenv()
ADMIN_BEARER_TOKEN = os.getenv("API_KEY", "")
CRON_SECRET_KEY = os.getenv("CRON_SECRET_KEY", "")
NOTIFIER_API_URL = os.getenv("NOTIFIER_API_URL", "")

# FastAPI Application and Jinja2 templates
BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
templates = Jinja2Templates(directory="templates")

# Rate limiter - 20 requests per 60 seconds - per IP + email
RATE_LIMIT = 20
RATE_WINDOW = 60
rate_lock = Lock()
rate_store = defaultdict(deque)

# Check if the request is within the rate limit for the given email and IP address
def check_rate_limit(request: Request, email: str):
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{email.lower()}"
    now = monotonic()
    with rate_lock:
        requests = rate_store[key]
        # Remove old requests
        while requests and now - requests[0] > RATE_WINDOW: requests.popleft()
        if len(requests) >= RATE_LIMIT:
            retry_after = int(RATE_WINDOW - (now - requests[0])) + 1
            raise HTTPException(status_code=429,
                                detail=f"Too many requests, Try again in {retry_after} seconds.",
                                headers={"Retry-After": str(retry_after)})
        # Add the current timestamp to the request history
        requests.append(now)

# Email validation before inserting the Database Table
def validate_email(email: str) -> str:
    email = email.strip().lower()
    EMAIL_REGEX = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
    if not EMAIL_REGEX.fullmatch(email): raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(email) > 254: raise HTTPException(status_code=400, detail="Email address is too long.")
    return email

# Payload model for configuration data
class ConfigPayload(BaseModel): email: str; value1: str; value2: str; value3: str

# Setup the home route and render main html page
@app.get("/")
def home(request: Request): return templates.TemplateResponse(request=request, name="index.html", context={})

# Function to set the Fav Icon
@app.get("/dataoorts.png", include_in_schema=False)
async def dataoorts_png(): return FileResponse(BASE_DIR / "dataoorts.png", media_type="image/png")
@app.get("/favicon.ico", include_in_schema=False)
async def favicon(): return FileResponse(BASE_DIR / "dataoorts.png", media_type="image/png")

# This route will add new row in the database
@app.post("/api/config")
def add_config(payload: ConfigPayload, request: Request):
    email = validate_email(payload.email)
    check_rate_limit(request, email)
    existing_configs = get_by_key(email)
    if len(existing_configs) >= 10: raise HTTPException(status_code=409, detail="Maximum 10 Configurations Allowed Per User.")
    try: # Try to add the row in Database
        result = insert_config(email, payload.value1.strip(), payload.value2.strip(), payload.value3.strip())
        return {"success": True, "message": "Configuration added successfully.", "data": result}
    # Handle the Value Exception
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

# Function to provide data to the frontend
@app.get("/api/options")
def get_options():
    try: # Try to provide all data
        value1 = get_gpu_description()
        value2 = [1, 2, 4, 6, 8]
        value3 = ['Both', 'SXM', 'PCIe']
        return {"success": True, "value1": value1, "value2": value2, "value3": value3}
    # Handle the Value Exception
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

# This route will delete the a row in the database
@app.delete("/api/config")
def remove_config(payload: ConfigPayload, request: Request):
    email = validate_email(payload.email)
    check_rate_limit(request, email)
    try: # Try to delete the row
        delete_config(email, payload.value1.strip(), payload.value2.strip(), payload.value3.strip())
        return {"success": True, "message": "Configuration deleted successfully."}
    # Handle the Value Exception
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

# This route will get all key matching rows from table
@app.get("/api/config")
def view_configs(email: str, request: Request):
    email = validate_email(email)
    check_rate_limit(request, email)
    try: # Try to get key matching rows from table
        result = get_by_key(email)
        return {"success": True, "data": result}
    # Handle the Value Exception
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

# Main Background Task - Fetches Available GPUs Data, Matches and Sends Email
def process_gpu_cron():
    print("Starting GPU Notifier Cron Job...")
    try: # 1. Try to Fetch All User Configurations from Database
        user_configs = get_all_configs()
    # Handle the Cron Exception
    except Exception as e: print(f"Cron Error - Failed to Fetch DB Configs - {e}."); return # Exit Function Here
    if not user_configs: print("No active configurations found - Skipping cron cycle."); return # Exit Function Here
    # 2. Fetch Live Inventory from all 6 Endpoints
    inventory = [] # Start with empty append later
    # 1. X-Series Available GPU Offers
    for item in safe_load(fetch_and_display_offers("/api/v1/xseries/offers")):
        if isinstance(item, str):
            count_match = re.search(r'x(\d+)(?:-spot)?_', item)
            count = int(count_match.group(1)) if count_match else 1
            inventory.append({"raw": item, "count": count, "series": "X-Series", "url": "https://cloud.dataoorts.com/xseries"})
    # 2. Nova Series Available GPU Offers Both On-Demand and Spot
    nova_data = safe_load(fetch_and_display_offers("/api/v1/nova/offers", params={"type": "on-demand"})) + \
                safe_load(fetch_and_display_offers("/api/v1/nova/offers", params={"type": "spot"}))
    for item in nova_data:
        inventory.append({"raw": str(item.get('gpu_model', '')), "count": int(item.get('gpu_count', 1)),
                          "series": "Nova Series", "url": "https://cloud.dataoorts.com/nova"})
    # 3. Orion Series Available GPU Offers
    for item in safe_load(fetch_and_display_offers("/api/v1/orion/offers")):
        inventory.append({"raw": str(item.get('gpu_name', '')), "count": int(item.get('gpu_count', 1)),
                          "series": "Orion Series", "url": "https://cloud.dataoorts.com/orion"})
    # 4. Orix Series Available GPU Offers
    for item in safe_load(fetch_and_display_offers("/api/v1/orix/offers")):
        raw_str = f"{item.get('gpu_type', '')} {item.get('gpu_form_factor', '')}"
        inventory.append({"raw": raw_str, "count": int(item.get('gpu_count', 1)),
                          "series": "Orix Series", "url": "https://cloud.dataoorts.com/orix"})
    # 5. K-Series Available GPU Offers
    for item in safe_load(fetch_and_display_offers("/api/v1/kseries/offers")):
        inventory.append({"raw": str(item.get('gpu', '')), "count": int(item.get('gpus', 1)),
                          "series": "K-Series", "url": "https://cloud.dataoorts.com/kseries"})
    # 6. Z-Series Available GPU Offers "Special Logic Here - User can choose up to available_nodes"
    for item in safe_load(fetch_and_display_offers("/api/v1/zseries/offers")):
        inventory.append({"raw": str(item.get('gpu_type', '')), "max_count": int(item.get('available_nodes', 1)),
                          "series": "Z-Series", "url": "https://cloud.dataoorts.com/zseries"})
    # 3. Matching Logic "Notification to Send to the User"
    notifications_to_send = [] # Start with empty append later
    # configs_to_delete = [] # Do Not Delete
    for config in user_configs:
        email = config.get('key')
        req_gpu = config.get('value1', 'H100')
        req_count = int(config.get('value2', 1))
        req_form = config.get('value3', 'Both').upper()
        clean_req_gpu = clean_string(req_gpu)
        match_found = False
        for inv in inventory:
            inv_raw = inv['raw'].upper()
            clean_inv_raw = clean_string(inv_raw)
            # Match 1: The GPU Model Check
            if clean_req_gpu in clean_inv_raw:
                # Match 2: GPU Count Check
                count_match = False
                if "max_count" in inv: # Special Z-Series Logic
                    if req_count <= inv["max_count"] and req_count in [1, 2, 4, 8]: count_match = True
                else: # Standard Logic for all other GPU Series
                    if req_count == inv["count"]: count_match = True
                # Match 3: GPU Instance Form Factor Check
                if count_match:
                    form_match = False
                    if req_form == "BOTH": form_match = True
                    elif req_form == "SXM" and "SXM" in inv_raw: form_match = True
                    elif req_form == "PCIE" and "SXM" not in inv_raw: form_match = True
                    # If all three conditions matched - Send email notification
                    if form_match:
                        match_found = True
                        notifications_to_send.append({"email": email, "gpu_type": req_gpu, "gpu_count": req_count,
                                                      "form_factor": req_form, "series_name": inv['series'], "series_url": inv['url']})
                        # Stop checking other inventory items for this config
                        # configs_to_delete.append(config) # Do Not Delete
                        break
    # 4. Push Emails via Main Application API
    if notifications_to_send:
        print(f"Found {len(notifications_to_send)} Matches - Sending to Email API...")
        try: # Try to send email notification to the users
            headers = {"Authorization": f"Bearer {ADMIN_BEARER_TOKEN}", "Content-Type": "application/json"}
            payload = {"notifications": notifications_to_send}
            # Calling the Notifier API
            resp = requests.post(NOTIFIER_API_URL, json=payload, headers=headers, timeout=15)
            # 5. If Email API Says Success
            if resp.status_code == 200: print("Emails sent to users successfully.")
            else: print(f"Email API failed With Status {resp.status_code} - {resp.text}.")
        # Handle the Exception
        except Exception as e: print(f"Failed to push notifications to main API: {e}.")
    else: print("No matching GPUs found in this cycle.")

# CRON Process - Call this endpoint every 15 minutes
@app.post("/api/cron/trigger_matcher")
def trigger_cron_matcher(background_tasks: BackgroundTasks, x_cron_secret: str = Header(None)):
    if x_cron_secret != CRON_SECRET_KEY: raise HTTPException(status_code=401, detail="Unauthorized Cron Access!")
    background_tasks.add_task(process_gpu_cron)
    try: deleted_count = delete_older_configs(); print(f"Older Configs Deleted: {deleted_count}.")
    except Exception as e: print(f"Error to Delete Older Configs: {e}.")
    return {"status": "success", "message": "Cron Started GPU Notifier Worker in Background."}
