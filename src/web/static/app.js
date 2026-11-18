const el = (id) => document.getElementById(id);

const INTERRUPT_REGEX = /\b(stop|stopp|forget it|vergiss es|cancel|abbrechen|ruhe|halt)\b/i;
let recognition = null;
let micActive = false;

function appendLog(sender, text, meta = "") {
  const box = el("chat-log");
  const item = document.createElement("div");
  item.style.marginBottom = "8px";
  item.innerHTML = `<strong>${sender}:</strong> ${text} <span style="color:#94a3b8;font-size:0.8em">${meta}</span>`;
  box.appendChild(item);
  box.scrollTop = box.scrollHeight;
}

function stopBrowserSpeech() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}

function speakChunks(chunks, lang) {
  if (!el("tts-toggle").checked || !("speechSynthesis" in window) || !chunks || !chunks.length) {
    return;
  }
  stopBrowserSpeech();
  const locale = lang === "en" ? "en-US" : "de-DE";
  for (const chunk of chunks) {
    const utter = new SpeechSynthesisUtterance(chunk);
    utter.lang = locale;
    window.speechSynthesis.speak(utter);
  }
}

async function triggerInterrupt(reason = "dashboard_stop_button") {
  stopBrowserSpeech();
  const res = await fetch("/api/interrupt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  }).then((r) => r.json());
  appendLog("System", `Interrupted immediately (dropped ${res.dropped_chunks} TTS chunks)`);
  refreshAll();
}

async function submitCommand(text) {
  const cleaned = text.trim();
  if (!cleaned) return;
  if (INTERRUPT_REGEX.test(cleaned)) {
    appendLog("You", cleaned);
    await triggerInterrupt("voice_or_text_stop");
    return;
  }

  appendLog("You", cleaned);
  const res = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: cleaned,
      require_wake_word: el("wake-toggle").checked,
      passphrase: el("passphrase-input").value || null,
      language: el("lang-select").value,
    }),
  }).then((r) => r.json());

  appendLog("Alfred", res.reply, `[${res.route} | beeps: ${res.beeps_played.join(",") || "none"}]`);
  if (res.interrupted) {
    stopBrowserSpeech();
  } else if (res.accepted) {
    speakChunks(res.tts_chunks && res.tts_chunks.length ? res.tts_chunks : [res.reply], res.language);
  }
  refreshAll();
}

async function refreshAll() {
  const [statusRes, memRes, skillRes] = await Promise.all([
    fetch("/api/status").then((r) => r.json()),
    fetch("/api/memories").then((r) => r.json()),
    fetch("/api/skills").then((r) => r.json()),
  ]);

  el("state-badge").textContent = statusRes.state.toUpperCase();
  el("audio-status").innerHTML = `Mic: <strong>${statusRes.devices.active_input_id || "none"}</strong><br/>Speaker: <strong>${statusRes.devices.active_output_id || "none"}</strong>`;
  el("sys-status").innerHTML = `CPU: <strong>${statusRes.cpu_percent}%</strong> | Lang: <strong>${statusRes.language}</strong> | Hermes: <strong>${statusRes.hermes_enabled}</strong>`;

  el("memories-list").innerHTML = memRes.memories.length
    ? memRes.memories.map((m) => `<div>• <b>${m.key}</b>: ${m.value}</div>`).join("")
    : "<div style='color:#94a3b8'>No memories saved yet.</div>";

  el("skills-list").innerHTML = skillRes.skills.length
    ? skillRes.skills.map((s) => `<div>• <b>${s.name}</b> (${s.http_method} ${s.endpoint_url})</div>`).join("")
    : "<div style='color:#94a3b8'>No custom skills learned yet.</div>";
}

function connectTelemetryStream() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  try {
    const ws = new WebSocket(`${proto}//${location.host}/api/stream`);
    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "interrupt") {
        stopBrowserSpeech();
      }
      if (payload.state) {
        el("state-badge").textContent = String(payload.state).toUpperCase();
      }
    };
  } catch (_) {
    // Graceful fallback to periodic HTTP polling
  }
}

el("mic-btn").addEventListener("click", () => {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) {
    appendLog("System", "Browser Web Speech API not supported here; use Chrome/Edge or text input.");
    return;
  }
  if (micActive && recognition) {
    micActive = false;
    recognition.stop();
    el("mic-btn").textContent = "🎤 Voice Mic";
    return;
  }

  recognition = new SpeechRec();
  recognition.lang = el("lang-select").value === "en" ? "en-US" : "de-DE";
  recognition.continuous = true;
  recognition.interimResults = false;

  recognition.onresult = (event) => {
    const latest = event.results[event.results.length - 1];
    if (latest && latest.isFinal) {
      submitCommand(latest[0].transcript);
    }
  };
  recognition.onerror = (ev) => {
    appendLog("Audio", `Mic listener stopped (${ev.error})`);
    micActive = false;
    el("mic-btn").textContent = "🎤 Voice Mic";
  };
  recognition.onend = () => {
    if (micActive) {
      recognition.start();
    }
  };

  micActive = true;
  recognition.start();
  el("mic-btn").textContent = "🔴 Listening...";
});

el("send-btn").addEventListener("click", () => {
  const text = el("cmd-input").value;
  el("cmd-input").value = "";
  submitCommand(text);
});

el("cmd-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    const text = el("cmd-input").value;
    el("cmd-input").value = "";
    submitCommand(text);
  }
});

el("interrupt-btn").addEventListener("click", () => triggerInterrupt("dashboard_stop_button"));

el("smart-audio-btn").addEventListener("click", async () => {
  await fetch("/api/devices/smart-select", { method: "POST" });
  refreshAll();
});

el("soundcheck-btn").addEventListener("click", async () => {
  const res = await fetch("/api/devices/soundcheck", { method: "POST" }).then((r) => r.json());
  appendLog("Audio", `Soundcheck passed=${res.passed}, speaker=${res.selected_device_id} (score ${res.score})`);
  refreshAll();
});

el("update-personality-btn").addEventListener("click", async () => {
  const tone = el("personality-tone").value.trim();
  if (!tone) return;
  await fetch("/api/personality", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tone }),
  });
  el("personality-tone").value = "";
  refreshAll();
});

refreshAll();
connectTelemetryStream();
setInterval(refreshAll, 5000);
