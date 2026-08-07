(function () {
  if (window.__wfInteractiveInit) return;
  window.__wfInteractiveInit = true;

  var doc = document;

  function ensureToastRoot() {
    var root = doc.getElementById("wf-toast-root");
    if (root) return root;
    root = doc.createElement("div");
    root.id = "wf-toast-root";
    root.style.position = "fixed";
    root.style.right = "16px";
    root.style.bottom = "16px";
    root.style.zIndex = "99999";
    root.style.display = "flex";
    root.style.flexDirection = "column";
    root.style.gap = "8px";
    doc.body.appendChild(root);
    return root;
  }

  function toast(message, tone) {
    var root = ensureToastRoot();
    var el = doc.createElement("div");
    el.textContent = message;
    el.style.padding = "10px 12px";
    el.style.borderRadius = "10px";
    el.style.color = "#fff";
    el.style.fontSize = "12px";
    el.style.fontWeight = "600";
    el.style.boxShadow = "0 10px 24px rgba(0,0,0,.18)";
    el.style.background = tone === "warn" ? "#D97706" : tone === "error" ? "#DC2626" : "#1D4ED8";
    root.appendChild(el);
    setTimeout(function () {
      el.style.opacity = "0";
      el.style.transform = "translateY(8px)";
      el.style.transition = "all .2s ease";
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 220);
    }, 2200);
  }
  window.wfToast = toast;

  function makeClickable(el, cb) {
    if (!el || el.dataset.wfBound === "1") return;
    el.dataset.wfBound = "1";
    el.style.cursor = "pointer";
    el.tabIndex = el.tabIndex >= 0 ? el.tabIndex : 0;
    el.addEventListener("click", cb);
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        cb(e);
      }
    });
  }

  function setupAvatarMenus() {
    var menu = doc.getElementById("wf-user-menu");
    if (!menu) {
      menu = doc.createElement("div");
      menu.id = "wf-user-menu";
      menu.style.position = "fixed";
      menu.style.minWidth = "170px";
      menu.style.background = "#fff";
      menu.style.border = "1px solid #E5E7EB";
      menu.style.borderRadius = "10px";
      menu.style.boxShadow = "0 14px 24px rgba(0,0,0,.14)";
      menu.style.padding = "8px";
      menu.style.zIndex = "99998";
      menu.style.display = "none";
      menu.innerHTML = '<button class="wf-menu-item" data-action="profile" style="display:block;width:100%;text-align:left;padding:8px 10px;border:none;background:transparent;border-radius:6px;font-size:12px;cursor:pointer;">Profile</button>' +
        '<button class="wf-menu-item" data-action="switch-role" style="display:block;width:100%;text-align:left;padding:8px 10px;border:none;background:transparent;border-radius:6px;font-size:12px;cursor:pointer;">Switch Role</button>' +
        '<button class="wf-menu-item" data-action="sign-out" style="display:block;width:100%;text-align:left;padding:8px 10px;border:none;background:transparent;border-radius:6px;font-size:12px;cursor:pointer;color:#B91C1C;">Sign Out</button>';
      doc.body.appendChild(menu);
      menu.addEventListener("click", function (e) {
        var t = e.target.closest(".wf-menu-item");
        if (!t) return;
        var action = t.dataset.action;
        menu.style.display = "none";
        if (action === "sign-out") {
          toast("Signed out — redirecting to login", "warn");
          setTimeout(function () { location.href = "wireframe-SCR-001-login.html"; }, 900);
        } else if (action === "profile") {
          location.href = "wireframe-SCR-012-profile.html";
        } else if (action === "switch-role") {
          location.href = "wireframe-SCR-013-switch-role.html";
        } else {
          toast(t.textContent + " clicked");
        }
      });
    }

    var avatars = doc.querySelectorAll(".avatar");
    avatars.forEach(function (avatar) {
      makeClickable(avatar, function (e) {
        e.stopPropagation();
        var rect = avatar.getBoundingClientRect();
        menu.style.top = rect.bottom + 8 + "px";
        menu.style.left = Math.max(8, rect.right - 170) + "px";
        menu.style.display = menu.style.display === "none" ? "block" : "none";
      });
    });

    doc.addEventListener("click", function (e) {
      if (!menu.contains(e.target)) menu.style.display = "none";
    });
  }

  function setupBellPanel() {
    var panel = doc.getElementById("wf-bell-panel");
    if (!panel) {
      panel = doc.createElement("div");
      panel.id = "wf-bell-panel";
      panel.style.position = "fixed";
      panel.style.width = "280px";
      panel.style.maxHeight = "300px";
      panel.style.overflow = "auto";
      panel.style.background = "#fff";
      panel.style.border = "1px solid #E5E7EB";
      panel.style.borderRadius = "12px";
      panel.style.boxShadow = "0 14px 28px rgba(0,0,0,.16)";
      panel.style.padding = "10px";
      panel.style.display = "none";
      panel.style.zIndex = "99998";
      panel.innerHTML = '<div style="font-size:12px;font-weight:700;margin-bottom:8px;">Notifications</div>' +
        '<div class="wf-notif" style="font-size:12px;padding:8px;border-radius:8px;background:#EFF6FF;margin-bottom:6px;cursor:pointer;">New discharge task assigned</div>' +
        '<div class="wf-notif" style="font-size:12px;padding:8px;border-radius:8px;background:#FEF2F2;margin-bottom:6px;cursor:pointer;">Medication conflict needs review</div>' +
        '<div class="wf-notif" style="font-size:12px;padding:8px;border-radius:8px;background:#F0FDF4;cursor:pointer;">Patient message received</div>';
      doc.body.appendChild(panel);
      panel.querySelectorAll(".wf-notif").forEach(function (n) {
        makeClickable(n, function () {
          toast("Opening: " + n.textContent);
          panel.style.display = "none";
        });
      });
    }

    doc.querySelectorAll(".bell-btn").forEach(function (btn) {
      makeClickable(btn, function (e) {
        e.stopPropagation();
        var rect = btn.getBoundingClientRect();
        panel.style.top = rect.bottom + 8 + "px";
        panel.style.left = Math.max(8, rect.right - 280) + "px";
        panel.style.display = panel.style.display === "none" ? "block" : "none";
        var badge = btn.querySelector(".badge");
        if (badge) badge.textContent = "0";
      });
    });

    doc.addEventListener("click", function (e) {
      if (!panel.contains(e.target)) panel.style.display = "none";
    });
  }

  function setupSearchOverlay() {
    var overlay = doc.getElementById("wf-search-overlay");
    if (!overlay) {
      overlay = doc.createElement("div");
      overlay.id = "wf-search-overlay";
      overlay.style.position = "fixed";
      overlay.style.inset = "0";
      overlay.style.background = "rgba(17,24,39,.45)";
      overlay.style.display = "none";
      overlay.style.alignItems = "flex-start";
      overlay.style.justifyContent = "center";
      overlay.style.paddingTop = "10vh";
      overlay.style.zIndex = "99997";
      overlay.innerHTML = '<div style="width:min(680px,92vw);background:#fff;border-radius:12px;padding:14px;box-shadow:0 22px 48px rgba(0,0,0,.25);">' +
        '<div style="display:flex;gap:8px;align-items:center;">' +
        '<input id="wf-search-input" type="text" placeholder="Search patients, MRN, tasks..." style="flex:1;padding:10px 12px;border:1px solid #D1D5DB;border-radius:8px;font-size:14px;" />' +
        '<button id="wf-search-close" style="padding:10px 12px;border:1px solid #D1D5DB;border-radius:8px;background:#fff;cursor:pointer;">Close</button>' +
        '</div>' +
        '<div id="wf-search-results" style="margin-top:10px;display:grid;gap:8px;">' +
        '<a href="wireframe-SCR-004-patient-detail.html?patient=smith" data-name="Smith, John" style="padding:10px;border:1px solid #E5E7EB;border-radius:8px;text-decoration:none;color:#111827;display:block;">Smith, John · 4-West · Discharging</a>' +
        '<a href="wireframe-SCR-004-patient-detail.html?patient=patel" data-name="Patel, Rita" style="padding:10px;border:1px solid #E5E7EB;border-radius:8px;text-decoration:none;color:#111827;display:block;">Patel, Rita · 3-North · Admitted</a>' +
        '<a href="wireframe-SCR-004-patient-detail.html?patient=nguyen" data-name="Nguyen, Lee" style="padding:10px;border:1px solid #E5E7EB;border-radius:8px;text-decoration:none;color:#111827;display:block;">Nguyen, Lee · ICU · Transferred</a>' +
        '<a href="wireframe-SCR-004-patient-detail.html?patient=garcia" data-name="Garcia, Maria" style="padding:10px;border:1px solid #E5E7EB;border-radius:8px;text-decoration:none;color:#111827;display:block;">Garcia, Maria · 3-North · Admitted</a>' +
        '</div>' +
      '</div>';
      doc.body.appendChild(overlay);

      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) overlay.style.display = "none";
      });

      overlay.querySelector("#wf-search-close").addEventListener("click", function () {
        overlay.style.display = "none";
      });

      overlay.querySelector("#wf-search-input").addEventListener("input", function (e) {
        var q = e.target.value.trim().toLowerCase();
        overlay.querySelectorAll("#wf-search-results a").forEach(function (a) {
          a.style.display = q === "" || a.textContent.toLowerCase().includes(q) ? "block" : "none";
        });
      });
    }

    var searchTargets = doc.querySelectorAll(".topbar-search, .search, .filter-input");
    searchTargets.forEach(function (el) {
      makeClickable(el, function () {
        overlay.style.display = "flex";
        var input = overlay.querySelector("#wf-search-input");
        input.value = "";
        input.focus();
      });
    });
  }

  function setupPatientListFilters() {
    var table = doc.querySelector("table tbody");
    if (!table || !doc.querySelector(".status-chip") || !doc.querySelector(".mrn-masked")) return;
    var filterSelects = doc.querySelectorAll(".filter-select");
    if (filterSelects.length < 2) return;

    var unitSelect = filterSelects[0];
    var statusSelect = filterSelects[1];
    var rows = Array.from(table.querySelectorAll("tr"));
    var paginationInfo = doc.querySelector(".pagination-info");
    var pageButtons = doc.querySelectorAll(".page-btn");
    var rowsSelect = doc.querySelector(".rows-select select");

    var currentPage = 1;
    var pageSize = rowsSelect ? parseInt(rowsSelect.value || "25", 10) : rows.length;

    function matchesFilters(row) {
      var unitValue = (unitSelect.value || "").toLowerCase();
      var statusValue = (statusSelect.value || "").toLowerCase();
      var unitCell = row.children[2] ? row.children[2].textContent.toLowerCase() : "";
      var statusChip = row.querySelector(".status-chip");
      var statusText = statusChip ? statusChip.textContent.toLowerCase() : "";
      var unitMatch = unitValue.includes("all") || unitCell.includes(unitValue);
      var statusMatch = statusValue.includes("all") || statusText.includes(statusValue);
      return unitMatch && statusMatch;
    }

    function applyFilters() {
      var filtered = rows.filter(matchesFilters);
      var total = filtered.length;
      var size = rowsSelect ? parseInt(rowsSelect.value || "25", 10) : total || rows.length;
      var pages = Math.max(1, Math.ceil(total / size));
      if (currentPage > pages) currentPage = pages;
      if (currentPage < 1) currentPage = 1;

      rows.forEach(function (row) { row.style.display = "none"; });
      filtered.forEach(function (row, idx) {
        var pageIndex = Math.floor(idx / size) + 1;
        row.dataset.page = pageIndex;
        if (pageIndex === currentPage) row.style.display = "";
      });

      if (paginationInfo) {
        if (total === 0) {
          paginationInfo.textContent = "No matching patients";
        } else {
          var start = (currentPage - 1) * size + 1;
          var end = Math.min(currentPage * size, total);
          paginationInfo.textContent = "Showing " + start + "–" + end + " of " + total + " matching patients";
        }
      }

      pageButtons.forEach(function (btn) {
        btn.classList.remove("active");
        var txt = btn.textContent.trim();
        if (txt === String(currentPage)) btn.classList.add("active");
      });
    }

    unitSelect.addEventListener("change", applyFilters);
    statusSelect.addEventListener("change", applyFilters);
    if (rowsSelect) rowsSelect.addEventListener("change", applyFilters);

    pageButtons.forEach(function (btn) {
      makeClickable(btn, function () {
        var txt = btn.textContent.trim();
        if (txt === "‹ Prev") currentPage -= 1;
        else if (txt === "Next ›") currentPage += 1;
        else if (/^\d+$/.test(txt)) currentPage = parseInt(txt, 10);
        applyFilters();
      });
    });

    applyFilters();
  }

  function setupBedBoardFilters() {
    var bedGrid = doc.querySelector(".bed-grid");
    if (!bedGrid) return;
    var tiles = Array.from(bedGrid.querySelectorAll(".bed-tile"));
    var selects = doc.querySelectorAll(".filter-select");
    if (selects.length < 2) return;

    tiles.forEach(function (tile) {
      tile.dataset.unit = "4-west";
      makeClickable(tile, function () {
        if (!tile.getAttribute("onclick")) {
          tile.classList.toggle("selected");
          tile.style.outline = tile.classList.contains("selected") ? "2px solid #2563EB" : "none";
        }
      });
    });

    function applyFilters() {
      var unit = (selects[0].value || "").toLowerCase();
      var status = (selects[1].value || "").toLowerCase();
      tiles.forEach(function (tile) {
        var unitMatch = unit.includes("all") || tile.dataset.unit === unit;
        var statusMatch = status.includes("all") || tile.classList.contains(status);
        tile.style.display = unitMatch && statusMatch ? "block" : "none";
      });
    }

    selects[0].addEventListener("change", applyFilters);
    selects[1].addEventListener("change", applyFilters);

    var edAlert = doc.querySelector(".ed-alert");
    var assignBtn = doc.getElementById("ed-assign");
    var viewBtn = doc.getElementById("ed-view-available");
    var dismissBtn = doc.getElementById("ed-dismiss");

    if (assignBtn) {
      assignBtn.addEventListener("click", function () {
        tiles.forEach(function (tile) {
          var id = tile.querySelector(".bed-id");
          if (id && id.textContent.trim() === "4W-03") {
            tile.classList.remove("clean");
            tile.classList.add("occupied");
            tile.style.background = "var(--bed-occupied)";
            tile.style.borderColor = "var(--bed-occupied-border)";
            tile.querySelector(".bed-status").textContent = "Occupied";
            tile.querySelector(".bed-status").style.color = "var(--bed-occupied-text)";
            var patientDiv = tile.querySelector(".bed-patient");
            patientDiv.textContent = "Garcia, M.";
            patientDiv.style.color = "var(--color-text-primary)";
            var risk = tile.querySelector(".bed-risk");
            if (!risk) {
              risk = doc.createElement("div");
              risk.className = "bed-risk high";
              tile.appendChild(risk);
            }
            risk.textContent = "0.75 HIGH";
            risk.className = "bed-risk high";
            var dc = tile.querySelector(".bed-dc");
            if (!dc) {
              dc = doc.createElement("div");
              dc.className = "bed-dc";
              tile.appendChild(dc);
            }
            dc.textContent = "DC est: 12h";
            tile.setAttribute("onclick", "location.href='wireframe-SCR-004-patient-detail.html?patient=garcia'");
            tile.setAttribute("title", "Open patient detail");
            tile.style.cursor = "pointer";
          }
        });
        if (edAlert) edAlert.style.display = "none";
        toast("Assigned Garcia, M. to 4W-03");
      });
    }

    if (viewBtn) {
      viewBtn.addEventListener("click", function () {
        selects[1].value = "Clean";
        applyFilters();
        toast("Showing available beds");
      });
    }

    if (dismissBtn) {
      dismissBtn.addEventListener("click", function () {
        if (edAlert) edAlert.style.display = "none";
        toast("Alert dismissed");
      });
    }
  }

  function setupInstructionTabs() {
    var tabBar = doc.querySelector(".tab-bar");
    var list = doc.querySelector(".section-list");
    var title = doc.querySelector(".section-title");
    if (!tabBar || !list || !title) return;

    var contentMap = {
      "Activity": ["Walk 5-10 minutes, 3 times daily", "No lifting over 10 lbs for 2 weeks", "Use incentive spirometer every 2 hours"],
      "Diet": ["Low sodium meals for 2 weeks", "Drink 8 glasses of water daily", "Avoid alcohol during medication course"],
      "Warning Signs": ["Fever above 100.4 F", "Shortness of breath", "Increased redness or swelling"],
      "When to Call": ["Call care team for non-urgent symptoms", "Call emergency for chest pain", "Use portal chat for medication questions"]
    };

    tabBar.querySelectorAll(".tab").forEach(function (tab) {
      makeClickable(tab, function () {
        tabBar.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        var label = tab.textContent.trim();
        var items = contentMap[label] || [];
        title.textContent = "Discharge Instructions - " + label;
        list.innerHTML = items.map(function (item) { return "<li>" + item + "</li>"; }).join("");
      });
    });
  }

  function setupPatientDetailFromQuery() {
    var params = new URLSearchParams(location.search);
    var patient = params.get("patient");
    if (!patient) return;
    var map = {
      "smith": { name: "Smith, John", unit: "4-West", bed: "4W-12", attending: "Dr. Chen", admitted: "2026-07-10", risk: "0.82", riskLabel: "HIGH RISK" },
      "patel": { name: "Patel, Rita", unit: "3-North", bed: "3N-08", attending: "Dr. Lee", admitted: "2026-07-12", risk: "0.45", riskLabel: "MEDIUM RISK" },
      "nguyen": { name: "Nguyen, Lee", unit: "ICU", bed: "ICU-04", attending: "Dr. Patel", admitted: "2026-07-13", risk: "0.18", riskLabel: "LOW RISK" },
      "garcia": { name: "Garcia, Maria", unit: "3-North", bed: "3N-12", attending: "Dr. Chen", admitted: "2026-07-14", risk: "0.75", riskLabel: "HIGH RISK" },
      "jones": { name: "Jones, Michael", unit: "4-West", bed: "4W-05", attending: "Dr. Lee", admitted: "2026-07-11", risk: "0.20", riskLabel: "LOW RISK" }
    };
    var data = map[patient.toLowerCase()] || map["smith"];

    var nameEl = doc.querySelector(".patient-name");
    if (nameEl) {
      var firstChild = nameEl.firstChild;
      if (firstChild && firstChild.nodeType === 3) firstChild.textContent = data.name + " \u00A0";
    }
    var meta = doc.querySelectorAll(".patient-meta strong");
    if (meta.length >= 5) {
      meta[1].textContent = data.unit;
      meta[2].textContent = data.bed;
      meta[3].textContent = data.attending;
      meta[4].textContent = data.admitted;
    }
    var riskBar = doc.querySelector(".risk-bar-fill");
    var riskText = doc.querySelector(".risk-chip-large");
    if (riskBar) riskBar.style.width = Math.round(parseFloat(data.risk) * 100) + "%";
    if (riskText) riskText.textContent = "⚠ " + data.riskLabel;

    var pageHeader = doc.querySelector(".page-header h1");
    if (pageHeader && pageHeader.textContent.indexOf("Medication") >= 0) {
      pageHeader.textContent = "Medication Reconciliation — " + data.name;
    }
    var backBtn = doc.querySelector(".back-btn");
    if (backBtn && backBtn.textContent.indexOf("Patient:") >= 0) {
      backBtn.textContent = "← Patient: " + data.name;
      backBtn.onclick = function () {
        location.href = "wireframe-SCR-004-patient-detail.html?patient=" + patient.toLowerCase();
      };
    }

    var medsTab = doc.querySelector(".tab[onclick*='medication-review']");
    if (medsTab) {
      medsTab.onclick = function () {
        location.href = "wireframe-SCR-005-medication-review.html?patient=" + patient.toLowerCase();
      };
    }

    var footerMedLink = doc.querySelector(".wf-nav-group a[href='wireframe-SCR-005-medication-review.html']");
    if (footerMedLink) {
      footerMedLink.href = "wireframe-SCR-005-medication-review.html?patient=" + patient.toLowerCase();
    }

    var docsTab = doc.getElementById("tab-documents");
    if (docsTab) {
      docsTab.onclick = function () {
        location.href = "wireframe-SCR-006-document-review.html?patient=" + patient.toLowerCase();
      };
    }

    var docReviewBtn = doc.getElementById("doc-review-btn");
    if (docReviewBtn) {
      docReviewBtn.onclick = function () {
        location.href = "wireframe-SCR-006-document-review.html?patient=" + patient.toLowerCase();
      };
    }

    var footerDocLink = doc.querySelector(".wf-nav-panel a[href='wireframe-SCR-006-document-review.html']");
    if (footerDocLink) {
      footerDocLink.href = "wireframe-SCR-006-document-review.html?patient=" + patient.toLowerCase();
    }

    if (params.get("docs") === "approved") {
      var docCard = doc.getElementById("doc-approval-card");
      var docBadge = doc.getElementById("doc-approval-badge");
      var docState = doc.getElementById("doc-approval-state");
      var docTitle = doc.getElementById("doc-approval-title");
      var docMeta = doc.getElementById("doc-approval-meta");
      var docBtn = doc.getElementById("doc-review-btn");
      var pendingBadge = doc.querySelector(".card-header [style*='alert-critical-bg']");
      if (docCard) docCard.style.borderColor = "var(--color-alert-success)";
      if (docBadge) {
        docBadge.style.background = "var(--color-alert-success-bg)";
        docBadge.style.borderColor = "#BBF7D0";
        docBadge.style.color = "var(--color-alert-success)";
      }
      if (docState) docState.textContent = "Approved & Signed";
      if (docTitle) docTitle.textContent = "Discharge Summary — Approved";
      if (docMeta) docMeta.textContent = "Signed by Dr. David Chen · " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      if (docBtn) {
        docBtn.textContent = "View Signed Document →";
        docBtn.disabled = false;
        docBtn.onclick = function () {
          location.href = "wireframe-SCR-006-document-review.html?patient=" + patient.toLowerCase() + "&signed=1";
        };
      }
      var docAgent = doc.querySelector(".agent-row:has(.agent-name):nth-child(2) .agent-status-badge");
      if (docAgent) docAgent.textContent = "Approved";
      if (pendingBadge) pendingBadge.textContent = "0";
      toast("Discharge summary approved");
    }

    if (params.get("medrec") === "complete") {
      var medRow = doc.getElementById("med-rec-row");
      var medDot = doc.getElementById("med-rec-dot");
      var medStatus = doc.getElementById("med-rec-status");
      if (medRow && medDot && medStatus) {
        medDot.className = "dot ok";
        medStatus.textContent = "Complete";
        medStatus.style.color = "var(--color-alert-success)";
      }
      var alertInteraction = doc.getElementById("alert-interaction");
      var alertMissing = doc.getElementById("alert-missing");
      if (alertInteraction) {
        alertInteraction.dataset.resolved = "true";
        alertInteraction.style.opacity = ".5";
        alertInteraction.querySelector(".alert-header").innerHTML = '<span style="font-size:16px">✅</span> Drug Interaction: Warfarin + Aspirin — Resolved';
        alertInteraction.querySelector(".alert-link").textContent = "Resolved ✓";
        alertInteraction.querySelector(".alert-link").style.pointerEvents = "none";
      }
      if (alertMissing) {
        alertMissing.dataset.resolved = "true";
        alertMissing.style.opacity = ".5";
        alertMissing.querySelector(".alert-header").innerHTML = '<span style="font-size:16px">✅</span> Chronic Medication Missing: Metformin — Resolved';
        alertMissing.querySelector(".alert-link").textContent = "Resolved ✓";
        alertMissing.querySelector(".alert-link").style.pointerEvents = "none";
      }
      var badge = doc.querySelector(".card-header [style*='alert-critical-bg']");
      if (badge) badge.textContent = "0";
      toast("Medication reconciliation completed");
    }
  }

  function setupMRNReveals() {
    doc.querySelectorAll(".mrn-masked").forEach(function (host) {
      if (!host.querySelector(".reveal-btn")) {
        var btn = doc.createElement("span");
        btn.className = "reveal-btn";
        btn.style.color = "#2563EB";
        btn.style.cursor = "pointer";
        btn.style.marginLeft = "6px";
        btn.textContent = "👁";
        host.appendChild(btn);
      }
    });

    doc.querySelectorAll(".reveal-btn").forEach(function (btn) {
      makeClickable(btn, function (e) {
        e.stopPropagation();
        e.preventDefault();
        var host = btn.closest(".mrn-masked");
        if (!host) return;
        var textNode = host.childNodes[0];
        var isMasked = textNode && textNode.textContent.indexOf("●") >= 0;
        if (isMasked) {
          textNode.textContent = "MRN-483729 ";
          btn.textContent = "🙈";
          toast("MRN revealed");
        } else {
          textNode.textContent = "●●●●●● ";
          btn.textContent = "👁";
          toast("MRN masked again");
        }
      });
    });
  }

  function setupGenericToggles() {
    doc.querySelectorAll(".tabs .tab, .admin-nav-item").forEach(function (tab) {
      makeClickable(tab, function () {
        var parent = tab.parentElement;
        if (parent) {
          parent.querySelectorAll(".active").forEach(function (activeEl) {
            if (activeEl !== tab) activeEl.classList.remove("active");
          });
        }
        tab.classList.add("active");
      });
    });

    doc.querySelectorAll(".page-btn").forEach(function (btn) {
      makeClickable(btn, function () {
        doc.querySelectorAll(".page-btn").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
      });
    });

    doc.querySelectorAll(".refresh-btn, .pause-btn, .chat-fab, .care-btn, .btn-filter, .btn-export, .reminder-btn, .pdf-btn, .send-btn, .mic-btn, .chat-btn, .appt-btn, .btn-assign, .btn-ghost-small").forEach(function (el) {
      makeClickable(el, function (e) {
        var text = (el.textContent || "Action").replace(/\s+/g, " ").trim();
        if (el.classList.contains("pause-btn")) {
          el.textContent = el.textContent.indexOf("Pause") >= 0 ? "▶ Resume" : "⏸ Pause";
        }
        if (el.classList.contains("reminder-btn")) {
          el.textContent = el.textContent.indexOf("Set") >= 0 ? "✅ Reminder Set" : "⏰ Set Reminder";
        }
        if (el.classList.contains("btn-filter")) {
          e.preventDefault();
        }
        toast(text + " triggered");
      });
    });

    setupMedicationReview();

    doc.querySelectorAll(".btn-action, .btn-review, .btn-generate, .btn-complete, .btn-view").forEach(function (btn) {
      if (btn.dataset.wfBound === "1") return;
      makeClickable(btn, function () {
        var text = (btn.textContent || "Action").replace(/\s+/g, " ").trim();
        toast(text + " action completed");
      });
    });

    doc.querySelectorAll("button").forEach(function (btn) {
      if (btn.dataset.wfBound === "1") return;
      if (btn.classList.contains("btn-add") || btn.closest("#wf-user-modal") || (btn.classList.contains("btn-sm") && btn.closest("table tbody"))) return;
      makeClickable(btn, function () {
        toast((btn.textContent || "Button").replace(/\s+/g, " ").trim() + " clicked");
      });
    });

    doc.querySelectorAll(".lang-sel, select").forEach(function (sel) {
      if (sel.dataset.wfBound === "1") return;
      sel.dataset.wfBound = "1";
      sel.addEventListener("change", function () {
        var label = sel.closest("[class*='filter'], [class*='rows']") ? "Filter" : "Language";
        toast(label + " changed to " + sel.value);
      });
    });

    doc.querySelectorAll(".toggle").forEach(function (toggle) {
      if (toggle.dataset.wfBound === "1") return;
      toggle.dataset.wfBound = "1";
      toggle.style.cursor = "pointer";
      toggle.addEventListener("click", function () {
        toggle.classList.toggle("on");
        var label = toggle.nextElementSibling;
        if (label) {
          label.textContent = toggle.classList.contains("on") ? "Enabled" : "Disabled";
          label.style.color = toggle.classList.contains("on") ? "#2563EB" : "#4B5563";
        }
        toast("Setting " + (toggle.classList.contains("on") ? "enabled" : "disabled"));
      });
    });

    doc.querySelectorAll(".state-chip, .chip").forEach(function (chip) {
      if (chip.dataset.wfBound === "1") return;
      chip.dataset.wfBound = "1";
      chip.style.cursor = "pointer";
      chip.addEventListener("click", function () {
        var group = chip.parentElement;
        if (!group) return;
        group.querySelectorAll(".on, .active").forEach(function (c) {
          c.classList.remove("on");
          c.classList.remove("active");
        });
        chip.classList.add(chip.classList.contains("state-chip") ? "active" : "on");
        toast("State changed: " + chip.textContent.trim());
      });
    });

    setupAdminUserModal();
    setupAuditLogFilters();
    setupAnalyticsDashboard();
  }

  function setupPatientDetailTabs() {
    var tabs = doc.querySelectorAll(".tab[data-tab]");
    var panels = doc.querySelectorAll(".tab-panel");
    if (!tabs.length || !panels.length) return;

    function activateTab(name) {
      tabs.forEach(function (t) {
        if (t.dataset.tab === name) t.classList.add("active");
        else t.classList.remove("active");
      });
      panels.forEach(function (p) {
        if (p.id === "tab-panel-" + name) p.classList.add("active");
        else p.classList.remove("active");
      });
      var chips = doc.querySelectorAll(".meta-panels .chip[data-chip-tab]");
      chips.forEach(function (c) {
        if (c.dataset.chipTab === name) c.classList.add("on");
        else c.classList.remove("on");
      });
    }

    tabs.forEach(function (tab) {
      makeClickable(tab, function () {
        activateTab(tab.dataset.tab);
        toast(tab.textContent.trim() + " tab selected");
      });
    });

    doc.querySelectorAll(".meta-panels .chip[data-chip-tab]").forEach(function (chip) {
      makeClickable(chip, function () {
        var target = chip.dataset.chipTab;
        if (target === "medications") {
          var params = new URLSearchParams(location.search);
          location.href = "wireframe-SCR-005-medication-review.html?patient=" + (params.get("patient") || "smith");
          return;
        }
        if (target === "documents") {
          var params = new URLSearchParams(location.search);
          location.href = "wireframe-SCR-006-document-review.html?patient=" + (params.get("patient") || "smith");
          return;
        }
        activateTab(target);
      });
    });

    doc.querySelectorAll(".task-checkbox").forEach(function (cb) {
      cb.addEventListener("change", function () {
        var item = cb.closest(".task-item");
        if (!item) return;
        if (cb.checked) {
          item.classList.add("done");
          var title = item.querySelector(".task-title")?.textContent || "Task";
          toast(title + " marked complete");
          var completedList = doc.getElementById("completed-tasks");
          if (completedList) completedList.appendChild(item);
        } else {
          item.classList.remove("done");
          var openList = doc.getElementById("open-tasks");
          if (openList) openList.appendChild(item);
        }
      });
    });
  }

  function setupAgentMonitor() {
    var failedTasks = doc.querySelectorAll(".failed-task");
    if (!failedTasks.length) return;

    function openModal(id) {
      var modal = doc.getElementById(id);
      if (modal) modal.classList.add("active");
    }
    function closeModal(id) {
      var modal = doc.getElementById(id);
      if (modal) modal.classList.remove("active");
    }
    function currentTaskId() {
      return doc.body.dataset.activeTaskId;
    }
    function escapeHtml(text) {
      return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    failedTasks.forEach(function (task) {
      var title = task.querySelector(".failed-task-title")?.textContent || "";
      var meta = task.querySelector(".failed-task-meta")?.textContent || "";
      var taskId = task.dataset.taskId || "";
      var attempt = task.dataset.attempt || "";
      var error = task.dataset.error || "";
      var patient = task.dataset.patient || "";

      var viewBtn = task.querySelector(".btn-view-details");
      var retryBtn = task.querySelector(".btn-retry");
      var escalateBtn = task.querySelector(".btn-escalate");

      if (viewBtn) {
        makeClickable(viewBtn, function () {
          doc.body.dataset.activeTaskId = taskId;
          doc.getElementById("detail-task-id").textContent = taskId ? "#" + taskId : "—";
          doc.getElementById("detail-task-agent").textContent = title.split(" — ")[1] || "—";
          doc.getElementById("detail-task-encounter").textContent = (title.match(/Encounter #(\d+)/) || [])[1] || "—";
          doc.getElementById("detail-task-patient").textContent = patient ? patient.charAt(0).toUpperCase() + patient.slice(1) : "—";
          doc.getElementById("detail-task-time").textContent = (meta.match(/Failed at:\s*([\d:]+)/) || [])[1] || "—";
          doc.getElementById("detail-task-attempt").textContent = attempt ? attempt + "/3" : "—";
          doc.getElementById("detail-task-log").innerHTML = error ? "ERROR: " + escapeHtml(error) + "<br/>TRACE: at executeTask (agent-worker.ts:142)<br/>at processFHIR (fhir-client.ts:89)<br/>at async runAgent (orchestrator.ts:56)" : "No log available.";
          openModal("wf-modal-task-details");
        });
      }

      if (retryBtn) {
        makeClickable(retryBtn, function () {
          doc.body.dataset.activeTaskId = taskId;
          doc.getElementById("retry-task-title").textContent = title ? title.split(" — ")[0] : "Task #—";
          openModal("wf-modal-retry");
        });
      }

      if (escalateBtn) {
        makeClickable(escalateBtn, function () {
          doc.body.dataset.activeTaskId = taskId;
          doc.getElementById("escalate-task-title").textContent = title ? title.split(" — ")[0] : "Task #—";
          openModal("wf-modal-escalate");
        });
      }
    });

    var confirmRetry = doc.getElementById("btn-confirm-retry");
    if (confirmRetry) {
      makeClickable(confirmRetry, function () {
        var taskId = currentTaskId();
        closeModal("wf-modal-retry");
        if (taskId) {
          var task = doc.querySelector('.failed-task[data-task-id="' + taskId + '"]');
          if (task) {
            var attemptEl = task.querySelector(".failed-task-meta");
            if (attemptEl) {
              attemptEl.textContent = attemptEl.textContent.replace(/Attempt: \d+\/3/, "Attempt: 0/3 — Queued");
            }
            task.style.opacity = ".6";
            var retryBtn = task.querySelector(".btn-retry");
            if (retryBtn) {
              retryBtn.textContent = "Queued";
              retryBtn.disabled = true;
            }
          }
        }
        toast("Task #" + taskId + " queued for retry");
      });
    }

    var confirmEscalate = doc.getElementById("btn-confirm-escalate");
    if (confirmEscalate) {
      makeClickable(confirmEscalate, function () {
        var taskId = currentTaskId();
        var urgency = doc.getElementById("escalate-urgency")?.value || "P3";
        closeModal("wf-modal-escalate");
        if (taskId) {
          var task = doc.querySelector('.failed-task[data-task-id="' + taskId + '"]');
          if (task) {
            task.style.borderColor = "#DC2626";
            task.style.boxShadow = "0 0 0 2px rgba(220,38,38,.15)";
            var escalateBtn = task.querySelector(".btn-escalate");
            if (escalateBtn) {
              escalateBtn.textContent = "Escalated " + urgency;
              escalateBtn.disabled = true;
            }
          }
        }
        toast("Task #" + taskId + " escalated to on-call (" + urgency + ")");
      });
    }
  }

  function setupDocumentReview() {
    var rejectBtn = doc.getElementById("btn-reject-return");
    var saveBtn = doc.getElementById("btn-save-draft");
    var approveBtn = doc.getElementById("btn-approve-sign");
    var confirmReject = doc.getElementById("btn-confirm-reject");
    var returnPatient = doc.getElementById("btn-return-patient");

    if (!rejectBtn && !saveBtn && !approveBtn) return;

    var params = new URLSearchParams(location.search);
    var patient = params.get("patient") || "smith";
    var patientHref = "wireframe-SCR-004-patient-detail.html?patient=" + patient;
    var isSigned = params.get("signed") === "1";

    var backBtn = doc.querySelector(".back-btn");
    if (backBtn && backBtn.textContent.indexOf("Patient Detail") >= 0) {
      backBtn.onclick = function () { location.href = patientHref; };
    }

    if (rejectBtn) {
      makeClickable(rejectBtn, function () {
        var modal = doc.getElementById("wf-modal-reject");
        if (modal) modal.classList.add("active");
      });
    }

    if (confirmReject) {
      makeClickable(confirmReject, function () {
        var reasonSel = doc.getElementById("reject-reason");
        var reason = reasonSel ? reasonSel.value : "";
        if (!reason) {
          toast("Please select a rejection reason", "warn");
          return;
        }
        var modal = doc.getElementById("wf-modal-reject");
        if (modal) modal.classList.remove("active");
        toast("Document returned to queue: " + reason);
        setTimeout(function () {
          location.href = "wireframe-SCR-008-agent-monitor.html";
        }, 700);
      });
    }

    if (saveBtn) {
      makeClickable(saveBtn, function () {
        var meta = doc.querySelector(".pane-header .meta");
        if (meta) meta.textContent = "Auto-saved " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + " · saved draft";
        toast("Draft saved");
      });
    }

    if (approveBtn) {
      if (isSigned) {
        approveBtn.disabled = true;
        approveBtn.textContent = "Approved ✓";
        var pageAiBadge = doc.querySelector(".page-header .ai-badge");
        if (pageAiBadge) {
          pageAiBadge.style.background = "var(--color-alert-success-bg)";
          pageAiBadge.style.borderColor = "#BBF7D0";
          pageAiBadge.style.color = "var(--color-alert-success)";
          pageAiBadge.innerHTML = "✅ Approved & Signed";
        }
      }
      makeClickable(approveBtn, function () {
        if (approveBtn.disabled) return;
        var ok = window.confirm("Approve and electronically sign this discharge summary?");
        if (!ok) return;
        var approvedModal = doc.getElementById("wf-modal-approved");
        var stamp = doc.getElementById("approved-timestamp");
        if (stamp) stamp.textContent = new Date().toLocaleString();
        if (approvedModal) approvedModal.classList.add("active");
        var aiBadge = doc.querySelector(".page-header .ai-badge");
        if (aiBadge) {
          aiBadge.style.background = "var(--color-alert-success-bg)";
          aiBadge.style.borderColor = "#BBF7D0";
          aiBadge.style.color = "var(--color-alert-success)";
          aiBadge.innerHTML = "✅ Approved & Signed";
        }
        approveBtn.disabled = true;
        approveBtn.textContent = "Approved ✓";
        toast("Discharge summary approved and signed");
      });
    }

    if (returnPatient) {
      makeClickable(returnPatient, function () {
        location.href = patientHref + "&docs=approved";
      });
    }
  }

  function setupMedicationReview() {
    var contactBtn = doc.getElementById("btn-contact-prescriber");
    var acceptBtn = doc.getElementById("btn-accept-monitoring");
    var evidenceBtn = doc.getElementById("btn-view-evidence");
    var flagBtn = doc.getElementById("btn-flag-physician");
    var omissionBtn = doc.getElementById("btn-intentional-omission");
    var generateBtn = doc.getElementById("btn-generate-summary");
    var completeBtn = doc.getElementById("btn-complete-reconciliation");

    if (!contactBtn && !acceptBtn && !evidenceBtn && !flagBtn && !omissionBtn && !generateBtn && !completeBtn) return;

    function openModal(id) {
      var modal = doc.getElementById(id);
      if (modal) modal.classList.add("active");
    }

    function updateAlertCount() {
      var remaining = 0;
      if (doc.getElementById("med-alert-interaction") && !doc.getElementById("med-alert-interaction").dataset.resolved) remaining++;
      if (doc.getElementById("med-alert-missing") && !doc.getElementById("med-alert-missing").dataset.resolved) remaining++;
      var header = doc.querySelector(".alerts-section h2");
      if (header) header.textContent = "Active Alerts (" + remaining + ")";
    }

    if (contactBtn) {
      makeClickable(contactBtn, function () { openModal("wf-modal-contact"); });
    }

    if (evidenceBtn) {
      makeClickable(evidenceBtn, function () { openModal("wf-modal-evidence"); });
    }

    if (acceptBtn) {
      makeClickable(acceptBtn, function () {
        var card = doc.getElementById("med-alert-interaction");
        var title = doc.getElementById("med-alert-interaction-title");
        var body = doc.getElementById("med-alert-interaction-body");
        var actions = doc.getElementById("med-alert-interaction-actions");
        var flag = doc.getElementById("aspirin-flag");
        if (card) {
          card.classList.remove("critical");
          card.classList.add("warning");
          card.dataset.resolved = "true";
          card.style.opacity = ".85";
        }
        if (title) title.innerHTML = '🟡 MAJOR INTERACTION: Warfarin + Aspirin — <span style="color:var(--color-alert-success)">Accepted with Monitoring Plan</span>';
        if (body) body.innerHTML = 'Plan: Monitor INR within 48 hours of discharge. Patient education on bleeding precautions provided.<br/>Drug interaction database confidence: 99.2%';
        if (actions) actions.innerHTML = '<button class="btn-action secondary" disabled>Accepted ✓</button>';
        if (flag) {
          flag.className = "med-flag ok";
          flag.textContent = "✓ OK (monitor)";
        }
        updateAlertCount();
        toast("Interaction accepted with monitoring plan");
      });
    }

    if (flagBtn) {
      makeClickable(flagBtn, function () {
        var card = doc.getElementById("med-alert-missing");
        var title = doc.getElementById("med-alert-missing-title");
        var body = doc.getElementById("med-alert-missing-body");
        var actions = doc.getElementById("med-alert-missing-actions");
        if (card) {
          card.dataset.resolved = "true";
          card.style.opacity = ".85";
        }
        if (title) title.textContent = "🚩 CHRONIC MED MISSING: Metformin 500mg BD — Flagged for Physician Review";
        if (body) body.innerHTML = 'Flagged for Dr. Chen review. Reason: Chronic medication not on Discharge Rx.<br/>Patient has Type 2 Diabetes (ICD-10: E11.9).';
        if (actions) actions.innerHTML = '<button class="btn-action secondary" disabled>Flagged ✓</button>';
        toast("Flagged for physician review");
        updateAlertCount();
      });
    }

    if (omissionBtn) {
      makeClickable(omissionBtn, function () {
        var card = doc.getElementById("med-alert-missing");
        var title = doc.getElementById("med-alert-missing-title");
        var body = doc.getElementById("med-alert-missing-body");
        var actions = doc.getElementById("med-alert-missing-actions");
        var missing = doc.getElementById("metformin-missing");
        if (card) {
          card.dataset.resolved = "true";
          card.style.opacity = ".85";
        }
        if (title) title.textContent = "✅ CHRONIC MED MISSING: Metformin 500mg BD — Intentional Omission";
        if (body) body.innerHTML = 'Documented as intentional omission. Prescriber confirmed: hold Metformin due to acute kidney injury.<br/>Patient has Type 2 Diabetes (ICD-10: E11.9).';
        if (actions) actions.innerHTML = '<button class="btn-action secondary" disabled>Omission Documented ✓</button>';
        if (missing) {
          missing.textContent = "⏸ Intentionally Omitted — documented";
          missing.style.background = "var(--color-grey-100)";
          missing.style.color = "var(--color-grey-700)";
        }
        toast("Marked as intentional omission");
        updateAlertCount();
      });
    }

    if (generateBtn) {
      makeClickable(generateBtn, function () { openModal("wf-modal-summary"); });
    }

    var summaryDownload = doc.querySelector("#wf-modal-summary [data-action='download-summary']");
    if (summaryDownload) {
      summaryDownload.addEventListener("click", function () {
        var csv = "Patient Medication Summary\n\nSmith, John\n\nMedication,Status\nWarfarin 5mg QD,Continue with monitoring\nAspirin 81mg QD,Continue with precautions\nMetformin 500mg BD,Under review\nLisinopril 10mg QD,Continue\nAtorvastatin 40mg QD,Continue\n";
        var blob = new Blob([csv], { type: "text/csv" });
        var url = URL.createObjectURL(blob);
        var a = doc.createElement("a");
        a.href = url;
        a.download = "medication-summary-smith-john.csv";
        doc.body.appendChild(a);
        a.click();
        doc.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast("Medication summary downloaded");
      });
    }

    if (completeBtn) {
      makeClickable(completeBtn, function () {
        var ok = window.confirm("Confirm medication reconciliation is complete?");
        if (!ok) return;
        var params = new URLSearchParams(location.search);
        var patient = params.get("patient") || "smith";
        location.href = "wireframe-SCR-004-patient-detail.html?patient=" + patient + "&medrec=complete";
      });
    }
  }

  function setupAnalyticsDashboard() {
    var rangeSel = doc.getElementById("analytics-range");
    var unitSel = doc.getElementById("analytics-unit");
    var tbody = doc.getElementById("analytics-table-body");
    var csvBtn = doc.getElementById("analytics-export-csv");
    var pdfBtn = doc.getElementById("analytics-export-pdf");

    if (!rangeSel || !unitSel || !tbody) return;

    var kpiData = {
      "30": { avgTime: "4.2h", readmit: "8.3%", medRecon: "96.4%", bed: "87%" },
      "7": { avgTime: "3.8h", readmit: "7.1%", medRecon: "98.1%", bed: "91%" },
      "90": { avgTime: "4.5h", readmit: "9.0%", medRecon: "94.2%", bed: "84%" }
    };

    function updateDashboard() {
      var range = rangeSel.value;
      var unit = unitSel.value;

      var kpis = kpiData[range] || kpiData["30"];
      var kpiCards = doc.querySelectorAll(".kpi-value");
      if (kpiCards.length >= 4) {
        kpiCards[0].textContent = kpis.avgTime;
        kpiCards[1].textContent = kpis.readmit;
        kpiCards[2].textContent = kpis.medRecon;
        kpiCards[3].textContent = kpis.bed;
      }

      var visible = 0;
      Array.from(tbody.querySelectorAll("tr")).forEach(function (row) {
        var rowUnit = row.dataset.unit;
        var rowRange = row.dataset.range;
        var unitMatch = unit === "all" || rowUnit === unit;
        var rangeMatch = parseInt(range, 10) >= parseInt(rowRange || "0", 10);
        var show = unitMatch && rangeMatch;
        row.style.display = show ? "" : "none";
        if (show) visible++;
      });

      var title = doc.querySelector(".card-header h2");
      if (title) title.textContent = "Top High-Risk Encounters — " + visible + " matching";

      var lineTitle = doc.getElementById("line-chart-title");
      if (lineTitle) lineTitle.textContent = "Discharge Volume — Last " + range + " Days";

      var donutData = {
        "7": { low: 70, med: 22, high: 8 },
        "30": { low: 64, med: 28, high: 8 },
        "90": { low: 58, med: 30, high: 12 }
      };
      var d = donutData[range] || donutData["30"];
      var lowEl = doc.getElementById("donut-low");
      var medEl = doc.getElementById("donut-med");
      var highEl = doc.getElementById("donut-high");
      if (lowEl) lowEl.textContent = d.low + "%";
      if (medEl) medEl.textContent = d.med + "%";
      if (highEl) highEl.textContent = d.high + "%";
      var circles = doc.querySelectorAll(".donut-svg circle");
      if (circles.length >= 4) {
        circles[1].setAttribute("stroke-dasharray", d.low + " " + (100 - d.low));
        circles[2].setAttribute("stroke-dasharray", d.med + " " + (100 - d.med));
        circles[2].setAttribute("transform", "rotate(" + (d.low * 3.6) + " 18 18)");
        circles[3].setAttribute("stroke-dasharray", d.high + " " + (100 - d.high));
        circles[3].setAttribute("transform", "rotate(" + ((d.low + d.med) * 3.6) + " 18 18)");
      }

      toast("Analytics updated — " + visible + " encounters");
    }

    rangeSel.addEventListener("change", updateDashboard);
    unitSel.addEventListener("change", updateDashboard);

    function exportCSV() {
      var rows = Array.from(tbody.querySelectorAll("tr")).filter(function (r) { return r.style.display !== "none"; });
      var csv = "Patient,Unit,Risk Score,Discharge Date,Follow-up\n";
      rows.forEach(function (row) {
        var cells = row.querySelectorAll("td");
        var line = Array.from(cells).map(function (c) { return '"' + c.textContent.replace(/\s+/g, " ").trim() + '"'; }).join(",");
        csv += line + "\n";
      });
      var blob = new Blob([csv], { type: "text/csv" });
      var url = URL.createObjectURL(blob);
      var a = doc.createElement("a");
      a.href = url;
      a.download = "analytics-export-" + new Date().toISOString().slice(0, 10) + ".csv";
      doc.body.appendChild(a);
      a.click();
      doc.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast("CSV exported — " + rows.length + " rows");
    }

    function exportPDF() {
      var content = doc.querySelector(".main");
      if (!content) return;
      var printWindow = window.open("", "_blank");
      if (!printWindow) {
        toast("Popup blocked — allow popups to export PDF");
        return;
      }
      printWindow.document.write("<html><head><title>Analytics Report</title><style>body{font-family:sans-serif;padding:24px;} .wf-meta,.wf-nav-panel,.export-row,.meta-panels{display:none;} .kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;} .kpi-card,.chart-card,.card{border:1px solid #ddd;border-radius:8px;padding:16px;margin-bottom:16px;}</style></head><body>" + content.innerHTML + "</body></html>");
      printWindow.document.close();
      printWindow.focus();
      printWindow.print();
      toast("PDF export opened in print dialog");
    }

    if (csvBtn) csvBtn.addEventListener("click", exportCSV);
    if (pdfBtn) pdfBtn.addEventListener("click", exportPDF);
  }

  function setupAuditLogFilters() {
    var container = doc.getElementById("audit-rows");
    var info = doc.getElementById("audit-results-info");
    var dateSel = doc.getElementById("audit-date");
    var userSel = doc.getElementById("audit-user");
    var actionSel = doc.getElementById("audit-action");
    var applyBtn = doc.getElementById("audit-apply");
    var exportBtn = doc.querySelector(".btn-export");

    if (!container) return;

    function applyFilters() {
      var days = parseInt(dateSel ? dateSel.value : "9999", 10);
      var user = userSel ? userSel.value.toLowerCase() : "all";
      var action = actionSel ? actionSel.value.toLowerCase() : "all";
      var base = new Date("2026-07-15T00:00:00");
      var cutoff = new Date(base);
      cutoff.setDate(cutoff.getDate() - days);

      var visible = 0;
      Array.from(container.querySelectorAll(".audit-row")).forEach(function (row) {
        var rowDate = new Date(row.dataset.date + "T00:00:00");
        var rowUser = row.dataset.user.toLowerCase();
        var rowAction = row.dataset.action.toLowerCase();
        var dateMatch = rowDate >= cutoff;
        var userMatch = user === "all" || rowUser === user;
        var actionMatch = action === "all" || rowAction === action;
        var show = dateMatch && userMatch && actionMatch;
        row.style.display = show ? "flex" : "none";
        if (show) visible++;
      });

      if (info) info.textContent = "Showing " + visible + " audit event" + (visible === 1 ? "" : "s");
      toast("Filters applied — " + visible + " result" + (visible === 1 ? "" : "s"));
    }

    if (applyBtn) applyBtn.addEventListener("click", applyFilters);
    if (dateSel) dateSel.addEventListener("change", applyFilters);
    if (userSel) userSel.addEventListener("change", applyFilters);
    if (actionSel) actionSel.addEventListener("change", applyFilters);
    applyFilters();

    if (exportBtn) {
      exportBtn.addEventListener("click", function () {
        var rows = Array.from(container.querySelectorAll(".audit-row")).filter(function (r) { return r.style.display !== "none"; });
        var csv = "Time,User,Action,Target\n";
        rows.forEach(function (row) {
          var time = row.querySelector(".audit-time")?.textContent.trim() || "";
          var user = row.querySelector(".audit-user")?.textContent.trim() || "";
          var action = row.querySelector(".audit-action")?.textContent.trim() || "";
          var target = row.querySelector(".audit-target")?.textContent.replace(/\s+/g, " ").trim() || "";
          csv += [time, user, action, '"' + target + '"'].join(",") + "\n";
        });
        var blob = new Blob([csv], { type: "text/csv" });
        var url = URL.createObjectURL(blob);
        var a = doc.createElement("a");
        a.href = url;
        a.download = "audit-log-" + new Date().toISOString().slice(0, 10) + ".csv";
        doc.body.appendChild(a);
        a.click();
        doc.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast("CSV exported — " + rows.length + " rows");
      });
    }
  }

  function setupAdminUserModal() {
    var modal = doc.getElementById("wf-user-modal");
    if (!modal) return;
    var title = doc.getElementById("wf-user-modal-title");
    var nameInput = doc.getElementById("wf-user-name");
    var emailInput = doc.getElementById("wf-user-email");
    var roleInput = doc.getElementById("wf-user-role");
    var unitInput = doc.getElementById("wf-user-unit");
    var statusInput = doc.getElementById("wf-user-status");

    function openModal(mode, rowData) {
      title.textContent = mode === "edit" ? "Edit User" : "Add User";
      if (mode === "edit" && rowData) {
        nameInput.value = rowData.name || "";
        emailInput.value = rowData.email || "";
        roleInput.value = rowData.role || "Nurse";
        unitInput.value = rowData.unit || "4-West";
        statusInput.value = rowData.status || "Active";
      } else {
        nameInput.value = "";
        emailInput.value = "";
        roleInput.value = "Nurse";
        unitInput.value = "4-West";
        statusInput.value = "Active";
      }
      modal.dataset.mode = mode;
      modal.classList.add("active");
    }

    var currentEditRow = null;

    function closeModal() { modal.classList.remove("active"); currentEditRow = null; }

    modal.querySelectorAll("[data-modal-close]").forEach(function (btn) {
      btn.addEventListener("click", closeModal);
    });
    modal.addEventListener("click", function (e) { if (e.target === modal) closeModal(); });

    var addBtn = doc.querySelector(".btn-add");
    if (addBtn) {
      addBtn.addEventListener("click", function () { openModal("add"); });
    }

    function buildRoleClass(role) {
      var map = { "Nurse": "nurse", "Physician": "physician", "Pharmacist": "pharmacist", "BedManager": "bedmgr", "Admin": "admin" };
      return map[role] || role.toLowerCase().replace(/[^a-z]/g, "");
    }

    function renderUserRow(name, email, role, status) {
      var roleClass = buildRoleClass(role);
      var statusClass = status.toLowerCase();
      var isInactive = status === "Inactive";
      var row = doc.createElement("tr");
      if (isInactive) row.style.opacity = ".6";
      row.innerHTML = '<td><strong>' + name + '</strong></td>' +
        '<td>' + email + '</td>' +
        '<td><span class="role-chip ' + roleClass + '">' + role + '</span></td>' +
        '<td><span class="status-chip ' + statusClass + '">' + status + '</span></td>' +
        '<td>' + (isInactive ? '—' : '2026-08-07 08:00') + '</td>' +
        '<td><div class="action-row"><button class="btn-sm edit">Edit</button><button class="btn-sm ' + (isInactive ? 'reenable' : 'disable') + '">' + (isInactive ? 'Re-enable' : 'Disable') + '</button></div></td>';
      return row;
    }

    var saveBtn = doc.getElementById("wf-user-save");
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        var mode = modal.dataset.mode || "add";
        var name = nameInput.value.trim() || "New User";
        var email = emailInput.value.trim() || name.toLowerCase().replace(/[^a-z\s]/g, "").replace(/\s+/g, ".") + "@hospital.org";
        var role = roleInput.value;
        var status = statusInput.value;

        if (mode === "edit" && currentEditRow) {
          var newRow = renderUserRow(name, email, role, status);
          currentEditRow.parentNode.replaceChild(newRow, currentEditRow);
          currentEditRow = newRow;
          toast("Updated user: " + name);
        } else {
          var tbody = doc.querySelector("table tbody");
          if (tbody) {
            tbody.appendChild(renderUserRow(name, email, role, status));
          }
          toast("Added user: " + name);
        }
        closeModal();
      });
    }

    function handleEditClick(btn) {
      var row = btn.closest("tr");
      if (!row) return;
      currentEditRow = row;
      var cells = row.querySelectorAll("td");
      var roleChip = row.querySelector(".role-chip");
      var statusChip = row.querySelector(".status-chip");
      openModal("edit", {
        name: cells[0] ? cells[0].textContent.trim() : "",
        email: cells[1] ? cells[1].textContent.trim() : "",
        role: roleChip ? roleChip.textContent.trim() : "Nurse",
        unit: "4-West",
        status: statusChip ? statusChip.textContent.trim() : "Active"
      });
    }

    var adminTable = doc.querySelector("table tbody");
    if (adminTable) {
      adminTable.addEventListener("click", function (e) {
        var editBtn = e.target.closest(".btn-sm.edit");
        var disableBtn = e.target.closest(".btn-sm.disable");
        var reenableBtn = e.target.closest(".btn-sm.reenable");
        if (editBtn) {
          e.stopPropagation();
          handleEditClick(editBtn);
        } else if (disableBtn) {
          e.stopPropagation();
          var ok = window.confirm("Disable this user and revoke active sessions?");
          if (!ok) return;
          var row = disableBtn.closest("tr");
          if (row) {
            row.style.opacity = ".6";
            row.querySelector(".status-chip").textContent = "Inactive";
            row.querySelector(".status-chip").className = "status-chip inactive";
            disableBtn.className = "btn-sm reenable";
            disableBtn.textContent = "Re-enable";
          }
          toast("Disabled user");
        } else if (reenableBtn) {
          e.stopPropagation();
          var row = reenableBtn.closest("tr");
          if (row) {
            row.style.opacity = "1";
            row.querySelector(".status-chip").textContent = "Active";
            row.querySelector(".status-chip").className = "status-chip active";
            reenableBtn.className = "btn-sm disable";
            reenableBtn.textContent = "Disable";
          }
          toast("Re-enabled user");
        }
      });
    }
  }

  function setupInlineModals() {
    doc.querySelectorAll("[data-modal-target]").forEach(function (trigger) {
      if (trigger.dataset.wfModalBound === "1") return;
      trigger.dataset.wfModalBound = "1";
      trigger.style.cursor = "pointer";
      trigger.addEventListener("click", function (e) {
        e.preventDefault();
        var modal = doc.getElementById(trigger.dataset.modalTarget);
        if (modal) modal.classList.add("active");
      });
    });

    doc.querySelectorAll(".modal-overlay").forEach(function (modal) {
      modal.addEventListener("click", function (e) {
        if (e.target === modal) modal.classList.remove("active");
      });
    });

    doc.querySelectorAll(".wf-modal").forEach(function (modal) {
      modal.addEventListener("click", function (e) {
        if (e.target === modal) modal.classList.remove("active");
      });
    });

    function updateAlertCount() {
      var badge = doc.querySelector(".card-header [style*='alert-critical-bg']");
      var alerts = doc.querySelectorAll(".alert-item:not([data-resolved='true'])");
      if (badge) badge.textContent = alerts.length;
      var medRow = doc.getElementById("med-rec-row");
      var medDot = doc.getElementById("med-rec-dot");
      var medStatus = doc.getElementById("med-rec-status");
      if (alerts.length === 0 && medRow && medDot && medStatus) {
        medDot.className = "dot ok";
        medStatus.textContent = "Complete";
        medStatus.style.color = "var(--color-alert-success)";
      } else if (medStatus) {
        medStatus.textContent = "⚠ " + alerts.length + " alert" + (alerts.length === 1 ? "" : "s");
      }
    }

    doc.querySelectorAll("[data-modal-close]").forEach(function (closeBtn) {
      if (closeBtn.dataset.wfModalCloseBound === "1") return;
      closeBtn.dataset.wfModalCloseBound = "1";
      closeBtn.addEventListener("click", function () {
        var modal = closeBtn.closest(".wf-modal") || closeBtn.closest(".modal-overlay");
        if (modal) modal.classList.remove("active");
        var action = closeBtn.dataset.action;
        if (action === "resolve") {
          var alertItem = doc.getElementById("alert-interaction");
          if (alertItem) {
            alertItem.dataset.resolved = "true";
            alertItem.style.opacity = ".5";
            alertItem.querySelector(".alert-header").innerHTML = '<span style="font-size:16px">✅</span> Drug Interaction: Warfarin + Aspirin — Resolved';
            alertItem.querySelector(".alert-link").textContent = "Resolved ✓";
            alertItem.querySelector(".alert-link").style.pointerEvents = "none";
          }
          toast("Drug interaction marked resolved");
          updateAlertCount();
        }
        if (action === "review") {
          var alertItem = doc.getElementById("alert-missing");
          if (alertItem) {
            alertItem.dataset.resolved = "true";
            alertItem.style.opacity = ".5";
            alertItem.querySelector(".alert-header").innerHTML = '<span style="font-size:16px">🚩</span> Chronic Medication Missing: Metformin — Flagged for Review';
            alertItem.querySelector(".alert-link").textContent = "Flagged ✓";
            alertItem.querySelector(".alert-link").style.pointerEvents = "none";
          }
          toast("Medication review flagged");
          updateAlertCount();
        }
      });
    });
  }

  function normalizeRole(role) {
    var r = (role || "nurse").toString().toLowerCase().replace(/\s+/g, "");
    var map = { bedmanager: "bedmgr", bedmgr: "bedmgr", administrator: "admin", admin: "admin", nurse: "nurse", physician: "physician", pharmacist: "pharmacist" };
    return map[r] || r;
  }

  function getRoleContext() {
    var params = new URLSearchParams(location.search);
    var role = normalizeRole(params.get("role") || localStorage.getItem("wf-role") || "nurse");
    var unit = params.get("unit") || localStorage.getItem("wf-unit") || "4-West";
    return { role: role, unit: unit };
  }

  function persistRoleContext(role, unit) {
    try {
      localStorage.setItem("wf-role", normalizeRole(role));
      localStorage.setItem("wf-unit", unit);
    } catch (e) {}
  }

  function setupSwitchRole() {
    var cards = doc.querySelectorAll(".role-card");
    var currentRoleEl = doc.getElementById("wf-current-role");
    var currentUnitEl = doc.getElementById("wf-current-unit");
    var unitSelect = doc.getElementById("wf-switch-unit");
    var confirmBtn = doc.getElementById("wf-confirm-switch");
    var ctx = getRoleContext();

    function selectRole(roleKey) {
      cards.forEach(function (c) { c.classList.remove("selected"); });
      var target = doc.querySelector('.role-card[data-role="' + roleKey.charAt(0).toUpperCase() + roleKey.slice(1) + '"]');
      if (!target) target = doc.querySelector('.role-card[data-role="' + roleKey.toLowerCase() + '"]');
      if (!target) {
        var map = { nurse: "Nurse", physician: "Physician", pharmacist: "Pharmacist", bedmanager: "Bed Manager", bedmgr: "Bed Manager", admin: "Administrator" };
        var title = map[roleKey.toLowerCase()];
        if (title) {
          cards.forEach(function (c) {
            if ((c.dataset.role || "").toLowerCase() === title.toLowerCase() || c.querySelector(".title").textContent.trim() === title) {
              target = c;
            }
          });
        }
      }
      if (!target) target = cards[0];
      if (target) {
        target.classList.add("selected");
        if (currentRoleEl) currentRoleEl.textContent = target.dataset.role || target.querySelector(".title").textContent;
      }
    }

    selectRole(ctx.role);
    if (unitSelect) unitSelect.value = ctx.unit;
    if (currentUnitEl) currentUnitEl.textContent = ctx.unit;

    cards.forEach(function (card) {
      card.addEventListener("click", function () {
        cards.forEach(function (c) { c.classList.remove("selected"); });
        card.classList.add("selected");
        if (currentRoleEl) currentRoleEl.textContent = card.querySelector(".title").textContent;
      });
    });

    if (unitSelect && currentUnitEl) {
      unitSelect.addEventListener("change", function () {
        currentUnitEl.textContent = unitSelect.value;
      });
    }

    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        var selected = doc.querySelector(".role-card.selected");
        var roleTitle = selected ? selected.querySelector(".title").textContent : "Nurse";
        var roleKey = normalizeRole(selected ? (selected.dataset.role || roleTitle) : "nurse");
        var unit = unitSelect ? unitSelect.value : "4-West";
        persistRoleContext(roleKey, unit);
        toast("Switched to " + roleTitle + " — " + unit, "success");
        setTimeout(function () {
          location.href = "wireframe-SCR-002-dashboard-home.html?role=" + encodeURIComponent(roleKey) + "&unit=" + encodeURIComponent(unit);
        }, 700);
      });
    }
  }

  function setupDashboardRoleContext() {
    var greeting = doc.getElementById("wf-dashboard-greeting");
    var avatar = doc.getElementById("wf-dashboard-avatar");
    if (!greeting && !avatar && !doc.querySelector(".wf-role-gated")) return;
    var ctx = getRoleContext();
    persistRoleContext(ctx.role, ctx.unit);

    var profiles = {
      nurse: { name: "Nancy", full: "Nurse Nancy (P-01)", initials: "NN" },
      physician: { name: "David", full: "Dr. David Chen (P-02)", initials: "DC" },
      pharmacist: { name: "Marcus", full: "Pharmacist Marcus Phil (P-03)", initials: "MP" },
      bedmgr: { name: "Carol", full: "Bed Manager Carol Johnson (P-04)", initials: "CJ" },
      admin: { name: "Tom", full: "Admin Tom Roberts (P-05)", initials: "TR" }
    };
    var p = profiles[ctx.role] || profiles.nurse;

    function timeGreeting() {
      var h = new Date().getHours();
      if (h < 12) return "Good morning";
      if (h < 18) return "Good afternoon";
      return "Good evening";
    }

    if (greeting) greeting.textContent = timeGreeting() + ", " + p.name;
    if (avatar) {
      avatar.textContent = p.initials;
      avatar.title = p.full;
      avatar.setAttribute("title", p.full);
    }

    var query = "?role=" + encodeURIComponent(ctx.role) + "&unit=" + encodeURIComponent(ctx.unit);

    doc.querySelectorAll(".wf-role-gated").forEach(function (item) {
      var allowed = (item.dataset.roles || "").split(",").map(function (r) { return normalizeRole(r); });
      var isAllowed = allowed.indexOf(ctx.role) !== -1;
      var originalHref = item.dataset.originalHref || (function () {
        var m = item.getAttribute("onclick").match(/location\.href='([^']+)'/);
        var href = m ? m[1].split("?")[0] : "#";
        item.dataset.originalHref = href;
        return href;
      })();
      if (isAllowed) {
        item.style.opacity = "1";
        item.style.pointerEvents = "auto";
        item.style.cursor = "pointer";
        item.title = "Available to " + ctx.role + " role";
        item.setAttribute("onclick", "location.href='" + originalHref + query + "'");
      } else {
        item.style.opacity = ".4";
        item.style.pointerEvents = "none";
        item.style.cursor = "not-allowed";
        item.title = "Not available to " + ctx.role + " role";
        item.setAttribute("onclick", "event.preventDefault(); event.stopPropagation(); return false;");
      }
    });
    doc.querySelectorAll(".sidebar .nav-item[onclick^=\"location.href='wireframe\"]").forEach(function (item) {
      var m = item.getAttribute("onclick").match(/location\.href='([^']+)'/);
      if (!m) return;
      var base = m[1].split("?")[0];
      item.setAttribute("onclick", "location.href='" + base + query + "'");
    });

    var topbarLogo = doc.querySelector(".topbar-logo[onclick^=\"location.href='wireframe-SCR-002-dashboard-home.html\"]");
    if (topbarLogo) topbarLogo.setAttribute("onclick", "location.href='wireframe-SCR-002-dashboard-home.html" + query + "'");

    var metaPersona = doc.querySelector(".wf-meta strong");
    if (metaPersona) {
      var roleLabel = ctx.role.charAt(0).toUpperCase() + ctx.role.slice(1);
      metaPersona.innerHTML = "SCR-002 — Dashboard Home &nbsp;|&nbsp; Route: <code>/dashboard</code> &nbsp;|&nbsp; Current role: " + roleLabel + " · " + ctx.unit + " &nbsp;|&nbsp; Priority: Must Have";
    }
  }

  function setupDashboardRefresh() {
    var refreshLink = doc.getElementById("wf-dashboard-refresh");
    var lastUpdated = doc.getElementById("wf-last-updated");
    if (!refreshLink || !lastUpdated) return;

    function formatTime(date) {
      return date.getHours().toString().padStart(2, "0") + ":" +
             date.getMinutes().toString().padStart(2, "0") + ":" +
             date.getSeconds().toString().padStart(2, "0");
    }

    refreshLink.addEventListener("click", function (e) {
      e.preventDefault();
      lastUpdated.textContent = "Last updated " + formatTime(new Date());

      var count = doc.querySelector(".card-header .count");
      if (count) {
        var base = parseInt(count.textContent, 10) || 7;
        var delta = Math.floor(Math.random() * 3) - 1;
        count.textContent = Math.max(0, base + delta) + " tasks";
      }

      var taskList = doc.querySelector(".task-list");
      if (taskList) taskList.style.opacity = ".6";
      setTimeout(function () { if (taskList) taskList.style.opacity = "1"; }, 200);

      toast("Dashboard refreshed", "success");
    });
  }

  function setupProfilePage() {
    var saveBtn = doc.getElementById("wf-profile-save");
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        var name = doc.getElementById("wf-profile-name");
        var unit = doc.getElementById("wf-profile-unit");
        var phone = doc.getElementById("wf-profile-phone");
        var displayNameEl = doc.querySelector(".identity .name");
        if (name && displayNameEl && name.value.trim()) displayNameEl.textContent = name.value.trim();
        toast("Profile preferences saved", "success");
        if (window.history.replaceState) {
          var params = new URLSearchParams(location.search);
          params.set("unit", unit ? unit.value : "4-West");
          window.history.replaceState({}, "", location.pathname + "?" + params.toString());
        }
      });
    }

    var revokeIphone = doc.getElementById("wf-revoke-iphone");
    if (revokeIphone) {
      revokeIphone.addEventListener("click", function () {
        var row = doc.getElementById("wf-session-iphone");
        if (row) row.classList.add("revoked");
        toast("Safari on iPhone session revoked", "warn");
      });
    }

    var changePassword = doc.getElementById("wf-change-password");
    var passwordModal = doc.getElementById("wf-password-modal");
    if (changePassword && passwordModal) {
      changePassword.addEventListener("click", function () { passwordModal.classList.add("active"); });
    }

    var passwordSubmit = doc.getElementById("wf-password-submit");
    if (passwordSubmit && passwordModal) {
      passwordSubmit.addEventListener("click", function () {
        var current = doc.getElementById("wf-password-current");
        var newPass = doc.getElementById("wf-password-new");
        var confirm = doc.getElementById("wf-password-confirm");
        if (!current || !current.value) { toast("Please enter your current password", "error"); return; }
        if (!newPass || newPass.value.length < 8) { toast("New password must be at least 8 characters", "error"); return; }
        if (newPass.value !== (confirm ? confirm.value : "")) { toast("Passwords do not match", "error"); return; }
        passwordModal.classList.remove("active");
        toast("Password updated successfully", "success");
        [current, newPass, confirm].forEach(function (el) { if (el) el.value = ""; });
      });
    }

    var signOutAll = doc.getElementById("wf-signout-all");
    var signoutModal = doc.getElementById("wf-signout-modal");
    if (signOutAll && signoutModal) {
      signOutAll.addEventListener("click", function () { signoutModal.classList.add("active"); });
    }

    var signoutConfirm = doc.getElementById("wf-signout-confirm");
    if (signoutConfirm && signoutModal) {
      signoutConfirm.addEventListener("click", function () {
        signoutModal.classList.remove("active");
        var iphone = doc.getElementById("wf-session-iphone");
        if (iphone) iphone.classList.add("revoked");
        toast("All other devices signed out", "warn");
      });
    }
  }

  setupAvatarMenus();
  setupBellPanel();
  setupSearchOverlay();
  setupPatientListFilters();
  setupBedBoardFilters();
  setupInstructionTabs();
  setupMRNReveals();
  setupPatientDetailFromQuery();
  setupPatientDetailTabs();
  setupDocumentReview();
  setupAgentMonitor();
  setupSwitchRole();
  setupDashboardRoleContext();
  setupDashboardRefresh();
  setupProfilePage();
  setupGenericToggles();
  setupInlineModals();
})();
