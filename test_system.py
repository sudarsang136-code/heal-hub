import os
import os
import datetime
import unittest
from encryption import encrypt_text, decrypt_text, mask_phone, mask_email
from database import (
    save_donor,
    get_donor_by_id,
    authenticate_donor,
    delete_donor_by_id,
    get_blood_group_path,
    compute_donor_eligibility,
    VALID_BLOOD_GROUPS,
    record_donation_completion
)
from matching_engine import calculate_haversine_distance, find_matching_donors

class TestHealHubBloodDonation(unittest.TestCase):

    def test_01_encryption(self):
        secret_phone = "+91 98451 12345"
        secret_email = "donor@example.com"
        
        cipher_phone = encrypt_text(secret_phone)
        cipher_email = encrypt_text(secret_email)
        
        self.assertNotEqual(secret_phone, cipher_phone)
        self.assertEqual(decrypt_text(cipher_phone), secret_phone)
        self.assertEqual(decrypt_text(cipher_email), secret_email)
        
        masked_p = mask_phone(secret_phone)
        masked_e = mask_email(secret_email)
        self.assertIn("*", masked_p)
        self.assertIn("*", masked_e)

    def test_02_haversine_distance(self):
        # Bangalore Center (12.9716, 77.5946) to Indiranagar (12.9740, 77.6010) ~ 0.74 km
        d = calculate_haversine_distance(12.9716, 77.5946, 12.9740, 77.6010)
        self.assertGreater(d, 0.5)
        self.assertLess(d, 2.0)

    def test_03_gender_cooldown_eligibility(self):
        today = datetime.date.today()

        # Male: 90 days
        male_recent_80d = (today - datetime.timedelta(days=80)).isoformat()
        is_elig_m, rem_m, msg_m = compute_donor_eligibility("male", male_recent_80d)
        self.assertFalse(is_elig_m)
        self.assertEqual(rem_m, 10)

        male_recent_95d = (today - datetime.timedelta(days=95)).isoformat()
        is_elig_m2, rem_m2, _ = compute_donor_eligibility("male", male_recent_95d)
        self.assertTrue(is_elig_m2)
        self.assertEqual(rem_m2, 0)

        # Female: 120 days
        female_recent_100d = (today - datetime.timedelta(days=100)).isoformat()
        is_elig_f, rem_f, msg_f = compute_donor_eligibility("female", female_recent_100d)
        self.assertFalse(is_elig_f)
        self.assertEqual(rem_f, 20)

        female_recent_125d = (today - datetime.timedelta(days=125)).isoformat()
        is_elig_f2, rem_f2, _ = compute_donor_eligibility("female", female_recent_125d)
        self.assertTrue(is_elig_f2)
        self.assertEqual(rem_f2, 0)

    def test_04_per_blood_group_databases(self):
        for bg in VALID_BLOOD_GROUPS:
            path = get_blood_group_path(bg)
            self.assertTrue(os.path.basename(path).startswith("donors_"))

    def test_05_donor_registration_auth_and_deletion(self):
        test_donor = {
            "name": "Test Candidate",
            "dob": "1995-10-10",
            "phone": "+91 99999 88888",
            "email": "candidate@test.com",
            "blood_group": "AB+",
            "age": 29,
            "gender": "male",
            "weight": 70.0,
            "donated_before": False,
            "recent_donation_date": None,
            "latitude": 12.9716,
            "longitude": 77.5946,
            "city": "Bangalore"
        }
        saved = save_donor(test_donor)
        donor_id = saved["donor_id"]
        self.assertTrue(donor_id.startswith("DONOR-ABPOS-"))

        # Auth with correct DOB
        auth_success = authenticate_donor(donor_id, "1995-10-10")
        self.assertIsNotNone(auth_success)
        self.assertEqual(auth_success["phone"], "+91 99999 88888")

        # Auth with wrong DOB
        auth_fail = authenticate_donor(donor_id, "1990-01-01")
        self.assertIsNone(auth_fail)

        # Delete donor
        del_res = delete_donor_by_id(donor_id)
        self.assertTrue(del_res)
        self.assertIsNone(get_donor_by_id(donor_id))

    def test_06_admin_and_hospital_endpoints(self):
        from app import app
        client = app.test_client()

        # 1. Admin login
        login_res = client.post("/api/admin/login", json={"admin_id": os.environ["ADMIN_ID"], "password": os.environ["ADMIN_PASSWORD"]})
        self.assertEqual(login_res.status_code, 200)
        self.assertTrue(login_res.get_json()["success"])

        # 2. Admin adds donor
        add_res = client.post("/api/admin/donor", json={
            "name": "Admin Registered Donor",
            "blood_group": "O-",
            "dob": "1992-04-12",
            "gender": "female",
            "phone": "+91 91234 56789",
            "email": "admin_donor@test.org",
            "city": "Bangalore"
        })
        self.assertEqual(add_res.status_code, 200)
        created_donor_id = add_res.get_json()["donor_id"]
        self.assertTrue(created_donor_id.startswith("DONOR-ONEG-"))

        # Verify donor in database
        fetched = get_donor_by_id(created_donor_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], "Admin Registered Donor")

        # 3. Admin deletes donor
        del_res = client.delete(f"/api/admin/donor/{created_donor_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json()["success"])
        self.assertIsNone(get_donor_by_id(created_donor_id))

        # 4. Create emergency request and test hospital close
        req_res = client.post("/api/hospital/request", json={
            "hospital_name": "Test General Hospital",
            "blood_group": "B+",
            "units_required": 1,
            "latitude": 12.9716,
            "longitude": 77.5946
        })
        self.assertEqual(req_res.status_code, 200)
        req_id = req_res.get_json()["request"]["request_id"]

        # Hospital close
        hosp_close = client.post(f"/api/hospital/request/{req_id}/close")
        self.assertEqual(hosp_close.status_code, 200)
        self.assertTrue(hosp_close.get_json()["success"])

        # 5. Create another request and test admin close
        req_res2 = client.post("/api/hospital/request", json={
            "hospital_name": "Test Emergency Care",
            "blood_group": "A+",
            "units_required": 1,
            "latitude": 12.9716,
            "longitude": 77.5946
        })
        self.assertEqual(req_res2.status_code, 200)
        req_id2 = req_res2.get_json()["request"]["request_id"]

        admin_close = client.post(f"/api/admin/request/{req_id2}/close")
        self.assertEqual(admin_close.status_code, 200)
        self.assertTrue(admin_close.get_json()["success"])

if __name__ == "__main__":
    unittest.main()
