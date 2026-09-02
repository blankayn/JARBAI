/* ============================================================
   J.A.R.B.A.I dashboard — wiring against dashboard_server.py
     GET  /api/stats                -> cpu, cores, ram, disk, net, uptime, procs
     GET  /api/weather?city=NAME    -> temp, code, wind, humidity, feels
     POST /api/ask     {text}       -> reply   (Ollama persona)
     POST /api/command {action}     -> detail  (volume / lock / screenshot / browser)
   Tasks and events have no server endpoint, so they persist in localStorage.
   ============================================================ */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var body = document.body;

  /* ============================================================ UTIL */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function icon(name, cls) {
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    if (cls) s.setAttribute("class", cls);
    s.innerHTML = '<use href="#i-' + name + '"/>';
    return s;
  }

  function bytes(v) {
    if (v == null || !isFinite(v)) return "—";
    if (v < 1024) return Math.round(v) + " B/s";
    if (v < 1048576) return (v / 1024).toFixed(0) + " KB/s";
    return (v / 1048576).toFixed(1) + " MB/s";
  }

  function duration(sec) {
    if (sec == null) return "—";
    var d = Math.floor(sec / 86400);
    var h = Math.floor((sec % 86400) / 3600);
    var m = Math.floor((sec % 3600) / 60);
    if (d) return d + "d " + String(h).padStart(2, "0") + "h";
    if (h) return h + "h " + String(m).padStart(2, "0") + "m";
    return m + "m";
  }

  function store(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }

  function save(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* quota / private mode */ }
  }

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  /* The app was renamed from JARVIS to JARBAI, which moved every storage key.
     Carry the old values over once so saved tasks, events and settings survive.
     Must run before the first store() call below. */
  (function migrateFromJarvis() {
    ["tasks", "events", "city", "tts"].forEach(function (key) {
      try {
        var to = "jarbai." + key;
        var from = localStorage.getItem("jarvis." + key);
        if (from !== null && localStorage.getItem(to) === null) {
          localStorage.setItem(to, from);
        }
      } catch (e) { /* private mode or quota — nothing to migrate */ }
    });
  })();

  /* ============================================================ CORE STATE */
  var core = new NeuralCore($("neural"));
  var stateTimer = null;

  function setState(name, holdMs) {
    body.dataset.state = name;
    $("coreState").textContent = core.setState(name);
    clearTimeout(stateTimer);
    if (holdMs) stateTimer = setTimeout(function () { setState("idle"); }, holdMs);
  }

  var ro = new ResizeObserver(function () { core.resize(); });
  ro.observe($("coreStage"));
  window.addEventListener("resize", function () { core.resize(); });

  /* ============================================================ FEED + TOASTS */
  var feed = $("feed");

  function say(who, text) {
    var line = el("div", "feed-line " + who);
    var tag = { jarbai: "JARBAI", you: "YOU", sys: "SYS", err: "FAULT" }[who] || "SYS";
    line.appendChild(el("b", null, tag));
    line.appendChild(el("span", null, text));
    feed.appendChild(line);
    while (feed.children.length > 40) feed.removeChild(feed.firstChild);
    feed.scrollTop = feed.scrollHeight;
  }

  function toast(text, bad) {
    var t = el("div", "toast" + (bad ? " bad" : ""), text);
    $("toasts").appendChild(t);
    setTimeout(function () {
      t.classList.add("out");
      setTimeout(function () { t.remove(); }, 320);
    }, 3400);
  }

  /* ============================================================ CLOCK */
  function tickClock() {
    var now = new Date();
    $("time").textContent = now.toLocaleTimeString([], { hour12: true });
    $("date").textContent = now.toLocaleDateString([], {
      weekday: "long", year: "numeric", month: "long", day: "numeric"
    });
  }

  function greet() {
    var h = new Date().getHours();
    var word = h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
    $("greeting").textContent = word + ", sir";
  }

  tickClock();
  greet();
  setInterval(tickClock, 1000);
  setInterval(greet, 60000);

  /* ============================================================ SYSTEM STATS */
  var bars = {};
  ["cpu", "ram", "disk", "net"].forEach(function (k) {
    var m = document.querySelector('.metric[data-k="' + k + '"]');
    bars[k] = { row: m, fill: m.querySelector("i"), val: m.querySelector(".metric-val") };
  });

  var netPeak = 1048576;   // adaptive scale for the network bar
  var linkOk = true;

  function setLink(ok, label) {
    if (ok === linkOk && !label) return;
    linkOk = ok;
    $("linkState").dataset.ok = ok ? "1" : "0";
    $("linkLabel").textContent = label || (ok ? "LINK ACTIVE" : "LINK DOWN");
  }

  function setBar(k, pct, text) {
    var b = bars[k];
    pct = Math.max(0, Math.min(100, pct || 0));
    b.fill.style.width = pct + "%";
    b.val.textContent = text;
    b.row.dataset.warn = pct >= 90 ? "2" : pct >= 75 ? "1" : "0";
  }

  function renderProcs(procs) {
    var box = $("procs");
    box.textContent = "";
    if (!procs || !procs.length) {
      box.appendChild(el("div", "empty", "No process data."));
      return;
    }
    procs.forEach(function (p) {
      var row = el("div", "proc");
      var left = el("div", "proc-name", p.name);
      left.appendChild(el("span", "proc-pid", "#" + p.pid));
      row.appendChild(left);
      row.appendChild(el("div", "proc-mem", p.mem >= 1024
        ? (p.mem / 1024).toFixed(1) + " GB"
        : Math.round(p.mem) + " MB"));
      box.appendChild(row);
    });
  }

  function renderCores(cores) {
    var box = $("cores");
    if (!cores || !cores.length) return;
    if (box.children.length !== cores.length) {
      box.textContent = "";
      cores.forEach(function () { box.appendChild(el("span")); });
      $("sbCores").textContent = cores.length;
    }
    for (var i = 0; i < cores.length; i++) {
      box.children[i].style.height = Math.max(4, cores[i]) + "%";
    }
  }

  function pollStats() {
    fetch("/api/stats", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) throw new Error(d.error || "bad stats");
        setLink(true);

        setBar("cpu", d.cpu, Math.round(d.cpu) + "%");
        setBar("ram", d.ram, Math.round(d.ram) + "%");
        setBar("disk", d.disk, Math.round(d.disk) + "%");

        var total = (d.up || 0) + (d.down || 0);
        if (total > netPeak) netPeak = total;
        else netPeak = Math.max(1048576, netPeak * 0.995);
        setBar("net", (total / netPeak) * 100, bytes(total).replace("/s", ""));

        $("ramDetail").textContent = d.ramUsed + " / " + d.ramTotal + " GB";
        $("netDetail").textContent = "↓ " + bytes(d.down) + "  ↑ " + bytes(d.up);
        $("uptime").textContent = "UP " + duration(d.uptime);
        $("sbUptime").textContent = duration(d.uptime);
        $("sbNet").textContent = bytes(total);
        $("coreLoad").textContent = "LOAD " + Math.round(d.cpu) + "%";

        core.setLoad(d.cpu / 100);
        renderCores(d.cores);
        renderProcs(d.procs);
      })
      .catch(function () {
        setLink(false);
        $("coreLoad").textContent = "LOAD --";
      });
  }

  pollStats();
  setInterval(pollStats, 2000);

  /* ============================================================ WEATHER */
  var WMO = {
    0: ["clear skies", "sun"], 1: ["mostly clear", "sun"], 2: ["partly cloudy", "partly"],
    3: ["overcast", "cloud"], 45: ["foggy", "fog"], 48: ["freezing fog", "fog"],
    51: ["light drizzle", "drizzle"], 53: ["drizzle", "drizzle"], 55: ["heavy drizzle", "drizzle"],
    56: ["freezing drizzle", "drizzle"], 57: ["freezing drizzle", "drizzle"],
    61: ["light rain", "rain"], 63: ["moderate rain", "rain"], 65: ["heavy rain", "rain"],
    66: ["freezing rain", "rain"], 67: ["freezing rain", "rain"],
    71: ["light snow", "snow"], 73: ["moderate snow", "snow"], 75: ["heavy snow", "snow"],
    77: ["snow grains", "snow"], 80: ["rain showers", "rain"], 81: ["heavy showers", "rain"],
    82: ["violent showers", "rain"], 85: ["snow showers", "snow"], 86: ["heavy snow showers", "snow"],
    95: ["thunderstorm", "storm"], 96: ["thunderstorm, hail", "storm"], 99: ["severe storm, hail", "storm"]
  };

  var WX_ART = {
    sun: '<circle cx="12" cy="12" r="4.6"/><path d="M12 1.5v2.6M12 19.9v2.6M4.2 4.2l1.9 1.9M17.9 17.9l1.9 1.9M1.5 12h2.6M19.9 12h2.6M4.2 19.8l1.9-1.9M17.9 6.1l1.9-1.9"/>',
    partly: '<circle cx="8.6" cy="8.4" r="3.4"/><path d="M8.6 1.9v1.9M3.3 3.6l1.4 1.4M2 8.4h1.9M13.9 3.6l-1.4 1.4"/><path d="M7.5 20.5h9.8a3.7 3.7 0 0 0 .3-7.4 5.2 5.2 0 0 0-10-1.2 3.8 3.8 0 0 0-.1 8.6z"/>',
    cloud: '<path d="M6.8 19.5h10.6a4 4 0 0 0 .3-8 5.6 5.6 0 0 0-10.8-1.3 4.1 4.1 0 0 0-.1 9.3z"/>',
    fog: '<path d="M6.8 15h10.6a4 4 0 0 0 .3-8 5.6 5.6 0 0 0-10.8-1.3 4.1 4.1 0 0 0-.1 9.3z"/><path d="M4 18.5h16M6.5 21.5h11"/>',
    drizzle: '<path d="M6.8 15.5h10.6a4 4 0 0 0 .3-8 5.6 5.6 0 0 0-10.8-1.3 4.1 4.1 0 0 0-.1 9.3z"/><path d="M9 18.5v1.8M13 18.5v2.6M17 18.5v1.8"/>',
    rain: '<path d="M6.8 14.5h10.6a4 4 0 0 0 .3-8 5.6 5.6 0 0 0-10.8-1.3 4.1 4.1 0 0 0-.1 9.3z"/><path d="M8.5 17.5 7 21.5M13 17.5l-1.5 4M17.5 17.5 16 21.5"/>',
    snow: '<path d="M6.8 14.5h10.6a4 4 0 0 0 .3-8 5.6 5.6 0 0 0-10.8-1.3 4.1 4.1 0 0 0-.1 9.3z"/><path d="M8.5 18.2h.01M12 20.2h.01M15.5 18.2h.01M10 21.5h.01M14 17.6h.01"/>',
    storm: '<path d="M6.8 13.5h10.6a4 4 0 0 0 .3-8 5.6 5.6 0 0 0-10.8-1.3 4.1 4.1 0 0 0-.1 9.3z"/><path d="m13 15-3.5 4.5h3L11 23.5"/>'
  };

  var cityInput = $("city");
  cityInput.value = store("jarbai.city", "Manila");

  function renderWeather(d) {
    var box = $("wx");
    box.textContent = "";
    var info = WMO[d.code] || ["conditions unclear", "cloud"];

    var main = el("div", "wx-main");
    var art = el("div", "wx-icon");
    art.innerHTML = '<svg viewBox="0 0 24 24">' + (WX_ART[info[1]] || WX_ART.cloud) + "</svg>";
    main.appendChild(art);

    var txt = el("div");
    var temp = el("div", "wx-temp");
    temp.textContent = Math.round(d.temp);
    var sup = el("sup", null, "°C");
    temp.appendChild(sup);
    txt.appendChild(temp);
    txt.appendChild(el("div", "wx-desc", info[0] + " · " + d.city));
    main.appendChild(txt);
    box.appendChild(main);

    var grid = el("div", "wx-grid");
    [["Feels", Math.round(d.feels) + "°"],
     ["Humidity", Math.round(d.humidity) + "%"],
     ["Wind", Math.round(d.wind) + " km/h"]].forEach(function (pair) {
      var cell = el("div", "wx-cell");
      cell.appendChild(el("span", null, pair[0]));
      cell.appendChild(el("b", null, pair[1]));
      grid.appendChild(cell);
    });
    box.appendChild(grid);
  }

  function loadWeather() {
    var city = (cityInput.value || "Manila").trim();
    $("wx").textContent = "";
    $("wx").appendChild(el("div", "empty", "Contacting weather relay…"));
    fetch("/api/weather?city=" + encodeURIComponent(city), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          $("wx").textContent = "";
          $("wx").appendChild(el("div", "empty", d.error || "Weather unavailable."));
          return;
        }
        save("jarbai.city", city);
        renderWeather(d);
      })
      .catch(function () {
        $("wx").textContent = "";
        $("wx").appendChild(el("div", "empty", "Weather relay unreachable."));
      });
  }

  cityInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); cityInput.blur(); loadWeather(); }
  });
  cityInput.addEventListener("blur", function () {
    if (cityInput.value.trim() !== store("jarbai.city", "Manila")) loadWeather();
  });

  loadWeather();
  setInterval(loadWeather, 600000);

  /* ============================================================ TASKS */
  var tasks = store("jarbai.tasks", []);

  function whenLabel(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var now = new Date();
    var diff = d - now;
    var day = 86400000;
    var sameDay = d.toDateString() === now.toDateString();
    var time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    var cls = diff < 0 ? "past" : diff < 3 * 3600000 ? "soon" : "";
    var text;
    if (sameDay) text = "Today, " + time;
    else if (diff > 0 && diff < 2 * day) text = "Tomorrow, " + time;
    else text = d.toLocaleDateString([], { month: "short", day: "numeric" }) + ", " + time;
    return { text: text, cls: cls };
  }

  function renderTasks() {
    var box = $("tasks");
    box.textContent = "";
    if (!tasks.length) {
      box.appendChild(el("div", "empty", "No tasks logged, sir."));
      return;
    }
    tasks.slice().sort(function (a, b) {
      if (a.done !== b.done) return a.done ? 1 : -1;
      if (!a.when) return 1;
      if (!b.when) return -1;
      return new Date(a.when) - new Date(b.when);
    }).forEach(function (t) {
      var row = el("div", "item" + (t.done ? " done" : ""));

      var chk = el("button", "check");
      chk.title = t.done ? "Mark as pending" : "Mark as complete";
      chk.addEventListener("click", function () {
        t.done = !t.done;
        save("jarbai.tasks", tasks);
        renderTasks();
      });
      row.appendChild(chk);

      var bodyEl = el("div", "item-body");
      bodyEl.appendChild(el("div", "item-text", t.text));
      var w = whenLabel(t.when);
      if (w) bodyEl.appendChild(el("div", "item-when " + (t.done ? "" : w.cls), w.text));
      row.appendChild(bodyEl);

      var del = el("button", "del");
      del.title = "Delete task";
      del.appendChild(icon("x"));
      del.addEventListener("click", function () {
        tasks = tasks.filter(function (x) { return x.id !== t.id; });
        save("jarbai.tasks", tasks);
        renderTasks();
      });
      row.appendChild(del);

      box.appendChild(row);
    });
  }

  $("btnAddTask").addEventListener("click", function () {
    var f = $("taskForm");
    f.hidden = !f.hidden;
    if (!f.hidden) $("taskText").focus();
  });

  $("taskForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var text = $("taskText").value.trim();
    if (!text) return;
    tasks.push({ id: uid(), text: text, when: $("taskWhen").value || "", done: false });
    save("jarbai.tasks", tasks);
    $("taskText").value = "";
    $("taskWhen").value = "";
    $("taskForm").hidden = true;
    renderTasks();
    toast("Task logged.");
  });

  renderTasks();

  /* ============================================================ EVENTS */
  var events = store("jarbai.events", []);
  var MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

  function renderEvents() {
    var box = $("events");
    box.textContent = "";
    var upcoming = events.slice().sort(function (a, b) {
      return new Date(a.when) - new Date(b.when);
    });
    if (!upcoming.length) {
      box.appendChild(el("div", "empty", "Calendar is clear."));
      return;
    }
    upcoming.forEach(function (ev) {
      var d = new Date(ev.when);
      var row = el("div", "item ev");

      var date = el("div", "ev-date");
      date.appendChild(el("b", null, isNaN(d) ? "--" : d.getDate()));
      date.appendChild(el("span", null, isNaN(d) ? "---" : MONTHS[d.getMonth()]));
      row.appendChild(date);

      var bodyEl = el("div", "item-body");
      bodyEl.appendChild(el("div", "item-text", ev.title));
      var w = whenLabel(ev.when);
      if (w) bodyEl.appendChild(el("div", "item-when " + w.cls, w.text));
      row.appendChild(bodyEl);

      var del = el("button", "del");
      del.title = "Delete event";
      del.appendChild(icon("x"));
      del.addEventListener("click", function () {
        events = events.filter(function (x) { return x.id !== ev.id; });
        save("jarbai.events", events);
        renderEvents();
      });
      row.appendChild(del);

      box.appendChild(row);
    });
  }

  $("btnAddEvent").addEventListener("click", function () {
    var f = $("eventForm");
    f.hidden = !f.hidden;
    if (!f.hidden) $("eventText").focus();
  });

  $("eventForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var title = $("eventText").value.trim();
    var when = $("eventWhen").value;
    if (!title || !when) return;
    events.push({ id: uid(), title: title, when: when });
    save("jarbai.events", events);
    $("eventText").value = "";
    $("eventWhen").value = "";
    $("eventForm").hidden = true;
    renderEvents();
    toast("Event added to calendar.");
  });

  renderEvents();
  setInterval(function () { renderTasks(); renderEvents(); }, 60000);

  /* Enter submits from any field in the add rows (including the date input,
     where implicit submission is not guaranteed). */
  document.querySelectorAll(".addrow").forEach(function (form) {
    form.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      e.preventDefault();
      if (form.checkValidity()) form.requestSubmit();
      else form.reportValidity();
    });
  });

  /* ============================================================ BRAIN SWITCH
     auto  - Gemini when online, local model when not
     cloud - always Gemini (fast, needs internet)
     local - always Ollama (private, works offline) */
  var brainBtns = Array.prototype.slice.call(
    document.querySelectorAll("#brainSwitch button"));

  function paintBrain(provider, active, hasKey) {
    brainBtns.forEach(function (b) {
      var p = b.dataset.p;
      b.setAttribute("aria-pressed", p === provider ? "true" : "false");
      // no API key means cloud is not an option
      b.disabled = (p === "cloud" && !hasKey);
      // underline whichever brain actually answered last
      b.classList.toggle("answering", !!active &&
        ((active === "cloud" && p === "cloud") || (active === "local" && p === "local")));
    });
  }

  function loadSettings() {
    fetch("/api/settings", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) return;
        paintBrain(d.provider, d.active, d.hasKey);
        $("brainSwitch").title = d.hasKey
          ? "auto: " + d.cloudModel + " online, " + d.localModel + " offline"
          : "No GEMINI_API_KEY in .env - local only";
      })
      .catch(function () { /* server down; the stats poll already reports it */ });
  }

  brainBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      if (b.disabled) return;
      var provider = b.dataset.p;
      fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: provider })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) { toast(d.error || "Could not switch brain.", true); return; }
          say("sys", "Brain set to " + provider + ", sir.");
          toast("Brain: " + provider.toUpperCase());
          loadSettings();
        })
        .catch(function () { toast("Could not reach the server.", true); });
    });
  });

  /* ============================================================ SETUP PANEL
     Paste an API key here rather than hand-editing .env - which is what makes
     JARBAI portable to another machine. The key is POSTed once, verified
     against Google, and stored server-side; the browser never gets it back. */
  var setup = $("setup");
  var keyInput = $("keyInput");

  function renderStatus(d) {
    var box = $("setupStatus");
    box.textContent = "";

    var cloud = el("span", "chip " + (d.hasKey ? "good" : "bad"));
    cloud.appendChild(el("b", null, "Cloud"));
    cloud.appendChild(document.createTextNode(
      d.hasKey ? "key set " + (d.keyHint || "") : "no API key"));
    box.appendChild(cloud);

    var local = el("span", "chip " + (d.ollamaUp ? "good" : "bad"));
    local.appendChild(el("b", null, "Local"));
    local.appendChild(document.createTextNode(
      d.ollamaUp ? d.localModel + " ready" : "Ollama not running"));
    box.appendChild(local);

    var mode = el("span", "chip");
    mode.appendChild(el("b", null, "Brain"));
    mode.appendChild(document.createTextNode(
      d.provider + (d.active ? " (using " + d.active + ")" : "")));
    box.appendChild(mode);

    keyInput.placeholder = d.hasKey
      ? "Key already set - paste a new one to replace it"
      : "Paste your API key here";
  }

  function openSetup() {
    setup.hidden = false;
    fetch("/api/settings", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(renderStatus)
      .catch(function () { toast("Could not read settings.", true); });
  }

  function closeSetup() {
    setup.hidden = true;
    keyInput.value = "";
    keyInput.type = "password";
    $("keyShow").textContent = "Show";
  }

  $("btnSetup").addEventListener("click", openSetup);
  $("setupClose").addEventListener("click", closeSetup);
  setup.addEventListener("click", function (e) { if (e.target === setup) closeSetup(); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !setup.hidden) closeSetup();
  });

  $("keyShow").addEventListener("click", function () {
    var showing = keyInput.type === "text";
    keyInput.type = showing ? "password" : "text";
    this.textContent = showing ? "Show" : "Hide";
  });

  function sendKey(value, verb) {
    var btn = $("keySave");
    btn.disabled = true;
    btn.textContent = verb;
    return fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geminiKey: value })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { toast(d.error || "That key was rejected.", true); return; }
        toast(d.detail || "Saved.");
        say("sys", d.detail || "API key updated, sir.");
        keyInput.value = "";
        openSetup();
        loadSettings();
      })
      .catch(function () { toast("Could not reach the server.", true); })
      .then(function () { btn.disabled = false; btn.textContent = "SAVE & TEST"; });
  }

  $("keySave").addEventListener("click", function () {
    var value = keyInput.value.trim();
    if (!value) { toast("Paste a key first, sir.", true); return; }
    sendKey(value, "TESTING…");
  });
  keyInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); $("keySave").click(); }
  });

  $("keyClear").addEventListener("click", function () {
    if (!confirm("Remove the stored API key? JARBAI will run on the local brain only.")) return;
    sendKey("", "REMOVING…");
  });

  loadSettings();

  /* ============================================================ CAPABILITIES
     Fetched from /api/skills, the live registry - so the panel and the
     prompt's skill list can never drift apart. Refetched on window focus to
     pick up server-side skill changes. */
  function loadSkills() {
    fetch("/api/skills", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) return;
        var box = $("skills");
        box.textContent = "";
        $("skillCount").textContent = d.skills.length + " ONLINE";
        d.skills.forEach(function (s) {
          var row = el("div", "skill");
          var head = el("div", "skill-name");
          head.appendChild(icon("check", "skill-tick"));
          head.appendChild(el("b", null, s.name));
          row.appendChild(head);
          row.appendChild(el("div", "skill-desc", s.description));
          box.appendChild(row);
        });
      })
      .catch(function () { /* server down - stats poll reports it */ });
  }

  loadSkills();
  window.addEventListener("focus", loadSkills);

  /* ============================================================ REMINDERS */
  function renderRems(list) {
    var box = $("rems");
    box.textContent = "";
    if (!list || !list.length) {
      box.appendChild(el("div", "empty", "No reminders armed, sir."));
      return;
    }
    var now = Date.now();
    list.slice().sort(function (a, b) { return new Date(a.when) - new Date(b.when); })
      .forEach(function (r) {
        var row = el("div", "item rem");
        var left = el("div", "item-body");
        left.appendChild(el("div", "item-text", r.what));
        var when = new Date(r.when);
        var mins = Math.round((when - now) / 60000);
        var eta = mins <= 0 ? "due now" :
          mins < 60 ? "in " + mins + " min" :
          mins < 1440 ? "in " + Math.round(mins / 60) + " h" :
          "in " + Math.round(mins / 1440) + " d";
        left.appendChild(el("div", "item-when " + (mins < 60 ? "soon" : ""), eta));
        row.appendChild(left);
        row.appendChild(icon("clock", "rem-clock"));
        box.appendChild(row);
      });
  }

  function pollRems() {
    fetch("/api/reminders", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d.ok) renderRems(d.reminders); })
      .catch(function () { /* server down */ });
  }

  $("btnAddRem").addEventListener("click", function () {
    var f = $("remForm");
    f.hidden = !f.hidden;
    if (!f.hidden) $("remText").focus();
  });

  $("remForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var text = $("remText").value.trim();
    if (!text) return;
    fetch("/api/reminders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { toast(d.error || "Could not set that reminder.", true); return; }
        $("remText").value = "";
        $("remForm").hidden = true;
        toast("Reminder armed: " + d.what);
        pollRems();
      })
      .catch(function () { toast("Could not reach the server.", true); });
  });

  pollRems();
  setInterval(pollRems, 30000);

  /* Reminders that fire while the dashboard is open are pushed over SSE, so
     they appear (and are spoken) the moment they come due, not on the next
     poll. The stream reconnects itself when the server restarts. */
  var events = new EventSource("/api/events");
  events.addEventListener("reminder", function (e) {
    try {
      var d = JSON.parse(e.data);
      var what = d.what || "your reminder";
      say("sys", "Reminder, sir: " + what);
      toast("Reminder: " + what);
      core.surge(0.8);
      speak("Reminder, sir: " + what);
      pollRems();
    } catch (err) { /* malformed frame - the poll will catch up */ }
  });
  events.onerror = function () { /* EventSource auto-reconnects; nothing to do */ };

  /* ============================================================ SPEECH OUT */
  var ttsOn = store("jarbai.tts", true);
  var speakEnvelope = 0;

  function paintTts() {
    $("btnTts").setAttribute("aria-pressed", ttsOn ? "true" : "false");
    $("btnTts").title = ttsOn ? "Spoken replies on" : "Spoken replies off";
  }
  paintTts();

  $("btnTts").addEventListener("click", function () {
    ttsOn = !ttsOn;
    save("jarbai.tts", ttsOn);
    paintTts();
    if (!ttsOn && window.speechSynthesis) speechSynthesis.cancel();
    toast(ttsOn ? "Spoken replies enabled." : "Spoken replies muted.");
  });

  function pickVoice() {
    if (!window.speechSynthesis) return null;
    var v = speechSynthesis.getVoices();
    return v.find(function (x) { return /en-GB/i.test(x.lang) && /male|ryan|george|daniel/i.test(x.name); })
        || v.find(function (x) { return /en-GB/i.test(x.lang); })
        || v.find(function (x) { return /^en/i.test(x.lang); })
        || null;
  }

  function speak(text) {
    if (!ttsOn || !window.speechSynthesis) { setState("idle"); return; }
    try {
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text);
      var v = pickVoice();
      if (v) u.voice = v;
      u.lang = "en-GB";
      u.rate = 1.06;
      u.pitch = 0.95;
      setState("speaking");
      speakEnvelope = 1;
      suspendAmbient();

      // If no voice or audio device is available, speak() can resolve nothing
      // and onend never fires — don't strand the core in the speaking state.
      var done = false;
      var finish = function () {
        if (done) return;
        done = true;
        clearTimeout(guard);
        speakEnvelope = 0;
        core.setLevel(0);
        setState("idle");
        releaseAmbient();
      };
      var guard = setTimeout(finish, Math.max(5000, text.length * 95));
      u.onend = u.onerror = finish;
      speechSynthesis.speak(u);
    } catch (e) {
      setState("idle");
    }
  }

  if (window.speechSynthesis) speechSynthesis.onvoiceschanged = pickVoice;

  /* ============================================================ ASK (streaming)
     /api/ask replies over server-sent events: "delta" previews stream in as
     the model types, "final" carries the authoritative reply. The fetch-based
     reader below works in every browser, EventSource or not, because the
     POST body needs to carry the question. */
  var busy = false;
  var input = $("input");
  var cmdbar = document.querySelector(".cmdbar");

  input.addEventListener("input", function () {
    cmdbar.classList.toggle("typing", input.value.length > 0);
  });

  function ask(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true;
    input.value = "";
    cmdbar.classList.remove("typing");
    say("you", text);
    setState("thinking");
    core.surge(0.55);

    // a live-updating JARBAI line grows in the feed as deltas arrive
    var line = null, span = null, shown = "";

    function ensureLine() {
      if (line) return;
      line = el("div", "feed-line jarbai streaming");
      line.appendChild(el("b", null, "JARBAI"));
      span = el("span");
      line.appendChild(span);
      feed.appendChild(line);
      feed.scrollTop = feed.scrollHeight;
    }

    function setSpan(text) {
      ensureLine();
      if (text && text !== shown) {
        shown = text;
        span.textContent = text;
        feed.scrollTop = feed.scrollHeight;
      }
    }

    var buffer = "", done = false;

    function readChunk(chunk) {
      // SSE frames arrive as "event: x\ndata: {...}\n\n" - split and parse
      var frames = chunk.split("\n\n");
      for (var i = 0; i < frames.length; i++) {
        var frame = frames[i];
        if (!frame.trim()) continue;
        var ev = "message", data = "";
        frame.split("\n").forEach(function (ln) {
          if (ln.indexOf("event:") === 0) ev = ln.slice(6).trim();
          else if (ln.indexOf("data:") === 0) data += ln.slice(5).trim();
        });
        handleFrame(ev, data);
      }
    }

    function handleFrame(ev, data) {
      if (done) return;
      var d = null;
      try { d = JSON.parse(data); } catch (e) { return; }
      if (ev === "delta") {
        setSpan(d.text);
      } else if (ev === "final") {
        done = true;
        finish(d);
      } else if (ev === "error") {
        done = true;
        if (line) line.remove();
        say("err", d.error || "Request failed.");
        setState("error", 2600);
        busy = false;
      }
    }

    function finish(d) {
      if (line) { line.remove(); line = span = null; }
      say("jarbai", d.reply);
      if (d.brain) loadSettings();
      core.surge(0.5);
      speak(d.reply);
      busy = false;
    }

    fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text })
    }).then(function (r) {
      if (!r.body || !r.body.getReader) return r.json().then(function (d) {
        if (!d.ok) { say("err", d.error || "Request failed."); setState("error", 2600); }
        else finish(d);
        busy = false;
      });
      var reader = r.body.getReader();
      var decoder = new TextDecoder();
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) {
            if (!done) {
              done = true;
              if (line) { line.remove(); line = null; }
              say("err", "The stream closed before a reply arrived, sir.");
              setState("error", 2600);
              busy = false;
            }
            return;
          }
          buffer += decoder.decode(res.value, { stream: true });
          readChunk(buffer);
          buffer = buffer.slice(buffer.lastIndexOf("\n\n") + 2);
          pump();
        });
      }
      pump().catch(function () {
        if (!done) { done = true; busy = false; setState("error", 2600); }
      });
    }).catch(function () {
      busy = false;
      say("err", "Dashboard link severed. Is the server still running, sir?");
      setState("error", 2600);
    });
  }

  $("btnSend").addEventListener("click", function () { ask(input.value); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); ask(input.value); }
  });

  /* ============================================================ QUICK COMMANDS */
  document.querySelectorAll(".cmd").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var action = btn.dataset.action;
      if (action === "lock" && !confirm("Lock the workstation now?")) return;

      btn.classList.add("busy");
      core.surge(0.4);

      fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          btn.classList.remove("busy");
          if (d.ok) {
            say("sys", d.detail);
            toast(d.detail);
          } else {
            say("err", d.error || "Command failed.");
            toast(d.error || "Command failed.", true);
            setState("error", 2000);
          }
        })
        .catch(function () {
          btn.classList.remove("busy");
          toast("Command channel unreachable.", true);
          setState("error", 2000);
        });
    });
  });

  /* ============================================================ SPEECH IN */
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var recog = null;
  var listening = false;
  var micBtns = [$("btnMic"), $("btnMicTop")];

  var audioCtx = null, analyser = null, micData = null, micStream = null;

  function paintMic() {
    micBtns.forEach(function (b) { b.classList.toggle("live", listening); });
  }

  function startMeter() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    if (analyser) return;
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(function (stream) {
        micStream = stream;
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        var src = audioCtx.createMediaStreamSource(stream);
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.75;
        micData = new Uint8Array(analyser.fftSize);
        src.connect(analyser);
      })
      .catch(function () { /* mic denied — waveform stays synthetic */ });
  }

  function stopMeter() {
    if (micStream) micStream.getTracks().forEach(function (t) { t.stop(); });
    if (audioCtx) audioCtx.close();
    micStream = null; audioCtx = null; analyser = null; micData = null;
    core.setLevel(0);
  }

  function stopListening() {
    listening = false;
    paintMic();
    stopMeter();
    if (recog) { try { recog.stop(); } catch (e) { /* already stopped */ } }
    if (body.dataset.state === "listening") setState("idle");
    if (ambientOn) startWake();       // hand the mic back to ambient mode
  }

  function startListening() {
    if (!SR) {
      toast("This browser has no speech recognition. Type instead, sir.", true);
      return;
    }
    if (listening) { stopListening(); return; }
    stopWake();      // only one recogniser may hold the mic at a time

    recog = new SR();
    recog.lang = "en-GB";
    recog.interimResults = true;
    recog.continuous = false;
    recog.maxAlternatives = 1;

    recog.onstart = function () {
      listening = true;
      paintMic();
      setState("listening");
      startMeter();
    };
    recog.onresult = function (e) {
      var text = "";
      var isFinal = false;
      for (var i = e.resultIndex; i < e.results.length; i++) {
        text += e.results[i][0].transcript;
        if (e.results[i].isFinal) isFinal = true;
      }
      input.value = text;
      cmdbar.classList.toggle("typing", text.length > 0);
      if (isFinal && text.trim()) {
        stopListening();
        ask(text);
      }
    };
    recog.onerror = function (e) {
      stopListening();
      if (e.error === "not-allowed") toast("Microphone access denied.", true);
      else if (e.error !== "aborted" && e.error !== "no-speech") toast("Voice channel error: " + e.error, true);
    };
    recog.onend = function () { if (listening) stopListening(); };

    try { recog.start(); } catch (e) { stopListening(); }
  }

  micBtns.forEach(function (b) { b.addEventListener("click", startListening); });
  if (!SR) micBtns.forEach(function (b) { b.classList.add("off"); b.title = "Speech recognition unavailable in this browser"; });

  /* ============================================================ AMBIENT MODE
     Always on, so there is no mic button to press back-to-back. Two triggers
     share one microphone:
       - continuous speech recognition, matched against the wake words
       - a snap detector watching for a sharp broadband transient

     Both are suspended while JARBAI is speaking. Without that it hears its own
     reply through the speakers and answers itself in a loop. */

  // "Jarbai" is not a dictionary word, so the recogniser mangles it — accept
  // the near-misses it actually produces rather than only the exact spelling.
  var WAKE_WORDS = ["jarbai", "jarbi", "jar bai", "jar by", "jar bye", "jarvai", "jarvis", "jarvi", "job ai", "jabai"];

  var ambientOn = store("jarbai.ambient", true);   // on by default
  var wakeRecog = null;
  var wakeTimer = null;
  var watchdog = null;
  var suspended = 0;

  // snap detector state
  var snapCtx = null, snapAnalyser = null, snapStream = null;
  var snapTime = null, snapFreq = null;
  var snapBaseline = 0.02, lastSnap = 0, snapRaf = null;

  // Live-tunable from the console: JARBAI.snap.minRms = 0.2, JARBAI.snap.debug = true
  window.JARBAI = window.JARBAI || {};
  window.JARBAI.snap = { minPeak: 0.25, minCrest: 6.0, minHigh: 0.45, overBaseline: 4.0, debug: false };

  function commandAfterWake(transcript) {
    var lower = transcript.toLowerCase();
    for (var i = 0; i < WAKE_WORDS.length; i++) {
      var at = lower.indexOf(WAKE_WORDS[i]);
      if (at === -1) continue;
      return transcript.slice(at + WAKE_WORDS[i].length).replace(/^[\s,.:;!?-]+/, "").trim();
    }
    return null;   // wake word not spoken — ignore the utterance entirely
  }

  function paintAmbient() {
    var b = $("btnWake");
    b.setAttribute("aria-pressed", ambientOn ? "true" : "false");
    b.classList.toggle("live", ambientOn && !suspended);
    b.title = ambientOn
      ? 'Ambient mode on — say "Jarbai ..." or snap. Click to stop.'
      : "Ambient mode off — click to always listen";
  }

  /* ---- continuous speech recognition ---- */
  function startWake() {
    if (!SR || wakeRecog || !ambientOn || suspended || listening) return;
    wakeRecog = new SR();
    wakeRecog.lang = "en-GB";
    wakeRecog.continuous = true;
    wakeRecog.interimResults = false;
    wakeRecog.onresult = function (e) {
      for (var i = e.resultIndex; i < e.results.length; i++) {
        if (!e.results[i].isFinal) continue;
        var cmd = commandAfterWake(e.results[i][0].transcript);
        if (cmd === null) continue;
        if (cmd) ask(cmd);
        else say("sys", "Yes, sir?");
      }
    };
    wakeRecog.onerror = function (e) {
      if (e.error === "not-allowed") {
        // Don't persist this: a one-off denial (or a browser that blocks
        // capture entirely) must not disable ambient mode forever. Stop for
        // this session only, so a reload with permission granted resumes.
        setAmbient(false, false);
        toast("Microphone blocked — ambient mode paused for this session.", true);
      }
    };
    // Chrome/Edge end continuous recognition after a silence; restart it.
    wakeRecog.onend = function () {
      wakeRecog = null;
      if (ambientOn && !suspended && !listening) wakeTimer = setTimeout(startWake, 350);
    };
    try { wakeRecog.start(); } catch (e) { wakeRecog = null; }
    paintAmbient();
  }

  function stopWake() {
    clearTimeout(wakeTimer);
    var r = wakeRecog;
    wakeRecog = null;
    if (r) { r.onend = null; try { r.stop(); } catch (e) { /* already stopped */ } }
  }

  /* Suspend/resume as a counter, so speaking and push-to-talk can overlap
     without one of them resuming the mic while the other still needs it. */
  function suspendAmbient() {
    suspended++;
    stopWake();
    paintAmbient();
  }

  function releaseAmbient() {
    suspended = Math.max(0, suspended - 1);
    if (!suspended) startWake();
    paintAmbient();
  }

  /* ---- snap detector ---- */
  function onSnap() {
    if (listening || suspended) return;
    say("sys", "Yes, sir?");
    core.surge(0.5);
    startListening();          // capture the command that follows the snap
  }

  function snapTick() {
    if (!snapAnalyser) return;
    snapRaf = requestAnimationFrame(snapTick);

    snapAnalyser.getByteTimeDomainData(snapTime);
    snapAnalyser.getByteFrequencyData(snapFreq);

    var sum = 0, peak = 0, i;
    for (i = 0; i < snapTime.length; i++) {
      var v = (snapTime[i] - 128) / 128;
      sum += v * v;
      var a = v < 0 ? -v : v;
      if (a > peak) peak = a;
    }
    var rms = Math.sqrt(sum / snapTime.length);
    // A snap lasts ~5-10ms inside a ~21ms analysis window, so its RMS is
    // diluted and reads quiet. Peak and crest factor (peak/rms) are what
    // separate an impulse from sustained speech.
    var crest = peak / Math.max(rms, 1e-6);

    // A snap is broadband and bright; speech is concentrated much lower.
    var bin = snapCtx.sampleRate / snapAnalyser.fftSize;   // Hz per bin
    var cut = Math.floor(2000 / bin);
    var hi = 0, all = 0;
    for (i = 1; i < snapFreq.length; i++) {
      all += snapFreq[i];
      if (i >= cut) hi += snapFreq[i];
    }
    var high = all > 0 ? hi / all : 0;

    var cfg = window.JARBAI.snap;
    var now = performance.now();
    var spike = peak > cfg.minPeak && peak > snapBaseline * cfg.overBaseline;

    if (cfg.debug && peak > 0.08) {
      console.log("peak", peak.toFixed(3), "crest", crest.toFixed(1),
                  "high", high.toFixed(2), "base", snapBaseline.toFixed(3));
    }
    if (spike && crest > cfg.minCrest && high > cfg.minHigh && now - lastSnap > 900) {
      lastSnap = now;
      onSnap();
    }
    // slow EMA on peak, and never let the spike itself raise the floor
    if (!spike) snapBaseline = snapBaseline * 0.94 + peak * 0.06;
  }

  function startSnap() {
    if (snapCtx || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    navigator.mediaDevices.getUserMedia({
      // AGC/noise suppression flatten exactly the transient we look for
      audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false }
    }).then(function (stream) {
      if (!ambientOn) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      snapStream = stream;
      snapCtx = new (window.AudioContext || window.webkitAudioContext)();
      var src = snapCtx.createMediaStreamSource(stream);
      snapAnalyser = snapCtx.createAnalyser();
      snapAnalyser.fftSize = 1024;
      snapAnalyser.smoothingTimeConstant = 0;   // transients, not averages
      snapTime = new Uint8Array(snapAnalyser.fftSize);
      snapFreq = new Uint8Array(snapAnalyser.frequencyBinCount);
      src.connect(snapAnalyser);
      snapTick();
    }).catch(function () { /* denied — wake word alone still works */ });
  }

  function stopSnap() {
    if (snapRaf) cancelAnimationFrame(snapRaf);
    snapRaf = null;
    if (snapStream) snapStream.getTracks().forEach(function (t) { t.stop(); });
    if (snapCtx) snapCtx.close();
    snapCtx = snapAnalyser = snapStream = snapTime = snapFreq = null;
  }

  /* ---- on/off ---- */
  function setAmbient(on, persist) {
    ambientOn = on;
    if (persist !== false) save("jarbai.ambient", on);
    suspended = 0;
    paintAmbient();
    if (on) {
      startWake();
      startSnap();
      clearInterval(watchdog);
      // Browsers stop recognition silently (tab backgrounded, device hiccup).
      // Poll so ambient mode cannot quietly die and leave you pressing buttons.
      watchdog = setInterval(function () {
        if (ambientOn && !suspended && !listening && !wakeRecog) startWake();
      }, 4000);
      say("sys", 'Ambient mode on. Say "Jarbai", or snap, sir.');
    } else {
      clearInterval(watchdog);
      stopWake();
      stopSnap();
      say("sys", "Ambient mode off, sir.");
    }
  }

  $("btnWake").addEventListener("click", function () {
    if (!SR) { toast("This browser has no speech recognition, sir.", true); return; }
    setAmbient(!ambientOn);
  });

  if (!SR) $("btnWake").classList.add("off");
  paintAmbient();
  if (ambientOn && SR) {
    // give the page a moment before grabbing the microphone on load
    setTimeout(function () { startWake(); startSnap();
      watchdog = setInterval(function () {
        if (ambientOn && !suspended && !listening && !wakeRecog) startWake();
      }, 4000);
    }, 800);
  }

  /* ============================================================ WAVEFORM */
  var wave = $("wave");
  var wctx = wave.getContext("2d");
  var wdpr = Math.min(window.devicePixelRatio || 1, 2);
  var smooth = [];

  function sizeWave() {
    var r = wave.getBoundingClientRect();
    if (!r.width) return;
    wave.width = Math.round(r.width * wdpr);
    wave.height = Math.round(r.height * wdpr);
    wctx.setTransform(wdpr, 0, 0, wdpr, 0, 0);
  }
  sizeWave();
  window.addEventListener("resize", sizeWave);
  new ResizeObserver(sizeWave).observe(wave);

  var wt = 0;
  var accentRgb = "34, 211, 238";
  var accentFor = "";

  function drawWave(now) {
    requestAnimationFrame(drawWave);
    var r = wave.getBoundingClientRect();
    var W = r.width, H = r.height;
    if (!W || !H) return;

    wt += 0.016;
    var state = body.dataset.state;

    // the accent only changes with state — no need to hit the cascade every frame
    if (state !== accentFor) {
      accentFor = state;
      accentRgb = getComputedStyle(body).getPropertyValue("--accent-rgb").trim() || accentRgb;
    }
    var css = accentRgb;

    var count = Math.max(24, Math.floor(W / 4));
    var level = 0;

    if (analyser && micData) {
      analyser.getByteTimeDomainData(micData);
      var sum = 0;
      for (var i = 0; i < micData.length; i++) {
        var v = (micData[i] - 128) / 128;
        sum += v * v;
      }
      level = Math.min(1, Math.sqrt(sum / micData.length) * 3.4);
    } else if (state === "speaking") {
      speakEnvelope = 0.55 + Math.sin(wt * 9) * 0.2 + Math.sin(wt * 23) * 0.12;
      level = Math.max(0, speakEnvelope);
    } else if (state === "thinking") {
      level = 0.34;
    } else {
      level = 0.09;
    }

    core.setLevel(level);

    wctx.clearRect(0, 0, W, H);
    var mid = H / 2;

    for (var b = 0; b < count; b++) {
      var f = b / (count - 1);
      // taper the ends so the trace fades into the bar
      var edge = Math.sin(f * Math.PI);
      var amp;

      if (state === "thinking") {
        // scanning sweep
        var head = (wt * 0.55) % 1;
        var dist = Math.abs(f - head);
        dist = Math.min(dist, 1 - dist);
        amp = Math.exp(-dist * 14) * 0.9 + 0.05;
      } else {
        amp = (
          Math.sin(f * 15 + wt * 6) * 0.5 +
          Math.sin(f * 27 - wt * 9) * 0.3 +
          Math.sin(f * 41 + wt * 13) * 0.2
        );
        amp = Math.abs(amp) * level;
      }

      var target = amp * edge * (H * 0.42) + 1;
      smooth[b] = smooth[b] == null ? target : smooth[b] + (target - smooth[b]) * 0.35;

      var h = smooth[b];
      var x = f * (W - 2) + 1;
      var alpha = 0.25 + edge * 0.5 * (0.35 + level);

      wctx.strokeStyle = "rgba(" + css + "," + alpha.toFixed(3) + ")";
      wctx.lineWidth = 1.6;
      wctx.beginPath();
      wctx.moveTo(x, mid - h);
      wctx.lineTo(x, mid + h);
      wctx.stroke();
    }
  }
  requestAnimationFrame(drawWave);

  /* ============================================================ SHORTCUTS */
  document.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (e.key === "/" && !typing) { e.preventDefault(); input.focus(); }
    else if (e.key.toLowerCase() === "m" && e.ctrlKey) { e.preventDefault(); startListening(); }
    else if (e.key === "Escape") {
      if (listening) stopListening();
      else document.activeElement.blur();
    }
  });

  /* ============================================================ BOOT */
  say("sys", "Neural core online. All systems nominal, sir.");
  setState("idle");
  setTimeout(function () { core.surge(0.9); }, 350);
})();
