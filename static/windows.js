/* ROCKY window manager — every result is a draggable, resizable,
   voice-controllable floating window. Small by default; "make it full screen"
   maximizes it. This is the generic surface every data provider renders into. */
"use strict";

const WM = (() => {
  let layer = null, dock = null, z = 40, idc = 0;
  const wins = [];        // {id, el, body, min, prevRect}
  let activeId = null;

  function ensure() {
    if (layer) return;
    layer = document.getElementById("wm-layer");
    dock = document.getElementById("wm-dock");
  }

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  /* External links can't open in a chromeless app window via target=_blank —
     route them through the server, which opens the real default browser. */
  function link(cls, text, href) {
    const a = el("a", cls, text);
    a.href = href || "#";
    a.onclick = (e) => {
      e.preventDefault();
      if (href && window.send) window.send({ type: "open_url", url: href });
    };
    return a;
  }

  function active() { return wins.find(w => w.id === activeId) || wins[wins.length - 1]; }

  function focus(w) {
    activeId = w.id;
    w.el.style.zIndex = ++z;
    wins.forEach(x => x.el.classList.toggle("active", x === w));
  }

  // ---------- lifecycle ----------

  function open(spec) {
    ensure();
    const id = "w" + (++idc);
    const win = el("div", "win");
    win.style.left = (120 + (wins.length % 5) * 34) + "px";
    win.style.top = (90 + (wins.length % 5) * 30) + "px";

    const bar = el("div", "win-bar");
    const title = el("div", "win-title", `<span class="win-glyph">${glyph(spec.kind)}</span>${escape(spec.title || spec.kind || "")}`);
    const btns = el("div", "win-btns");
    const bMin = el("button", "win-btn", "—");
    const bMax = el("button", "win-btn", "▢");
    const bClose = el("button", "win-btn close", "✕");
    btns.append(bMin, bMax, bClose);
    bar.append(title, btns);

    const body = el("div", "win-body");
    render(body, spec);

    win.append(bar, body);
    layer.appendChild(win);
    const rec = { id, el: win, body, min: false, prevRect: null };
    wins.push(rec);
    focus(rec);

    win.addEventListener("mousedown", () => focus(rec));
    bClose.onclick = (e) => { e.stopPropagation(); close(rec); };
    bMax.onclick = (e) => { e.stopPropagation(); toggleMax(rec); };
    bMin.onclick = (e) => { e.stopPropagation(); minimize(rec); };
    makeDraggable(win, bar, rec);

    requestAnimationFrame(() => win.classList.add("show"));
    return id;
  }

  function close(rec) {
    rec.el.classList.remove("show");
    setTimeout(() => rec.el.remove(), 200);
    const i = wins.indexOf(rec); if (i >= 0) wins.splice(i, 1);
    if (rec.dockChip) rec.dockChip.remove();
  }

  function toggleMax(rec) {
    if (rec.el.classList.contains("max")) {
      rec.el.classList.remove("max");
    } else {
      rec.el.classList.add("max");
    }
    focus(rec);
  }

  function minimize(rec) {
    rec.el.classList.remove("show");
    rec.min = true;
    if (!rec.dockChip) {
      const chip = el("button", "dock-chip", glyph(rec.spec ? rec.spec.kind : "") + " " +
        escape((rec.titleText || "window").slice(0, 18)));
      chip.onclick = () => restore(rec);
      dock.appendChild(chip);
      rec.dockChip = chip;
    }
  }

  function restore(rec) {
    rec.min = false;
    rec.el.classList.add("show");
    if (rec.dockChip) { rec.dockChip.remove(); rec.dockChip = null; }
    focus(rec);
  }

  // ---------- voice / UI actions ----------

  function action(a, id) {
    const rec = id ? wins.find(w => w.id === id) : active();
    if (a === "close" && !rec) { wins.slice().forEach(close); return; }
    if (!rec) return;
    if (a === "fullscreen") { rec.el.classList.add("max"); focus(rec); }
    else if (a === "restore") { rec.el.classList.remove("max"); if (rec.min) restore(rec); }
    else if (a === "minimize") minimize(rec);
    else if (a === "close") close(rec);
  }

  // ---------- dragging ----------

  function makeDraggable(win, handle, rec) {
    let sx, sy, ox, oy, dragging = false;
    handle.addEventListener("mousedown", (e) => {
      if (e.target.closest(".win-btn")) return;
      if (win.classList.contains("max")) return;
      dragging = true; sx = e.clientX; sy = e.clientY;
      const r = win.getBoundingClientRect(); ox = r.left; oy = r.top;
      document.body.style.userSelect = "none";
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      win.style.left = Math.max(0, ox + e.clientX - sx) + "px";
      win.style.top = Math.max(56, oy + e.clientY - sy) + "px";
    });
    window.addEventListener("mouseup", () => { dragging = false; document.body.style.userSelect = ""; });
  }

  // ---------- content ----------

  function glyph(kind) {
    return ({ weather: "☀", news: "📰", wiki: "📖", place: "📍", video: "▶" })[kind] || "◆";
  }
  function escape(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

  function render(body, spec) {
    if (spec.kind === "weather") return weather(body, spec);
    if (spec.kind === "news") return news(body, spec);
    if (spec.kind === "wiki") return wiki(body, spec);
    if (spec.kind === "place") return place(body, spec);
    body.appendChild(el("pre", "win-raw", escape(JSON.stringify(spec, null, 2))));
  }

  function grid(pairs) {
    const g = el("div", "kv-grid");
    pairs.forEach(([k, v]) => {
      if (v == null || v === "") return;
      const c = el("div", "kv-cell");
      c.appendChild(el("span", "kv-k", k));
      c.appendChild(el("span", "kv-v", escape(v)));
      g.appendChild(c);
    });
    return g;
  }

  function weather(body, c) {
    const main = el("div", "wx-main");
    main.appendChild(el("div", "wx-emoji", c.emoji || "🌡"));
    const t = el("div");
    t.appendChild(el("div", "wx-temp", `${c.temp}°`));
    t.appendChild(el("div", "wx-desc", escape(c.desc || "")));
    t.appendChild(el("div", "wx-sub", `H:${c.hi}°  L:${c.lo}°` + (c.local_time ? "  ·  " + escape(c.local_time) : "")));
    main.append(t);
    body.appendChild(main);

    // 7-day forecast strip
    if (c.days && c.days.length) {
      body.appendChild(el("div", "wx-section", "7-DAY FORECAST"));
      const fc = el("div", "forecast");
      c.days.forEach(d => {
        const cell = el("div", "fc-day");
        cell.appendChild(el("div", "fc-name", escape(d.day)));
        cell.appendChild(el("div", "fc-emoji", d.emoji || "🌡"));
        if (d.pop != null) cell.appendChild(el("div", "fc-pop", `💧${d.pop}%`));
        cell.appendChild(el("div", "fc-hi", `${d.hi}°`));
        cell.appendChild(el("div", "fc-lo", `${d.lo}°`));
        fc.appendChild(cell);
      });
      body.appendChild(fc);
    }

    body.appendChild(el("div", "wx-section", "CONDITIONS"));
    body.appendChild(grid([
      ["FEELS LIKE", `${c.feels}°`],
      ["HUMIDITY", c.humidity != null ? `${c.humidity}%` : null],
      ["WIND", `${c.wind} km/h`],
      ["RAIN CHANCE", c.pop != null ? `${c.pop}%` : null],
      ["UV INDEX", c.uv != null ? `${c.uv}` : null],
      ["CLOUD", c.cloud != null ? `${c.cloud}%` : null],
      ["PRESSURE", c.pressure ? `${c.pressure} hPa` : null],
      ["PRECIP", c.precip != null ? `${c.precip} mm` : null],
      ["SUNRISE", c.sunrise], ["SUNSET", c.sunset],
    ]));
  }

  function news(body, c) {
    if (c.video_id) {
      const vid = el("div", "win-video");
      vid.innerHTML = `<iframe src="https://www.youtube.com/embed/${c.video_id}?autoplay=1&mute=1&rel=0" `
        + `allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen frameborder="0"></iframe>`;
      body.appendChild(vid);
    }
    const list = el("div", "news-list");
    (c.items || []).forEach((it, i) => {
      const a = link("news-item" + (i === 0 ? " lead" : ""), null, it.link);
      a.appendChild(el("div", "news-title", escape(it.title || "")));
      const meta = el("div", "news-meta");
      if (it.source) meta.appendChild(el("span", "news-src", escape(it.source)));
      if (it.published) meta.appendChild(el("span", "news-time", escape(it.published)));
      a.appendChild(meta);
      list.appendChild(a);
    });
    body.appendChild(list);
  }

  function wiki(body, c) {
    if (c.thumb) {
      const im = el("div", "wiki-hero");
      im.style.backgroundImage = `url("${c.thumb}")`;
      body.appendChild(im);
    }
    body.appendChild(el("div", "wiki-extract", escape(c.extract || "")));
    if (c.url) body.appendChild(link("win-link", "READ ON WIKIPEDIA →", c.url));
  }

  function place(body, c) {
    body.appendChild(grid([
      ["LOCAL TIME", c.local_time], ["COUNTRY", c.country],
      ["POPULATION", c.population ? Intl.NumberFormat().format(c.population) : null],
      ["COORDS", `${c.lat}, ${c.lng}`],
    ]));
  }

  // patch: remember spec/title + server id on the record
  const _open = open;
  function openWrapped(spec) {
    ensure();
    const id = _open(spec);
    const rec = wins.find(w => w.id === id);
    if (rec) { rec.spec = spec; rec.titleText = spec.title || spec.kind; rec.wid = spec.id; }
    return id;
  }

  /* Patch an already-open window (deferred video / title from the server). */
  function update(wid, patch) {
    const rec = wins.find(w => w.wid === wid);
    if (!rec || !patch) return;
    if (patch.title) {
      rec.titleText = patch.title;
      const span = rec.el.querySelector(".win-title");
      if (span) span.innerHTML = `<span class="win-glyph">${glyph(rec.spec && rec.spec.kind)}</span>${escape(patch.title)}`;
    }
    if (patch.video_id && !rec.el.querySelector(".win-video")) {
      const vid = el("div", "win-video");
      vid.innerHTML = `<iframe src="https://www.youtube.com/embed/${patch.video_id}?autoplay=1&mute=1&rel=0" `
        + `allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen frameborder="0"></iframe>`;
      rec.body.insertBefore(vid, rec.body.firstChild);
    }
  }

  return { open: openWrapped, action, update };
})();
