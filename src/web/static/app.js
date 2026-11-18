const el = (id) => document.getElementById(id);

const INTERRUPT_REGEX = /\b(stop|stopp|forget it|vergiss es|cancel|abbrechen|ruhe|halt)\b/i;

let activeTtsAudio = null;
let browserRecState = null;
let selectedMicChoice = localStorage.getItem("alfred_mic_choice") || "";
let selectedSpeakerChoice = localStorage.getItem("alfred_speaker_choice") || "";

function appendLog(sender, text, meta = "") {
  const box = el("chat-log");
  const item = document.createElement("div");
  item.style.marginBottom = "8px";
  item.innerHTML = `<strong>${sender}:</strong> ${text} <span style="color:#94a3b8;font-size:0.8em">${meta}</span>`;
  box.appendChild(item);
  box.scrollTop = box.scrollHeight;
}

function updateSecureContextHint() {
  const hint = el("mic-context-hint");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    hint.style.display = "block";
    hint.innerHTML =
      `Browser microphone API is disabled on this origin (<code>${location.origin}</code> is not localhost/HTTPS). ` +
      `Choose a <strong>[Host]</strong> microphone in the dropdown to record directly on the server, ` +
      `open via <code>http://localhost:${location.port || 8020}</code>, or whitelist <code>${location.origin}</code> in ` +
      `<code>chrome://flags/#unsafely-treat-insecure-origin-as-secure</code>.`;
  } else {
    hint.style.display = "none";
  }
}

function stopBrowserSpeech() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
  if (activeTtsAudio) {
    activeTtsAudio.pause();
    activeTtsAudio = null;
  }
}

async function speakChunks(chunks, lang) {
  if (!el("tts-toggle").checked || !chunks || !chunks.length) {
    return;
  }
  stopBrowserSpeech();

  // If a specific browser speaker is chosen and setSinkId is supported, play LocalAI TTS WAV there.
  if (selectedSpeakerChoice.startsWith("browser:")) {
    const sinkId = selectedSpeakerChoice.slice("browser:".length);
    try {
      const resp = await fetch("/api/tts/audio", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: chunks.join(" "), language: lang }),
      });
      if (resp.ok && resp.headers.get("X-Alfred-TTS-Provider") === "localai-tts") {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        if (typeof audio.setSinkId === "function" && sinkId) {
          await audio.setSinkId(sinkId);
        }
        activeTtsAudio = audio;
        audio.onended = () => URL.revokeObjectURL(url);
        await audio.play();
        return;
      }
    } catch (_) {
      // Fall through to Web Speech synthesis
    }
  }

  if ("speechSynthesis" in window) {
    const locale = lang === "en" ? "en-US" : "de-DE";
    for (const chunk of chunks) {
      const utter = new SpeechSynthesisUtterance(chunk);
      utter.lang = locale;
      window.speechSynthesis.speak(utter);
    }
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

function handleAssistantReply(res) {
  if (!res) return;
  appendLog("Alfred", res.reply, `[${res.route} | beeps: ${(res.beeps_played || []).join(",") || "none"}]`);
  if (res.interrupted) {
    stopBrowserSpeech();
  } else if (res.accepted) {
    speakChunks(res.tts_chunks && res.tts_chunks.length ? res.tts_chunks : [res.reply], res.language);
  }
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

  handleAssistantReply(res);
  refreshAll();
}

async function enumerateBrowserAudio(askPermission = false) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    return { inputs: [], outputs: [] };
  }
  if (askPermission && navigator.mediaDevices.getUserMedia) {
    try {
      const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      tempStream.getTracks().forEach((t) => t.stop());
    } catch (_) {
      // Permission denied or unavailable; still enumerate whatever labels exist
    }
  }
  const list = await navigator.mediaDevices.enumerateDevices();
  return {
    inputs: list.filter((d) => d.kind === "audioinput"),
    outputs: list.filter((d) => d.kind === "audiooutput"),
  };
}

