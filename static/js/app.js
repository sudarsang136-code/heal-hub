// Heal Hub Blood Donation Module - Unified Frontend Controller

let activeRequestId = null;
let currentDonorSession = null;
let isAdminAuthenticated = false;
let pollTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initHospitalPresets();
  initBloodRequestForm();
  initHospitalAcceptedFeed();
  initDonorRegistration();
  initDonorLoginForm();
  initAdminControl();
  initAdminAddDonorModal();
  initDonationCompletionModal();
  
  // Initial data loads
  loadHospitalAcceptedDonors(true);
  checkAdminStatus();

  // Setup auto refresh every 3 seconds for immediate donor acceptance visibility
  pollTimer = setInterval(() => {
    loadHospitalAcceptedDonors(false);
    if (isAdminAuthenticated) {
      if (activeRequestId) {
        refreshActiveRequest(activeRequestId);
      }
      loadHospitalRequests(false);
      loadTwilioLogs(false);
      loadEmailInbox(false);
    }
  }, 3000);
});

// ======================= Navigation Tabs =======================
function initTabs() {
  const tabBtns = document.querySelectorAll(".nav-tabs .tab-btn");
  const tabPanels = document.querySelectorAll(".main-content > .tab-panel");

  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");
      
      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanels.forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const activePanel = document.getElementById(targetTab);
      if (activePanel) {
        activePanel.classList.add("active");
      }

      // Refresh corresponding data
      if (targetTab === "tab-hospital") {
        loadHospitalAcceptedDonors(true);
      } else if (targetTab === "tab-admin") {
        checkAdminStatus();
      }
    });
  });
}

