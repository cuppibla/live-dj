// Drive frontend/main.js in a stubbed browser to prove the barge-in fix:
// after a cut, the rest of the turn must be DROPPED, not played.
const fs = require("fs");
const vm = require("vm");

let sourcesCreated = 0;
let sourcesStopped = 0;
let sent = 0;
const sockets = [];
const workletNodes = [];

function fakeEl() {
  const el = {
    classList: { add() {}, remove() {} }, style: {}, hidden: false,
    textContent: "", innerHTML: "", scrollTop: 0, className: "",
    appendChild() {}, scrollIntoView() {}, addEventListener() {},
    querySelector: () => fakeEl(), querySelectorAll: () => [],
  };
  return el;
}

const ctx = {
  console,
  setTimeout, clearTimeout, setInterval, clearInterval, Date,
  Int16Array, Float32Array, Math, JSON, Object,
  document: { getElementById: () => fakeEl(), createElement: () => fakeEl() },
  window: { addEventListener() {}, AudioContext: null },
  location: { protocol: "http:", host: "localhost:8000" },
  fetch: () => Promise.reject(new Error("no branding in test")),
  navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } },
  WebSocket: class {
    constructor() { this.readyState = 1; sockets.push(this); }
    close() {} send() { sent++; }
  },
};
ctx.window.AudioContext = class {
  constructor() {
    this.currentTime = 0;
    this.destination = {};
    this.audioWorklet = { addModule: async () => {} };
  }
  createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
  createBuffer(_c, len) {
    return { duration: len / 24000, getChannelData: () => new Float32Array(len) };
  }
  createBufferSource() {
    sourcesCreated++;
    return { buffer: null, connect() {}, start() {}, stop() { sourcesStopped++; }, onended: null };
  }
  close() {}
};
ctx.AudioContext = ctx.window.AudioContext;
ctx.AudioWorkletNode = class {
  constructor() { this.port = {}; workletNodes.push(this); }
  connect() {} disconnect() {}
};
ctx.WebSocket.OPEN = 1;
ctx.globalThis = ctx;

vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2] || "frontend/main.js", "utf8"), ctx);

const chunk = () => new Int16Array(2400).buffer;   // 100 ms of 24 kHz audio
const ok = [];
function check(label, cond) {
  ok.push(cond);
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}`);
}

(async () => {
  await ctx.startMic();

  // 1. a normal turn plays
  sourcesCreated = 0;
  for (let i = 0; i < 3; i++) ctx.playVoice(chunk());
  check("normal turn plays every chunk", sourcesCreated === 3);

  // 2. barge-in cuts what is queued
  sourcesStopped = 0;
  ctx.stopVoice(true);
  check("barge-in stops the queued audio", sourcesStopped === 3);

  // 3. THE BUG: the rest of the turn keeps arriving and must be dropped
  sourcesCreated = 0;
  for (let i = 0; i < 5; i++) ctx.playVoice(chunk());
  check("rest of the cut turn is DROPPED (was: played as a jump to the end)",
        sourcesCreated === 0);

  // 4. the next turn plays normally again
  ctx.resumeVoice();
  sourcesCreated = 0;
  for (let i = 0; i < 2; i++) ctx.playVoice(chunk());
  check("next turn plays normally after turn_end", sourcesCreated === 2);

  // 5. safety net: a missing turn_end must not mute the assistant forever
  ctx.stopVoice(true);
  ctx.playVoice(chunk());                       // tail still arriving
  await new Promise((r) => setTimeout(r, 900)); // ... then it stops for > DRAIN_MS
  sourcesCreated = 0;
  ctx.playVoice(chunk());
  check("drain watchdog restores audio if turn_end never comes", sourcesCreated === 1);

  // ---- hold-the-floor mode, for a room too loud to trust ----
  ctx.connect();                                  // gives the worklet a socket to send on
  const mic = (d) => workletNodes[0].port.onmessage({ data: d });
  const LOUD = { pcm: new Int16Array(43).buffer, rms: 0.9 };
  const QUIET = { pcm: new Int16Array(43).buffer, rms: 0.001 };

  ctx.setInterruptible(true);
  ctx.resumeVoice();
  ctx.playVoice(chunk());                         // assistant starts speaking
  sourcesStopped = 0;
  for (let i = 0; i < 20; i++) mic(LOUD);
  check("interruptible: sustained speech cuts the assistant off", sourcesStopped > 0);

  ctx.resumeVoice();
  ctx.playVoice(chunk());
  sourcesStopped = 0;
  mic(LOUD); mic(QUIET); mic(LOUD); mic(QUIET);
  check("interruptible: a lone click does NOT cut it off", sourcesStopped === 0);

  ctx.setInterruptible(false);
  ctx.resumeVoice();
  ctx.playVoice(chunk());                         // assistant speaking -> floor is held
  sourcesStopped = 0; sent = 0;
  for (let i = 0; i < 40; i++) mic(LOUD);
  check("no-interruptions: room noise does not cut the assistant off", sourcesStopped === 0);
  check("no-interruptions: no audio reaches Gemini while it speaks (blocks server VAD)",
        sent === 0);

  ctx.stopVoice(false); ctx.resumeVoice();
  await new Promise((r) => setTimeout(r, 400));   // past HOLD_TAIL_MS
  sent = 0;
  for (let i = 0; i < 5; i++) mic(LOUD);
  check("no-interruptions: mic reopens once the assistant stops", sent === 5);

  ctx.setInterruptible(true);
  sent = 0;
  for (let i = 0; i < 5; i++) mic(QUIET);
  check("interruptible: audio flows normally again", sent === 5);

  console.log(ok.every(Boolean) ? "\nALL PASS" : "\nFAILURES");
  process.exit(ok.every(Boolean) ? 0 : 1);
})();
