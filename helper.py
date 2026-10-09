import os, requests, json
from dotenv import load_dotenv

# Get the Supabase URL and API key from environment variables
load_dotenv()
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Set the URL for the Database table and the headers for the request
TABLE_URL = f"{SUPABASE_URL}/rest/v1/configs"
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
           "Content-Type": "application/json", "Prefer": "return=representation"}

# Function to insert a new configuration into the Database table
def insert_config(key, value1, value2, value3):
    data = {"key": key, "value1": value1, "value2": value2, "value3": value3}
    response = requests.post(TABLE_URL, headers=HEADERS, json=data, timeout=30)
    if response.status_code == 201: return response.json()
    if response.status_code == 409: raise ValueError("Same key + value1 + value2 + value3 configuration already exists!")
    raise Exception(f"Insert failed: {response.status_code} and {response.text}!")

# Function to delete a row from the Database table based on key and all values
def delete_config(key, value1, value2, value3):
    response = requests.delete(TABLE_URL, headers=HEADERS, params={"key": f"eq.{key}", "value1": f"eq.{value1}",
                                                                   "value2": f"eq.{value2}", "value3": f"eq.{value3}"}, timeout=30)
    # Check if the response status code is 200 "OK-with-response" or 204 "Ok-without-response" and return True
    if response.status_code in (200, 204): return True
    raise Exception(f"Delete failed: {response.status_code} and {response.text}!")

# Function to get some rows from the Database table based on key
def get_by_key(key):
    response = requests.get(TABLE_URL, headers=HEADERS,
                            params={"key": f"eq.{key}", "select": "key, value1, value2, value3"}, timeout=30)
    if response.status_code == 200: return response.json()
    raise Exception(f"Search failed: {response.status_code} and {response.text}!")

# Function to get all rows from the Database table
def get_all_configs():
    response = requests.get(TABLE_URL, headers=HEADERS, params={"select": "key, value1, value2, value3"}, timeout=30)
    if response.status_code == 200: return response.json()
    raise Exception(f"Fetch all failed: {response.status_code} and {response.text}!")

# Function will get all the available GPUs in the Market
def get_gpu_description():
    GPU_URL = "https://raw.githubusercontent.com/rajat709/params/main/notifier_gpus.txt"
    response = requests.get(GPU_URL, timeout=10)
    response.raise_for_status()
    return [gpu.strip() for gpu in response.text.splitlines() if gpu.strip()]

# This Function Will Fetch and Store all GPU Series Offers Available
def fetch_and_display_offers(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}" # Set the endpoint
    try: # Try to call the provider API
        HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        response = requests.get(url, headers=HEADERS, params=params)
        # Check if request was successful
        if response.status_code == 200:
            data = response.json()
            offers = data.get("offers", [])
            return json.dumps(offers, indent=2)
    # Handle the Exception
    except requests.exceptions.RequestException as e:
        print(f"API request failed for - {e}!")
        return json.dumps({"error": "Failed to fetch offers"})
    # Handle the Value Error Exception
    except ValueError as e:
        print(f"Invalid JSON response for - {e}!")
        return json.dumps({"error": "Invalid API response"})

# Function clean strings for perfect matching
def clean_string(s):
    return str(s).upper().replace("_", "").replace("-", "").replace(" ", "")

# Function to parse JSON strings safely
def safe_load(json_str):
    try: # Try to Load the Json String
        data = json.loads(json_str)
        return data if isinstance(data, list) else []
    except: return []
