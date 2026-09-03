"""Emergency dispatch dashboard and its read-only KV query."""

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
    """Return booked and unassigned emergency service records."""
    bookings = []
    for prefix in ("booking:", "service-request:"):
        listing = await env.CALLERS.list({"prefix": prefix, "limit": 1000})
        for key in listing["keys"]:
            stored = await env.CALLERS.get(key["name"])
            if not stored:
                continue
            try:
                booking = json.loads(stored)
            except ValueError:
                continue
            if booking.get("is_emergency"):
                # Bookings created before status tracking was added were confirmed
                # immediately, so keep them visible in the active queue.
                booking.setdefault(
                    "status",
                    "STAFF_REVIEW" if prefix == "service-request:" else "CONFIRMED",
                )
                bookings.append(booking)

    bookings.sort(
        key=lambda booking: (
            booking.get("status") not in ACTIVE_STATUSES,
            not booking.get("after_hours_surcharge", False),
            -_parse_timestamp(
                booking.get("booked_at") or booking.get("created_at")
            ).timestamp(),
        )
    )
    active = sum(
        booking.get("status") in ACTIVE_STATUSES for booking in bookings
    )
    return Response.json(
        {
            "status": "OK",
            "emergencies": bookings,
            "counts": {
                "total": len(bookings),
                "active": active,
                "after_hours": sum(
                    bool(booking.get("after_hours_surcharge"))
                    and booking.get("status") in ACTIVE_STATUSES
                    for booking in bookings
                ),
                "pending": sum(
                    booking.get("status") in {"PENDING_CONFIRMATION", "STAFF_REVIEW"}
                    for booking in bookings
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
  <title>Revin Emergency Dispatch</title>
  <meta name="description" content="Live emergency HVAC dispatch queue">
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
    .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 34px 0 26px; }
    .stat { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 18px 20px; }
    .stat label { display: block; color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
    .stat strong { display: block; margin-top: 5px; font-size: 29px; letter-spacing: -.04em; }
    .stat.urgent { background: linear-gradient(135deg, var(--red-soft), var(--panel)); border-color: rgba(255,96,53,.35); }
    .toolbar { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--line); margin-bottom: 14px; }
    .tabs { display: flex; gap: 22px; }
    .tab { position: relative; padding: 12px 0; border: 0; background: transparent; color: var(--muted); cursor: pointer; }
    .tab.active { color: var(--text); }
    .tab.active:after { content: ''; position: absolute; height: 2px; background: var(--orange); left: 0; right: 0; bottom: -1px; }
    .updated { color: var(--muted); font-size: 12px; }
    .queue { display: grid; gap: 10px; }
    .card { display: grid; grid-template-columns: 112px minmax(220px,1.4fr) minmax(180px,1fr) minmax(155px,.8fr) 32px; align-items: center; gap: 18px; padding: 18px 20px; border: 1px solid var(--line); background: var(--panel); border-radius: 13px; transition: border-color .15s, transform .15s; }
    .card:hover { border-color: #424955; transform: translateY(-1px); }
    .priority { display: flex; align-items: center; gap: 9px; color: var(--orange); font-weight: 800; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
    .priority i { width: 8px; height: 8px; background: var(--orange); border-radius: 50%; box-shadow: 0 0 0 5px var(--red-soft); }
    .customer strong, .tech strong { display: block; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .meta { color: var(--muted); margin-top: 3px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .time strong { display: block; font-size: 13px; }
    .pill { display: inline-block; border: 1px solid var(--line); border-radius: 99px; padding: 4px 8px; margin-top: 5px; color: var(--muted); font-size: 10px; font-weight: 800; letter-spacing: .05em; }
    .pill.pending { color: var(--amber); border-color: rgba(255,181,71,.35); background: rgba(255,181,71,.08); }
    .pill.confirmed { color: var(--green); border-color: rgba(89,212,155,.32); background: rgba(89,212,155,.07); }
    .chev { color: var(--muted); font-size: 20px; }
    .empty, .locked { text-align: center; padding: 68px 20px; border: 1px dashed var(--line); border-radius: 14px; color: var(--muted); background: rgba(20,23,28,.5); }
    .empty strong, .locked strong { display: block; color: var(--text); font-size: 17px; margin-bottom: 5px; }
    .auth { display: flex; gap: 8px; justify-content: center; margin-top: 20px; }
    .auth input { width: min(330px, 70vw); color: var(--text); border: 1px solid var(--line); background: var(--bg); border-radius: 9px; padding: 10px 12px; outline: none; }
    .auth input:focus { border-color: var(--orange); }
    .auth button { color: white; border: 0; background: var(--orange); border-radius: 9px; padding: 10px 15px; font-weight: 700; cursor: pointer; }
    .error { color: #ff8e73; margin-top: 12px; min-height: 20px; }
    @media (max-width: 850px) { .stats { grid-template-columns: repeat(2,1fr); } .card { grid-template-columns: 90px 1fr 1fr; } .tech, .chev { display: none; } }
    @media (max-width: 580px) { header { padding: 0 18px; } main { padding: 32px 18px 50px; } .topline { align-items: start; } .stats { grid-template-columns: 1fr 1fr; } .card { grid-template-columns: 1fr; gap: 9px; } .priority { margin-bottom: 2px; } .time { border-top: 1px solid var(--line); padding-top: 10px; } .updated { display: none; } }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="brand"><div class="mark">R</div><div><strong>Revin Dispatch</strong><span>HVAC operations</span></div></div>
      <div class="live"><i></i><span>Live queue</span></div>
    </header>
    <main>
      <div class="topline">
        <div><div class="eyebrow">Operations center</div><h1>Emergency queue</h1><p class="lede">Priority calls that need immediate dispatch attention, directly from the active booking queue.</p></div>
        <button class="refresh" id="refresh" hidden>Refresh</button>
      </div>
      <section class="stats" aria-label="Queue summary">
        <div class="stat urgent"><label>Active emergencies</label><strong id="activeCount">—</strong></div>
        <div class="stat"><label>After-hours</label><strong id="afterHoursCount">—</strong></div>
        <div class="stat"><label>Awaiting review</label><strong id="pendingCount">—</strong></div>
        <div class="stat"><label>Total records</label><strong id="totalCount">—</strong></div>
      </section>
      <div class="toolbar">
        <div class="tabs"><button class="tab active" data-filter="active">Active</button><button class="tab" data-filter="all">All emergencies</button></div>
        <span class="updated" id="updated"></span>
      </div>
      <section id="queue" class="queue" aria-live="polite">
        <div class="locked"><strong>Connect to the dispatch queue</strong><span>Enter the dashboard access token to load emergency calls.</span><form class="auth" id="auth"><input id="token" type="password" autocomplete="current-password" placeholder="Access token" aria-label="Access token" required><button>Connect</button></form><div class="error" id="error"></div></div>
      </section>
    </main>
  </div>
  <script>
    const state = { emergencies: [], filter: 'active', token: __LOCAL_DASHBOARD_TOKEN__ || sessionStorage.getItem('revinDashboardToken') || '' };
    const activeStatuses = new Set(['CONFIRMED', 'PENDING_CONFIRMATION', 'STAFF_REVIEW']);
    const queue = document.querySelector('#queue');
    const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    const formatPhone = value => { const d = String(value || '').replace(/\D/g,'').slice(-10); return d.length === 10 ? `(${d.slice(0,3)}) ${d.slice(3,6)}-${d.slice(6)}` : value || 'No phone'; };
    const formatTime = value => value ? new Intl.DateTimeFormat('en-US',{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(new Date(value)) : 'Time not assigned';
    const age = value => { if (!value) return 'Age unknown'; const mins = Math.max(0, Math.floor((Date.now()-new Date(value))/60000)); return mins < 60 ? `${mins}m in queue` : mins < 1440 ? `${Math.floor(mins/60)}h ${mins%60}m in queue` : `${Math.floor(mins/1440)}d in queue`; };
    function render() {
      const records = state.filter === 'active' ? state.emergencies.filter(x => activeStatuses.has(x.status)) : state.emergencies;
      if (!records.length) { queue.innerHTML = `<div class="empty"><strong>No ${state.filter === 'active' ? 'active ' : ''}emergencies</strong><span>The queue is clear. New emergency bookings will appear here.</span></div>`; return; }
      queue.innerHTML = records.map(x => {
        const status = String(x.status || 'UNKNOWN'); const pending = status === 'PENDING_CONFIRMATION';
        return `<article class="card">
          <div class="priority"><i></i>${x.after_hours_surcharge ? 'After-hours' : 'Emergency'}</div>
          <div class="customer"><strong>${escapeHtml(x.customer_name || x.business_name || 'Unknown caller')}</strong><div class="meta">${escapeHtml(formatPhone(x.customer_phone || x.site_contact_phone))} · ${escapeHtml(x.location || 'Unassigned location')}</div><div class="meta">${escapeHtml(x.summary || x.issue_description || 'No issue summary')}</div></div>
          <div class="tech"><strong>${escapeHtml(x.tech_name || 'Unassigned')}</strong><div class="meta">${escapeHtml(x.address || 'No address')}</div></div>
          <div class="time"><strong>${escapeHtml(formatTime(x.start))}</strong><div class="meta">${escapeHtml(age(x.booked_at || x.created_at))}</div><span class="pill ${pending || status === 'STAFF_REVIEW' ? 'pending' : status === 'CONFIRMED' ? 'confirmed' : ''}">${escapeHtml(status.replaceAll('_',' '))}</span></div>
          <div class="chev">›</div>
        </article>`;
      }).join('');
    }
    async function loadQueue() {
      const refresh = document.querySelector('#refresh'); refresh.disabled = true;
      try {
        const response = await fetch('/api/emergency-queue', {headers:{authorization:`Bearer ${state.token}`}});
        if (response.status === 401) throw new Error('That access token was not accepted.');
        if (!response.ok) throw new Error('The queue could not be loaded.');
        const data = await response.json(); state.emergencies = data.emergencies || [];
        sessionStorage.setItem('revinDashboardToken', state.token);
        document.querySelector('#activeCount').textContent = data.counts.active;
        document.querySelector('#afterHoursCount').textContent = data.counts.after_hours;
        document.querySelector('#pendingCount').textContent = data.counts.pending;
        document.querySelector('#totalCount').textContent = data.counts.total;
        document.querySelector('#updated').textContent = `Updated ${new Date(data.refreshed_at).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'})}`;
        refresh.hidden = false; render();
      } catch (error) {
        sessionStorage.removeItem('revinDashboardToken'); state.token = '';
        queue.innerHTML = `<div class="locked"><strong>Connect to the dispatch queue</strong><span>Enter the dashboard access token to load emergency calls.</span><form class="auth" id="auth"><input id="token" type="password" autocomplete="current-password" placeholder="Access token" aria-label="Access token" required><button>Connect</button></form><div class="error" id="error">${escapeHtml(error.message)}</div></div>`;
        bindAuth();
      } finally { refresh.disabled = false; }
    }
    function bindAuth() { const form = document.querySelector('#auth'); if (!form) return; form.addEventListener('submit', e => { e.preventDefault(); state.token = document.querySelector('#token').value.trim(); loadQueue(); }); }
    document.querySelector('#refresh').addEventListener('click', loadQueue);
    document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => { document.querySelectorAll('.tab').forEach(x => x.classList.remove('active')); tab.classList.add('active'); state.filter = tab.dataset.filter; render(); }));
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
