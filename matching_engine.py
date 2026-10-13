import math
from typing import List, Dict, Tuple, Optional
from database import get_donors_by_blood_group, VALID_BLOOD_GROUPS, compute_donor_eligibility

# Earth's radius in kilometers
EARTH_RADIUS_KM = 6371.0

# Medical Blood Compatibility Matrix: Recipient -> Compatible Donor Blood Groups
COMPATIBILITY_MATRIX = {
    "A+":  ["A+", "A-", "O+", "O-"],
    "A-":  ["A-", "O-"],
    "B+":  ["B+", "B-", "O+", "O-"],
    "B-":  ["B-", "O-"],
    "AB+": ["AB+", "AB-", "A+", "A-", "B+", "B-", "O+", "O-"], # Universal recipient
    "AB-": ["AB-", "A-", "B-", "O-"],
    "O+":  ["O+", "O-"],
    "O-":  ["O-"] # Universal donor
}

def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes the great-circle distance between two points on the Earth's surface
    using the standard Haversine formula.
    Returns distance in kilometers, rounded to 2 decimal places.
    """
    try:
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        delta_phi = math.radians(float(lat2) - float(lat1))
        delta_lambda = math.radians(float(lon2) - float(lon1))

        a = (math.sin(delta_phi / 2.0) ** 2 +
             math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        distance = EARTH_RADIUS_KM * c
        return round(distance, 2)
    except Exception as e:
        print(f"Error calculating Haversine distance: {e}")
        return 9999.0

def find_matching_donors(
    required_blood_group: str,
    hospital_lat: float,
    hospital_lon: float,
    max_radius_km: float = 50.0,
    allow_compatible_groups: bool = True
) -> List[dict]:
    """
    Finds and ranks all eligible donors matching the requested blood group.
    
    Filters based on:
    1. Blood Group Compatibility (exact first, then compatible if enabled)
    2. Donor Availability & Cooldown (Male >= 90 days, Female >= 120 days)
    3. Medical eligibility (Age >= 18, Weight >= 50 kg)
    4. Donor consent (willing to contact & willing to donate)
    
    Ranks based on:
    1. Exact Match Priority (Exact group ranked above compatible)
    2. Haversine Distance (Closest proximity first)
    3. Cooldown recovery readiness
    """
    req_bg = required_blood_group.strip().upper()
    if req_bg not in COMPATIBILITY_MATRIX:
        return []

    target_groups = [req_bg]
    if allow_compatible_groups:
        target_groups = COMPATIBILITY_MATRIX[req_bg]

    candidates = []

    for bg in target_groups:
        donors = get_donors_by_blood_group(bg, eligible_only=False)
        for donor in donors:
            # 1. Eligibility Check
            is_eligible, days_remaining, status_msg = compute_donor_eligibility(
                donor.get("gender", "male"),
                donor.get("recent_donation_date")
            )
            if not is_eligible or not donor.get("manual_availability", True):
                continue  # In cooldown or turned off availability

            # 2. Medical & Consent checks
            age = donor.get("age", 0)
            weight = donor.get("weight", 0.0)
            willing_contact = donor.get("willing_to_contact", True)
            willing_donate = donor.get("willing_to_donate", True)

            if age < 18 or weight < 50.0 or not willing_contact or not willing_donate:
                continue

            # 3. Location distance check
            donor_lat = donor.get("latitude")
            donor_lon = donor.get("longitude")
            if donor_lat is None or donor_lon is None:
                continue

            dist_km = calculate_haversine_distance(hospital_lat, hospital_lon, donor_lat, donor_lon)
            if dist_km > max_radius_km:
                continue

            # Estimated Travel Time (assuming average urban speed of 30 km/h + 10 mins prep)
            eta_minutes = int(round((dist_km / 30.0) * 60 + 10))

            is_exact = (donor.get("blood_group") == req_bg)

            # Masked donor representation for privacy (No raw phone or email exposed to hospital)
            donor_record = {
                "donor_id": donor.get("donor_id"),
                "blood_group": donor.get("blood_group"),
                "is_exact_match": is_exact,
                "gender": donor.get("gender"),
                "age": donor.get("age"),
                "distance_km": dist_km,
                "eta_minutes": eta_minutes,
                "city": donor.get("city", "Nearby"),
                "hospital_verified": donor.get("hospital_verified", False),
                "recent_donation_date": donor.get("recent_donation_date"),
                "cooldown_status": status_msg
            }
            candidates.append(donor_record)

    # Ranking Sort:
    # 1. Exact match first (True before False)
    # 2. Distance ascending (Closest first)
    candidates.sort(key=lambda d: (
        0 if d["is_exact_match"] else 1,
        d["distance_km"]
    ))

    return candidates

def get_escalation_batch(
    ranked_donors: List[dict],
    batch_index: int,
    batch_size: int
) -> List[dict]:
    """
    Slices the ranked donor pool into sequential escalation batches.
    e.g. Batch 0: Donors 0 to 3, Batch 1: Donors 4 to 7, etc.
    """
    start = batch_index * batch_size
    end = start + batch_size
    if start >= len(ranked_donors):
        return []
    return ranked_donors[start:end]