// Sub-tab toggling for Donors (Register vs Login)
window.switchDonorSubTab = function(subTabId) {
  document.querySelectorAll(".donor-subtab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".donor-subtab-panel").forEach(p => p.style.display = "none");

  const activeBtn = document.getElementById(`btn-${subTabId}`);
  const activePanel = document.getElementById(subTabId);
  if (activeBtn) activeBtn.classList.add("active");
  if (activePanel) activePanel.style.display = "block";
};

// Sub-tab toggling for Admin
window.switchAdminSubTab = function(panelId) {
  document.querySelectorAll(".admin-subtab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".admin-subtab-content").forEach(p => p.style.display = "none");

  // Mark correct button as active
  document.querySelectorAll(".admin-subtab-btn").forEach(b => {
    if (b.getAttribute("onclick")?.includes(panelId)) b.classList.add("active");
  });

  const panel = document.getElementById(panelId);
  if (panel) panel.style.display = "block";

  if (panelId === "admin-panel-donors") {
    loadDonorsDirectory();
  } else if (panelId === "admin-panel-history") {
    loadHospitalRequests();
  } else if (panelId === "admin-panel-monitor") {
    if (activeRequestId) refreshActiveRequest(activeRequestId);
  } else if (panelId === "admin-panel-dispatch") {
    renderDispatchVisualizer();
    loadTwilioLogs(true);
    loadEmailInbox(true);
  }
};

// ======================= Hospital Presets =======================
const HOSPITAL_PRESETS = [
  {
    name: "Bangalore Central Emergency Hospital",
    id: "HOSP-BLR-01",
    address: "Residency Road, Ashok Nagar, Bengaluru",
    lat: 12.9716,
    lon: 77.5946,
    contact_person: "Dr. Arvind Rao",
    contact_phone: "+91 80 2299 1100"
  },
  {
    name: "Apollo Emergency & Trauma Care",
    id: "HOSP-APO-02",
    address: "Bannerghatta Main Road, J.P. Nagar, Bengaluru",
    lat: 12.8980,
    lon: 77.5990,
    contact_person: "Dr. Sunita Sharma",
    contact_phone: "+91 80 2630 2000"
  },
  {
    name: "St. Jude Super Specialty Hospital",
    id: "HOSP-STJ-03",
    address: "Old Airport Road, Kodihalli, Bengaluru",
    lat: 12.9600,
    lon: 77.6500,
    contact_person: "Dr. Matthew Paul",
    contact_phone: "+91 80 4015 3333"
  }
];

function initHospitalPresets() {
  const container = document.getElementById("hospital-presets-bar");
  if (!container) return;

  container.innerHTML = `<span style="font-size: 0.8rem; color: var(--text-secondary); margin-right: 4px;">⚡ Quick Presets:</span>`;
  HOSPITAL_PRESETS.forEach(p => {
    const pill = document.createElement("span");
    pill.className = "preset-pill";
    pill.textContent = p.name.split(" ")[0] + " Hospital";
    pill.title = `Auto-fill details for ${p.name}`;
    pill.onclick = () => {
      document.getElementById("req-hospital-name").value = p.name;
      document.getElementById("req-hospital-id").value = p.id;
      document.getElementById("req-address").value = p.address;
      document.getElementById("req-lat").value = p.lat;
      document.getElementById("req-lon").value = p.lon;
      document.getElementById("req-contact-name").value = p.contact_person;
      document.getElementById("req-contact-phone").value = p.contact_phone;
    };
    container.appendChild(pill);
  });
}

// ======================= Hospital Blood Request Form =======================
function initBloodRequestForm() {
  const form = document.getElementById("blood-request-form");
  if (!form) return;

  const now = new Date();
  now.setHours(now.getHours() + 2);
  const reqByInput = document.getElementById("req-required-by");
  if (reqByInput) {
    reqByInput.value = now.toISOString().slice(0, 16);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = document.getElementById("btn-submit-request");
    submitBtn.disabled = true;
    submitBtn.innerHTML = `⏳ Verifying & Contacting Donors...`;

    const payload = {
      hospital_name: document.getElementById("req-hospital-name").value,
      hospital_id: document.getElementById("req-hospital-id").value,
      address: document.getElementById("req-address").value,
      latitude: parseFloat(document.getElementById("req-lat").value || 12.9716),
      longitude: parseFloat(document.getElementById("req-lon").value || 77.5946),
      blood_group: form.querySelector('input[name="blood_group"]:checked')?.value || "B+",
      units_required: parseInt(document.getElementById("req-units").value || 1),
      urgency: form.querySelector('input[name="urgency"]:checked')?.value || "Emergency",
      required_by: document.getElementById("req-required-by").value,
      reason: document.getElementById("req-reason").value,
      contact_person: document.getElementById("req-contact-name").value,
      contact_phone: document.getElementById("req-contact-phone").value,
      authorized: document.getElementById("req-authorized").checked
    };

    try {
      const res = await fetch("/api/hospital/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      submitBtn.disabled = false;
      submitBtn.innerHTML = `🚨 Submit Emergency Blood Request`;

      if (data.success) {
        activeRequestId = data.request.request_id;
        loadHospitalAcceptedDonors(true);
        if (data.status === "NO_DONORS") {
          alert("⚠️ Alert: There is no blood donor available right now for this requirement.");
        } else {
          alert(`✅ Emergency Alert Dispatched!\n${data.message}`);
        }
      } else {
        alert("Error: " + (data.error || "Failed to submit request"));
      }
    } catch (err) {
      console.error(err);
      submitBtn.disabled = false;
      submitBtn.innerHTML = `🚨 Submit Emergency Blood Request`;
      alert("Network error submitting request");
    }
  });
}

// ======================= Hospital Accepted Donors Feed =======================
function initHospitalAcceptedFeed() {
  loadHospitalAcceptedDonors(true);
}

window.loadHospitalAcceptedDonors = async function(showFeedback = false) {
  const container = document.getElementById("hospital-accepted-donors-container");
  if (!container) return;

  try {
    const res = await fetch("/api/hospital/active-accepted");
    const data = await res.json();
    if (!data.success || !data.has_active || !data.request) {
      container.innerHTML = `
        <div style="text-align: center; color: var(--text-muted); padding: 3rem 1rem;">
          <div style="font-size: 2.5rem; margin-bottom: 0.5rem; opacity: 0.5;">🩸</div>
          <p>No active emergency request yet.</p>
          <p style="font-size: 0.8rem;">Submit an emergency blood request on the left. When a donor accepts from their email, their Donor ID will be displayed here immediately.</p>
        </div>
      `;
      return;
    }

    const req = data.request;
    activeRequestId = req.request_id;
    const confirmed = data.confirmed_donors || [];

    let statusBadge = `<span class="badge badge-warning" style="animation: pulseBeacon 1.5s infinite;">📡 CONTACTING DONORS</span>`;
    if (req.status === "CONFIRMED") {
      statusBadge = `<span class="badge badge-success">✅ REQUIREMENT MET (${confirmed.length}/${req.units_required} Units)</span>`;
    } else if (req.status === "CLOSED") {
      statusBadge = `<span class="badge badge-gray">🏁 CLOSED / COMPLETED</span>`;
    } else if (req.status === "NO_DONORS") {
      statusBadge = `<span class="badge badge-emergency">❌ NO DONORS AVAILABLE</span>`;
    }

    let donorsCardsHtml = "";
    if (confirmed.length === 0) {
      donorsCardsHtml = `
        <div style="background: rgba(15, 23, 42, 0.6); border: 1px dashed rgba(239,68,68,0.3); border-radius: 8px; padding: 2rem 1rem; text-align: center;">
          <div style="font-size: 2rem; margin-bottom: 0.5rem; animation: pulseBeacon 2s infinite;">⏳</div>
          <div style="font-weight: 700; color: #f8fafc; font-size: 0.95rem;">Awaiting Donor Confirmation</div>
          <p style="font-size: 0.8rem; color: var(--text-secondary); margin: 6px 0 0 0;">
            Dispatched alerts to eligible donors. As soon as a donor clicks <strong>"YES, I AM AVAILABLE"</strong> in their email, their <strong>Donor ID</strong> will appear here instantly.
          </p>
        </div>
      `;
    } else {
      donorsCardsHtml = confirmed.map(c => `
        <div class="card" style="background: #111827; border: 1px solid rgba(16, 185, 129, 0.5); padding: 1.25rem; margin-bottom: 1rem; border-radius: 10px; box-shadow: 0 4px 15px rgba(16, 185, 129, 0.15);">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px;">
            <div>
              <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">Confirmed Donor ID</div>
              <div style="display: flex; align-items: center; gap: 8px; margin: 4px 0;">
                <span style="font-family: var(--font-mono); font-size: 1.35rem; font-weight: 800; color: #38bdf8; background: #0b0f19; padding: 4px 12px; border-radius: 6px; border: 1px solid rgba(56, 189, 248, 0.4);">
                  ${c.donor_id}
                </span>
                <span class="badge badge-emergency" style="font-size: 0.85rem;">${c.blood_group || req.blood_group}</span>
              </div>
              <div style="font-size: 0.8rem; color: #34d399; font-weight: 600; margin-top: 6px;">
                ✅ Available & Ready for Donation
              </div>
              <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 2px;">
                Confirmed at: ${c.confirmed_at ? new Date(c.confirmed_at).toLocaleTimeString() : 'Just now'} | Status: <strong>${c.status || 'EN_ROUTE'}</strong>
              </div>
            </div>
            <div>
              <button class="btn btn-success" onclick="openCompleteDonationModal('${c.donor_id}', '${req.request_id}', '${req.hospital_name}')">
                ✅ Donor Arrived & Donated
              </button>
            </div>
          </div>
        </div>
      `).join("");
    }

    // Show Close Request button only if request is not already closed
    const showClose = req.status !== "CLOSED";
    const closeBtn = showClose
      ? `<button class="btn btn-outline" style="border-color: rgba(239,68,68,0.5); color: #fca5a5; font-size: 0.8rem; padding: 6px 14px;" onclick="hospitalCloseRequest('${req.request_id}')">
           🏁 Close Request
         </button>`
      : `<span class="badge badge-gray">🏁 CLOSED</span>`;

    container.innerHTML = `
      <!-- Active Request Info Header -->
      <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid var(--border-color); border-radius: 8px; padding: 1rem; margin-bottom: 1.25rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; flex-wrap: wrap; gap: 8px;">
          <div>
            <span style="font-size: 0.75rem; color: var(--text-secondary);">ACTIVE REQUEST:</span>
            <strong style="color: #38bdf8; font-family: var(--font-mono); margin-left: 4px;">${req.request_id}</strong>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">${statusBadge} ${closeBtn}</div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; font-size: 0.85rem;">
          <div><span style="color: var(--text-secondary);">Hospital:</span> <strong>${req.hospital_name}</strong></div>
          <div><span style="color: var(--text-secondary);">Need:</span> <strong style="color: var(--accent-red);">${req.blood_group} (${req.units_required} Units)</strong></div>
          <div><span style="color: var(--text-secondary);">Urgency:</span> <strong>${req.urgency}</strong></div>
          <div><span style="color: var(--text-secondary);">Confirmed Donors:</span> <strong style="color: #34d399;">${confirmed.length} of ${req.units_required}</strong></div>
        </div>
      </div>

      <!-- Accepted Donors List -->
      <div style="margin-bottom: 0.5rem;">
        <div style="font-size: 0.9rem; font-weight: 700; color: #f8fafc; margin-bottom: 0.75rem; display: flex; justify-content: space-between; align-items: center;">
          <span>🎯 Matched Donor IDs (${confirmed.length} Accepted)</span>
          <span style="font-size: 0.75rem; color: var(--text-muted);">Privacy protected (Only Donor ID shared)</span>
        </div>
        ${donorsCardsHtml}
      </div>
    `;

  } catch (err) {
    console.error("Error loading accepted donors:", err);
  }
};

window.hospitalCloseRequest = async function(reqId) {
  if (!reqId) return;
  if (!confirm(`Are you sure you want to mark Emergency Request ${reqId} as CLOSED?`)) {
    return;
  }
  try {
    const res = await fetch(`/api/hospital/request/${reqId}/close`, {
      method: "POST"
    });
    const data = await res.json();
    if (data.success) {
      alert(`✅ Emergency Request ${reqId} is now marked as CLOSED.`);
      loadHospitalAcceptedDonors(true);
      if (isAdminAuthenticated) {
        loadHospitalRequests();
        if (activeRequestId === reqId) {
          refreshActiveRequest(reqId);
        }
      }
    } else {
      alert("Error closing request: " + (data.error || "Unknown error"));
    }
  } catch (err) {
    alert("Network error while closing request");
  }
};

// ======================= Admin Authentication & Control =======================
function initAdminControl() {
  const loginForm = document.getElementById("admin-login-form");
  if (!loginForm) return;

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const adminId = document.getElementById("admin-id-input").value.trim();
    const password = document.getElementById("admin-pass-input").value.trim();
    const errDiv = document.getElementById("admin-login-error");

    try {
      const res = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ admin_id: adminId, password: password })
      });
      const data = await res.json();
      if (data.success) {
        isAdminAuthenticated = true;
        showAdminDashboard();
      } else {
        errDiv.textContent = data.error || "Invalid Admin ID or Password";
        errDiv.style.display = "block";
      }
    } catch (err) {
      errDiv.textContent = "Network error logging in as admin";
      errDiv.style.display = "block";
    }
  });
}

