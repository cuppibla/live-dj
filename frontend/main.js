// MERCIL Voice Sales Agent — browser client.
// The browser owns the audio: 16 kHz mic up, 24 kHz voice down, and client-side barge-in
// (we cut playback the instant the mic hears you, which feels faster than waiting for the
// server's `interrupted`). Everything else is panel rendering driven by the agent's tools.

const $ = (id) => document.getElementById(id);
const orb = $("orb"), statusEl = $("status"), txEl = $("transcript");
const reqEl = $("requirements"), prodEl = $("products"), enqEl = $("enquiry");
const wantEl = $("wanted"), wantPanel = $("wantedpanel");
const companyEl = $("company");

// Barge-in has to survive a cough, a keyboard, and the assistant's own voice coming out of
// a speaker. The worklet posts a message every 128 samples (~2.7 ms at 48 kHz), so a single
// noisy quantum used to be enough to cut the assistant off mid-word.
const BARGE_RMS = 0.035;
const BARGE_SUSTAIN = 8;          // consecutive loud quanta (~21 ms) before we believe it
const DRAIN_MS = 600;             // how long a cut-off turn keeps arriving after we stop it
const VOICE_RMS = 0.015;          // anything above this counts as someone being present
const IDLE_MS = 120000;           // hang up after two minutes of true silence
const talkBtn = $("talk");

let ws, audioCtx, workletNode, micStream, micSource;
let live = false, idleTimer = null, lastVoiceAt = 0;
let loudQuanta = 0, suppressTurn = false, drainTimer = null;
let nextStart = 0;
let activeSources = [];
let speaking = false;

function setOrb(state) { orb.className = "orb " + state; }       // idle | listening | thinking | speaking
function setStatus(t) { statusEl.textContent = t; }
// Live transcription arrives a fragment at a time — a few syllables per message. Rendering
// each as its own line turned every sentence into a column of single words. Fragments are
// appended to the current speaker's line instead, and a new line starts only when the
// speaker changes or the turn ends.
let currentLine = null, currentRole = null;

function addLine(role, text) {
  if (currentLine && currentRole === role) {
    currentLine.body.textContent += text;
  } else {
    const p = document.createElement("div");
    p.className = "line " + role;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = role === "agent" ? "assistant" : "you";
    const body = document.createElement("span");
    body.textContent = text;                       // textContent, never innerHTML — this is speech
    p.appendChild(who);
    p.appendChild(body);
    txEl.appendChild(p);
    currentLine = { el: p, body };
    currentRole = role;
  }
  txEl.scrollTop = txEl.scrollHeight;
}

function endTurn() { currentLine = null; currentRole = null; }

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

// Two panels, one list. What the customer actually asked for is the deliverable; the rest
// is the trail that got them there, and the sales team needs to tell them apart.
function renderProducts(items) {
  if (!items || !items.length) return;
  const wanted = items.filter((p) => p.interest === "wanted");
  const rest = items.filter((p) => p.interest !== "wanted");
  wantPanel.hidden = wanted.length === 0;
  renderCards(wantEl, wanted);
  renderCards(prodEl, rest);
  if (!rest.length) prodEl.innerHTML = '<div class="empty">— everything discussed is above —</div>';
}

function renderCards(host, items) {
  host.innerHTML = "";
  items.forEach((p) => {
    const card = document.createElement("div");
    card.className = "card";
    const bits = [
      ["name", p.name],
      ["th", p.name_th || ""],
      ["cat", [(p.category || "").replace(/_/g, " "),
               (p.brands || []).join(" · ")].filter(Boolean).join("  ·  ")],
      ["why", p.why || (p.benefits || []).slice(0, 2).join(" · ")],
    ];
    bits.forEach(([cls, text]) => {
      if (!text) return;
      const d = document.createElement("div");
      d.className = cls; d.textContent = text;
      card.appendChild(d);
    });
    // A looked-up product is not a recommendation. Saying so on the card keeps the panel
    // honest when the assistant checked the catalogue without proposing anything.
    if (p.source === "looked_up" && p.interest !== "wanted") card.classList.add("lookup");
    if (p.interest === "declined") card.classList.add("declined");
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = (p.interest === "wanted" ? "Customer asked for this · "
                        : p.interest === "declined" ? "Ruled out · "
                        : p.source === "looked_up" ? "Looked up · " : "")
      + "Price: contact sales · Availability: to confirm · demo data";
    card.appendChild(meta);
    host.appendChild(card);
  });
}

function renderEnquiry(m) {
  enqEl.hidden = false;
  enqEl.querySelector(".eid").textContent = m.enquiry_id;
  enqEl.querySelector(".esum").textContent = m.summary || "";
  const list = enqEl.querySelector(".wantlist");
  list.innerHTML = "";
  (m.products_wanted || []).forEach((p) => {
    const d = document.createElement("div");
    d.textContent = "• " + p.name + (p.name_th ? "  " + p.name_th : "");
    list.appendChild(d);
  });
  enqEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  setStatus("enquiry prepared for the sales team");
}

