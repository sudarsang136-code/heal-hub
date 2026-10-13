# Heal Hub - Emergency Blood Donor Alert System

Flask app that lets hospitals raise emergency blood requests, finds the nearest eligible donors by blood group and distance, and contacts them in priority order (P1 -> P2 -> P3) by email and a simulated automated call. Donor phone/email are stored encrypted; donations are verified and credited after hospital confirmation.

## Features
- Hospital emergency request with donor matching (blood group, eligibility, availability, distance)
- Tiered escalation: P1 -> P2 -> P3 with accept / decline / no-response handling
- Encrypted donor PII (Fernet) with masked display
- Donor login (ID + DOB), cooldown/eligibility checks, donation records and credits
- Document verification for donation proof
- Admin console: donor CRUD, request monitor, close requests

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # then fill in the values
set -a; source .env; set +a                          # Windows: set each variable manually
python app.py                                        # http://127.0.0.1:5000
```
Sample donors are seeded automatically on first run. No Twilio account is needed (calls are simulated). Real emails are sent only if `SMTP_SENDER` and `APP_PASSWORD` are set; otherwise they are logged locally.

## Configuration
See `.env.example`. `ADMIN_ID` and `ADMIN_PASSWORD` must be set to use the admin console. If `HEALHUB_ENCRYPTION_KEY` is unset, a local dev key is generated in `data/secret.key` (git-ignored).

## Tests
```bash
ADMIN_ID=test ADMIN_PASSWORD=test python -m unittest test_system test_e2e_workflow
```

## Project layout
`app.py` routes - `database.py` JSON storage - `matching_engine.py` donor ranking - `notification_service.py` email - `twilio_service.py` simulated calls - `verification_service.py` document checks - `encryption.py` - `templates/` + `static/` frontend - `docs/` design notes

## Security notes
Secrets live in environment variables only. `data/*.json` and `uploads/` hold personal data and are git-ignored. Do not commit real donor information.
