// MERCIL Voice Sales Agent — browser client.
// The browser owns the audio: 16 kHz mic up, 24 kHz voice down, and client-side barge-in
// (we cut playback the instant the mic hears you, which feels faster than waiting for the
// server's `interrupted`). Everything else is panel rendering driven by the agent's tools.

const $ = (id) => document.getElementById(id);
const orb = $("orb"), statusEl = $("status"), txEl = $("transcript");
const reqEl = $("requirements"), prodEl = $("products"), enqEl = $("enquiry");
const companyEl = $("company");

const BARGE_RMS = 0.02;
let ws, audioCtx, workletNode, micStream;
let nextStart = 0;
let activeSources = [];
let speaking = false;

function setOrb(state) { orb.className = "orb " + state; }       // idle | listening | thinking | speaking
function setStatus(t) { statusEl.textContent = t; }
function addLine(role, text) {
  const p = document.createElement("div");
  p.className = "line " + role;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = role === "agent" ? "assistant" : "you";
  p.appendChild(who);
  p.appendChild(document.createTextNode(text));    // textContent, never innerHTML — this is speech
  txEl.appendChild(p);
  txEl.scrollTop = txEl.scrollHeight;
}

// ---------- panels (driven by the agent's tool calls) ----------
const FIELD_LABELS = {
  contact_name: "Contact", company_name: "Company", phone: "Phone",
  email_or_line: "Email / LINE", business_type: "Business type", location: "Location",
  scale: "Scale", priority: "Priority", timeline: "Timeline", notes: "Notes",
};

function renderRequirements(reqs) {
  const entries = Object.entries(reqs || {});
  if (!entries.length) return;
  reqEl.innerHTML = "";
  entries.forEach(([k, v]) => {
    const row = document.createElement("div");
    row.className = "req";
    const key = document.createElement("span");
    key.className = "k"; key.textContent = FIELD_LABELS[k] || k;
    const val = document.createElement("span");
    val.className = "v"; val.textContent = v;   // customer-spoken text — never innerHTML
    row.appendChild(key); row.appendChild(val);
    reqEl.appendChild(row);
  });
}

function renderProducts(items) {
  if (!items || !items.length) return;
  prodEl.innerHTML = "";
  items.forEach((p) => {
    const card = document.createElement("div");
    card.className = "card";
    const bits = [
      ["name", p.name],
      ["th", p.name_th || ""],
      ["cat", (p.category || "").replace(/_/g, " ")],
      ["why", p.why || (p.benefits || []).slice(0, 2).join(" · ")],
    ];
    bits.forEach(([cls, text]) => {
      if (!text) return;
      const d = document.createElement("div");
      d.className = cls; d.textContent = text;
      card.appendChild(d);
    });
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = "Price: contact sales · Availability: to confirm · demo data";
    card.appendChild(meta);
    prodEl.appendChild(card);
  });
}

function renderEnquiry(m) {
  enqEl.hidden = false;
  enqEl.querySelector(".eid").textContent = m.enquiry_id;
  enqEl.querySelector(".esum").textContent = m.summary || "";
  enqEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  setStatus("enquiry prepared for the sales team");
}

// ---------- voice playback (24k PCM from the server) ----------
function playVoice(buf) {
  const int16 = new Int16Array(buf);
  const f32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 0x8000;
  const ab = audioCtx.createBuffer(1, f32.length, 24000);
  ab.getChannelData(0).set(f32);
  const src = audioCtx.createBufferSource();
  src.buffer = ab; src.connect(audioCtx.destination);
  const now = audioCtx.currentTime;
  if (nextStart < now) nextStart = now;
  src.start(nextStart); nextStart += ab.duration;
  activeSources.push(src);
  src.onended = () => { activeSources = activeSources.filter((s) => s !== src); if (!activeSources.length) { speaking = false; setOrb("listening"); } };
  speaking = true; setOrb("speaking");
}
function stopVoice() {                                                     // barge-in
  activeSources.forEach((s) => { try { s.stop(); } catch {} });
  activeSources = []; nextStart = 0; speaking = false; setOrb("listening");
}

// ---------- the live socket ----------
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { setStatus("listening…"); setOrb("listening"); };
  ws.onclose = () => { setStatus("the line dropped — reload to reconnect"); setOrb("idle"); };
  ws.onmessage = (evt) => {
    if (typeof evt.data !== "string") { playVoice(evt.data); return; }     // binary = voice
    const m = JSON.parse(evt.data);
    if (m.type === "transcript") { if (m.role === "user") setOrb("thinking"); addLine(m.role, m.text); }
    else if (m.type === "products") renderProducts(m.items);
    else if (m.type === "requirements") renderRequirements(m.requirements);
    else if (m.type === "enquiry") renderEnquiry(m);
    else if (m.type === "interrupted") stopVoice();
    else if (m.type === "error") { setStatus("error: " + m.message); console.error(m.message); }
  };
}

async function startMic() {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  await audioCtx.audioWorklet.addModule("/pcm-processor.js");
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const source = audioCtx.createMediaStreamSource(micStream);
  workletNode = new AudioWorkletNode(audioCtx, "pcm-processor");
  workletNode.port.onmessage = (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data.pcm);       // 16k PCM up
    if (e.data.rms >= BARGE_RMS && speaking) stopVoice();                  // client-side barge-in
  };
  source.connect(workletNode);
  workletNode.connect(audioCtx.destination);                              // keeps the graph alive (silent)
}

// Branding comes from the active company profile, not from this file — so switching
// COMPANY_PROFILE rebrands the page without a frontend change.
async function loadBranding() {
  try {
    const c = await (await fetch("/api/company")).json();
    companyEl.textContent = c.company_name;
    document.title = `${c.product_name} · ${c.company_name}`;
  } catch { companyEl.textContent = "—"; }
}

async function go() {
  $("talk").disabled = true;
  setStatus("connecting…"); setOrb("thinking");
  try {
    await startMic();
    connect();
    $("talk").textContent = "● live";
  } catch (err) {
    setStatus("microphone blocked: " + err.message);
    setOrb("idle");
    $("talk").disabled = false;
  }
}

$("talk").addEventListener("click", go);
loadBranding();
