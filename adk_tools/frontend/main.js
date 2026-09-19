// live-dj — minimal test client (Phase 1).
// The polished UI is aniradio's Next.js room (next step). This is enough to RUN the de-risk:
// talk to Mira, hear her back, interrupt her, and ask her to play music.

const $ = (id) => document.getElementById(id);
const orb = $("orb"), statusEl = $("status"), nowEl = $("nowplaying"), txEl = $("transcript");
const actEl = $("actionlog"), timerEl = $("timer");
const music = $("music");

// ?log=0 hides the action-log panel (e.g. for EP2 takes; EP3 wants it visible)
if (new URLSearchParams(location.search).get("log") === "0")
  document.querySelector(".actions").style.display = "none";

const BARGE_RMS = 0.02;
let ws, audioCtx, workletNode, micStream;
let nextStart = 0;
let activeSources = [];
let speaking = false;
let duckTimer = null;
let tracks = [];
let queue = [];
let qi = 0;

function setOrb(state) { orb.className = "orb " + state; }       // idle | listening | thinking | speaking
function setStatus(t) { statusEl.textContent = t; }
function addLine(role, text) {
  const p = document.createElement("div");
  p.className = "line " + role;
  p.textContent = (role === "mira" ? "mira  " : "you  ") + text;
  txEl.appendChild(p); txEl.scrollTop = txEl.scrollHeight;
}

// ---------- music player (driven by Mira's tool calls) ----------
async function loadTracks() {
  try { tracks = await (await fetch("/assets/tracks.json")).json(); } catch { tracks = []; }
}
function startQueue(list) {
  queue = list.length ? list : tracks;
  qi = 0;
  if (queue.length) { music.src = "/assets/" + queue[0].file; music.volume = 1; music.play().catch(() => {}); setNow(queue[0]); }
}
function setNow(t) { nowEl.textContent = t ? `now playing · ${t.title} — ${t.artist || ""}` : ""; }
function handlePlay(cmd) {
  if (cmd.action === "playlist") startQueue(tracks);                       // one vibe (all dream pop here)
  else if (cmd.action === "track") {
    const t = tracks.find((x) => x.title.toLowerCase().includes((cmd.value || "").toLowerCase()));
    startQueue(t ? [t] : tracks);
  } else if (cmd.action === "skip") { qi = (qi + 1) % Math.max(1, queue.length); if (queue[qi]) { music.src = "/assets/" + queue[qi].file; music.play().catch(() => {}); setNow(queue[qi]); } }
  else if (cmd.action === "pause") { music.paused ? music.play().catch(() => {}) : music.pause(); }
  else if (cmd.action === "sleep_timer") setSleepTimer(cmd.value);
}

// ---------- sleep timer (EP3 demo #2) ----------
let sleepTimeout = null;
function setSleepTimer(minutes) {
  if (sleepTimeout) clearTimeout(sleepTimeout);
  timerEl.textContent = `sleep timer · music fades out in ${minutes} min`;
  sleepTimeout = setTimeout(() => {
    const fade = setInterval(() => {
      music.volume = Math.max(0, music.volume - 0.05);
      if (music.volume <= 0) { clearInterval(fade); music.pause(); timerEl.textContent = "sleep timer · faded out. goodnight"; }
    }, 250);
  }, minutes * 60 * 1000);
}

// ---------- action log (EP3: every tool call passes ONE policy gate) ----------
function addAction(m) {
  const div = document.createElement("div");
  div.className = "act" + (m.status === "blocked" ? " blocked" : "");
  const args = Object.entries(m.args || {}).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ");
  const call = document.createElement("div");
  call.textContent = `▸ ${m.tool}(${args})`;
  const verdict = document.createElement("span");
  verdict.className = "verdict";
  verdict.textContent = m.status === "blocked" ? `⛔ blocked · ${m.reason || ""}` : "✓ allowed";
  div.appendChild(call); div.appendChild(verdict);
  actEl.appendChild(div); actEl.scrollTop = actEl.scrollHeight;
}
function duck() {                                                          // music down while Mira talks
  music.volume = 0.12;
  if (duckTimer) clearTimeout(duckTimer);
  duckTimer = setTimeout(() => { music.volume = 1; }, 450);
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
  speaking = true; setOrb("speaking"); duck();
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
  ws.onclose = () => { setStatus("the line dropped — tap to reconnect"); setOrb("idle"); };
  ws.onmessage = (evt) => {
    if (typeof evt.data !== "string") { playVoice(evt.data); return; }     // binary = voice
    const m = JSON.parse(evt.data);
    if (m.type === "transcript") { if (m.role === "user") setOrb("thinking"); addLine(m.role, m.text); }
    else if (m.type === "play") handlePlay(m);
    else if (m.type === "action") addAction(m);
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

async function go() {
  $("talk").disabled = true;
  setStatus("waking mira up…"); setOrb("thinking");
  await loadTracks();
  await startMic();
  connect();
  $("talk").textContent = "● live";
}
$("talk").addEventListener("click", go);
