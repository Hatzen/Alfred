const el = (id) => document.getElementById(id);

function appendLog(sender, text, meta = "") {
  const box = el("chat-log");
  const item = document.createElement("div");
  item.style.marginBottom = "8px";
  item.innerHTML = `<strong>${sender}:</strong> ${text} <span style="color:#94a3b8;font-size:0.8em">${meta}</span>`;
  box.appendChild(item);
  box.scrollTop = box.scrollHeight;
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

el("send-btn").addEventListener("click", async () => {
  const text = el("cmd-input").value.trim();
  if (!text) return;
  appendLog("You", text);
  el("cmd-input").value = "";

  const res = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      require_wake_word: el("wake-toggle").checked,
      passphrase: el("passphrase-input").value || null,
      language: el("lang-select").value,
    }),
  }).then((r) => r.json());

  appendLog("Alfred", res.reply, `[${res.route} | beeps: ${res.beeps_played.join(",") || "none"}]`);
  refreshAll();
});

el("interrupt-btn").addEventListener("click", async () => {
  const res = await fetch("/api/interrupt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: "dashboard_stop_button" }),
  }).then((r) => r.json());
  appendLog("System", `Interrupted immediately (dropped ${res.dropped_chunks} TTS chunks)`);
  refreshAll();
});

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
setInterval(refreshAll, 5000);