async function checkAdminStatus() {
  try {
    const res = await fetch("/api/admin/status");
    const data = await res.json();
    if (data.success && data.authenticated) {
      isAdminAuthenticated = true;
      showAdminDashboard();
    } else {
      isAdminAuthenticated = false;
      showAdminLogin();
    }
  } catch (err) {
    isAdminAuthenticated = false;
    showAdminLogin();
  }
}

function showAdminLogin() {
  const loginCard = document.getElementById("admin-login-card");
  const dashView = document.getElementById("admin-dashboard-view");
  if (loginCard) loginCard.style.display = "block";
  if (dashView) dashView.style.display = "none";
}

function showAdminDashboard() {
  const loginCard = document.getElementById("admin-login-card");
  const dashView = document.getElementById("admin-dashboard-view");
  if (loginCard) loginCard.style.display = "none";
  if (dashView) dashView.style.display = "block";

  // Load all admin modules
  loadDonorsDirectory();
  loadHospitalRequests();
  loadTwilioLogs(true);
  loadEmailInbox(true);
  renderDispatchVisualizer();
}

window.adminLogout = async function() {
  try {
    await fetch("/api/admin/logout", { method: "POST" });
    isAdminAuthenticated = false;
    showAdminLogin();
  } catch (e) {
    showAdminLogin();
  }
};