// ---------- voice playback (24k PCM from the server) ----------
function playVoice(buf) {
  if (!audioCtx) return;                 // a frame can land in the gap after the call ends
  // Cutting the assistant off only stops what is already queued. The server has no idea we
  // did it and keeps streaming the rest of the turn, so those chunks used to arrive, find an
  // empty queue and play at once — you heard the opening, a cut, then the tail. That is the
  // "skips to the end" symptom. Drop the remainder instead.
  if (suppressTurn) { armDrain(); return; }
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
function stopVoice(suppressRest) {                                         // barge-in
  activeSources.forEach((s) => { try { s.stop(); } catch {} });
  activeSources = []; nextStart = 0; speaking = false;
  if (suppressRest) { suppressTurn = true; armDrain(); }
  setOrb(live ? "listening" : "idle");
}

// Safety net. Suppression normally ends at the server's turn_end; this makes sure a missing
// turn_end can never leave the assistant permanently mute — once the tail stops arriving,
// listening resumes.
function armDrain() {
  clearTimeout(drainTimer);
  drainTimer = setTimeout(() => { suppressTurn = false; }, DRAIN_MS);
}

function resumeVoice() {
  suppressTurn = false;
  clearTimeout(drainTimer);
  loudQuanta = 0;
}

// ---------- the live socket ----------
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { setStatus("listening…"); setOrb("listening"); watchForIdle(); };
  ws.onclose = () => { if (live) endCall("the line dropped — tap to start again"); };
  ws.onmessage = (evt) => {
    if (typeof evt.data !== "string") { playVoice(evt.data); return; }     // binary = voice
    const m = JSON.parse(evt.data);
    if (m.type === "transcript") { if (m.role === "user") setOrb("thinking"); addLine(m.role, m.text); }
    else if (m.type === "products") renderProducts(m.items);
    else if (m.type === "requirements") renderRequirements(m.requirements);
    else if (m.type === "enquiry") renderEnquiry(m);
    else if (m.type === "turn_end") { endTurn(); resumeVoice(); }
    else if (m.type === "interrupted") { endTurn(); stopVoice(true); }
    else if (m.type === "error") { setStatus("error: " + m.message); console.error(m.message); }
  };
}

async function startMic() {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  await audioCtx.audioWorklet.addModule("/pcm-processor.js");
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  micSource = audioCtx.createMediaStreamSource(micStream);
  workletNode = new AudioWorkletNode(audioCtx, "pcm-processor");
  workletNode.port.onmessage = (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data.pcm);       // 16k PCM up
    // Sustained energy, not one loud sample — otherwise a click cuts the assistant off.
    loudQuanta = e.data.rms >= BARGE_RMS ? loudQuanta + 1 : 0;
    if (loudQuanta >= BARGE_SUSTAIN && speaking) { loudQuanta = 0; stopVoice(true); }
    if (e.data.rms >= VOICE_RMS) lastVoiceAt = Date.now();                 // someone is in the room
  };
  micSource.connect(workletNode);
  workletNode.connect(audioCtx.destination);                              // keeps the graph alive (silent)
}

// The mic streams to Gemini for as long as it is open, and audio is billed by the second
// whether anyone is talking or not. Without this, leaving the tab open over lunch bills a
// full hour of an empty room — which is how the API budget went, not the conversations.
function endCall(reason) {
  if (!live) return;
  live = false;
  clearInterval(idleTimer); idleTimer = null;
  try { ws && ws.close(); } catch {}
  try { micStream && micStream.getTracks().forEach((t) => t.stop()); } catch {}
  try { micSource && micSource.disconnect(); } catch {}
  try { workletNode && workletNode.disconnect(); } catch {}
  try { audioCtx && audioCtx.close(); } catch {}
  ws = micStream = micSource = workletNode = audioCtx = null;
  stopVoice(false);
  resumeVoice();
  endTurn();
  setOrb("idle");
  setStatus(reason);
  talkBtn.textContent = "🎙 start call";
  talkBtn.disabled = false;
}

function watchForIdle() {
  lastVoiceAt = Date.now();
  clearInterval(idleTimer);
  idleTimer = setInterval(() => {
    // The assistant talking counts as activity: never hang up mid-sentence.
    if (speaking) { lastVoiceAt = Date.now(); return; }
    if (Date.now() - lastVoiceAt > IDLE_MS) {
      endCall(`ended after ${IDLE_MS / 1000}s of silence — tap to start again`);
    }
  }, 2000);
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
  talkBtn.disabled = true;
  setStatus("connecting…"); setOrb("thinking");
  try {
    await startMic();
    connect();
    live = true;
    talkBtn.textContent = "■ end call";
    talkBtn.disabled = false;
  } catch (err) {
    setStatus("microphone blocked: " + err.message);
    setOrb("idle");
    talkBtn.disabled = false;
  }
}

talkBtn.addEventListener("click", () => {
  if (live) endCall("call ended — tap to start again");
  else go();
});

// Closing or reloading the tab must tear the session down too, not leave it streaming.
window.addEventListener("pagehide", () => endCall("call ended"));

loadBranding();
