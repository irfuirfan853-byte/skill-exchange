/* Skill Exchange — voice/video calls.
 * WebRTC peer connection, with offer/answer/ICE relayed through the
 * server (polled from the call_signals table) so it works without websockets.
 * Both people must be on the same exchange page.
 *
 * Roles: whoever presses "Call" becomes the caller (creates the offer).
 * The other side is polling and AUTO-ANSWERS incoming offers. Previously
 * both sides created offers, so two offers collided and nobody could answer.
 */
(function () {
  "use strict";

  const EXCHANGE_ID = window.EXCHANGE_ID;
  const ME_ID = window.ME_ID;
  const POLL_MS = 1500;
  const RTC_CONFIG = { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] };

  let pc = null;            // RTCPeerConnection
  let localStream = null;
  let callType = "video";
  let startedAt = 0;
  let pollTimer = null;
  let lastSignalId = 0;
  let muted = false;
  let camOff = false;
  let isInitiator = false;  // true = I pressed the call button
  let busy = false;         // a call is being set up right now

  const overlay = () => document.getElementById("callOverlay");

  function setStatus(text) {
    const el = document.getElementById("callStatus");
    if (el) el.textContent = text;
  }

  function log(...args) { console.log("[call]", ...args); }

  async function fetchJSON(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function postSignal(msgType, payload) {
    const body = new URLSearchParams();
    body.append("msg_type", msgType);
    body.append("payload", payload);
    return fetchJSON(`/exchange/${EXCHANGE_ID}/call/signal`, {
      method: "POST",
      body,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRF-Token": window.CSRF_TOKEN || "",
      },
    });
  }

  // ---------- media + peer connection helpers ----------

  async function ensureMedia() {
    if (localStream) return;
    localStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
      video: callType === "video",
    });
    const localVideo = document.getElementById("localVideo");
    if (localVideo) localVideo.srcObject = localStream;
    if (callType === "voice") {
      if (localVideo) localVideo.style.display = "none";
      const camBtn = document.getElementById("camBtn");
      if (camBtn) camBtn.style.display = "none";
    }
  }

  function createPC() {
    const conn = new RTCPeerConnection(RTC_CONFIG);
    localStream.getTracks().forEach((t) => conn.addTrack(t, localStream));

    conn.onicecandidate = (e) => {
      if (e.candidate) {
        postSignal("candidate", JSON.stringify(e.candidate)).catch(log);
      }
    };
    conn.ontrack = (e) => {
      const remoteVideo = document.getElementById("remoteVideo");
      if (remoteVideo && e.streams && e.streams[0]) {
        remoteVideo.srcObject = e.streams[0];
      }
    };
    conn.onconnectionstatechange = () => {
      log("connection state:", conn.connectionState);
      if (conn.connectionState === "connected") {
        setStatus("Connected");
      } else if (conn.connectionState === "failed") {
        setStatus("Connection failed — try calling again.");
      } else if (conn.connectionState === "disconnected") {
        setStatus("Connection lost — the other person may have left.");
      }
    };
    return conn;
  }

  function startPolling() {
    if (!pollTimer) pollTimer = setInterval(pollSignals, POLL_MS);
  }

  // ---------- caller side ----------

  async function startCall(type) {
    if (pc || busy) { setStatus("A call is already in progress."); return; }
    callType = type || "video";
    muted = false; camOff = false;
    startedAt = Date.now();
    isInitiator = true;
    busy = true;
    overlay().hidden = false;
    setStatus("Connecting…");
    const muteBtn = document.getElementById("muteBtn");
    if (muteBtn) muteBtn.textContent = "🎙️";
    const camBtn = document.getElementById("camBtn");
    if (camBtn) { camBtn.textContent = "📷"; camBtn.style.display = ""; }
    const localVideo = document.getElementById("localVideo");
    if (localVideo) localVideo.style.display = "";

    try {
      await ensureMedia();
      pc = createPC();
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await postSignal("offer", JSON.stringify(pc.localDescription));
      setStatus("Ringing… (waiting for the other person to accept)");
      busy = false;
      startPolling();
    } catch (err) {
      log("start error:", err);
      setStatus("Could not start the call: " + (err && err.message ? err.message : err) +
        " — check camera/microphone permission.");
      busy = false;
      setTimeout(() => teardown(false), 2500);
    }
  }

  // ---------- callee side (auto-answer incoming call) ----------

  async function acceptCall(offerPayload) {
    if (pc || busy) return; // already in a call
    busy = true;
    isInitiator = false;
    callType = "video";
    startedAt = Date.now();
    muted = false; camOff = false;
    overlay().hidden = false;
    setStatus("Incoming call — connecting…");

    try {
      await ensureMedia();
      pc = createPC();
      await pc.setRemoteDescription(offerPayload);
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      await postSignal("answer", JSON.stringify(pc.localDescription));
      setStatus("Connected");
      busy = false;
      startPolling();
    } catch (err) {
      log("accept error:", err);
      setStatus("Could not answer the call: " + (err && err.message ? err.message : err));
      busy = false;
      setTimeout(() => teardown(false), 2500);
    }
  }

  // ---------- signal polling ----------

  async function pollSignals() {
    try {
      const rows = await fetchJSON(`/exchange/${EXCHANGE_ID}/call/signals/after/${lastSignalId}`);
      if (!rows.length) return;
      for (const sig of rows) {
        lastSignalId = Math.max(lastSignalId, sig.id);
        if (sig.mine) continue; // ignore our own signals
        let payload;
        try { payload = JSON.parse(sig.payload); } catch (e) { continue; }

        if (sig.msg_type === "offer") {
          if (isInitiator) continue;       // collision/echo — caller waits for an answer
          if (!pc) await acceptCall(payload);
        } else if (sig.msg_type === "answer") {
          if (pc && pc.signalingState !== "stable") {
            await pc.setRemoteDescription(payload);
            setStatus("Connected");
          }
        } else if (sig.msg_type === "candidate") {
          if (pc) {
            try { await pc.addIceCandidate(payload); } catch (e) { /* race — ignore */ }
          }
          // candidates that arrive before our pc exists are replayed anyway,
          // because lastSignalId only advances after we've seen the row.
        }
      }
    } catch (err) {
      log("poll error:", err);
    }
  }

  // ---------- teardown ----------

  function teardown(record) {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    busy = false;
    isInitiator = false;

    const duration = Math.round((Date.now() - startedAt) / 1000);
    const type = callType;

    if (pc) {
      try { pc.close(); } catch (e) {}
      pc = null;
    }
    if (localStream) {
      localStream.getTracks().forEach((t) => t.stop());
      localStream = null;
    }
    const remoteVideo = document.getElementById("remoteVideo");
    if (remoteVideo) remoteVideo.srcObject = null;
    const localVideo = document.getElementById("localVideo");
    if (localVideo) { localVideo.srcObject = null; localVideo.style.display = ""; }
    const camBtn = document.getElementById("camBtn");
    if (camBtn) { camBtn.style.display = ""; camBtn.textContent = "📷"; }
    const muteBtn = document.getElementById("muteBtn");
    if (muteBtn) muteBtn.textContent = "🎙️";

    const ov = overlay();
    if (ov) ov.hidden = true;   // CSS [hidden] rule guarantees it actually hides

    if (record) {
      const body = new URLSearchParams();
      body.append("call_type", type);
      body.append("duration", duration);
      fetchJSON(`/exchange/${EXCHANGE_ID}/call/end`, {
        method: "POST",
        body,
        headers: { "X-CSRF-Token": window.CSRF_TOKEN || "" },
      }).catch(log);
    }
  }

  // ---------- public API ----------

  window.SkillCall = {
    start: startCall,
    hangup() { teardown(true); },
    toggleMute() {
      muted = !muted;
      if (localStream) {
        localStream.getAudioTracks().forEach((t) => { t.enabled = !muted; });
      }
      const btn = document.getElementById("muteBtn");
      if (btn) btn.textContent = muted ? "🔇" : "🎙️";
    },
    toggleCam() {
      camOff = !camOff;
      if (localStream) {
        localStream.getVideoTracks().forEach((t) => { t.enabled = !camOff; });
      }
      const btn = document.getElementById("camBtn");
      if (btn) btn.textContent = camOff ? "🚫" : "📷";
    },
  };
})();
