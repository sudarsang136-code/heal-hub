import os
import json
import uuid
import datetime
from typing import Dict, List, Optional, Tuple
from encryption import encrypt_text, decrypt_text, mask_phone, mask_email

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REQUESTS_FILE = os.path.join(DATA_DIR, "emergency_requests.json")
DONATIONS_FILE = os.path.join(DATA_DIR, "donation_records.json")

VALID_BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

def blood_group_to_filename(group: str) -> str:
    """Normalizes blood group string to a safe file suffix, e.g. A+ -> A_POS."""
    clean = group.strip().upper().replace("+", "_POS").replace("-", "_NEG")
    return f"donors_{clean}.json"

def get_blood_group_path(group: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, blood_group_to_filename(group))

def _load_json_file(filepath: str, default):
    if not os.path.exists(filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return default

def _save_json_file(filepath: str, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    temp_file = filepath + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, filepath)

def compute_donor_eligibility(gender: str, recent_donation_date_str: Optional[str]) -> Tuple[bool, int, str]:
    """
    Evaluates cooldown eligibility based on gender:
    - Male: minimum 90 days after previous donation
    - Female: minimum 120 days after previous donation
    - Other/Unspecified: minimum 90 days
    Returns: (is_eligible: bool, days_remaining: int, status_message: str)
    """
    if not recent_donation_date_str:
        return True, 0, "Eligible to donate (No recent donation recorded)"

    try:
        recent_date = datetime.datetime.strptime(recent_donation_date_str, "%Y-%m-%d").date()
    except Exception:
        return True, 0, "Eligible to donate"

    today = datetime.date.today()
    days_passed = (today - recent_date).days

    required_cooldown = 120 if (gender and gender.lower() == "female") else 90

    if days_passed >= required_cooldown:
        return True, 0, f"Eligible to donate ({days_passed} days since last donation; cooldown was {required_cooldown} days)"
    else:
        days_remaining = required_cooldown - days_passed
        return False, days_remaining, f"Cooldown in progress: {days_remaining} days remaining (Minimum {required_cooldown} days required for {gender})"

def generate_donor_id(blood_group: str) -> str:
    """Generates unique donor ID, e.g. DONOR-BPOS-4891."""
    tag = blood_group.strip().upper().replace("+", "POS").replace("-", "NEG")
    short_uuid = str(uuid.uuid4().hex[:4]).upper()
    return f"DONOR-{tag}-{short_uuid}"

def save_donor(donor_data: dict) -> dict:
    """Saves or updates a donor in their dedicated blood group database file."""
    blood_group = donor_data.get("blood_group", "").strip().upper()
    if blood_group not in VALID_BLOOD_GROUPS:
        raise ValueError(f"Invalid blood group: {blood_group}")

    filepath = get_blood_group_path(blood_group)
    donors = _load_json_file(filepath, [])

    donor_id = donor_data.get("donor_id") or generate_donor_id(blood_group)
    donor_data["donor_id"] = donor_id

    # If updating an existing donor whose blood group was changed, remove from other blood group files
    for bg in VALID_BLOOD_GROUPS:
        if bg != blood_group:
            bg_path = get_blood_group_path(bg)
            bg_donors = _load_json_file(bg_path, [])
            filtered = [d for d in bg_donors if d.get("donor_id") != donor_id]
            if len(filtered) < len(bg_donors):
                _save_json_file(bg_path, filtered)

    # Encrypt PII if not already encrypted
    if "phone" in donor_data and donor_data["phone"]:
        donor_data["phone_encrypted"] = encrypt_text(donor_data.pop("phone"))
    if "email" in donor_data and donor_data["email"]:
        donor_data["email_encrypted"] = encrypt_text(donor_data.pop("email"))

    # Compute availability
    is_eligible, days_remaining, status_msg = compute_donor_eligibility(
        donor_data.get("gender", "male"),
        donor_data.get("recent_donation_date")
    )
    donor_data["computed_availability"] = is_eligible and donor_data.get("manual_availability", True)
    donor_data["cooldown_days_remaining"] = days_remaining
    donor_data["eligibility_reason"] = status_msg
    # Column named 'availability' as specified in prompt
    donor_data["availability"] = "Available" if donor_data["computed_availability"] else "Unavailable"
    donor_data["updated_at"] = datetime.datetime.now().isoformat()
    if "registered_at" not in donor_data:
        donor_data["registered_at"] = donor_data["updated_at"]

    # Upsert in the list
    updated = False
    for i, d in enumerate(donors):
        if d.get("donor_id") == donor_id:
            donors[i] = donor_data
            updated = True
            break
    if not updated:
        donors.append(donor_data)

    _save_json_file(filepath, donors)
    return donor_data

def get_donor_by_id(donor_id: str) -> Optional[dict]:
    """Finds a donor across all blood group databases."""
    for bg in VALID_BLOOD_GROUPS:
        filepath = get_blood_group_path(bg)
        donors = _load_json_file(filepath, [])
        for d in donors:
            if d.get("donor_id") == donor_id:
                # Recalculate dynamic eligibility based on today's date
                is_eligible, days_remaining, status_msg = compute_donor_eligibility(
                    d.get("gender", "male"),
                    d.get("recent_donation_date")
                )
                d["computed_availability"] = is_eligible and d.get("manual_availability", True)
                d["cooldown_days_remaining"] = days_remaining
                d["eligibility_reason"] = status_msg
                d["availability"] = "Available" if d["computed_availability"] else "Unavailable"
                return d
    return None

def authenticate_donor(donor_id: str, dob: str) -> Optional[dict]:
    """Authenticates donor using Donor ID and Date of Birth (as password)."""
    donor = get_donor_by_id(donor_id)
    if not donor:
        return None
    donor_dob = donor.get("dob", "").strip()
    # Normalize comparison YYYY-MM-DD
    if donor_dob == dob.strip():
        # Decrypt PII for authenticated donor's own view
        safe_copy = dict(donor)
        safe_copy["phone"] = decrypt_text(donor.get("phone_encrypted", ""))
        safe_copy["email"] = decrypt_text(donor.get("email_encrypted", ""))
        return safe_copy
    return None

def delete_donor_by_id(donor_id: str) -> bool:
    """Deletes a donor from their respective database file."""
    for bg in VALID_BLOOD_GROUPS:
        filepath = get_blood_group_path(bg)
        donors = _load_json_file(filepath, [])
        new_list = [d for d in donors if d.get("donor_id") != donor_id]
        if len(new_list) < len(donors):
            _save_json_file(filepath, new_list)
            return True
    return False

def get_donors_by_blood_group(blood_group: str, eligible_only: bool = False) -> List[dict]:
    """Retrieves donors from a specific blood group file."""
    bg = blood_group.strip().upper()
    if bg not in VALID_BLOOD_GROUPS:
        return []
    filepath = get_blood_group_path(bg)
    donors = _load_json_file(filepath, [])

    result = []
    for d in donors:
        is_eligible, days_rem, status_msg = compute_donor_eligibility(
            d.get("gender", "male"),
            d.get("recent_donation_date")
        )
        d["computed_availability"] = is_eligible and d.get("manual_availability", True)
        d["cooldown_days_remaining"] = days_rem
        d["eligibility_reason"] = status_msg
        d["availability"] = "Available" if d["computed_availability"] else "Unavailable"

        if eligible_only:
            if d["computed_availability"] and d.get("willing_to_donate", True) and d.get("willing_to_contact", True):
                result.append(d)
        else:
            result.append(d)
    return result

def get_all_donors(mask_pii: bool = True) -> List[dict]:
    """Aggregates all donors across all 8 blood group databases."""
    all_donors = []
    for bg in VALID_BLOOD_GROUPS:
        donors = get_donors_by_blood_group(bg, eligible_only=False)
        for d in donors:
            d_copy = dict(d)
            if mask_pii:
                raw_phone = decrypt_text(d.get("phone_encrypted", ""))
                raw_email = decrypt_text(d.get("email_encrypted", ""))
                d_copy["phone_masked"] = mask_phone(raw_phone)
                d_copy["email_masked"] = mask_email(raw_email)
                d_copy.pop("phone_encrypted", None)
                d_copy.pop("email_encrypted", None)
            all_donors.append(d_copy)
    return all_donors

# ======================= Emergency Requests =======================

def save_emergency_request(req_data: dict) -> dict:
    """Saves or updates an emergency blood request from a hospital."""
    requests = _load_json_file(REQUESTS_FILE, [])
    req_id = req_data.get("request_id")
    if not req_id:
        req_id = f"REQ-{datetime.datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        req_data["request_id"] = req_id
        req_data["created_at"] = datetime.datetime.now().isoformat()
        req_data["status"] = req_data.get("status", "SEARCHING")
        req_data["contacted_donors"] = req_data.get("contacted_donors", [])
        req_data["confirmed_donors"] = req_data.get("confirmed_donors", [])
        req_data["declined_donors"] = req_data.get("declined_donors", [])
        req_data["current_batch"] = req_data.get("current_batch", 0)

    req_data["updated_at"] = datetime.datetime.now().isoformat()

    updated = False
    for i, r in enumerate(requests):
        if r.get("request_id") == req_id:
            requests[i] = req_data
            updated = True
            break
    if not updated:
        requests.insert(0, req_data)

    _save_json_file(REQUESTS_FILE, requests)
    return req_data

def get_emergency_request(req_id: str) -> Optional[dict]:
    requests = _load_json_file(REQUESTS_FILE, [])
    for r in requests:
        if r.get("request_id") == req_id:
            return r
    return None

def get_all_emergency_requests() -> List[dict]:
    return _load_json_file(REQUESTS_FILE, [])

# ======================= Donation Completion Records =======================

def record_donation_completion(hospital_id: str, hospital_name: str, donor_id: str, request_id: str, units: int = 1) -> dict:
    """
    Called when donor reaches the hospital and blood donation is completed.
    1. Updates the donor's previous donation date to TODAY.
    2. Updates donor availability column to Unavailable (cooldown active: 90 days male / 120 days female).
    3. Saves permanent audit record.
    4. Marks emergency request CLOSED if fulfilled.
    """
    donor = get_donor_by_id(donor_id)
    if not donor:
        raise ValueError(f"Donor {donor_id} not found")

    today_str = datetime.date.today().isoformat()

    # Update donor
    donor["recent_donation_date"] = today_str
    donor["donated_before"] = True
    save_donor(donor)

    # Save donation history record
    records = _load_json_file(DONATIONS_FILE, [])
    record = {
        "record_id": f"REC-{uuid.uuid4().hex[:8].upper()}",
        "hospital_id": hospital_id,
        "hospital_name": hospital_name,
        "donor_id": donor_id,
        "blood_group": donor.get("blood_group"),
        "request_id": request_id,
        "units": units,
        "donated_at": datetime.datetime.now().isoformat(),
        "cooldown_applied_days": 120 if donor.get("gender", "").lower() == "female" else 90
    }
    records.insert(0, record)
    _save_json_file(DONATIONS_FILE, records)

    # Update Emergency Request
    if request_id:
        req = get_emergency_request(request_id)
        if req:
            req["status"] = "CLOSED"
            req["closed_at"] = datetime.datetime.now().isoformat()
            req["completed_donor_id"] = donor_id
            save_emergency_request(req)

    return record

def get_donation_records_for_donor(donor_id: str) -> List[dict]:
    records = _load_json_file(DONATIONS_FILE, [])
    return [r for r in records if r.get("donor_id") == donor_id]

# ======================= Seed Data Initialization =======================

def seed_sample_donors_if_empty():
    """Seeds realistic sample donors across all 8 blood groups around central city hospitals."""
    # Check if any data exists
    total_existing = 0
    for bg in VALID_BLOOD_GROUPS:
        filepath = get_blood_group_path(bg)
        donors = _load_json_file(filepath, [])
        total_existing += len(donors)

    if total_existing > 0:
        return  # Already seeded

    print("Seeding sample donors across all 8 blood group databases...")

    # Reference City Center: Latitude 12.9716, Longitude 77.5946 (e.g. Bangalore / Metro Center)
    # Realistic donors with various distances, genders, and cooldown states
    sample_donors = [
        # B+ Donors (Direct target for user prompt's B+ emergency example)
        {
            "name": "Rahul Sharma",
            "dob": "1994-05-14",
            "phone": "+91 98451 12345",
            "email": "rahul.sharma94@example.com",
            "blood_group": "B+",
            "age": 30,
            "gender": "male",
            "weight": 72.5,
            "donated_before": True,
            "recent_donation_date": "2025-11-10",  # > 90 days ago -> ELIGIBLE
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9740,
            "longitude": 77.6010,
            "city": "Indiranagar",
            "manual_availability": True,
            "notes": "Regular blood donor, verified at Red Cross."
        },
        {
            "name": "Pooja Hegde",
            "dob": "1998-08-22",
            "phone": "+91 98860 98765",
            "email": "pooja.hegde@example.com",
            "blood_group": "B+",
            "age": 26,
            "gender": "female",
            "weight": 58.0,
            "donated_before": True,
            "recent_donation_date": "2025-09-15",  # > 120 days ago -> ELIGIBLE
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9810,
            "longitude": 77.5890,
            "city": "Malleshwaram",
            "manual_availability": True,
            "notes": "Verified donor."
        },
        {
            "name": "Karthik Nair",
            "dob": "1991-12-03",
            "phone": "+91 99001 54321",
            "email": "karthik.nair@example.com",
            "blood_group": "B+",
            "age": 32,
            "gender": "male",
            "weight": 76.0,
            "donated_before": True,
            "recent_donation_date": "2026-08-25",  # Under 90 days (Recent donation) -> INELIGIBLE / COOLDOWN
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9350,
            "longitude": 77.6240,
            "city": "Koramangala",
            "manual_availability": True,
            "notes": "Recently donated, in cooldown."
        },
        {
            "name": "Aditya Verma",
            "dob": "1997-03-19",
            "phone": "+91 97400 33221",
            "email": "aditya.verma@example.com",
            "blood_group": "B+",
            "age": 27,
            "gender": "male",
            "weight": 68.0,
            "donated_before": False,
            "recent_donation_date": None,  # First time -> ELIGIBLE
            "hospital_verified": False,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9920,
            "longitude": 77.6600,
            "city": "Whitefield",
            "manual_availability": True,
            "notes": "First time eager donor."
        },
        # O- Donors (Universal Donors - compatible with B+, A+, etc.)
        {
            "name": "Vikram Sen",
            "dob": "1989-10-12",
            "phone": "+91 91234 56789",
            "email": "vikram.sen@example.com",
            "blood_group": "O-",
            "age": 35,
            "gender": "male",
            "weight": 79.0,
            "donated_before": True,
            "recent_donation_date": "2025-10-01",  # > 90 days -> ELIGIBLE
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9650,
            "longitude": 77.5990,
            "city": "Richmond Town",
            "manual_availability": True,
            "notes": "Universal donor O negative."
        },
        {
            "name": "Sneha Patel",
            "dob": "1996-01-30",
            "phone": "+91 98765 43210",
            "email": "sneha.patel@example.com",
            "blood_group": "O-",
            "age": 28,
            "gender": "female",
            "weight": 54.0,
            "donated_before": True,
            "recent_donation_date": "2026-08-10",  # Donated last month -> Under 120 days -> COOLDOWN
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9280,
            "longitude": 77.5830,
            "city": "Jayanagar",
            "manual_availability": True,
            "notes": "O- donor, waiting for cooldown."
        },
        # O+ Donors (Compatible with B+, A+, AB+, O+)
        {
            "name": "Arjun Das",
            "dob": "1995-07-07",
            "phone": "+91 98111 22334",
            "email": "arjun.das@example.com",
            "blood_group": "O+",
            "age": 29,
            "gender": "male",
            "weight": 70.0,
            "donated_before": True,
            "recent_donation_date": "2025-12-05",  # > 90 days -> ELIGIBLE
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9560,
            "longitude": 77.5710,
            "city": "Basavanagudi",
            "manual_availability": True,
            "notes": "O+ donor."
        },
        # B- Donors (Compatible with B+, B-)
        {
            "name": "Ananya Roy",
            "dob": "1999-04-18",
            "phone": "+91 97333 44556",
            "email": "ananya.roy@example.com",
            "blood_group": "B-",
            "age": 25,
            "gender": "female",
            "weight": 52.0,
            "donated_before": False,
            "recent_donation_date": None,
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9880,
            "longitude": 77.5550,
            "city": "Rajajinagar",
            "manual_availability": True,
            "notes": "B- donor."
        },
        # A+ Donors
        {
            "name": "David Fernandes",
            "dob": "1992-06-25",
            "phone": "+91 96555 77889",
            "email": "david.f@example.com",
            "blood_group": "A+",
            "age": 32,
            "gender": "male",
            "weight": 81.0,
            "donated_before": True,
            "recent_donation_date": "2025-08-15",
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9600,
            "longitude": 77.6400,
            "city": "Domlur",
            "manual_availability": True,
            "notes": "A+ donor."
        },
        # A- Donors
        {
            "name": "Meera Krishnan",
            "dob": "1997-11-09",
            "phone": "+91 95444 88990",
            "email": "meera.k@example.com",
            "blood_group": "A-",
            "age": 27,
            "gender": "female",
            "weight": 56.5,
            "donated_before": True,
            "recent_donation_date": "2025-10-20",
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 13.0100,
            "longitude": 77.5650,
            "city": "Yeshwantpur",
            "manual_availability": True,
            "notes": "A- rare donor."
        },
        # AB+ Donors (Universal Recipient)
        {
            "name": "Siddharth Rao",
            "dob": "1993-02-14",
            "phone": "+91 94333 11223",
            "email": "sid.rao@example.com",
            "blood_group": "AB+",
            "age": 31,
            "gender": "male",
            "weight": 74.0,
            "donated_before": True,
            "recent_donation_date": "2025-11-01",
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9100,
            "longitude": 77.6000,
            "city": "BTM Layout",
            "manual_availability": True,
            "notes": "AB+ donor."
        },
        # AB- Donors
        {
            "name": "Tanvi Joshi",
            "dob": "1998-09-03",
            "phone": "+91 93222 66778",
            "email": "tanvi.joshi@example.com",
            "blood_group": "AB-",
            "age": 26,
            "gender": "female",
            "weight": 53.0,
            "donated_before": False,
            "recent_donation_date": None,
            "hospital_verified": True,
            "willing_to_contact": True,
            "willing_to_donate": True,
            "latitude": 12.9400,
            "longitude": 77.5700,
            "city": "Southend",
            "manual_availability": True,
            "notes": "AB- rare donor."
        }
    ]

    for d in sample_donors:
        save_donor(d)

    print(f"Successfully seeded {len(sample_donors)} sample donors across individual blood group databases.")
