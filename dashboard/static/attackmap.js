// Attack map: where each source is connecting from, and what the defenses did with its traffic.
// Shared by the attack console (/) and the cyber range (/range). Land comes from vendor/worldmask.js (offline): the
// finest grid that covers the map's bounds (a 1.5 degree world grid, a 0.4 degree Europe grid).
// Origins are ASSIGNED to lab IPs (dashboard/geo.py); the counts and colours come from real defense decisions.
"use strict";
(function () {
  const COLORS = { passing: "#00bfff", partial: "#ff9f1c", blocked: "#ff3b3b", breached: "#ff4fd8", idle: "#3d5a73" };
  const STATUS_TEXT = { passing: "reaching server", partial: "partly stopped", blocked: "blocked / shed",
                        breached: "objective reached", idle: "no traffic yet" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const WORLD = { latMin: -58, latMax: 84, lngMin: -180, lngMax: 180 };

  const LAND = {};
  // The finest mask whose box covers the bounds; the world grid otherwise.
  function maskFor(b) {
    const all = window.WORLD_MASKS || [];
    const fits = all.filter((m) => m.latTop + m.step >= b.latMax && m.latTop - m.step * (m.rows.length + 1) <= b.latMin &&
      m.lngMin - m.step <= b.lngMin && m.lngMin + m.step * (m.cols + 1) >= b.lngMax);
    return (fits.length ? fits : all).slice().sort((x, y) => x.step - y.step)[0] || null;
  }
  function landCells(M) {
    if (!M) return [];
    if (LAND[M.name]) return LAND[M.name];
    const out = [];
    M.rows.forEach((hex, r) => {
      const lat = M.latTop - M.step * (r + 0.5);
      let bits = "";
      for (const ch of hex) bits += parseInt(ch, 16).toString(2).padStart(4, "0");
      for (let c = 0; c < M.cols; c++) if (bits[c] === "1") out.push([lat, M.lngMin + M.step * (c + 0.5)]);
    });
    return (LAND[M.name] = out);
  }

  class AttackMap {
    constructor(canvas, opts) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.bounds = Object.assign({}, WORLD, (opts && opts.bounds) || {});
      this.data = { server: null, origins: [], active: false };
      this.prev = {};            // ip -> last seen counts, to animate only new traffic
      this.flow = {};            // ip -> {rate, stopShare} of the latest delta
      this.packets = []; this.sparks = []; this.lastSpawn = 0; this.hover = null;
      const host = canvas.parentElement;
      if (getComputedStyle(host).position === "static") host.style.position = "relative";
      this.tip = document.createElement("div");
      this.tip.style.cssText = "position:absolute;pointer-events:none;display:none;z-index:5;min-width:190px;max-width:260px;" +
        "background:rgba(3,8,24,.96);border:1px solid rgba(0,191,255,.45);border-radius:6px;padding:9px 11px;" +
        "font:11.5px/1.5 'Courier New',ui-monospace,monospace;color:#cfe8ff;box-shadow:0 6px 20px rgba(0,0,0,.5)";
      host.appendChild(this.tip);
      canvas.addEventListener("mousemove", (e) => this.onMove(e));
      canvas.addEventListener("mouseleave", () => { this.hover = null; this.tip.style.display = "none"; });
      this.resize();
      window.addEventListener("resize", () => this.resize());
      requestAnimationFrame((ts) => this.loop(ts));
    }

    resize() {
      const dpr = window.devicePixelRatio || 1;
      const b = this.bounds;
      this.w = Math.max(320, Math.floor(this.canvas.getBoundingClientRect().width));
      const aspect = (b.latMax - b.latMin) / (b.lngMax - b.lngMin);
      this.h = Math.max(240, Math.min(520, Math.round(this.w * aspect)));
      this.canvas.style.height = this.h + "px";
      this.canvas.width = Math.floor(this.w * dpr); this.canvas.height = Math.floor(this.h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.bg = this.drawLand(dpr);
    }

    proj(lat, lng) {
      const b = this.bounds;
      return { x: ((lng - b.lngMin) / (b.lngMax - b.lngMin)) * this.w, y: ((b.latMax - lat) / (b.latMax - b.latMin)) * this.h };
    }

    drawLand(dpr) {
      const off = document.createElement("canvas");
      off.width = this.canvas.width; off.height = this.canvas.height;
      const g = off.getContext("2d");
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const M = maskFor(this.bounds);
      const step = M ? M.step : 1.5;
      const cellPx = (step / (this.bounds.lngMax - this.bounds.lngMin)) * this.w;
      const r = Math.max(0.8, Math.min(3.2, cellPx * 0.3));
      g.fillStyle = "rgba(0,191,255,0.22)";
      for (const [lat, lng] of landCells(M)) {
        if (lat < this.bounds.latMin - step || lat > this.bounds.latMax + step) continue;
        if (lng < this.bounds.lngMin - step || lng > this.bounds.lngMax + step) continue;
        const p = this.proj(lat, lng);
        g.beginPath(); g.arc(p.x, p.y, r, 0, Math.PI * 2); g.fill();
      }
      return off;
    }

    update(data) {
      data = data || {};
      const origins = data.origins || [];
      const flow = {};
      origins.forEach((o) => {
        const p = this.prev[o.ip] || { requests: 0, stopped: 0 };
        const dReq = Math.max(0, o.requests - p.requests);
        const dStop = Math.max(0, o.stopped - p.stopped);
        flow[o.ip] = { rate: dReq, stopShare: dReq ? dStop / dReq : (o.requests ? o.stopped / o.requests : 0) };
        this.prev[o.ip] = { requests: o.requests, stopped: o.stopped };
      });
      this.flow = flow;
      this.data = { server: data.server || null, origins: origins, active: !!data.active };
    }

    radius(o) { return o.requests ? Math.min(13, 4 + 2.2 * Math.log2(1 + o.requests / 5)) : 3; }

    arcPoint(a, b, t) {
      const lift = Math.min(this.h * 0.32, Math.hypot(a.x - b.x, a.y - b.y) * 0.28 + 18);
      const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2 - lift, mt = 1 - t;
      return { x: mt * mt * a.x + 2 * mt * t * cx + t * t * b.x, y: mt * mt * a.y + 2 * mt * t * cy + t * t * b.y };
    }

    spawn() {
      this.data.origins.forEach((o, i) => {
        const f = this.flow[o.ip];
        if (!f || !f.rate) return;
        const n = Math.min(3, Math.ceil(f.rate / 15));
        for (let k = 0; k < n; k++) {
          if (Math.random() < 0.6) this.packets.push({ i, t: 0, stopped: Math.random() < f.stopShare, speed: 0.011 + Math.random() * 0.01 });
        }
      });
      if (this.packets.length > 320) this.packets.splice(0, this.packets.length - 320);
    }

    loop(ts) {
      const g = this.ctx, d = this.data;
      g.clearRect(0, 0, this.w, this.h);
      if (this.bg) g.drawImage(this.bg, 0, 0, this.w, this.h);
      const server = d.server ? this.proj(d.server.lat, d.server.lng) : null;
      const pts = d.origins.map((o) => this.proj(o.lat, o.lng));
      if (server) {
        d.origins.forEach((o, i) => {
          if (!o.requests) return;
          const a = pts[i];
          g.strokeStyle = COLORS[o.status] || COLORS.passing; g.globalAlpha = 0.28; g.lineWidth = 1.2;
          g.beginPath(); g.moveTo(a.x, a.y);
          for (let t = 0.05; t <= 1.0001; t += 0.05) { const q = this.arcPoint(a, server, t); g.lineTo(q.x, q.y); }
          g.stroke(); g.globalAlpha = 1;
        });
      }
      if (d.active && ts - this.lastSpawn > 140) { this.spawn(); this.lastSpawn = ts; }
      this.packets = this.packets.filter((p) => {
        const a = pts[p.i];
        if (!a || !server) return false;
        p.t += p.speed;
        const end = p.stopped ? 0.55 : 1.0;
        const pos = this.arcPoint(a, server, Math.min(p.t, end));
        if (p.t >= end) { this.sparks.push({ x: pos.x, y: pos.y, life: 1, stopped: p.stopped }); return false; }
        const c = p.stopped ? COLORS.blocked : "#22d36a";
        g.fillStyle = c; g.shadowColor = c; g.shadowBlur = 8;
        g.beginPath(); g.arc(pos.x, pos.y, 2.3, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
        return true;
      });
      this.sparks = this.sparks.filter((s) => {
        s.life -= 0.05; if (s.life <= 0) return false;
        g.fillStyle = (s.stopped ? "rgba(255,59,59," : "rgba(34,211,106,") + s.life + ")";
        g.beginPath(); g.arc(s.x, s.y, (1 - s.life) * 10 + 2, 0, Math.PI * 2); g.fill();
        return true;
      });
      d.origins.forEach((o, i) => {
        const p = pts[i], r = this.radius(o), c = COLORS[o.status] || COLORS.passing;
        if (o.status === "breached" || (d.active && this.flow[o.ip] && this.flow[o.ip].rate)) {
          g.strokeStyle = c; g.globalAlpha = 0.5; g.lineWidth = 1.5;
          g.beginPath(); g.arc(p.x, p.y, r + 4 + 3 * Math.sin(ts / 200), 0, Math.PI * 2); g.stroke(); g.globalAlpha = 1;
        }
        g.fillStyle = c; g.shadowColor = c; g.shadowBlur = o.requests ? 12 : 0;
        g.beginPath(); g.arc(p.x, p.y, r, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
        if (o.requests || this.hover === i) {
          g.font = "10.5px 'Courier New', monospace";
          const lw = Math.max(g.measureText(o.city).width, g.measureText(o.ip).width) + 6;
          g.fillStyle = "rgba(0,4,13,.72)"; g.fillRect(p.x + r + 2, p.y - 11, lw, 25);
          g.fillStyle = "rgba(207,232,255,.95)"; g.fillText(o.city, p.x + r + 5, p.y - 1);
          g.fillStyle = "rgba(135,170,200,.85)"; g.fillText(o.ip, p.x + r + 5, p.y + 10);
        }
      });
      if (server) {
        const pr = 7 + Math.sin(ts / 220) * 2;
        g.fillStyle = "#ffd700"; g.shadowColor = "#ffd700"; g.shadowBlur = 16;
        g.beginPath(); g.arc(server.x, server.y, pr, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
        g.font = "bold 11px 'Courier New', monospace";
        const sl = d.server.label || "Bank", sw = g.measureText(sl).width + 8;
        g.fillStyle = "rgba(0,4,13,.78)"; g.fillRect(server.x - sw / 2, server.y + 11, sw, 16);
        g.fillStyle = "#ffd700"; g.textAlign = "center"; g.fillText(sl, server.x, server.y + 23); g.textAlign = "left";
      }
      requestAnimationFrame((t) => this.loop(t));
    }

    onMove(e) {
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      let best = -1, bestD = 16;
      this.data.origins.forEach((o, i) => {
        const p = this.proj(o.lat, o.lng), dd = Math.hypot(p.x - x, p.y - y) - this.radius(o);
        if (dd < bestD) { bestD = dd; best = i; }
      });
      this.hover = best >= 0 ? best : null;
      if (best < 0) { this.tip.style.display = "none"; return; }
      const o = this.data.origins[best];
      const kinds = Object.entries(o.kinds || {}).map(([k, v]) => `${esc(k)} ${v}`).join(" · ") || "-";
      this.tip.innerHTML = `<b style="color:${COLORS[o.status]}">${esc(o.city)}, ${esc(o.country)}</b><br>` +
        `<span style="color:#87aac8">${esc(o.ip)} · ${esc(o.role)}</span><br>` +
        `requests <b>${o.requests}</b> · stopped <b>${o.stopped}</b> · passed <b>${o.passed}</b><br>` +
        (o.malicious ? `malicious <b>${o.malicious}</b> · ` : "") + (o.breached ? `<b style="color:${COLORS.breached}">objective reached ${o.breached}</b><br>` : "") +
        `traffic: ${kinds}<br><span style="color:${COLORS[o.status]}">${STATUS_TEXT[o.status] || o.status}</span>` +
        (o.placed === "hashed" ? `<br><span style="color:#5f7f9a">unlisted IP: origin placed by hash</span>` : "");
      this.tip.style.display = "block";
      const tx = Math.min(x + 14, this.w - 270), ty = Math.max(4, y - 10);
      this.tip.style.left = Math.max(4, tx) + "px"; this.tip.style.top = ty + "px";
    }
  }

  function table(el, origins) {
    if (!el) return;
    const rows = (origins || []).filter((o) => o.requests);
    if (!rows.length) { el.innerHTML = `<div style="font:12px 'Courier New',monospace;color:#5f7f9a;padding:8px 0">No traffic yet: start a run to see where requests come from.</div>`; return; }
    el.innerHTML = `<table class="origin-table"><thead><tr><th>Origin</th><th>Source IP</th><th>Role</th><th>Requests</th>` +
      `<th>Stopped</th><th>Passed</th><th>Stop rate</th><th>Traffic</th><th>Status</th></tr></thead><tbody>` +
      rows.map((o) => `<tr><td>${esc(o.city)}, ${esc(o.country)}</td><td>${esc(o.ip)}</td><td>${esc(o.role)}</td>` +
        `<td>${o.requests}</td><td>${o.stopped}</td><td>${o.passed}</td>` +
        `<td>${o.stop_rate == null ? "-" : (100 * o.stop_rate).toFixed(1) + "%"}</td>` +
        `<td>${Object.entries(o.kinds || {}).map(([k, v]) => `${esc(k)} ${v}`).join(", ")}</td>` +
        `<td><span style="color:${COLORS[o.status]};font-weight:700">${esc(STATUS_TEXT[o.status] || o.status)}</span></td></tr>`).join("") +
      `</tbody></table>`;
  }

  function legend() {
    return Object.keys(COLORS).filter((k) => k !== "idle").map((k) =>
      `<span><span class="swatch" style="background:${COLORS[k]}"></span>${STATUS_TEXT[k]}</span>`).join("") +
      `<span><span class="swatch" style="background:#ffd700"></span>bank server</span>`;
  }

  window.AttackMap = {
    mount: (canvas, opts) => (canvas ? new AttackMap(canvas, opts) : null),
    table, legend, COLORS,
    EUROPE: { latMin: 33, latMax: 60, lngMin: -14, lngMax: 36 },
  };
})();