// ======================= Admin Module 1: Donors Directory =======================
window.loadDonorsDirectory = async function() {
  const tableBody = document.getElementById("donors-directory-body");
  if (!tableBody) return;

  try {
    const res = await fetch("/api/donors/all");
    const data = await res.json();
    if (data.success && data.donors) {
      if (data.donors.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">No donors registered yet. Click "Add New Donor" to register one.</td></tr>`;
        return;
      }

      tableBody.innerHTML = data.donors.map(d => {
        let availBadge = "";
        if (d.computed_availability) {
          availBadge = `<span class="badge badge-success">Available</span>`;
        } else {
          availBadge = `<span class="badge badge-warning" title="${d.eligibility_reason}">Cooldown (${d.cooldown_days_remaining}d)</span>`;
        }

        const safeName = (d.name || "").replace(/'/g, "\\'");

        return `
          <tr>
            <td><strong style="color: #38bdf8; font-family: monospace;">${d.donor_id}</strong></td>
            <td><strong>${d.name}</strong></td>
            <td><span class="badge badge-emergency">${d.blood_group}</span></td>
            <td>${(d.gender || 'male').toUpperCase()}</td>
            <td>${d.phone_masked}</td>
            <td>${d.city || 'Bangalore'}</td>
            <td>${d.recent_donation_date || '<span style="color: var(--text-muted);">None</span>'}</td>
            <td>${availBadge}</td>
            <td>
              <button class="btn btn-sm btn-outline" style="border-color: rgba(239,68,68,0.5); color: #f87171; font-size: 0.75rem; padding: 4px 8px;" onclick="adminDeleteDonor('${d.donor_id}', '${safeName}')">
                🗑️ Delete
              </button>
            </td>
          </tr>
        `;
      }).join("");
    }
  } catch (err) {
    console.error("Error loading donors directory:", err);
  }
};

window.adminDeleteDonor = async function(donorId, donorName) {
  if (!donorId) return;
  if (!confirm(`Are you sure you want to permanently delete donor ${donorId} (${donorName}) from the database?`)) {
    return;
  }
  try {
    const res = await fetch(`/api/admin/donor/${donorId}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (data.success) {
      alert(`✅ Donor ${donorId} (${donorName}) was deleted successfully.`);
      loadDonorsDirectory();
    } else {
      alert("Error deleting donor: " + (data.error || "Unknown error"));
    }
  } catch (err) {
    alert("Network error while deleting donor");
  }
};

window.openAdminAddDonorModal = function() {
  const modal = document.getElementById("admin-add-donor-modal");
  if (modal) modal.classList.add("show");
};

window.closeAdminAddDonorModal = function() {
  const modal = document.getElementById("admin-add-donor-modal");
  if (modal) modal.classList.remove("show");
};

function initAdminAddDonorModal() {
  const form = document.getElementById("admin-add-donor-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("btn-admin-submit-donor");
    const errDiv = document.getElementById("admin-add-donor-error");
    if (errDiv) errDiv.style.display = "none";
    if (btn) {
      btn.disabled = true;
      btn.innerText = "⏳ Saving Donor & Encrypting...";
    }

    const payload = {
      name: document.getElementById("admin-donor-name").value.trim(),
      blood_group: document.getElementById("admin-donor-bg").value.trim(),
      dob: document.getElementById("admin-donor-dob").value.trim(),
      gender: document.getElementById("admin-donor-gender").value.trim(),
      phone: document.getElementById("admin-donor-phone").value.trim(),
      email: document.getElementById("admin-donor-email").value.trim(),
      city: document.getElementById("admin-donor-city").value.trim(),
      weight: parseFloat(document.getElementById("admin-donor-weight").value) || 68.0,
      latitude: parseFloat(document.getElementById("admin-donor-lat").value) || 12.9716,
      longitude: parseFloat(document.getElementById("admin-donor-lon").value) || 77.5946,
      recent_donation_date: document.getElementById("admin-donor-recent-date").value.trim() || null,
      manual_availability: document.getElementById("admin-donor-avail").value === "true"
    };

    try {
      const res = await fetch("/api/admin/donor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (btn) {
        btn.disabled = false;
        btn.innerText = "🩸 Create Donor & Save Encrypted Record";
      }

      if (data.success) {
        alert(`🎉 Donor Created Successfully!\nDonor ID: ${data.donor_id}\nBlood Group: ${payload.blood_group}\nName: ${payload.name}`);
        form.reset();
        closeAdminAddDonorModal();
        loadDonorsDirectory();
      } else {
        if (errDiv) {
          errDiv.textContent = data.error || "Failed to create donor";
          errDiv.style.display = "block";
        } else {
          alert("Error: " + data.error);
        }
      }
    } catch (err) {
      if (btn) {
        btn.disabled = false;
        btn.innerText = "🩸 Create Donor & Save Encrypted Record";
      }
      if (errDiv) {
        errDiv.textContent = "Network error while creating donor";
        errDiv.style.display = "block";
      } else {
        alert("Network error while creating donor");
      }
    }
  });
}

// ======================= Admin Module 2: Requests History =======================
window.loadHospitalRequests = async function() {
  const tableBody = document.getElementById("requests-history-body");
  if (!tableBody) return;

  try {
    const res = await fetch("/api/hospital/requests");
    const data = await res.json();
    if (data.success && data.requests) {
      if (data.requests.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No requests recorded yet.</td></tr>`;
        return;
      }

      tableBody.innerHTML = data.requests.map(r => {
        let badge = `<span class="badge badge-gray">${r.status}</span>`;
        if (r.status === "CONFIRMED") badge = `<span class="badge badge-success">CONFIRMED</span>`;
        if (r.status === "CONTACTING") badge = `<span class="badge badge-warning">CONTACTING</span>`;
        if (r.status === "NO_DONORS") badge = `<span class="badge badge-emergency">NO DONORS</span>`;
        if (r.status === "CLOSED") badge = `<span class="badge badge-gray">CLOSED</span>`;

        return `
          <tr style="cursor: pointer;" onclick="viewRequest('${r.request_id}')">
            <td><strong style="color: #38bdf8; font-family: monospace;">${r.request_id}</strong></td>
            <td><strong>${r.hospital_name}</strong></td>
            <td><span class="badge badge-emergency">${r.blood_group}</span></td>
            <td>${r.units_required}</td>
            <td>${r.urgency}</td>
            <td>${badge}</td>
            <td>
              <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                <button class="btn btn-sm btn-outline" onclick="event.stopPropagation(); viewRequest('${r.request_id}')">
                  View Tracker
                </button>
                ${r.status !== 'CLOSED' ? `
                  <button class="btn btn-sm btn-outline" style="border-color: rgba(239,68,68,0.5); color: #f87171;" onclick="event.stopPropagation(); adminCloseRequest('${r.request_id}')">
                    🏁 Close
                  </button>
                ` : ''}
              </div>
            </td>
          </tr>
        `;
      }).join("");

      if (!activeRequestId && data.requests.length > 0) {
        renderActiveRequest(data.requests[0]);
      }
    }
  } catch (err) {
    console.error("Error loading requests:", err);
  }
};

window.adminCloseRequest = async function(reqId) {
  if (!reqId) return;
  if (!confirm(`Are you sure you want to mark Emergency Request ${reqId} as CLOSED?`)) {
    return;
  }
  try {
    const res = await fetch(`/api/admin/request/${reqId}/close`, {
      method: "POST"
    });
    const data = await res.json();
    if (data.success) {
      alert(`✅ Emergency Request ${reqId} was closed by Admin.`);
      loadHospitalRequests();
      if (activeRequestId === reqId) {
        refreshActiveRequest(reqId);
      }
      loadHospitalAcceptedDonors(true);
    } else {
      alert("Error closing request: " + (data.error || "Unknown error"));
    }
  } catch (err) {
    alert("Network error while closing request");
  }
};

