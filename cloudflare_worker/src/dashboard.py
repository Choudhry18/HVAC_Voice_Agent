"""Dispatch dashboard and its read-only KV query."""

import json
from datetime import datetime, timezone

from workers import Response


ACTIVE_STATUSES = {"CONFIRMED", "PENDING_CONFIRMATION", "STAFF_REVIEW"}


def _parse_timestamp(value: object) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


async def handle_emergency_queue(env):
    """Return emergency bookings and every request awaiting staff review."""
    records = []
    emergencies = []
    for prefix in ("booking:", "service-request:"):
        listing = await env.CALLERS.list({"prefix": prefix, "limit": 1000})
        for key in listing["keys"]:
            stored = await env.CALLERS.get(key["name"])
            if not stored:
                continue
            try:
                record = json.loads(stored)
            except ValueError:
                continue
            default_status = (
                "STAFF_REVIEW" if prefix == "service-request:" else "CONFIRMED"
            )
            status = record.get("status", default_status)
            is_staff_review = (
                prefix == "service-request:" and status == "STAFF_REVIEW"
            )
            if not record.get("is_emergency") and not is_staff_review:
                continue

            normalized = {**record, "status": status}
            if record.get("is_emergency"):
                emergencies.append(normalized)
            records.append(
                {
                    "kv_key": key["name"],
                    "record_type": (
                        "service_request" if prefix == "service-request:" else "booking"
                    ),
                    "status": status,
                    "is_emergency": bool(record.get("is_emergency")),
                    # Keep this untouched so the detail view is the exact stored JSON.
                    "record": record,
                }
            )

    records.sort(
        key=lambda item: (
            item["status"] not in ACTIVE_STATUSES,
            not item["record"].get("after_hours_surcharge", False),
            -_parse_timestamp(
                item["record"].get("booked_at")
                or item["record"].get("created_at")
            ).timestamp(),
        )
    )
    emergencies.sort(
        key=lambda record: (
            record.get("status") not in ACTIVE_STATUSES,
            not record.get("after_hours_surcharge", False),
            -_parse_timestamp(
                record.get("booked_at") or record.get("created_at")
            ).timestamp(),
        )
    )
    active = sum(
        record.get("status") in ACTIVE_STATUSES for record in emergencies
    )
    return Response.json(
        {
            "status": "OK",
            # Retained for clients using the original emergency-only response.
            "emergencies": emergencies,
            "records": records,
            "counts": {
                "total": len(records),
                "active": active,
                "after_hours": sum(
                    bool(record.get("after_hours_surcharge"))
                    and record.get("status") in ACTIVE_STATUSES
                    for record in emergencies
                ),
                "pending": sum(
                    item["status"] in {"PENDING_CONFIRMATION", "STAFF_REVIEW"}
                    for item in records
                ),
            },
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
    )


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Summit Air Dispatch</title>
  <meta name="description" content="Live emergency and staff-review HVAC queue">
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0d10; --panel: #14171c; --panel-2: #191d23;
      --line: #2b3038; --text: #f5f3ed; --muted: #969da8;
      --orange: #ff6035; --amber: #ffb547; --green: #59d49b;
      --red-soft: rgba(255, 96, 53, .12);
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, sans-serif; }
    button, input { font: inherit; }
    .shell { min-height: 100vh; }
    header { height: 72px; padding: 0 34px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line); background: rgba(11,13,16,.94); position: sticky; top: 0; z-index: 5; backdrop-filter: blur(12px); }
    .brand { display: flex; align-items: center; gap: 13px; }
    .mark { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; background: var(--orange); color: white; font-size: 18px; font-weight: 900; box-shadow: 0 0 26px rgba(255,96,53,.24); }
    .brand strong { display: block; font-size: 15px; letter-spacing: .02em; }
    .brand span { color: var(--muted); font-size: 12px; }
    .live { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
    .live i { width: 7px; height: 7px; background: var(--green); border-radius: 50%; box-shadow: 0 0 0 4px rgba(89,212,155,.12); }
    main { max-width: 1260px; margin: 0 auto; padding: 46px 34px 70px; }
    .eyebrow { color: var(--orange); font-size: 11px; font-weight: 800; letter-spacing: .15em; text-transform: uppercase; }
    h1 { margin: 9px 0 8px; font-size: clamp(30px, 4vw, 48px); line-height: 1.04; letter-spacing: -.045em; }
    .lede { margin: 0; color: var(--muted); max-width: 620px; font-size: 15px; }
    .topline { display: flex; justify-content: space-between; gap: 20px; align-items: end; }
    .refresh { border: 1px solid var(--line); color: var(--text); background: var(--panel); border-radius: 10px; padding: 10px 14px; cursor: pointer; }
    .refresh:hover { border-color: #4a515c; }
    .refresh:disabled { opacity: .55; cursor: wait; }
    .review-queues { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 34px; }
    .queue-panel { min-width: 0; padding: 18px; border: 1px solid var(--line); background: var(--panel); border-radius: 15px; }
    .queue-panel.emergency { border-color: rgba(255,96,53,.35); background: linear-gradient(145deg, var(--red-soft), var(--panel) 34%); }
    .queue-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 2px 2px 16px; }
    .queue-head h2 { margin: 0; font-size: 17px; }
    .count { min-width: 28px; padding: 3px 8px; text-align: center; color: var(--muted); background: var(--panel-2); border: 1px solid var(--line); border-radius: 99px; font-weight: 800; }
    .queue-list { display: grid; gap: 10px; }
    .card { display: grid; width: 100%; color: inherit; text-align: left; cursor: pointer; grid-template-columns: minmax(0, 1fr) 24px; align-items: center; gap: 14px; padding: 16px; border: 1px solid var(--line); background: var(--panel-2); border-radius: 11px; transition: border-color .15s, transform .15s; }
    .card:hover, .card:focus-visible { border-color: #596170; transform: translateY(-1px); outline: none; }
    .customer strong { display: block; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .meta { color: var(--muted); margin-top: 3px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .chev { color: var(--muted); font-size: 20px; }
    .empty, .locked { text-align: center; padding: 68px 20px; border: 1px dashed var(--line); border-radius: 14px; color: var(--muted); background: rgba(20,23,28,.5); }
    .empty strong, .locked strong { display: block; color: var(--text); font-size: 17px; margin-bottom: 5px; }
    .auth { display: flex; gap: 8px; justify-content: center; margin-top: 20px; }
    .auth input { width: min(330px, 70vw); color: var(--text); border: 1px solid var(--line); background: var(--bg); border-radius: 9px; padding: 10px 12px; outline: none; }
    .auth input:focus { border-color: var(--orange); }
    .auth button { color: white; border: 0; background: var(--orange); border-radius: 9px; padding: 10px 15px; font-weight: 700; cursor: pointer; }
    .error { color: #ff8e73; margin-top: 12px; min-height: 20px; }
    dialog { width: min(760px, calc(100vw - 32px)); max-height: min(82vh, 900px); padding: 0; color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 28px 90px rgba(0,0,0,.6); }
    dialog::backdrop { background: rgba(0,0,0,.72); backdrop-filter: blur(4px); }
    .detail-head { position: sticky; top: 0; display: flex; align-items: start; justify-content: space-between; gap: 20px; padding: 20px 22px; background: var(--panel); border-bottom: 1px solid var(--line); }
    .detail-head strong { display: block; font-size: 17px; }
    .detail-key { margin-top: 4px; color: var(--muted); font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
    .close { width: 34px; height: 34px; flex: 0 0 auto; color: var(--text); background: var(--panel-2); border: 1px solid var(--line); border-radius: 9px; cursor: pointer; }
    .record-json { margin: 0; padding: 22px; overflow: auto; color: #d9e2ef; background: #0e1115; font: 12px/1.65 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
    @media (max-width: 760px) { .review-queues { grid-template-columns: 1fr; } }
    @media (max-width: 580px) { header { padding: 0 18px; } main { padding: 32px 18px 50px; } .topline { align-items: start; } }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="brand"><div class="mark">S</div><div><strong>Summit Air Dispatch</strong><span>HVAC operations</span></div></div>
      <div class="live"><i></i><span>Live queue</span></div>
    </header>
    <main>
      <div class="topline">
        <div><div class="eyebrow">Operations center</div><h1>Staff review</h1><p class="lede">Requests that need attention. Select any request to see every detail stored about the job.</p></div>
        <button class="refresh" id="refresh" hidden>Refresh</button>
      </div>
      <section id="queue" class="queue" aria-live="polite">
        <div class="locked"><strong>Connect to the dispatch queue</strong><span>Enter the dashboard access token to load dispatch records.</span><form class="auth" id="auth"><input id="token" type="password" autocomplete="current-password" placeholder="Access token" aria-label="Access token" required><button>Connect</button></form><div class="error" id="error"></div></div>
      </section>
    </main>
  </div>
  <dialog id="recordDetail" aria-labelledby="detailTitle">
    <div class="detail-head"><div><strong id="detailTitle">Complete stored record</strong><div class="detail-key" id="detailKey"></div></div><button class="close" id="closeDetail" aria-label="Close">×</button></div>
    <pre class="record-json" id="recordJson"></pre>
  </dialog>
  <script>
    const state = { records: [], token: __LOCAL_DASHBOARD_TOKEN__ || sessionStorage.getItem('summitAirDashboardToken') || '' };
    const queue = document.querySelector('#queue');
    const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    const formatPhone = value => { const d = String(value || '').replace(/\D/g,'').slice(-10); return d.length === 10 ? `(${d.slice(0,3)}) ${d.slice(3,6)}-${d.slice(6)}` : value || 'No phone'; };
    const age = value => { if (!value) return 'Age unknown'; const mins = Math.max(0, Math.floor((Date.now()-new Date(value))/60000)); return mins < 60 ? `${mins}m in queue` : mins < 1440 ? `${Math.floor(mins/60)}h ${mins%60}m in queue` : `${Math.floor(mins/1440)}d in queue`; };
    function openRecord(index) {
      const item = state.records[index]; if (!item) return;
      document.querySelector('#detailKey').textContent = item.kv_key || 'Stored record';
      document.querySelector('#recordJson').textContent = JSON.stringify(item.record, null, 2);
      document.querySelector('#recordDetail').showModal();
    }
    function cards(items, emptyMessage) {
      if (!items.length) return `<div class="empty"><strong>Queue is clear</strong><span>${emptyMessage}</span></div>`;
      return items.map(item => { const x = item.record; const index = state.records.indexOf(item); return `<button class="card" type="button" data-record-index="${index}" aria-label="Open complete record for ${escapeHtml(x.customer_name || x.business_name || 'unknown caller')}"><div class="customer"><strong>${escapeHtml(x.customer_name || x.business_name || 'Unknown caller')}</strong><div class="meta">${escapeHtml(x.issue_description || x.summary || 'No issue summary')}</div><div class="meta">${escapeHtml(formatPhone(x.customer_phone || x.site_contact_phone))} · ${escapeHtml(x.address || 'No address')}</div><div class="meta">${escapeHtml(x.review_reason || 'Staff review')} · ${escapeHtml(age(x.created_at || x.booked_at))}</div></div><div class="chev">›</div></button>`; }).join('');
    }
    function render() {
      const reviewRequests = state.records.filter(item => item.record_type === 'service_request' && item.status === 'STAFF_REVIEW');
      const emergencies = reviewRequests.filter(item => item.is_emergency);
      const normal = reviewRequests.filter(item => !item.is_emergency);
      queue.innerHTML = `<div class="review-queues"><section class="queue-panel emergency"><div class="queue-head"><h2>Emergency requests</h2><span class="count">${emergencies.length}</span></div><div class="queue-list">${cards(emergencies, 'No emergency requests need review.')}</div></section><section class="queue-panel"><div class="queue-head"><h2>Normal requests</h2><span class="count">${normal.length}</span></div><div class="queue-list">${cards(normal, 'No normal requests need review.')}</div></section></div>`;
      queue.querySelectorAll('[data-record-index]').forEach(card => card.addEventListener('click', () => openRecord(Number(card.dataset.recordIndex))));
    }
    async function loadQueue() {
      const refresh = document.querySelector('#refresh'); refresh.disabled = true;
      try {
        const response = await fetch('/api/emergency-queue', {headers:{authorization:`Bearer ${state.token}`}});
        if (response.status === 401) throw new Error('That access token was not accepted.');
        if (!response.ok) throw new Error('The queue could not be loaded.');
        const data = await response.json(); state.records = data.records || (data.emergencies || []).map(record => ({record, status: record.status || 'CONFIRMED', is_emergency: true}));
        sessionStorage.setItem('summitAirDashboardToken', state.token);
        refresh.hidden = false; render();
      } catch (error) {
        sessionStorage.removeItem('summitAirDashboardToken'); state.token = '';
        queue.innerHTML = `<div class="locked"><strong>Connect to the dispatch queue</strong><span>Enter the dashboard access token to load dispatch records.</span><form class="auth" id="auth"><input id="token" type="password" autocomplete="current-password" placeholder="Access token" aria-label="Access token" required><button>Connect</button></form><div class="error" id="error">${escapeHtml(error.message)}</div></div>`;
        bindAuth();
      } finally { refresh.disabled = false; }
    }
    function bindAuth() { const form = document.querySelector('#auth'); if (!form) return; form.addEventListener('submit', e => { e.preventDefault(); state.token = document.querySelector('#token').value.trim(); loadQueue(); }); }
    document.querySelector('#refresh').addEventListener('click', loadQueue);
    document.querySelector('#closeDetail').addEventListener('click', () => document.querySelector('#recordDetail').close());
    document.querySelector('#recordDetail').addEventListener('click', event => { if (event.target === event.currentTarget) event.currentTarget.close(); });
    if (state.token) loadQueue(); else bindAuth();
    setInterval(() => { if (state.token) loadQueue(); }, 30000);
  </script>
</body>
</html>"""


def handle_dashboard(local_token: str | None = None):
    html = DASHBOARD_HTML.replace(
        "__LOCAL_DASHBOARD_TOKEN__", json.dumps(local_token)
    )
    return Response(
        html,
        headers={
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "content-security-policy": (
                "default-src 'self'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "img-src 'self' data:; frame-ancestors 'none'"
            ),
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
        },
    )
