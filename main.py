import asyncio
import json
import logging
import os
import random
import string
import sys
import traceback

from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChannelInvalidError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CheckUsernameRequest,
    UpdateUsernameRequest,
)
from telethon.tl.types import InputPeerChannel

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- SAFE CONFIGURATION LOADING ---
api_id_str = os.environ.get("TELEGRAM_API_ID", "").strip()
api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
phone = os.environ.get("TELEGRAM_PHONE", "").strip()
session_string = os.environ.get("TELEGRAM_SESSION", "").strip()
initial_channel = os.environ.get("INITIAL_CHANNEL_USERNAME", "").strip().replace("@", "")

missing_secrets = []
if not api_id_str: missing_secrets.append("TELEGRAM_API_ID")
if not api_hash: missing_secrets.append("TELEGRAM_API_HASH")
if not phone: missing_secrets.append("TELEGRAM_PHONE")
if not session_string: missing_secrets.append("TELEGRAM_SESSION")
if not initial_channel: missing_secrets.append("INITIAL_CHANNEL_USERNAME")

if missing_secrets:
    logger.critical(f"❌ CRITICAL: The following GitHub Secrets are missing or empty: {', '.join(missing_secrets)}")
    logger.critical("Go to Repo -> Settings -> Secrets and variables -> Actions to add them.")
    sys.exit(1)

try:
    API_ID = int(api_id_str)
except ValueError:
    logger.critical(f"❌ CRITICAL: TELEGRAM_API_ID must be a number.")
    sys.exit(1)

API_HASH = api_hash
PHONE = phone
SESSION_STRING = session_string
INITIAL_CHANNEL = initial_channel
MAX_CYCLES = 30
TARGET_URL = "https://flowfame.com/free-telegram-members"

# --- HELPER FUNCTIONS ---
def generate_random_username():
    return "ch_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

def load_state():
    if not os.path.exists("state.json"):
        return {"cycle": 0, "channel_id": None, "access_hash": None, "current_username": None}
    try:
        with open("state.json", "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error("state.json is corrupted! Resetting state.")
        return {"cycle": 0, "channel_id": None, "access_hash": None, "current_username": None}

def save_state(state):
    with open("state.json", "w") as f:
        json.dump(state, f, indent=2)

# --- BROWSER AUTOMATION ---
def process_flowfame_with_sb(link):
    logger.info(f"=== STARTING BROWSER PROCESS FOR: {link} ===")
    
    try:
        with SB(uc=True, headless=True, incognito=True) as sb:
            logger.info("Browser connected via SB Manager.")
            sb.open(TARGET_URL)
            sb.sleep(3)

            # --- SOLVE CLOUDFLARE TURNSTILE ---
            logger.info("Attempting to solve Cloudflare Turnstile...")
            try:
                sb.solve_captcha()
                logger.info("CAPTCHA solving triggered.")
            except Exception as e:
                logger.warning(f"CAPTCHA note: {e}. Proceeding anyway...")

            # --- WAIT FOR PAGE TO BE INTERACTABLE ---
            wait = WebDriverWait(sb.driver, 20)
            link_input = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[placeholder*='t.me']"))
            )
            link_input.clear()
            link_input.send_keys(link)
            logger.info("Link entered.")

            # --- SUBMIT FORM ---
            submit_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
            )
            submit_btn.click()
            logger.info("Form submitted. Waiting for confirmation...")

            # --- WAIT FOR SUCCESS CONFIRMATION ---
            success = False
            for _ in range(24):  # Wait up to 2 minutes
                sb.sleep(5)
                page_text = sb.driver.find_element(By.TAG_NAME, "body").text
                if "on the way" in page_text or "free claims remaining" in page_text:
                    logger.info("🎉 Members claimed successfully!")
                    success = True
                    break
            
            if not success:
                logger.warning("Timeout waiting for confirmation message.")
                sb.save_screenshot("error_timeout.png")
            return success

    except Exception as e:
        logger.critical(f"Browser execution error: {e}")
        logger.critical(traceback.format_exc())
        return False

