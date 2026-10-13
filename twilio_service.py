import os
import json
import uuid
import datetime
from typing import Dict, List, Optional
from encryption import decrypt_text, mask_phone

CALL_LOGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "twilio_call_logs.json")

def _load_call_logs() -> List[dict]:
    if not os.path.exists(CALL_LOGS_FILE):
        return []
    try:
        with open(CALL_LOGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_call_logs(logs: List[dict]):
    os.makedirs(os.path.dirname(CALL_LOGS_FILE), exist_ok=True)
    with open(CALL_LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)

def generate_emergency_twiml(hospital_name: str, blood_group: str, units: int, request_id: str, donor_id: str, base_url: str = "") -> str:
    """Generates simulated voice XML response for emergency calls."""
    announcement = (
        f"Hello. This is an emergency blood donation alert from Heal Hub. "
        f"Hospital {hospital_name} has an urgent need for {units} units of {blood_group} blood. "
        f"An emergency confirmation link has been sent to your registered email address. "
        f"Press 1 to confirm you are available to donate, or press 2 if you are not available."
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">{announcement}</Say>
</Response>"""

def trigger_automated_call(
    donor: dict,
    hospital_name: str,
    blood_group: str,
    units: int,
    request_id: str,
    base_url: str = "http://127.0.0.1:5000"
) -> dict:
    """
    Simulates an automated phone call to the donor without requiring external Twilio credentials.
    Marks status as 'Phone call going (Simulated)'.
    """
    donor_id = donor.get("donor_id", "UNKNOWN")
    raw_phone = decrypt_text(donor.get("phone_encrypted", donor.get("phone", "")))
    clean_phone = raw_phone.strip()

    script_text = (
        f"Emergency Alert from Heal Hub: Hospital '{hospital_name}' urgently needs {units} units of {blood_group} blood. "
        f"An automated emergency message has been dispatched to your email. "
        f"Please check your email to respond, or press 1 for Available, 2 for Not Available."
    )

    call_id = f"SIM-CALL-{uuid.uuid4().hex[:12].upper()}"
    timestamp = datetime.datetime.now().isoformat()
    call_status = "Phone call going (Simulated)"

    log_entry = {
        "call_id": call_id,
        "mode": "SIMULATED_PHONE_CALL",
        "donor_id": donor_id,
        "phone_masked": mask_phone(clean_phone),
        "phone_raw": clean_phone,
        "hospital_name": hospital_name,
        "blood_group": blood_group,
        "units": units,
        "request_id": request_id,
        "script": script_text,
        "status": call_status,
        "timestamp": timestamp,
        "error": None
    }

    logs = _load_call_logs()
    logs.insert(0, log_entry)
    _save_call_logs(logs)

    return log_entry

def get_call_logs(limit: int = 50) -> List[dict]:
    logs = _load_call_logs()
    return logs[:limit]