function populateDeviceDropdowns(hostDevices, browserDevices) {
  const micSel = el("mic-select");
  const spkSel = el("speaker-select");

  const prevMic = selectedMicChoice || micSel.value;
  const prevSpk = selectedSpeakerChoice || spkSel.value;

  micSel.innerHTML = "";
  const hostInGroup = document.createElement("optgroup");
  hostInGroup.label = "Host Microphones (Server / Spark)";
  for (const d of hostDevices.inputs || []) {
    const opt = document.createElement("option");
    opt.value = `host:${d.device_id}`;
    opt.textContent = `[Host] ${d.name}${d.device_id === hostDevices.active_input_id ? " ★" : ""}`;
    hostInGroup.appendChild(opt);
  }
  micSel.appendChild(hostInGroup);

  if (browserDevices.inputs.length) {
    const brInGroup = document.createElement("optgroup");
    brInGroup.label = "Browser Microphones (Local PC)";
    browserDevices.inputs.forEach((d, idx) => {
      const opt = document.createElement("option");
      opt.value = `browser:${d.deviceId}`;
      opt.textContent = `[Browser] ${d.label || `Microphone ${idx + 1}`}`;
      brInGroup.appendChild(opt);
    });
    micSel.appendChild(brInGroup);
  }

  spkSel.innerHTML = "";
  const hostOutGroup = document.createElement("optgroup");
  hostOutGroup.label = "Host Speakers (Server / Spark)";
  for (const d of hostDevices.outputs || []) {
    const opt = document.createElement("option");
    opt.value = `host:${d.device_id}`;
    opt.textContent = `[Host] ${d.name}${d.device_id === hostDevices.active_output_id ? " ★" : ""}`;
    hostOutGroup.appendChild(opt);
  }
  spkSel.appendChild(hostOutGroup);

  if (browserDevices.outputs.length) {
    const brOutGroup = document.createElement("optgroup");
    brOutGroup.label = "Browser Speakers (Local PC)";
    browserDevices.outputs.forEach((d, idx) => {
      const opt = document.createElement("option");
      opt.value = `browser:${d.deviceId}`;
      opt.textContent = `[Browser] ${d.label || `Speaker ${idx + 1}`}`;
      brOutGroup.appendChild(opt);
    });
    spkSel.appendChild(brOutGroup);
  }

  const pickOption = (selectEl, savedVal, hostFallback) => {
    const options = Array.from(selectEl.options);
    if (savedVal && options.some((o) => o.value === savedVal)) {
      selectEl.value = savedVal;
      return selectEl.value;
    }
    if (hostFallback && options.some((o) => o.value === `host:${hostFallback}`)) {
      selectEl.value = `host:${hostFallback}`;
      return selectEl.value;
    }
    return selectEl.value;
  };

  selectedMicChoice = pickOption(micSel, prevMic, hostDevices.active_input_id);
  selectedSpeakerChoice = pickOption(spkSel, prevSpk, hostDevices.active_output_id);
}

async function refreshAll(askBrowserMicPermission = false) {
  updateSecureContextHint();
  const [statusRes, memRes, skillRes, browserDevices] = await Promise.all([
    fetch("/api/status").then((r) => r.json()),
    fetch("/api/memories").then((r) => r.json()),
    fetch("/api/skills").then((r) => r.json()),
    enumerateBrowserAudio(askBrowserMicPermission),
  ]);

  el("state-badge").textContent = statusRes.state.toUpperCase();
  el("audio-status").innerHTML =
    `Host Mic: <strong>${statusRes.devices.active_input_id || "none"}</strong><br/>` +
    `Host Speaker: <strong>${statusRes.devices.active_output_id || "none"}</strong>`;
  el("sys-status").innerHTML =
    `CPU: <strong>${statusRes.cpu_percent}%</strong> | Lang: <strong>${statusRes.language}</strong> | Hermes: <strong>${statusRes.hermes_enabled}</strong>`;

  populateDeviceDropdowns(statusRes.devices, browserDevices);

  el("memories-list").innerHTML = memRes.memories.length
    ? memRes.memories.map((m) => `<div>• <b>${m.key}</b>: ${m.value}</div>`).join("")
    : "<div style='color:#94a3b8'>No memories saved yet.</div>";

  el("skills-list").innerHTML = skillRes.skills.length
    ? skillRes.skills.map((s) => `<div>• <b>${s.name}</b> (${s.http_method} ${s.endpoint_url})</div>`).join("")
    : "<div style='color:#94a3b8'>No custom skills learned yet.</div>";
}

function encodeMono16kWavBase64(chunks, inputSampleRate) {
  const totalLen = chunks.reduce((acc, c) => acc + c.length, 0);
  const merged = new Float32Array(totalLen);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }

  const targetRate = 16000;
  const ratio = inputSampleRate / targetRate;
  const outLen = Math.max(1, Math.round(merged.length / ratio));
  const pcm = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const sample = merged[Math.min(merged.length - 1, Math.floor(i * ratio))];
    const clamped = Math.max(-1, Math.min(1, sample));
    pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }

  const buffer = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buffer);
  const writeStr = (pos, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(pos + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + pcm.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, targetRate, true);
  view.setUint32(28, targetRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, pcm.length * 2, true);
  new Uint8Array(buffer, 44).set(new Uint8Array(pcm.buffer));

  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function stopBrowserRecordingAndSend() {
  if (!browserRecState) return;
  const { stream, audioCtx, processor, source, muteGain, chunks } = browserRecState;
  browserRecState = null;
  el("mic-btn").textContent = "🎤 Voice Mic";

  processor.disconnect();
  source.disconnect();
  if (muteGain) muteGain.disconnect();
  stream.getTracks().forEach((t) => t.stop());
  const sampleRate = audioCtx.sampleRate || 48000;
  await audioCtx.close();

  const b64 = encodeMono16kWavBase64(chunks, sampleRate);
  appendLog("Audio", "Transcribing microphone audio via LocalAI STT...");
  const res = await fetch("/api/voice/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      audio_base64: b64,
      require_wake_word: el("wake-toggle").checked,
      passphrase: el("passphrase-input").value || null,
      language: el("lang-select").value,
    }),
  }).then((r) => r.json());

  if (res.transcription) {
    appendLog("You (Mic)", res.transcription, `[${res.stt_provider}]`);
    handleAssistantReply(res.assistant);
  } else {
    appendLog("Audio", res.error || "No transcription received from LocalAI STT.");
  }
  refreshAll();
}