window.viewRequest = async function(reqId) {
  try {
    const res = await fetch(`/api/hospital/request/${reqId}`);
    const data = await res.json();
    if (data.success) {
      activeRequestId = reqId;
      renderActiveRequest(data.request);
      renderDispatchVisualizer(data.request);
      switchAdminSubTab('admin-panel-monitor');
      document.getElementById("active-request-tracker")?.scrollIntoView({ behavior: 'smooth' });
    }
  } catch (e) {}
};

// ======================= Admin Module 3: Live Monitor (Escalation Engine Only) =======================
function renderActiveRequest(req) {
  const container = document.getElementById("active-request-tracker");
  if (!container) return;

  if (!req) {
    container.innerHTML = `
      <div style="text-align: center; color: var(--text-muted); padding: 3rem 1rem;">
        <div style="font-size: 3rem; margin-bottom: 0.5rem; opacity: 0.4;">🩸</div>
        <p>No active emergency request selected.</p>
        <p style="font-size: 0.8rem;">Select a request from the Requests History tab.</p>
      </div>
    `;
    return;
  }

  activeRequestId = req.request_id;

  let statusBadge = "";
  if (req.status === "CONFIRMED") {
    statusBadge = `<span class="badge badge-success">✅ REQUIREMENT MET (${req.confirmed_donors?.length || 0}/${req.units_required} Units)</span>`;
  } else if (req.status === "CLOSED") {
    statusBadge = `<span class="badge badge-gray">🏁 CLOSED</span>`;
  } else if (req.status === "NO_DONORS") {
    statusBadge = `<span class="badge badge-emergency">❌ NO DONORS AVAILABLE</span>`;
  } else {
    statusBadge = `<span class="badge badge-warning" style="animation: pulseBeacon 1.5s infinite;">📡 CONTACTING DONORS</span>`;
  }

  const contactedList = req.contacted_donors || [];
  const contactedHtml = contactedList.map(c => `
    <span class="donor-pill" title="Dispatched: ${c.dispatched_at || 'N/A'} | Distance: ${c.distance_km} km | ETA: ~${c.eta_minutes} mins">
      ${c.donor_id} (${c.distance_km}km • ~${c.eta_minutes}m)
    </span>
  `).join("");

  container.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 0.75rem; flex-wrap: wrap; gap: 8px;">
      <div>
        <div style="font-size: 1.15rem; font-weight: 700; color: #f8fafc;">
          Emergency Request: <span style="color: #38bdf8; font-family: monospace;">${req.request_id}</span>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 2px;">
          ${req.hospital_name} | Urgency: <strong style="color: #ef4444;">${req.urgency}</strong> | Destination: ${req.address || 'Bangalore'}
        </div>
      </div>
      <div>${statusBadge}</div>
    </div>

    <!-- Live Escalation Metrics Grid -->
    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 1.25rem; background: rgba(15, 23, 42, 0.4); padding: 12px; border-radius: 6px; font-size: 0.85rem;">
      <div><span style="color: var(--text-secondary);">Blood Needed:</span> <strong style="color: var(--accent-red);">${req.blood_group}</strong></div>
      <div><span style="color: var(--text-secondary);">Units:</span> <strong>${req.units_required} Unit(s)</strong></div>
      <div><span style="color: var(--text-secondary);">Eligible Pool:</span> <strong>${req.total_eligible_available || req.ranked_donors_count || 0} Donors</strong></div>
      <div><span style="color: var(--text-secondary);">Contacted:</span> <strong>${contactedList.length} Donors</strong></div>
      <div><span style="color: var(--text-secondary);">Current Batch:</span> <strong style="color: #38bdf8;">Batch #${req.current_batch || 1}</strong></div>
      <div><span style="color: var(--text-secondary);">Required By:</span> <strong>${req.required_by}</strong></div>
    </div>

    <!-- Escalation Batch Tracking Monitor -->
    <div style="margin-bottom: 1.25rem; background: rgba(30, 41, 59, 0.35); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 1rem;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
        <div style="font-size: 0.85rem; font-weight: 700; color: #f8fafc;">
          ⚡ Escalation Batch Tracker: Dispatched Donors (${contactedList.length})
        </div>
        <span class="badge badge-info">AUTOMATED DISPATCH ENGINE</span>
      </div>
      <div style="display: flex; flex-wrap: wrap; gap: 8px;">
        ${contactedHtml || '<span style="color: var(--text-muted); font-size: 0.8rem; font-style: italic;">No donors contacted in this batch yet.</span>'}
      </div>
      <div style="margin-top: 0.75rem; font-size: 0.75rem; color: var(--text-muted);">
        ℹ️ <em>Note: Confirmed Donor IDs and Donation Completion actions are routed directly to the Hospital Portal for clinical reception. Escalations and dispatch sequencing are monitored here.</em>
      </div>
    </div>

    <!-- Escalation Control Action -->
    <div style="display: flex; gap: 0.5rem; justify-content: flex-end; border-top: 1px solid rgba(255, 255, 255, 0.05); padding-top: 1rem;">
      ${req.status !== "CLOSED" ? `
        <button class="btn btn-sm btn-primary" onclick="triggerManualEscalation('${req.request_id}')">
          ⚡ Escalate to Next Batch
        </button>
      ` : `
        <span style="color: var(--text-muted); font-size: 0.85rem;">Request Completed and Closed.</span>
      `}
    </div>
  `;
}

async function refreshActiveRequest(reqId) {
  try {
    const res = await fetch(`/api/hospital/request/${reqId}`);
    const data = await res.json();
    if (data.success) {
      renderActiveRequest(data.request);
    }
  } catch (e) {}
}

window.triggerManualEscalation = async function(reqId) {
  try {
    const res = await fetch("/api/dispatch/escalate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: reqId })
    });
    const data = await res.json();
    if (data.success) {
      renderActiveRequest(data.request);
      loadHospitalAcceptedDonors(true);
      loadTwilioLogs(true);
      loadEmailInbox(true);
      alert("Escalated: Contacting next batch of eligible donors.");
    }
  } catch (e) {
    alert("Escalation error");
  }
};

// ======================= Admin Module 4: Dispatch Visualizer & Outbox =======================
function renderDispatchVisualizer(req) {
  const container = document.getElementById("dispatch-visualizer-content");
  if (!container) return;

  const r = req || (activeRequestId ? { request_id: activeRequestId } : null);
  if (!r || !r.request_id) {
    container.innerHTML = `<p style="color: var(--text-muted); text-align: center; padding: 2rem;">No active dispatch to visualize. Submit or select an emergency blood request.</p>`;
    return;
  }

  fetch(`/api/hospital/request/${r.request_id}`)
    .then(res => res.json())
    .then(data => {
      if (!data.success) return;
      const curReq = data.request;

      container.innerHTML = `
        <div style="background: rgba(15, 23, 42, 0.6); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-color); margin-bottom: 1.5rem;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <h4 style="margin: 0;">Heal Hub Emergency Dispatch Engine: <span style="color: var(--accent-red);">${curReq.blood_group}</span> (${curReq.units_required} Units)</h4>
            <span class="badge ${curReq.status === 'CONFIRMED' ? 'badge-success' : 'badge-emergency'}">${curReq.status}</span>
          </div>
          <p style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.4rem;">
            Hospital: <strong>${curReq.hospital_name}</strong> | Urgency: <strong>${curReq.urgency}</strong> | Cooldown Rules: <strong>Male 90d / Female 120d</strong>
          </p>
        </div>

        <div class="pipeline-track">
          <div class="pipeline-step done">
            <div class="step-circle">✓</div>
            <div class="step-label">Hospital Request</div>
          </div>
          <div class="pipeline-step done">
            <div class="step-circle">✓</div>
            <div class="step-label">Haversine Match</div>
          </div>
          <div class="pipeline-step ${curReq.contacted_donors?.length > 0 ? 'done' : 'active'}">
            <div class="step-circle">${curReq.contacted_donors?.length > 0 ? '✓' : '3'}</div>
            <div class="step-label">Phone & Email Alert</div>
          </div>
          <div class="pipeline-step ${curReq.confirmed_donors?.length >= curReq.units_required ? 'done' : 'active'}">
            <div class="step-circle">${curReq.confirmed_donors?.length >= curReq.units_required ? '✓' : '4'}</div>
            <div class="step-label">Donor Acceptance</div>
          </div>
          <div class="pipeline-step ${curReq.status === 'CLOSED' ? 'done' : ''}">
            <div class="step-circle">${curReq.status === 'CLOSED' ? '✓' : '5'}</div>
            <div class="step-label">Donation Closed</div>
          </div>
        </div>

        <div class="card" style="background: rgba(15, 23, 42, 0.4); margin-top: 1.5rem;">
          <h4 style="font-size: 0.95rem; margin-bottom: 0.75rem;">📐 Proximity & Haversine Distance Logic</h4>
          <div style="font-size: 0.8rem; font-family: monospace; background: #0b0f19; padding: 12px; border-radius: 6px; border: 1px solid #1e293b; color: #38bdf8; line-height: 1.6;">
            d = 2R · arcsin(√(sin²(Δφ/2) + cos(φ₁)·cos(φ₂)·sin²(Δλ/2)))<br>
            R = 6371.0 km | Origin: (${curReq.latitude}, ${curReq.longitude})<br>
            Filter Rules: (Gender == 'male' && Days >= 90) || (Gender == 'female' && Days >= 120)
          </div>
        </div>
      `;
    });
}

// Simulated Phone Calls Outbox
async function loadTwilioLogs(force = false) {
  const tableBody = document.getElementById("twilio-logs-body");
  if (!tableBody) return;

  try {
    const res = await fetch("/api/twilio/logs");
    const data = await res.json();
    if (data.success && data.logs) {
      if (data.logs.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No automated calls logged yet.</td></tr>`;
        return;
      }

      tableBody.innerHTML = data.logs.map(log => `
        <tr>
          <td><strong style="color: #38bdf8; font-family: monospace; font-size: 0.75rem;">${log.call_id.substring(0, 16)}...</strong></td>
          <td><strong style="color: #f87171;">${log.donor_id}</strong></td>
          <td>${log.phone_masked}</td>
          <td>${log.hospital_name}</td>
          <td><span class="badge badge-emergency">${log.blood_group}</span></td>
          <td><span class="badge badge-info">${log.status}</span></td>
          <td>
            <button class="btn btn-sm btn-outline" onclick="playTwilioCallAudio('${encodeURIComponent(log.script)}', '${log.request_id}', '${log.donor_id}')">
              🔊 Listen / Test DTMF
            </button>
          </td>
        </tr>
      `).join("");
    }
  } catch (err) {}
}

