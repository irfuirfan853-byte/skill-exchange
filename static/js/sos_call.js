/* Skill Exchange — voice / video calls on SOS reports (member <-> admin).
 *
 * Signaling goes through the server (polled from the sos_call_signals table),
 * exactly like the exchange calls, so no websockets are needed.
 *
 * window.SOS_ROOMS is a list of rooms the current page listens on:
 *   - member: their own open SOS reports
 *   - admin : every open / acknowledged SOS report
 * Whoever presses a call button becomes the caller (creates the offer); the
 * other side is listening and auto-answers, so an emergency call connects
 * even if nobody presses "accept".
 *
 * Only the report owner and admins can read/write a room — enforced server
 * side in the /sos/<id>/call/* routes.
 */
(function () {
  "use strict";

  const ROOMS = window.SOS_ROOMS || [];
  const POLL_MS = 2000;
  const RTC_CONFIG = { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] };

  let pc = null;
  let localStream = null;
  let callType = "video";
  let roomId = null;
  let isInitiator = false;
  let busy = false;
  let muted = false;
  let camOff = false;
  let pollTimer = null;
  const cursors = {}; // room id -> last seen signal id

  const overlay = () => document.getElementById("callOverlay");

  function setStatus(text) {
    const el = document.getElementById("callStatus");
    if (el) el.textContent = text;
  }

  function setName(text) {
    const el = document.getElementById("callName");
    if (el) el.textContent = text;
  }

  function log() {
    console.log.apply(console, ["[sos-call]"].concat([].slice.call(arguments)));
  }

  async function fetchJSON(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function postSignal(room, msgType, payload) {
    const body = new URLSearchParams();
    body.append("msg_type", msgType);
    body.append("payload", payload);
    return fetchJSON("/sos/" + room + "/call/signal", {
      method: "POST",
      body: body,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRF-Token": window.CSRF_TOKEN || "",
      },
    });
  }

  function endRoom(room) {
    return fetchJSON("/sos/" + room + "/call/end", {
      method: "POST",
      headers: { "X-CSRF-Token": window.CSRF_TOKEN || "" },
    }).catch(log);
  }

  function roomName(room) {
    for (let i = 0; i < ROOMS.length; i++) {
      if (ROOMS[i].id === room) return ROOMS[i].name || "SOS support";
    }
    return "SOS support";
  }

  // ---------- media + peer connection ----------

  async function ensureMedia(wantVideo) {
    if (localStream) return;
    try {
      localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: wantVideo });
    } catch (err) {
      if (!wantVideo) throw err;
      // No camera / camera denied — an audio call still helps in an emergency.
      localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      callType = "voice";
    }
    const localVideo = document.getElementById("localVideo");
    if (localVideo) localVideo.srcObject = localStream;
    if (callType === "voice") {
      if (localVideo) localVideo.style.display = "none";
      const camBtn = document.getElementById("camBtn");
      if (camBtn) camBtn.style.display = "none";
    }
  }

  function createPC(room) {
    const conn = new RTCPeerConnection(RTC_CONFIG);
    localStream.getTracks().forEach(function (t) { conn.addTrack(t, localStream); });

    conn.onicecandidate = function (e) {
      if (e.candidate) postSignal(room, "candidate", JSON.stringify(e.candidate)).catch(log);
    };
    conn.ontrack = function (e) {
      const remoteVideo = document.getElementById("remoteVideo");
      if (remoteVideo && e.streams && e.streams[0]) remoteVideo.srcObject = e.streams[0];
    };
    conn.onconnectionstatechange = function () {
      log("state:", conn.connectionState);
      if (conn.connectionState === "connected") setStatus("Connected");
      else if (conn.connectionState === "failed") setStatus("Connection failed — try calling again.");
      else if (conn.connectionState === "disconnected") setStatus("Connection lost — try calling again.");
    };
    return conn;
  }

  function showOverlay(name, status) {
    const ov = overlay();
    if (!ov) return false;
    setName(name || "SOS support");
    setStatus(status || "Starting…");
    const muteBtn = document.getElementById("muteBtn");
    if (muteBtn) muteBtn.textContent = "🎙️";
    const camBtn = document.getElementById("camBtn");
    if (camBtn) { camBtn.textContent = "📷"; camBtn.style.display = ""; }
    const localVideo = document.getElementById("localVideo");
    if (localVideo) localVideo.style.display = "";
    ov.hidden = false;
    return true;
  }

  // ---------- caller ----------

  async function startCall(room, type) {
    if (!overlay()) return;
    if (pc || busy) { setStatus("A call is already in progress."); return; }
    roomId = room;
    isInitiator = true;
    callType = (type === "voice") ? "voice" : "video";
    muted = false;
    camOff = false;
    busy = true;
    showOverlay(roomName(room), "Connecting…");

    try {
      await ensureMedia(callType === "video");
      pc = createPC(room);
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await postSignal(room, "offer", JSON.stringify(pc.localDescription));
      setStatus("Ringing… (waiting for the other side)");
      busy = false;
    } catch (err) {
      log("start error:", err);
      setStatus("Could not start the call: " + (err && err.message ? err.message : err) +
        " — check microphone/camera permission.");
      busy = false;
      setTimeout(function () { teardown(true); }, 2500);
    }
  }

  // ---------- callee (auto-answer an incoming SOS call) ----------

  async function acceptCall(room, offerPayload) {
    if (pc || busy) return;
    busy = true;
    roomId = room;
    isInitiator = false;
    callType = "video";
    muted = false;
    camOff = false;
    showOverlay(roomName(room), "Incoming SOS call — connecting…");

    try {
      await ensureMedia(true);
      pc = createPC(room);
      await pc.setRemoteDescription(offerPayload);
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      await postSignal(room, "answer", JSON.stringify(pc.localDescription));
      setStatus("Connected");
      busy = false;
    } catch (err) {
      log("accept error:", err);
      setStatus("Could not answer: " + (err && err.message ? err.message : err));
      busy = false;
      setTimeout(function () { teardown(false); }, 2500);
    }
  }

  // ---------- teardown ----------

  function teardown(notifyOther) {
    const room = roomId;
    if (notifyOther && room && pc) postSignal(room, "bye", "{}").catch(log);

    if (pc) { try { pc.close(); } catch (e) {} pc = null; }
    if (localStream) {
      localStream.getTracks().forEach(function (t) { t.stop(); });
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
    if (ov) ov.hidden = true;

    roomId = null;
    isInitiator = false;
    busy = false;

    // Give the other side time to receive the "bye", then drop the SDP from
    // the database so call details are not kept around.
    if (notifyOther && room) setTimeout(function () { endRoom(room); }, 3000);
  }

  // ---------- polling ----------

  async function pollRoom(room) {
    const last = cursors[room] || 0;
    const rows = await fetchJSON("/sos/" + room + "/call/signals/after/" + last);
    if (!rows.length) return;
    for (let i = 0; i < rows.length; i++) {
      const sig = rows[i];
      cursors[room] = Math.max(cursors[room] || 0, sig.id);
      if (sig.mine) continue;
      let payload;
      try { payload = JSON.parse(sig.payload); } catch (e) { continue; }

      if (sig.msg_type === "offer") {
        if (pc && roomId === room && isInitiator) continue; // our own call setup
        if (!pc) await acceptCall(room, payload);
      } else if (sig.msg_type === "answer") {
        if (pc && roomId === room && pc.signalingState !== "stable") {
          try { await pc.setRemoteDescription(payload); setStatus("Connected"); } catch (e) { log(e); }
        }
      } else if (sig.msg_type === "candidate") {
        if (pc && roomId === room) {
          try { await pc.addIceCandidate(payload); } catch (e) { /* race — ignore */ }
        }
      } else if (sig.msg_type === "bye") {
        if (pc && roomId === room) {
          setStatus("Call ended by the other person.");
          setTimeout(function () { teardown(false); }, 900);
        }
      }
    }
  }

  async function pollAll() {
    for (let i = 0; i < ROOMS.length; i++) {
      try { await pollRoom(ROOMS[i].id); } catch (e) { /* closed / no access */ }
    }
  }

  // ---------- public API ----------

  window.SOSCall = {
    start: startCall,
    hangup: function () { teardown(true); },
    toggleMute: function () {
      muted = !muted;
      if (localStream) localStream.getAudioTracks().forEach(function (t) { t.enabled = !muted; });
      const btn = document.getElementById("muteBtn");
      if (btn) btn.textContent = muted ? "🔇" : "🎙️";
    },
    toggleCam: function () {
      camOff = !camOff;
      if (localStream) localStream.getVideoTracks().forEach(function (t) { t.enabled = !camOff; });
      const btn = document.getElementById("camBtn");
      if (btn) btn.textContent = camOff ? "🚫" : "📷";
    },
  };

  // Listen for incoming calls as soon as the page opens (skip old signals).
  (async function init() {
    if (!overlay() || !ROOMS.length) return;
    for (let i = 0; i < ROOMS.length; i++) {
      try {
        const rows = await fetchJSON("/sos/" + ROOMS[i].id + "/call/signals/after/0");
        if (rows.length) cursors[ROOMS[i].id] = rows[rows.length - 1].id;
      } catch (e) { /* ignore */ }
    }
    if (!pollTimer) pollTimer = setInterval(pollAll, POLL_MS);
  })();
})();