async function handleVoiceMicClick() {
  if (browserRecState) {
    await stopBrowserRecordingAndSend();
    return;
  }

  const useHostMic =
    selectedMicChoice.startsWith("host:") ||
    !navigator.mediaDevices ||
    !navigator.mediaDevices.getUserMedia;

  if (useHostMic) {
    el("mic-btn").textContent = "🔴 Recording Host Mic...";
    try {
      const res = await fetch("/api/voice/listen-host", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          duration_ms: 3500,
          require_wake_word: el("wake-toggle").checked,
          passphrase: el("passphrase-input").value || null,
          language: el("lang-select").value,
        }),
      }).then((r) => r.json());
      if (res.transcription) {
        appendLog("You (Host Mic)", res.transcription, `[${res.stt_provider}]`);
        handleAssistantReply(res.assistant);
      } else {
        appendLog("Audio", res.error || res.detail || "No speech transcribed from host mic.");
      }
    } finally {
      el("mic-btn").textContent = "🎤 Voice Mic";
      refreshAll();
    }
    return;
  }

  try {
    const devId = selectedMicChoice.startsWith("browser:")
      ? selectedMicChoice.slice("browser:".length)
      : "";
    const constraints = {
      audio: devId && devId !== "default" ? { deviceId: { exact: devId } } : true,
    };
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const audioCtx = new AudioCtx();
    const source = audioCtx.createMediaStreamSource(stream);
    const processor = audioCtx.createScriptProcessor(4096, 1, 1);
    const muteGain = audioCtx.createGain();
    muteGain.gain.value = 0;
    const chunks = [];
    processor.onaudioprocess = (ev) => {
      chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
    };
    source.connect(processor);
    processor.connect(muteGain);
    muteGain.connect(audioCtx.destination);
    browserRecState = { stream, audioCtx, processor, source, muteGain, chunks };
    el("mic-btn").textContent = "⏹️ Stop & Send";
  } catch (err) {
    appendLog("Audio", `Could not open browser microphone (${err.message}). Try selecting a [Host] microphone.`);
  }
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

el("mic-select").addEventListener("change", async (ev) => {
  const val = ev.target.value;
  selectedMicChoice = val;
  localStorage.setItem("alfred_mic_choice", val);
  if (val.startsWith("host:")) {
    await fetch("/api/devices/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_device_id: val.slice("host:".length) }),
    });
    appendLog("Audio", `Selected host microphone: ${val.slice("host:".length)}`);
  } else {
    appendLog("Audio", `Selected browser microphone: ${ev.target.selectedOptions[0].textContent}`);
  }
});

el("speaker-select").addEventListener("change", async (ev) => {
  const val = ev.target.value;
  selectedSpeakerChoice = val;
  localStorage.setItem("alfred_speaker_choice", val);
  if (val.startsWith("host:")) {
    await fetch("/api/devices/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output_device_id: val.slice("host:".length) }),
    });
    appendLog("Audio", `Selected host speaker: ${val.slice("host:".length)}`);
  } else {
    appendLog("Audio", `Selected browser speaker: ${ev.target.selectedOptions[0].textContent}`);
  }
});

el("refresh-devices-btn").addEventListener("click", async () => {
  await fetch("/api/devices");
  await refreshAll(true);
  appendLog("Audio", "Audio device list refreshed.");
});

el("mic-btn").addEventListener("click", handleVoiceMicClick);

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
  const res = await fetch("/api/devices/smart-select", { method: "POST" }).then((r) => r.json());
  if (res.selected_input) {
    selectedMicChoice = `host:${res.selected_input}`;
    localStorage.setItem("alfred_mic_choice", selectedMicChoice);
  }
  if (res.soundcheck && res.soundcheck.selected_output) {
    selectedSpeakerChoice = `host:${res.soundcheck.selected_output}`;
    localStorage.setItem("alfred_speaker_choice", selectedSpeakerChoice);
  }
  appendLog(
    "Audio",
    `Smart Select: Mic=${res.selected_input_name || res.selected_input || "none"}, Speaker=${res.soundcheck?.selected_output_name || "none"}`
  );
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