window.playTwilioCallAudio = function(encodedScript, reqId, donorId) {
  const script = decodeURIComponent(encodedScript);
  
  const modal = document.getElementById("twilio-simulator-modal");
  if (modal) {
    document.getElementById("sim-call-script").textContent = script;
    document.getElementById("sim-call-req-id").value = reqId || "";
    document.getElementById("sim-call-donor-id").value = donorId || "";
    modal.classList.add("show");
  }

  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(script);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
  }
};

window.closeTwilioSimulator = function() {
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
  }
  document.getElementById("twilio-simulator-modal")?.classList.remove("show");
};

window.simulateKeypress = async function(digit) {
  const reqId = document.getElementById("sim-call-req-id").value;
  const donorId = document.getElementById("sim-call-donor-id").value;
  const statusElem = document.getElementById("sim-call-status");

  statusElem.innerHTML = `<span style="color: var(--accent-teal);">Transmitting simulated DTMF keypress '${digit}'...</span>`;

  try {
    const formData = new URLSearchParams();
    formData.append("Digits", digit);

    const res = await fetch(`/api/twilio/voice-response?request_id=${reqId}&donor_id=${donorId}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formData.toString()
    });
    await res.text();

    if (digit === '1') {
      statusElem.innerHTML = `<span style="color: var(--accent-green); font-weight: bold;">✅ Confirmed Available via DTMF Key 1! Matched Donor ID transmitted to hospital.</span>`;
    } else {
      statusElem.innerHTML = `<span style="color: var(--text-secondary); font-weight: bold;">❌ Declined via DTMF Key 2. Request escalated to next donor.</span>`;
    }

    if (reqId) refreshActiveRequest(reqId);
    loadHospitalAcceptedDonors(true);
    loadHospitalRequests();
    loadTwilioLogs(true);
    loadEmailInbox(true);
  } catch (err) {
    statusElem.innerHTML = `<span style="color: var(--accent-red);">Error processing DTMF response.</span>`;
  }
};

// Dispatched Emails Inbox
async function loadEmailInbox(force = false) {
  const container = document.getElementById("email-inbox-cards");
  if (!container) return;

  try {
    const res = await fetch("/api/emails/inbox");
    const data = await res.json();
    if (data.success && data.emails) {
      if (data.emails.length === 0) {
        container.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 2rem;">No dispatched emails found. Submit an emergency blood request to trigger alerts!</div>`;
        return;
      }

      container.innerHTML = data.emails.map(e => `
        <div class="card" style="background: #1e293b; margin-bottom: 1.5rem; border: 1px solid #334155;">
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 0.75rem; margin-bottom: 1rem;">
            <div>
              <div style="font-size: 0.8rem; color: var(--text-secondary);">
                From: <code>${e.sender || 'Heal Hub'}</code> &rarr; To: <strong style="color: #38bdf8;">${e.recipient_name}</strong> (${e.recipient_email_masked})
              </div>
              <div style="font-size: 0.75rem; color: var(--text-muted);">Donor ID: <strong style="color: var(--accent-red); font-family: monospace;">${e.donor_id}</strong> | Sent at: ${new Date(e.sent_at).toLocaleTimeString()}</div>
            </div>
            <div>
              ${e.response === 'ACCEPTED' ? '<span class="badge badge-success">✅ Responded: AVAILABLE</span>' :
                e.response === 'DECLINED' ? '<span class="badge badge-gray">❌ Responded: NOT AVAILABLE</span>' :
                '<span class="badge badge-warning">⏳ Awaiting Response</span>'}
            </div>
          </div>

          <div style="background: #0f172a; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
            <h4 style="color: #ef4444; margin-top: 0;">🩸 Emergency Requirement: ${e.blood_group}</h4>
            <p style="font-size: 0.85rem; color: #cbd5e1; margin: 4px 0;">
              Hospital: <strong>${e.hospital_name}</strong> (~${e.distance_km} km away)<br>
              Urgency: <strong>${e.urgency}</strong> | Request ID: <code>${e.request_id}</code><br>
              <span style="font-size: 0.75rem; color: var(--text-muted);">SMTP Dispatch Status: ${e.smtp_status || 'Delivered'}</span>
            </p>
          </div>

          <div style="display: flex; gap: 10px; justify-content: flex-end;">
            <button class="btn btn-sm btn-success" onclick="respondFromInbox('${e.request_id}', '${e.donor_id}', 'accept')">
              ✅ Click "Available"
            </button>
            <button class="btn btn-sm btn-outline" onclick="respondFromInbox('${e.request_id}', '${e.donor_id}', 'reject')">
              ❌ Click "Not Available"
            </button>
          </div>
        </div>
      `).join("");
    }
  } catch (err) {}
}