# --- MAIN EXECUTION ---
async def main():
    logger.info("========== SCRIPT STARTED ==========")
    
    state = load_state()
    current_cycle = state["cycle"]

    if current_cycle >= MAX_CYCLES:
        logger.info(f"🏁 Reached {MAX_CYCLES} cycles. Automation complete. Exiting.")
        sys.exit(0)

    logger.info(f"--- 🔄 Starting Cycle {current_cycle + 1}/{MAX_CYCLES} ---")

    # Initialize Telegram Client
    try:
        session = StringSession(SESSION_STRING)
        client = TelegramClient(session, API_ID, API_HASH)
        await client.start()
        logger.info("Telegram client connected.")
    except Exception as e:
        logger.critical(f"Failed to connect to Telegram: {e}")
        sys.exit(1)

    try:
        # ---------------------------------------------------------
        # FIRST RUN VALIDATION (DRY RUN)
        # ---------------------------------------------------------
        if not state.get("channel_id"):
            logger.info(f"First run: Validating provided channel @{INITIAL_CHANNEL}...")
            try:
                entity = await client.get_entity(INITIAL_CHANNEL)
                state["channel_id"] = entity.id
                state["access_hash"] = entity.access_hash
                state["current_username"] = INITIAL_CHANNEL
                save_state(state)
                logger.info("✅ Channel successfully found and saved to state.")
                logger.info("🏁 Validation mode complete. Exiting now.")
                logger.info("The next scheduled run will start the actual claims.")
                await client.disconnect()
                sys.exit(0)  # <--- EXIT HERE! No browser, no claims.
            except Exception as e:
                logger.critical(f"❌ Failed to resolve @{INITIAL_CHANNEL}. Is the username correct? Error: {e}")
                await client.disconnect()
                sys.exit(1)

        # ---------------------------------------------------------
        # SUBSEQUENT RUNS (LIVE)
        # ---------------------------------------------------------
        else:
            # We already have the channel. Rotate the username.
            logger.info("Existing channel found. Rotating username...")
            peer = InputPeerChannel(state["channel_id"], state["access_hash"])
            
            # Find an available username
            new_username = None
            for attempt in range(5):
                test_username = generate_random_username()
                if await client(CheckUsernameRequest(peer, test_username)):
                    new_username = test_username
                    break
                
            if not new_username:
                logger.error("Failed to find an available username after 5 attempts.")
                sys.exit(1)
                
            try:
                await client(UpdateUsernameRequest(peer, new_username))
                state["current_username"] = new_username
                save_state(state)
                logger.info(f"Username successfully updated: https://t.me/{new_username}")
            except ChannelInvalidError:
                logger.error("❌ Channel is invalid (did you delete it?). Resetting state...")
                state = {"cycle": 0, "channel_id": None, "access_hash": None, "current_username": None}
                save_state(state)
                sys.exit(0)
            except FloodWaitError as e:
                logger.error(f"⚠️ Telegram FloodWait: {e.seconds} seconds.")
                sys.exit(0)
            except Exception as e:
                logger.error(f"Failed to update username: {e}")
                sys.exit(1)
                
    except Exception as e:
        logger.critical(f"Telegram Error: {e}")
        await client.disconnect()
        sys.exit(1)
    finally:
        if client.is_connected():
            await client.disconnect()

    # Claim Members
    link_to_claim = f"https://t.me/{state['current_username']}"
    success = process_flowfame_with_sb(link_to_claim)

    # Save State ONLY if successful
    if success:
        state["cycle"] += 1
        save_state(state)
        logger.info(f"✅ Cycle {current_cycle + 1} complete. State saved.")
    else:
        logger.error("❌ Cycle failed. State NOT updated.")

if __name__ == "__main__":
    asyncio.run(main())
