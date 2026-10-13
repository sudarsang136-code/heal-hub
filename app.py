import os
import json
import uuid
import hmac
import secrets
import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, url_for, Response, session
from database import (
    save_donor,
    get_donor_by_id,
    authenticate_donor,
    delete_donor_by_id,
    get_all_donors,
    get_donors_by_blood_group,
    save_emergency_request,
    get_emergency_request,
    get_all_emergency_requests,
    record_donation_completion,
    get_donation_records_for_donor,
    seed_sample_donors_if_empty,
    VALID_BLOOD_GROUPS,
    compute_donor_eligibility
)
from matching_engine import (
    find_matching_donors,
    calculate_haversine_distance,
    get_escalation_batch
)
from twilio_service import (
    generate_emergency_twiml,
    trigger_automated_call,
    get_call_logs
)
from notification_service import (
    contact_donor,
    get_dispatched_emails,
    update_email_response
)
from verification_service import (
    save_uploaded_document,
    verify_donation_document
)
from encryption import decrypt_text, mask_phone, mask_email

app = Flask(__name__)
_secret = os.environ.get("FLASK_SECRET")
if not _secret:
    # No secret configured: use a random one for this run only (sessions reset on restart).
    _secret = secrets.token_hex(32)
    print("[WARN] FLASK_SECRET is not set - using a temporary random secret key.")
app.config["SECRET_KEY"] = _secret
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

# Seed initial realistic database if empty
seed_sample_donors_if_empty()

@app.route("/")
def index():
    return render_template("index.html")

# ======================= Hospital Blood Request Routes =======================

@app.route("/api/hospital/request", methods=["POST"])
def create_hospital_request():
    """
    Step 1 & 2: Hospital submits emergency blood request.
    System verifies request and finds matching donors based on:
    - Blood group compatibility
    - Location / Haversine distance
    - Donor availability & cooldown (Male 90d, Female 120d)
    - Medical eligibility & consent
    """
    data = request.get_json() or {}
    
    hospital_name = data.get("hospital_name", "").strip()
    blood_group = data.get("blood_group", "").strip().upper()
    units_required = int(data.get("units_required", 1))
    urgency = data.get("urgency", "Emergency").strip()
    
    if not hospital_name:
        return jsonify({"success": False, "error": "Hospital name or ID is required"}), 400
    if blood_group not in VALID_BLOOD_GROUPS:
        return jsonify({"success": False, "error": f"Invalid blood group '{blood_group}'"}), 400

    lat = float(data.get("latitude", 12.9716))
    lon = float(data.get("longitude", 77.5946))

    # Base URL for callback links
    base_url = request.host_url.rstrip("/")

    # Step 3: Find and rank matching donors
    ranked_donors = find_matching_donors(
        required_blood_group=blood_group,
        hospital_lat=lat,
        hospital_lon=lon,
        max_radius_km=float(data.get("max_radius_km", 50.0)),
        allow_compatible_groups=True
    )

    req_id = f"REQ-{datetime.datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    req_data = {
        "request_id": req_id,
        "hospital_id": data.get("hospital_id", "HOSP-" + hospital_name.replace(" ", "").upper()[:6]),
        "hospital_name": hospital_name,
        "address": data.get("address", "Hospital Center, Bangalore"),
        "latitude": lat,
        "longitude": lon,
        "blood_group": blood_group,
        "units_required": units_required,
        "urgency": urgency,
        "required_by": data.get("required_by", "ASAP / Next 2 Hours"),
        "reason": data.get("reason", "Emergency Surgery"),
        "contact_person": data.get("contact_person", "Duty Medical Officer"),
        "contact_phone": data.get("contact_phone", "+91 80 2234 5678"),
        "authorized": bool(data.get("authorized", True)),
        "ranked_donors_count": len(ranked_donors),
        "status": "SEARCHING" if ranked_donors else "NO_DONORS",
        "current_batch": 0,
        "contacted_donors": [],
        "confirmed_donors": [],
        "declined_donors": []
    }

    # If no donors found
    if not ranked_donors:
        req_data["status"] = "NO_DONORS"
        req_data["system_message"] = "There is no blood donor available right now."
        saved_req = save_emergency_request(req_data)
        return jsonify({
            "success": True,
            "status": "NO_DONORS",
            "message": "There is no blood donor available right now.",
            "request": saved_req
        })

    # Step 4 & 5: Contact first batch of suitable donors
    # Initial batch size: units_required * 2 (or minimum 2 donors)
    batch_size = max(units_required * 2, 2)
    initial_batch = get_escalation_batch(ranked_donors, 0, batch_size)

    contacted_info = []
    for d in initial_batch:
        full_donor = get_donor_by_id(d["donor_id"])
        if full_donor:
            # Merge computed distance for email context
            full_donor["distance_km"] = d["distance_km"]
            res = contact_donor(full_donor, req_data, base_url=base_url)
            contacted_info.append({
                "donor_id": d["donor_id"],
                "blood_group": d["blood_group"],
                "distance_km": d["distance_km"],
                "eta_minutes": d["eta_minutes"],
                "dispatched_at": res["dispatched_at"]
            })

    req_data["status"] = "CONTACTING"
    req_data["contacted_donors"] = contacted_info
    req_data["current_batch"] = 1
    req_data["total_eligible_available"] = len(ranked_donors)

    saved_req = save_emergency_request(req_data)

    return jsonify({
        "success": True,
        "status": "CONTACTING",
        "message": f"Successfully initiated emergency alert to {len(contacted_info)} prioritized donors via automated phone call and email.",
        "request": saved_req,
        "contacted_count": len(contacted_info),
        "remaining_pool": len(ranked_donors) - len(contacted_info)
    })