window.respondFromInbox = async function(reqId, donorId, action) {
  try {
    const res = await fetch(`/api/dispatch/respond?request_id=${reqId}&donor_id=${donorId}&action=${action}`, {
      headers: { "Accept": "application/json" }
    });
    const data = await res.json();
    if (data.success) {
      loadHospitalAcceptedDonors(true);
      if (reqId) refreshActiveRequest(reqId);
      loadHospitalRequests();
      loadEmailInbox(true);
      loadTwilioLogs(true);
      alert(action === 'accept' ? 'Confirmed Available! Donor ID sent to hospital.' : 'Marked Not Available. Auto-escalating...');
    }
  } catch (e) {
    alert("Response error");
  }
};

// ======================= Complete Donation Modal =======================
function initDonationCompletionModal() {
  const modal = document.getElementById("complete-donation-modal");
  const form = document.getElementById("complete-donation-form");
  if (!modal || !form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const donorId = document.getElementById("modal-donor-id").value.trim();
    const reqId = document.getElementById("modal-request-id").value.trim();
    const hospName = document.getElementById("modal-hosp-name").value.trim();

    try {
      const res = await fetch("/api/hospital/confirm-donation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          donor_id: donorId,
          request_id: reqId,
          hospital_name: hospName
        })
      });
      const data = await res.json();
      if (data.success) {
        alert(`✅ Donation Completed Successfully!\n${data.message}`);
        closeCompleteDonationModal();
        loadHospitalAcceptedDonors(true);
        if (reqId) refreshActiveRequest(reqId);
        loadHospitalRequests();
        loadDonorsDirectory();
      } else {
        alert("Error: " + data.error);
      }
    } catch (err) {
      alert("Failed to confirm donation");
    }
  });
}

window.openCompleteDonationModal = function(donorId, reqId, hospName) {
  const modal = document.getElementById("complete-donation-modal");
  if (!modal) return;
  document.getElementById("modal-donor-id").value = donorId || "";
  document.getElementById("modal-request-id").value = reqId || "";
  document.getElementById("modal-hosp-name").value = hospName || "";
  modal.classList.add("show");
};

window.closeCompleteDonationModal = function() {
  document.getElementById("complete-donation-modal")?.classList.remove("show");
};

