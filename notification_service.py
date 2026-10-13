import os
import json
import uuid
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
from encryption import decrypt_text, mask_email
from twilio_service import trigger_automated_call
from database import (
    get_donor_by_id,
    get_emergency_request,
    save_emergency_request,
    save_donor
)

SENDER_EMAIL = os.getenv("SMTP_SENDER", "noreply@example.com")

EMAILS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dispatched_emails.json")

def _load_emails() -> List[dict]:
    if not os.path.exists(EMAILS_FILE):
        return []
    try:
        with open(EMAILS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_emails(emails: List[dict]):
    os.makedirs(os.path.dirname(EMAILS_FILE), exist_ok=True)
    with open(EMAILS_FILE, "w", encoding="utf-8") as f:
        json.dump(emails, f, indent=2)

def _send_real_smtp_email(to_email: str, subject: str, html_body: str) -> dict:
    """Dispatches a real email via Gmail SMTP using the user-specified credentials."""
    sender = SENDER_EMAIL
    app_password = os.getenv("APP_PASSWORD")
    
    if not app_password:
        return {
            "sent": False,
            "reason": "APP_PASSWORD not set in environment (saved in local dispatch logs for preview)"
        }
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Heal Hub Emergency <{sender}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))
        
        # Connect via Gmail SSL (port 465)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(sender, app_password)
            server.sendmail(sender, [to_email], msg.as_string())
        return {"sent": True, "reason": "Delivered via Gmail SMTP (SSL:465)"}
    except Exception as err_ssl:
        # Fallback to TLS (port 587)
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
                server.starttls()
                server.login(sender, app_password)
                server.sendmail(sender, [to_email], msg.as_string())
            return {"sent": True, "reason": "Delivered via Gmail SMTP (TLS:587)"}
        except Exception as err_tls:
            print(f"[SMTP Error] Failed to send email to {to_email}: {err_tls}")
            return {"sent": False, "reason": f"SMTP Error: {str(err_tls)}"}

