// Drive frontend/main.js in a stubbed browser to prove the barge-in fix:
// after a cut, the rest of the turn must be DROPPED, not played.
const fs = require("fs");
const vm = require("vm");

let sourcesCreated = 0;
let sourcesStopped = 0;

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
  WebSocket: class { constructor() { this.readyState = 0; } close() {} send() {} },
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
ctx.AudioWorkletNode = class { constructor() { this.port = {}; } connect() {} disconnect() {} };
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

  console.log(ok.every(Boolean) ? "\nALL PASS" : "\nFAILURES");
  process.exit(ok.every(Boolean) ? 0 : 1);
})();