// ======================= Donor Registration & Portal =======================
function initDonorRegistration() {
  const form = document.getElementById("donor-reg-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("btn-register-donor");
    btn.disabled = true;
    btn.innerHTML = `⏳ Encrypting PII & Saving...`;

    const formData = new FormData(form);

    try {
      const res = await fetch("/api/donors/register", {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      btn.disabled = false;
      btn.innerHTML = `🩸 Complete Registration & Generate Donor ID`;

      if (data.success) {
        showRegistrationSuccess(data.donor);
        form.reset();
        loadDonorsDirectory();
      } else {
        alert("Registration failed: " + (data.error || "Unknown error"));
      }
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = `🩸 Complete Registration & Generate Donor ID`;
      alert("Network error during registration");
    }
  });
}

function showRegistrationSuccess(donor) {
  const card = document.getElementById("donor-reg-success-card");
  if (!card) return;

  document.getElementById("success-donor-id").textContent = donor.donor_id;
  document.getElementById("success-donor-name").textContent = donor.name;
  document.getElementById("success-donor-bg").textContent = donor.blood_group;
  document.getElementById("success-donor-avail").textContent = donor.availability;
  
  if (donor.document_report) {
    document.getElementById("success-ai-report").innerHTML = `
      <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 6px; padding: 10px; margin-top: 10px; font-size: 0.8rem; color: #86efac;">
        <strong>🤖 AI Document Verification:</strong> ${donor.document_report.verification_status} (Confidence: ${(donor.document_report.ai_confidence_score * 100).toFixed(0)}%)<br>
        <span style="font-size: 0.75rem; color: var(--text-secondary);">Issuer: ${donor.document_report.issuer} | Seal Verified: Yes</span>
      </div>
    `;
  } else {
    document.getElementById("success-ai-report").innerHTML = "";
  }

  card.style.display = "block";
  card.scrollIntoView({ behavior: "smooth" });
}

function initDonorLoginForm() {
  const form = document.getElementById("donor-login-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const donorId = document.getElementById("login-donor-id").value.trim();
    const dob = document.getElementById("login-donor-dob").value.trim();

    try {
      const res = await fetch("/api/donors/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ donor_id: donorId, dob: dob })
      });
      const data = await res.json();
      if (data.success) {
        currentDonorSession = data.donor;
        renderDonorDashboard(data.donor);
      } else {
        alert("Authentication failed: " + data.error);
      }
    } catch (err) {
      alert("Login error");
    }
  });
}

function renderDonorDashboard(donor) {
  const loginCard = document.getElementById("donor-login-card");
  const dashboardCard = document.getElementById("donor-dashboard-card");
  if (loginCard) loginCard.style.display = "none";
  if (dashboardCard) dashboardCard.style.display = "block";

  document.getElementById("dash-donor-id").textContent = donor.donor_id;
  document.getElementById("dash-name").textContent = donor.name;
  document.getElementById("dash-bg").textContent = donor.blood_group;
  document.getElementById("dash-gender").textContent = (donor.gender || "Male").toUpperCase();
  document.getElementById("dash-phone").textContent = donor.phone || "Not set";
  document.getElementById("dash-email").textContent = donor.email || "Not set";
  document.getElementById("dash-weight").textContent = (donor.weight || 60) + " kg";
  document.getElementById("dash-recent-date").textContent = donor.recent_donation_date || "None";

  const cooldownDays = donor.cooldown_days_remaining || 0;
  const cooldownNumElem = document.getElementById("dash-cooldown-num");
  const cooldownMsgElem = document.getElementById("dash-cooldown-msg");

  if (donor.computed_availability) {
    cooldownNumElem.textContent = "0";
    cooldownNumElem.style.color = "var(--accent-green)";
    cooldownMsgElem.textContent = "✅ Fully Eligible & Available to donate!";
  } else {
    cooldownNumElem.textContent = cooldownDays;
    cooldownNumElem.style.color = "var(--accent-yellow)";
    cooldownMsgElem.textContent = `⏳ Cooldown in progress: ${cooldownDays} days remaining (${donor.gender === 'female' ? '120' : '90'} days recovery required)`;
  }

  const availToggle = document.getElementById("dash-toggle-avail");
  if (availToggle) {
    availToggle.checked = donor.manual_availability !== false;
  }

  const historyBody = document.getElementById("dash-history-body");
  if (historyBody) {
    const history = donor.donation_history || [];
    if (history.length === 0) {
      historyBody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No donations completed yet.</td></tr>`;
    } else {
      historyBody.innerHTML = history.map(h => `
        <tr>
          <td><strong style="color: #38bdf8;">${h.record_id}</strong></td>
          <td>${h.hospital_name}</td>
          <td>${h.donated_at ? new Date(h.donated_at).toLocaleDateString() : 'Recent'}</td>
          <td>${h.units} Unit(s) (${h.cooldown_applied_days}d Cooldown)</td>
        </tr>
      `).join("");
    }
  }
}

window.donorLogout = function() {
  currentDonorSession = null;
  document.getElementById("donor-login-card").style.display = "block";
  document.getElementById("donor-dashboard-card").style.display = "none";
};

window.toggleDonorAvailability = async function() {
  if (!currentDonorSession) return;
  const isAvailable = document.getElementById("dash-toggle-avail").checked;

  try {
    const res = await fetch("/api/donors/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        donor_id: currentDonorSession.donor_id,
        dob: currentDonorSession.dob,
        manual_availability: isAvailable
      })
    });
    const data = await res.json();
    if (data.success) {
      currentDonorSession = data.donor;
      renderDonorDashboard(data.donor);
      loadDonorsDirectory();
    }
  } catch (e) {
    alert("Error updating availability");
  }
};

window.deleteDonorAccount = async function() {
  if (!currentDonorSession) return;
  if (!confirm(`Are you sure you want to permanently delete Donor ID ${currentDonorSession.donor_id}?`)) {
    return;
  }

  try {
    const res = await fetch("/api/donors/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        donor_id: currentDonorSession.donor_id,
        dob: currentDonorSession.dob
      })
    });
    const data = await res.json();
    if (data.success) {
      alert(data.message);
      donorLogout();
      loadDonorsDirectory();
    } else {
      alert("Deletion failed: " + data.error);
    }
  } catch (e) {
    alert("Error deleting account");
  }
};