def send_emergency_email(
    donor: dict,
    hospital_name: str,
    hospital_address: str,
    distance_km: float,
    blood_group: str,
    units: int,
    urgency: str,
    required_by: str,
    reason: str,
    request_id: str,
    base_url: str = "http://127.0.0.1:5000"
) -> dict:
    """Dispatches an emergency email to the donor with one-click action links."""
    donor_id = donor.get("donor_id", "")
    raw_email = decrypt_text(donor.get("email_encrypted", donor.get("email", "")))
    donor_name = donor.get("name", "Valued Donor")

    email_id = f"EML-{uuid.uuid4().hex[:8].upper()}"
    accept_url = f"{base_url}/api/dispatch/respond?request_id={request_id}&donor_id={donor_id}&action=accept"
    reject_url = f"{base_url}/api/dispatch/respond?request_id={request_id}&donor_id={donor_id}&action=reject"

    html_content = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #fee2e2; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(239, 68, 68, 0.1);">
      <div style="background: linear-gradient(135deg, #dc2626, #ef4444); color: #ffffff; padding: 24px; text-align: center;">
        <h1 style="margin: 0; font-size: 24px; letter-spacing: 0.5px;">🩸 URGENT BLOOD DONATION REQUEST</h1>
        <p style="margin: 6px 0 0 0; opacity: 0.9; font-size: 14px;">Heal Hub Emergency Dispatch System</p>
      </div>
      <div style="padding: 24px; background: #ffffff; color: #1e293b;">
        <p style="font-size: 16px; margin-top: 0;">Dear <strong>{donor_name}</strong> (ID: <span style="font-family: monospace; background: #f1f5f9; padding: 2px 6px; border-radius: 4px;">{donor_id}</span>),</p>
        <p style="line-height: 1.6;">There is a critical emergency requiring your blood group <strong>{blood_group}</strong>. Your immediate assistance can save a life.</p>
        
        <div style="background: #f8fafc; border-left: 4px solid #ef4444; padding: 16px; border-radius: 6px; margin: 20px 0;">
          <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
            <tr><td style="padding: 4px 0; color: #64748b;">Hospital:</td><td style="padding: 4px 0; font-weight: 600;">{hospital_name}</td></tr>
            <tr><td style="padding: 4px 0; color: #64748b;">Location:</td><td style="padding: 4px 0;">{hospital_address} (~{distance_km} km away)</td></tr>
            <tr><td style="padding: 4px 0; color: #64748b;">Blood Group Needed:</td><td style="padding: 4px 0; font-weight: 700; color: #dc2626;">{blood_group} ({units} Units)</td></tr>
            <tr><td style="padding: 4px 0; color: #64748b;">Urgency Level:</td><td style="padding: 4px 0;"><span style="background: #fee2e2; color: #b91c1c; padding: 2px 8px; border-radius: 12px; font-weight: 600; font-size: 12px;">{urgency.upper()}</span></td></tr>
            <tr><td style="padding: 4px 0; color: #64748b;">Required By:</td><td style="padding: 4px 0;">{required_by}</td></tr>
            <tr><td style="padding: 4px 0; color: #64748b;">Reason:</td><td style="padding: 4px 0;">{reason}</td></tr>
          </table>
        </div>

        <p style="text-align: center; font-weight: 600; margin-bottom: 20px;">Can you donate blood for this emergency request?</p>

        <div style="display: flex; gap: 12px; justify-content: center; text-align: center; margin: 25px 0;">
          <a href="{accept_url}" target="_blank" style="background: #10b981; color: #ffffff; text-decoration: none; padding: 14px 28px; border-radius: 8px; font-weight: 700; font-size: 15px; display: inline-block; box-shadow: 0 4px 10px rgba(16, 185, 129, 0.3);">
            ✅ YES, I AM AVAILABLE
          </a>
          &nbsp;&nbsp;
          <a href="{reject_url}" target="_blank" style="background: #64748b; color: #ffffff; text-decoration: none; padding: 14px 24px; border-radius: 8px; font-weight: 600; font-size: 15px; display: inline-block;">
            ❌ NOT AVAILABLE
          </a>
        </div>
        <p style="font-size: 12px; color: #94a3b8; text-align: center; margin-top: 24px;">Note: Your contact details remain confidential. The hospital only receives your Donor ID once you confirm availability.</p>
      </div>
    </div>
    """

    # Trigger real SMTP email send
    smtp_res = _send_real_smtp_email(
        to_email=raw_email,
        subject=f"🚨 URGENT: Blood Needed ({blood_group}) - {hospital_name}",
        html_body=html_content
    )

    email_entry = {
        "email_id": email_id,
        "request_id": request_id,
        "donor_id": donor_id,
        "recipient_name": donor_name,
        "recipient_email": raw_email,
        "recipient_email_masked": mask_email(raw_email),
        "sender": SENDER_EMAIL,
        "blood_group": blood_group,
        "hospital_name": hospital_name,
        "distance_km": distance_km,
        "urgency": urgency,
        "sent_at": datetime.datetime.now().isoformat(),
        "accept_url": accept_url,
        "reject_url": reject_url,
        "html": html_content,
        "smtp_sent": smtp_res["sent"],
        "smtp_status": smtp_res["reason"],
        "response": None  # "ACCEPTED", "DECLINED", or None
    }

    emails = _load_emails()
    emails.insert(0, email_entry)
    _save_emails(emails)

    return email_entry

def contact_donor(donor: dict, request: dict, base_url: str = "http://127.0.0.1:5000") -> dict:
    """Dispatches both a simulated voice call ('Phone call going') and an emergency email to the donor."""
    hospital_name = request.get("hospital_name", "Local Hospital")
    hospital_address = request.get("address", "Hospital Address")
    blood_group = request.get("blood_group", "O+")
    units = request.get("units_required", 1)
    urgency = request.get("urgency", "Emergency")
    required_by = request.get("required_by", "Immediately")
    reason = request.get("reason", "Emergency patient requirement")
    request_id = request.get("request_id", "")
    distance_km = donor.get("distance_km", 0.0)

    # 1. Trigger simulated call ("Phone call going")
    call_res = trigger_automated_call(
        donor=donor,
        hospital_name=hospital_name,
        blood_group=blood_group,
        units=units,
        request_id=request_id,
        base_url=base_url
    )

    # 2. Trigger real email via the configured sender
    email_res = send_emergency_email(
        donor=donor,
        hospital_name=hospital_name,
        hospital_address=hospital_address,
        distance_km=distance_km,
        blood_group=blood_group,
        units=units,
        urgency=urgency,
        required_by=required_by,
        reason=reason,
        request_id=request_id,
        base_url=base_url
    )

    return {
        "donor_id": donor.get("donor_id"),
        "call_id": call_res.get("call_id"),
        "email_id": email_res.get("email_id"),
        "dispatched_at": datetime.datetime.now().isoformat()
    }

def get_dispatched_emails(request_id: Optional[str] = None) -> List[dict]:
    emails = _load_emails()
    if request_id:
        return [e for e in emails if e.get("request_id") == request_id]
    return emails

def update_email_response(request_id: str, donor_id: str, action: str):
    emails = _load_emails()
    for e in emails:
        if e.get("request_id") == request_id and e.get("donor_id") == donor_id:
            e["response"] = "ACCEPTED" if action.lower() == "accept" else "DECLINED"
            e["responded_at"] = datetime.datetime.now().isoformat()
    _save_emails(emails)