@app.route("/api/hospital/active-accepted", methods=["GET"])
def get_hospital_active_accepted():
    """
    Returns the current active emergency request and all donors who confirmed availability via email,
    exposing their Donor IDs directly to the Hospital page.
    """
    requests = get_all_emergency_requests()
    if not requests:
        return jsonify({"success": True, "has_active": False, "request": None, "confirmed_donors": []})
    
    # Return latest active/contacting/confirmed request or most recent
    active = next((r for r in requests if r.get("status") in ["CONTACTING", "CONFIRMED"]), requests[0])
    confirmed = active.get("confirmed_donors", [])
    return jsonify({
        "success": True,
        "has_active": True,
        "request": active,
        "confirmed_donors": confirmed
    })

@app.route("/api/hospital/requests", methods=["GET"])
def list_hospital_requests():
    """Lists all active and closed emergency requests."""
    return jsonify({"success": True, "requests": get_all_emergency_requests()})

@app.route("/api/hospital/request/<req_id>", methods=["GET"])
def get_request_details(req_id):
    """Retrieves specific emergency request status."""
    req = get_emergency_request(req_id)
    if not req:
        return jsonify({"success": False, "error": "Request not found"}), 404
    return jsonify({"success": True, "request": req})

@app.route("/api/hospital/confirm-donation", methods=["POST"])
def confirm_donation_completion():
    """
    Step: Donor reaches hospital -> Blood donation completed.
    Hospital enters / confirms Donor ID.
    System updates donation record (updates donation date to today, sets availability to false/cooldown)
    and marks Emergency Request CLOSED.
    """
    data = request.get_json() or {}
    donor_id = data.get("donor_id", "").strip()
    request_id = data.get("request_id", "").strip()
    hospital_id = data.get("hospital_id", "HOSP-01")
    hospital_name = data.get("hospital_name", "Hospital Management")
    units = int(data.get("units", 1))

    if not donor_id:
        return jsonify({"success": False, "error": "Donor ID is required to complete donation"}), 400

    donor = get_donor_by_id(donor_id)
    if not donor:
        return jsonify({"success": False, "error": f"Donor with ID '{donor_id}' not found in any database"}), 404

    try:
        record = record_donation_completion(
            hospital_id=hospital_id,
            hospital_name=hospital_name,
            donor_id=donor_id,
            request_id=request_id,
            units=units
        )
        return jsonify({
            "success": True,
            "message": f"Donation confirmed! Donor {donor_id} donation record updated. 90/120 days availability cooldown applied. Emergency request closed.",
            "record": record
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ======================= Donor Response & Escalation =======================

@app.route("/api/dispatch/respond", methods=["GET", "POST"])
def handle_donor_response():
    """
    Step: Donor receives request and responds:
    - Available (✅)
    - Not Available (❌)
    
    If Available: Matched donor ID sent to hospital.
    If Not Available or insufficient responses: Escalates automatically to next suitable donors.
    """
    request_id = request.args.get("request_id") or (request.json or {}).get("request_id")
    donor_id = request.args.get("donor_id") or (request.json or {}).get("donor_id")
    action = request.args.get("action") or (request.json or {}).get("action", "")

    if not request_id or not donor_id:
        return "<h3>Error: Missing request_id or donor_id.</h3>", 400

    req = get_emergency_request(request_id)
    if not req:
        return "<h3>Error: Emergency request not found or expired.</h3>", 404

    donor = get_donor_by_id(donor_id)
    donor_name = donor.get("name", "Donor") if donor else "Donor"

    update_email_response(request_id, donor_id, action)

    is_accepted = (action.lower() == "accept")

    if is_accepted:
        # Add to confirmed list if not already present
        if not any(c.get("donor_id") == donor_id for c in req.get("confirmed_donors", [])):
            req.setdefault("confirmed_donors", []).append({
                "donor_id": donor_id,
                "blood_group": donor.get("blood_group") if donor else req.get("blood_group"),
                "confirmed_at": datetime.datetime.now().isoformat(),
                "status": "EN_ROUTE"
            })
        
        # Check if units requirement is met
        if len(req.get("confirmed_donors", [])) >= req.get("units_required", 1):
            req["status"] = "CONFIRMED"
        save_emergency_request(req)

        # If user opened via browser click on email link, show beautiful feedback page
        if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
              <title>Thank You - Heal Hub</title>
              <meta name="viewport" content="width=device-width, initial-scale=1.0">
              <style>
                body {{ font-family: 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
                .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 40px; text-align: center; max-width: 480px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
                .badge {{ background: #065f46; color: #34d399; padding: 6px 14px; border-radius: 999px; font-weight: bold; display: inline-block; margin-bottom: 20px; }}
                .btn {{ display: inline-block; background: #ef4444; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 24px; }}
              </style>
            </head>
            <body>
              <div class="card">
                <div class="badge">CONFIRMATION RECORDED</div>
                <h2 style="margin: 0 0 12px 0;">Thank you, {donor_name}! ❤️</h2>
                <p style="color: #94a3b8; line-height: 1.6;">You have confirmed availability for Request <strong>{request_id}</strong> at <strong>{req.get('hospital_name')}</strong>.</p>
                <div style="background: #0f172a; border-radius: 8px; padding: 16px; margin: 20px 0; text-align: left; font-size: 14px;">
                  <div><strong>Your Donor ID:</strong> <span style="color: #38bdf8;">{donor_id}</span></div>
                  <div><strong>Hospital:</strong> {req.get('hospital_name')}</div>
                  <div><strong>Location:</strong> {req.get('address')}</div>
                </div>
                <p style="font-size: 13px; color: #64748b;">Please proceed to the hospital blood bank and present your Donor ID upon arrival.</p>
                <a class="btn" href="/">Return to Heal Hub</a>
              </div>
            </body>
            </html>
            """
        return jsonify({"success": True, "action": "accept", "donor_id": donor_id, "request_status": req["status"]})

    else:
        # Declined
        if not any(d.get("donor_id") == donor_id for d in req.get("declined_donors", [])):
            req.setdefault("declined_donors", []).append({
                "donor_id": donor_id,
                "declined_at": datetime.datetime.now().isoformat()
            })
        
        # Check if we should escalate to next batch
        confirmed_count = len(req.get("confirmed_donors", []))
        units_needed = req.get("units_required", 1)
        
        if confirmed_count < units_needed:
            # Auto-escalate: find next batch
            escalate_request(req)

        save_emergency_request(req)

        if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
              <title>Response Recorded - Heal Hub</title>
              <meta name="viewport" content="width=device-width, initial-scale=1.0">
              <style>
                body {{ font-family: 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
                .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 40px; text-align: center; max-width: 480px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
                .btn {{ display: inline-block; background: #475569; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 24px; }}
              </style>
            </head>
            <body>
              <div class="card">
                <h2 style="margin: 0 0 12px 0;">Response Recorded</h2>
                <p style="color: #94a3b8; line-height: 1.6;">Thank you for letting us know, {donor_name}. The system has automatically escalated this urgent request to the next suitable donor in your area.</p>
                <a class="btn" href="/">Return to Heal Hub</a>
              </div>
            </body>
            </html>
            """
        return jsonify({"success": True, "action": "reject", "donor_id": donor_id, "escalated": True})

def escalate_request(req: dict):
    """Escalates an ongoing request to the next batch of donors."""
    blood_group = req.get("blood_group")
    lat = req.get("latitude")
    lon = req.get("longitude")
    current_batch = req.get("current_batch", 1)

    ranked_donors = find_matching_donors(blood_group, lat, lon)
    batch_size = max(req.get("units_required", 1) * 2, 2)
    next_batch = get_escalation_batch(ranked_donors, current_batch, batch_size)

    already_contacted = {c["donor_id"] for c in req.get("contacted_donors", [])}
    new_contacted = []

    for d in next_batch:
        if d["donor_id"] in already_contacted:
            continue
        full_donor = get_donor_by_id(d["donor_id"])
        if full_donor:
            full_donor["distance_km"] = d["distance_km"]
            contact_donor(full_donor, req)
            new_contacted.append({
                "donor_id": d["donor_id"],
                "blood_group": d["blood_group"],
                "distance_km": d["distance_km"],
                "eta_minutes": d["eta_minutes"],
                "dispatched_at": datetime.datetime.now().isoformat(),
                "escalation_batch": current_batch
            })

    if new_contacted:
        req.setdefault("contacted_donors", []).extend(new_contacted)
        req["current_batch"] = current_batch + 1
        req["status"] = "CONTACTING"
    else:
        # Exhausted all donors
        if not req.get("confirmed_donors"):
            req["status"] = "NO_DONORS"
            req["system_message"] = "There is no blood donor available right now."

@app.route("/api/dispatch/escalate", methods=["POST"])
def manual_escalate():
    data = request.get_json() or {}
    req_id = data.get("request_id")
    req = get_emergency_request(req_id)
    if not req:
        return jsonify({"success": False, "error": "Request not found"}), 404
    escalate_request(req)
    save_emergency_request(req)
    return jsonify({"success": True, "request": req})

# ======================= Twilio Webhooks & Simulator =======================

@app.route("/api/twilio/voice-twiml", methods=["GET", "POST"])
def twilio_voice_twiml():
    """Returns TwiML Voice XML when Twilio connects the call."""
    request_id = request.args.get("request_id", "")
    donor_id = request.args.get("donor_id", "")
    req = get_emergency_request(request_id) if request_id else None
    
    hospital_name = req.get("hospital_name", "Local Hospital") if req else "Local Hospital"
    blood_group = req.get("blood_group", "O+") if req else "O+"
    units = req.get("units_required", 1) if req else 1
    
    base_url = request.host_url.rstrip("/")
    twiml_xml = generate_emergency_twiml(hospital_name, blood_group, units, request_id, donor_id, base_url=base_url)
    return Response(twiml_xml, mimetype="text/xml")

@app.route("/api/twilio/voice-response", methods=["POST"])
def twilio_voice_response():
    """Handles DTMF keypress (1=Accept, 2=Decline) from the automated Twilio call."""
    digits = request.form.get("Digits", "")
    request_id = request.args.get("request_id", "")
    donor_id = request.args.get("donor_id", "")

    resp = ""
    if digits == "1":
        # Donor confirms availability
        if request_id and donor_id:
            req = get_emergency_request(request_id)
            donor = get_donor_by_id(donor_id)
            if req and donor:
                req.setdefault("confirmed_donors", []).append({
                    "donor_id": donor_id,
                    "blood_group": donor.get("blood_group"),
                    "confirmed_at": datetime.datetime.now().isoformat(),
                    "source": "TWILIO_IVR_KEYPAD"
                })
                if len(req.get("confirmed_donors", [])) >= req.get("units_required", 1):
                    req["status"] = "CONFIRMED"
                save_emergency_request(req)
        resp = """<?xml version="1.0" encoding="UTF-8"?>
        <Response>
          <Say voice="Polly.Joanna">Thank you for confirming your availability! Your Donor ID has been transmitted to the hospital. Please check your email for full hospital address details. Goodbye.</Say>
        </Response>"""
    elif digits == "2":
        if request_id and donor_id:
            req = get_emergency_request(request_id)
            if req:
                req.setdefault("declined_donors", []).append({
                    "donor_id": donor_id,
                    "declined_at": datetime.datetime.now().isoformat(),
                    "source": "TWILIO_IVR_KEYPAD"
                })
                escalate_request(req)
                save_emergency_request(req)
        resp = """<?xml version="1.0" encoding="UTF-8"?>
        <Response>
          <Say voice="Polly.Joanna">Thank you for responding. We have noted that you are currently unavailable and will escalate to the next nearby donor. Have a nice day.</Say>
        </Response>"""
    else:
        resp = """<?xml version="1.0" encoding="UTF-8"?>
        <Response>
          <Say voice="Polly.Joanna">Input not recognized. Please review your email for emergency details. Goodbye.</Say>
        </Response>"""

    return Response(resp, mimetype="text/xml")

@app.route("/api/twilio/call-status", methods=["POST"])
def twilio_call_status():
    """Callback for Twilio call status updates."""
    sid = request.form.get("CallSid")
    status = request.form.get("CallStatus")
    print(f"Twilio Call Callback: SID={sid}, Status={status}")
    return "OK", 200

@app.route("/api/twilio/logs", methods=["GET"])
def get_all_call_logs():
    return jsonify({"success": True, "logs": get_call_logs()})

# ======================= Donor Registration & Management =======================

@app.route("/api/donors/register", methods=["POST"])
def register_donor():
    """
    Donor Registration:
    Provides: Name, DOB, Phone, Email
    Questionnaire:
    1. Age
    2. Gender
    3. Blood Group
    4. Weight
    5. Donated before?
    6. Most recent donation date?
    7. Verified by hospital/blood bank?
    8. Upload document (card/certificate/receipt) -> AI verification
    9. Willing to be contacted?
    10. Willing to donate?
    """
    # Can be JSON or Form data (for file upload)
    if request.is_json:
        data = request.get_json() or {}
        uploaded_doc = None
    else:
        data = request.form.to_dict()
        uploaded_doc = request.files.get("donation_document")

    name = data.get("name", "").strip()
    dob = data.get("dob", "").strip()
    blood_group = data.get("blood_group", "").strip().upper()
    phone = data.get("phone", "").strip()
    email = data.get("email", "").strip()

    if not name or not dob or not blood_group or not phone:
        return jsonify({"success": False, "error": "Name, DOB, Blood Group, and Phone are required"}), 400

    if blood_group not in VALID_BLOOD_GROUPS:
        return jsonify({"success": False, "error": f"Invalid blood group: {blood_group}"}), 400

    # Handle document upload & AI verification
    doc_filename = None
    doc_verified_report = None
    if uploaded_doc and uploaded_doc.filename:
        doc_filename = save_uploaded_document(uploaded_doc)
        doc_verified_report = verify_donation_document(doc_filename, name, blood_group)

    donated_before_val = str(data.get("donated_before", "false")).lower() in ["true", "1", "yes"]
    recent_date_val = data.get("recent_donation_date") if donated_before_val else None
    if recent_date_val == "":
        recent_date_val = None

    donor_dict = {
        "name": name,
        "dob": dob,
        "phone": phone,
        "email": email,
        "blood_group": blood_group,
        "age": int(data.get("age", 25)),
        "gender": data.get("gender", "male").lower(),
        "weight": float(data.get("weight", 65.0)),
        "donated_before": donated_before_val,
        "recent_donation_date": recent_date_val,
        "hospital_verified": str(data.get("hospital_verified", "false")).lower() in ["true", "1", "yes"],
        "document_filename": doc_filename,
        "document_verified": bool(doc_verified_report),
        "document_report": doc_verified_report,
        "willing_to_contact": str(data.get("willing_to_contact", "true")).lower() in ["true", "1", "yes"],
        "willing_to_donate": str(data.get("willing_to_donate", "true")).lower() in ["true", "1", "yes"],
        "latitude": float(data.get("latitude", 12.9716)),
        "longitude": float(data.get("longitude", 77.5946)),
        "city": data.get("city", "Bangalore"),
        "manual_availability": True,
        "notes": data.get("notes", "")
    }

    saved = save_donor(donor_dict)

    # Return safe profile
    return jsonify({
        "success": True,
        "message": "Donor registered successfully!",
        "donor_id": saved["donor_id"],
        "donor": saved
    })

@app.route("/api/donors/login", methods=["POST"])
def donor_login():
    """
    Step: Donor Update / Portal Login.
    Donor logs in using Donor ID and Date of Birth (as password).
    """
    data = request.get_json() or {}
    donor_id = data.get("donor_id", "").strip()
    dob = data.get("dob", "").strip()

    if not donor_id or not dob:
        return jsonify({"success": False, "error": "Donor ID and Date of Birth are required"}), 400

    authenticated = authenticate_donor(donor_id, dob)
    if not authenticated:
        return jsonify({"success": False, "error": "Invalid Donor ID or Date of Birth"}), 401

    history = get_donation_records_for_donor(donor_id)
    authenticated["donation_history"] = history

    return jsonify({
        "success": True,
        "message": "Authenticated successfully",
        "donor": authenticated
    })

@app.route("/api/donors/update", methods=["POST"])
def update_donor_profile():
    """Allows authenticated donor to update all data fields they entered when registered."""
    data = request.get_json() or {}
    donor_id = data.get("donor_id", "").strip()
    dob = data.get("dob", "").strip()

    authenticated = authenticate_donor(donor_id, dob)
    if not authenticated:
        return jsonify({"success": False, "error": "Unauthorized: Invalid Donor ID or current DOB"}), 401

    existing = get_donor_by_id(donor_id)
    if not existing:
        return jsonify({"success": False, "error": "Donor record not found"}), 404

    # 1. Personal Information
    if "name" in data and data["name"]:
        existing["name"] = str(data["name"]).strip()
    if "new_dob" in data and data["new_dob"]:
        existing["dob"] = str(data["new_dob"]).strip()
    elif "dob_change" in data and data["dob_change"]:
        existing["dob"] = str(data["dob_change"]).strip()
    if "phone" in data and data["phone"]:
        existing["phone"] = str(data["phone"]).strip()
    if "email" in data and data["email"]:
        existing["email"] = str(data["email"]).strip()
    if "city" in data:
        existing["city"] = str(data["city"]).strip()
    if "latitude" in data:
        try:
            existing["latitude"] = float(data["latitude"])
        except (ValueError, TypeError):
            pass
    if "longitude" in data:
        try:
            existing["longitude"] = float(data["longitude"])
        except (ValueError, TypeError):
            pass

    # 2. Medical & Eligibility Information
    if "blood_group" in data and data["blood_group"]:
        bg = str(data["blood_group"]).strip().upper()
        if bg in VALID_BLOOD_GROUPS:
            existing["blood_group"] = bg
    if "age" in data:
        try:
            existing["age"] = int(data["age"])
        except (ValueError, TypeError):
            pass
    if "gender" in data and data["gender"]:
        existing["gender"] = str(data["gender"]).strip().lower()
    if "weight" in data:
        try:
            existing["weight"] = float(data["weight"])
        except (ValueError, TypeError):
            pass
    if "donated_before" in data:
        existing["donated_before"] = str(data["donated_before"]).lower() in ["true", "1", "yes"]
    if "recent_donation_date" in data:
        existing["recent_donation_date"] = data["recent_donation_date"] or None
    if "hospital_verified" in data:
        existing["hospital_verified"] = str(data["hospital_verified"]).lower() in ["true", "1", "yes"]
    if "willing_to_contact" in data:
        existing["willing_to_contact"] = str(data["willing_to_contact"]).lower() in ["true", "1", "yes"]
    if "willing_to_donate" in data:
        existing["willing_to_donate"] = str(data["willing_to_donate"]).lower() in ["true", "1", "yes"]
    if "manual_availability" in data:
        existing["manual_availability"] = str(data["manual_availability"]).lower() in ["true", "1", "yes"]
    if "notes" in data:
        existing["notes"] = str(data["notes"]).strip()

    saved = save_donor(existing)
    safe_copy = dict(saved)
    safe_copy["phone"] = decrypt_text(saved.get("phone_encrypted", ""))
    safe_copy["email"] = decrypt_text(saved.get("email_encrypted", ""))
    return jsonify({"success": True, "message": "All donor details updated successfully", "donor": safe_copy})

@app.route("/api/donors/delete", methods=["POST"])
def delete_donor_profile():
    """Allows donor to delete their ID securely."""
    data = request.get_json() or {}
    donor_id = data.get("donor_id", "").strip()
    dob = data.get("dob", "").strip()

    authenticated = authenticate_donor(donor_id, dob)
    if not authenticated:
        return jsonify({"success": False, "error": "Unauthorized: Invalid Donor ID or DOB"}), 401

    success = delete_donor_by_id(donor_id)
    if success:
        return jsonify({"success": True, "message": f"Donor {donor_id} successfully deleted from the database."})
    return jsonify({"success": False, "error": "Failed to delete donor"}), 500

@app.route("/api/donors/all", methods=["GET"])
def get_donors_directory():
    """Returns directory of all registered donors across all 8 databases with PII masked for security."""
    return jsonify({"success": True, "donors": get_all_donors(mask_pii=True)})

# ======================= Virtual Email Inbox Viewer =======================

@app.route("/api/emails/inbox", methods=["GET"])
def get_inbox():
    req_id = request.args.get("request_id")
    emails = get_dispatched_emails(req_id)
    return jsonify({"success": True, "emails": emails})

# ======================= Admin Authentication & Control =======================

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    """Authenticates admin against ADMIN_ID / ADMIN_PASSWORD environment variables."""
    expected_id = os.environ.get("ADMIN_ID", "")
    expected_pw = os.environ.get("ADMIN_PASSWORD", "")
    if not expected_id or not expected_pw:
        return jsonify({"success": False, "error": "Admin login is not configured on the server"}), 503
    data = request.get_json(silent=True) or {}
    admin_id = str(data.get("admin_id", "")).strip()
    password = str(data.get("password", "")).strip()

    id_ok = hmac.compare_digest(admin_id.encode(), expected_id.encode())
    pw_ok = hmac.compare_digest(password.encode(), expected_pw.encode())
    if id_ok and pw_ok:
        session["admin_logged_in"] = True
        session["admin_id"] = expected_id
        return jsonify({
            "success": True,
            "message": "Admin authenticated successfully",
            "admin_id": expected_id
        })
    return jsonify({"success": False, "error": "Invalid Admin ID or Password"}), 401

@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    """Logs out admin session."""
    session.pop("admin_logged_in", None)
    session.pop("admin_id", None)
    return jsonify({"success": True, "message": "Admin logged out successfully"})

@app.route("/api/admin/status", methods=["GET"])
def admin_status():
    """Returns current admin authentication status."""
    is_auth = bool(session.get("admin_logged_in", False))
    return jsonify({
        "success": True,
        "authenticated": is_auth,
        "admin_id": session.get("admin_id") if is_auth else None
    })

# ---- Admin-only data routes (require admin session) ----

def _require_admin():
    """Returns a 401 response if admin is not authenticated, else None."""
    if not session.get("admin_logged_in"):
        return jsonify({"success": False, "error": "Admin authentication required"}), 401
    return None

@app.route("/api/admin/donors", methods=["GET"])
def admin_get_donors():
    """Admin: returns full donor directory (PII masked)."""
    err = _require_admin()
    if err: return err
    donors = get_all_donors(mask_pii=True)
    return jsonify(donors)

@app.route("/api/admin/requests", methods=["GET"])
def admin_get_requests():
    """Admin: returns all emergency blood requests."""
    err = _require_admin()
    if err: return err
    requests_list = get_all_emergency_requests()
    return jsonify(requests_list)

@app.route("/api/admin/request/<request_id>", methods=["GET"])
def admin_get_single_request(request_id):
    """Admin: returns full detail for a single request including donor contact logs."""
    err = _require_admin()
    if err: return err
    req = get_emergency_request(request_id)
    if not req:
        return jsonify({"success": False, "error": "Request not found"}), 404
    return jsonify(req)

# ---- Admin: Close any request ----

@app.route("/api/admin/request/<request_id>/close", methods=["POST"])
def admin_close_request(request_id):
    """Admin: forcefully closes a blood request and marks it CLOSED."""
    err = _require_admin()
    if err: return err
    req = get_emergency_request(request_id)
    if not req:
        return jsonify({"success": False, "error": "Request not found"}), 404
    req["status"] = "CLOSED"
    req["closed_by"] = "ADMIN"
    req["closed_at"] = datetime.datetime.now().isoformat()
    save_emergency_request(req)
    return jsonify({"success": True, "message": f"Request {request_id} closed by admin"})

# ---- Hospital: Close active request (no PII, no admin auth needed) ----
# Hospital page calls this to mark a request closed after donors confirmed.

@app.route("/api/hospital/request/<request_id>/close", methods=["POST"])
def hospital_close_request(request_id):
    """Hospital-facing: marks a request as CLOSED once fulfilled."""
    req = get_emergency_request(request_id)
    if not req:
        return jsonify({"success": False, "error": "Request not found"}), 404
    req["status"] = "CLOSED"
    req["closed_by"] = "HOSPITAL"
    req["closed_at"] = datetime.datetime.now().isoformat()
    save_emergency_request(req)
    return jsonify({"success": True, "message": f"Request {request_id} closed"})

# ---- Admin: Donor CRUD ----

@app.route("/api/admin/donor", methods=["POST"])
def admin_add_donor():
    """Admin: add a new donor to the database."""
    err = _require_admin()
    if err: return err
    data = request.get_json() or {}
    name = str(data.get("name", "")).strip()
    blood_group = str(data.get("blood_group", "")).strip().upper()
    if not blood_group or not name:
        return jsonify({"success": False, "error": "name and blood_group are required"}), 400
    if blood_group not in VALID_BLOOD_GROUPS:
        return jsonify({"success": False, "error": f"Invalid blood group: {blood_group}"}), 400

    try:
        donor_dict = {
            "name": name,
            "dob": str(data.get("dob", "1995-01-01")).strip(),
            "blood_group": blood_group,
            "gender": str(data.get("gender", "male")).strip().lower(),
            "phone": str(data.get("phone", "+91 98450 11223")).strip(),
            "email": str(data.get("email", "donor@healhub.org")).strip(),
            "city": str(data.get("city", "Bangalore")).strip(),
            "latitude": float(data.get("latitude", 12.9716)),
            "longitude": float(data.get("longitude", 77.5946)),
            "weight": float(data.get("weight", 65.0)),
            "age": int(data.get("age", 25)),
            "donated_before": bool(data.get("donated_before", False)),
            "recent_donation_date": data.get("recent_donation_date") if data.get("recent_donation_date") else None,
            "manual_availability": bool(data.get("manual_availability", True)),
            "willing_to_contact": True,
            "willing_to_donate": True,
            "notes": str(data.get("notes", "Registered via Admin Console"))
        }
        saved = save_donor(donor_dict)
        return jsonify({"success": True, "donor_id": saved["donor_id"], "message": "Donor created successfully", "donor": saved})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/admin/donor/<donor_id>", methods=["PUT"])
def admin_edit_donor(donor_id):
    """Admin: edit an existing donor's fields (name, availability, phone, email, etc.)."""
    err = _require_admin()
    if err: return err
    existing = get_donor_by_id(donor_id)
    if not existing:
        return jsonify({"success": False, "error": "Donor not found"}), 404
    updates = request.get_json() or {}
    
    for field in ["name", "dob", "blood_group", "gender", "age", "weight", "phone", "email", 
                  "city", "latitude", "longitude", "donated_before", "recent_donation_date", 
                  "hospital_verified", "willing_to_contact", "willing_to_donate", 
                  "manual_availability", "notes"]:
        if field in updates:
            if field == "blood_group":
                bg = str(updates[field]).strip().upper()
                if bg in VALID_BLOOD_GROUPS:
                    existing["blood_group"] = bg
            elif field == "age":
                try:
                    existing["age"] = int(updates[field])
                except (ValueError, TypeError):
                    pass
            elif field in ["weight", "latitude", "longitude"]:
                try:
                    existing[field] = float(updates[field])
                except (ValueError, TypeError):
                    pass
            elif field in ["donated_before", "hospital_verified", "willing_to_contact", "willing_to_donate", "manual_availability"]:
                existing[field] = str(updates[field]).lower() in ["true", "1", "yes"] if isinstance(updates[field], str) else bool(updates[field])
            else:
                existing[field] = updates[field]

    existing["donor_id"] = donor_id  # ensure ID stays the same
    saved = save_donor(existing)
    return jsonify({"success": True, "message": "Donor updated successfully", "donor_id": donor_id})

@app.route("/api/admin/donor/<donor_id>", methods=["DELETE"])
def admin_delete_donor(donor_id):
    """Admin: permanently delete a donor from the database."""
    err = _require_admin()
    if err: return err
    deleted = delete_donor_by_id(donor_id)
    if deleted:
        return jsonify({"success": True, "message": f"Donor {donor_id} deleted"})
    return jsonify({"success": False, "error": "Donor not found"}), 404

@app.route("/api/admin/donor/<donor_id>", methods=["GET"])
def admin_get_donor(donor_id):
    """Admin: get a single donor's full record (decrypted PII for admin use)."""
    err = _require_admin()
    if err: return err
    donor = get_donor_by_id(donor_id)
    if not donor:
        return jsonify({"success": False, "error": "Donor not found"}), 404
    # Decrypt PII for admin view
    from encryption import decrypt_text
    safe = dict(donor)
    safe["phone"] = decrypt_text(donor.get("phone_encrypted", ""))
    safe["email"] = decrypt_text(donor.get("email_encrypted", ""))
    return jsonify(safe)

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    app.run(debug=debug, port=int(os.environ.get("PORT", 5000)), host=host)
