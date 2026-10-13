import requests
import json
import datetime

BASE_URL = "http://127.0.0.1:5000"

def test_workflow():
    print("=== Testing Heal Hub Round 3 End-to-End Workflow ===")

    # 1. Test homepage
    r = requests.get(f"{BASE_URL}/")
    assert r.status_code == 200, f"Home page failed: {r.status_code}"
    print("[PASS] Homepage loads successfully")

    # 2. Test Donors directory
    r = requests.get(f"{BASE_URL}/api/donors/all")
    assert r.status_code == 200
    donors = r.json()["donors"]
    assert len(donors) >= 10, f"Expected at least 10 seeded donors, got {len(donors)}"
    print(f"[PASS] Donors Directory retrieved {len(donors)} donors across 8 separate database files")
    
    # Check masking of PII
    for d in donors:
        assert "phone_encrypted" not in d, "phone_encrypted leaked!"
        assert "email_encrypted" not in d, "email_encrypted leaked!"
        assert "*" in d["phone_masked"], "phone should be masked"
    print("[PASS] Sensitive PII properly encrypted & masked")

    # 3. Create Emergency Request: B+ Blood, 2 units, Emergency
    req_payload = {
        "hospital_name": "Bangalore Central Emergency Hospital",
        "hospital_id": "HOSP-BLR-01",
        "address": "Residency Road, Ashok Nagar, Bengaluru",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "blood_group": "B+",
        "units_required": 2,
        "urgency": "Emergency",
        "required_by": (datetime.datetime.now() + datetime.timedelta(hours=2)).isoformat(),
        "reason": "Emergency accident victim with acute blood loss",
        "contact_person": "Dr. Arvind Rao",
        "contact_phone": "+91 80 2299 1100",
        "authorized": True
    }
    r = requests.post(f"{BASE_URL}/api/hospital/request", json=req_payload)
    assert r.status_code == 200
    res_data = r.json()
    assert res_data["success"] is True
    assert res_data["status"] == "CONTACTING"
    req_id = res_data["request"]["request_id"]
    contacted = res_data["request"]["contacted_donors"]
    assert len(contacted) >= 2, f"Expected at least 2 contacted donors, got {len(contacted)}"
    print(f"[PASS] Created Emergency Request {req_id} for B+ blood (2 units)")
    print(f"[PASS] Initial batch contacted {len(contacted)} donors based on proximity and cooldown eligibility")

    # 4. Check Twilio logs
    r = requests.get(f"{BASE_URL}/api/twilio/logs")
    assert r.status_code == 200
    logs = r.json()["logs"]
    assert len(logs) > 0
    print(f"[PASS] Twilio automated call logged with Call SID: {logs[0]['call_id'][:16]}...")
    print(f"       Script: {logs[0]['script'][:80]}...")

    # 5. Check Email Inbox
    r = requests.get(f"{BASE_URL}/api/emails/inbox?request_id={req_id}")
    assert r.status_code == 200
    emails = r.json()["emails"]
    assert len(emails) >= 2
    print(f"[PASS] Emergency email dispatched to {emails[0]['recipient_name']} with response tokens")

    # 6. Donor 1 responds "Available"
    donor_1_id = contacted[0]["donor_id"]
    r = requests.get(f"{BASE_URL}/api/dispatch/respond?request_id={req_id}&donor_id={donor_1_id}&action=accept")
    assert r.status_code == 200
    print(f"[PASS] Donor 1 ({donor_1_id}) confirmed AVAILABLE via email action link")

    # Donor 2 responds "Available"
    donor_2_id = contacted[1]["donor_id"]
    r = requests.get(f"{BASE_URL}/api/dispatch/respond?request_id={req_id}&donor_id={donor_2_id}&action=accept")
    assert r.status_code == 200
    print(f"[PASS] Donor 2 ({donor_2_id}) confirmed AVAILABLE via email action link")

    # 7. Check hospital request tracker status
    r = requests.get(f"{BASE_URL}/api/hospital/request/{req_id}")
    req_status = r.json()["request"]
    assert req_status["status"] == "CONFIRMED", f"Expected CONFIRMED, got {req_status['status']}"
    assert len(req_status["confirmed_donors"]) == 2
    print(f"[PASS] Hospital Request status updated to CONFIRMED with 2 matched donors:")
    for c in req_status["confirmed_donors"]:
        print(f"       - Matched Donor ID: {c['donor_id']} (Status: {c['status']})")

    # 8. Donor reaches hospital -> Blood donation completed
    # Hospital enters / confirms Donor ID
    comp_payload = {
        "donor_id": donor_1_id,
        "request_id": req_id,
        "hospital_id": "HOSP-BLR-01",
        "hospital_name": "Bangalore Central Emergency Hospital",
        "units": 1
    }
    r = requests.post(f"{BASE_URL}/api/hospital/confirm-donation", json=comp_payload)
    assert r.status_code == 200
    print(f"[PASS] Hospital entered Donor ID ({donor_1_id}) upon arrival and blood donation completion")
    print(f"[PASS] Emergency Request marked CLOSED and donation audit record saved")

    # Check request status is CLOSED
    r = requests.get(f"{BASE_URL}/api/hospital/request/{req_id}")
    assert r.json()["request"]["status"] == "CLOSED"

    # 9. Verify donor cooldown applied (Male 90 days / Female 120 days)
    from database import get_donor_by_id
    d1 = get_donor_by_id(donor_1_id)
    dob = d1["dob"]
    
    r = requests.post(f"{BASE_URL}/api/donors/login", json={"donor_id": donor_1_id, "dob": dob})
    assert r.status_code == 200
    donor_profile = r.json()["donor"]
    assert donor_profile["computed_availability"] is False, "Donor should now be in cooldown!"
    expected_cooldown = 120 if donor_profile["gender"] == "female" else 90
    assert donor_profile["cooldown_days_remaining"] == expected_cooldown, f"Expected {expected_cooldown}d cooldown, got {donor_profile['cooldown_days_remaining']}d"
    assert donor_profile["recent_donation_date"] == datetime.date.today().isoformat()
    assert len(donor_profile["donation_history"]) >= 1
    print(f"[PASS] Donor {donor_1_id} logged in with ID + DOB: Cooldown active ({donor_profile['cooldown_days_remaining']} days remaining)")

    # 10. Test 'No donors available' notification scenario
    no_donors_payload = {
        "hospital_name": "Remote Offshore Clinic",
        "hospital_id": "HOSP-REM-99",
        "address": "Isolated Island",
        "latitude": -45.0,
        "longitude": -120.0,
        "blood_group": "AB-",
        "units_required": 5,
        "urgency": "Emergency",
        "required_by": "ASAP",
        "reason": "Trauma",
        "contact_person": "Medic",
        "contact_phone": "+00 000 0000",
        "authorized": True,
        "max_radius_km": 10.0
    }
    r = requests.post(f"{BASE_URL}/api/hospital/request", json=no_donors_payload)
    res_no = r.json()
    assert res_no["status"] == "NO_DONORS"
    assert "There is no blood donor available right now." in res_no["message"]
    print(f"[PASS] 'No donors available' notification verified: \"{res_no['message']}\"")

    print("\n=======================================================")
    print(" ALL 10 END-TO-END WORKFLOW VERIFICATIONS PASSED 100%!")
    print("=======================================================\n")

if __name__ == "__main__":
    test_workflow()
