/* Skill Exchange — voice/video calls.
 * WebRTC peer connection, with offer/answer/ICE relayed through the
 * server (polled from the call_signals table) so it works without websockets.
 * Both people must be on the same exchange page.
 */
(function () {
  "use strict";

  const EXCHANGE_ID = window.EXCHANGE_ID;
  const ME_ID = window.ME_ID;
  const POLL_MS = 1500;

  let pc = null;            // RTCPeerConnection
  let localStream = null;
  let callType = "video";
  let startedAt = 0;
  let signalTimer = null;
  let pollTimer = null;
  let lastSignalId = 0;
  let muted = false;
  let camOff = false;
  let statusEl, callStatus;

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

  // ---------- public API ----------
  window.SkillCall = {
    start(type) {
      if (pc) { setStatus("A call is already in progress."); return; }
      callType = type || "video";
      muted = false; camOff = false;
      startedAt = Date.now();
      overlay().hidden = false;
      setStatus("Connecting…");
      this._boot();
    },

    hangup() {
      this._teardown(true);
    },

    toggleMute() {
      muted = !muted;
      if (localStream) {
        localStream.getAudioTracks().forEach((t) => { t.enabled = !muted; });
      }
      document.getElementById("muteBtn").textContent = muted ? "🔇" : "🎙️";
    },

    toggleCam() {
      camOff = !camOff;
      if (localStream) {
        localStream.getVideoTracks().forEach((t) => { t.enabled = !camOff; });
      }
      document.getElementById("camBtn").textContent = camOff ? "🚫" : "📷";
    },

    async _boot() {
      try {
        localStream = await navigator.mediaDevices.getUserMedia({
          audio: true,
          video: callType === "video",
        });
        const localVideo = document.getElementById("localVideo");
        if (localVideo) localVideo.srcObject = localStream;
        if (callType === "voice") {
          localVideo.style.display = "none";
          document.getElementById("camBtn").style.display = "none";
        }

        pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
        localStream.getTracks().forEach((t) => pc.addTrack(t, localStream));

        pc.onicecandidate = (e) => {
          if (e.candidate) {
            postSignal("candidate", JSON.stringify(e.candidate)).catch(log);
          }
        };
        pc.ontrack = (e) => {
          const remoteVideo = document.getElementById("remoteVideo");
          if (remoteVideo && e.streams && e.streams[0]) {
            remoteVideo.srcObject = e.streams[0];
          }
        };
        pc.onconnectionstatechange = () => {
          log("connection state:", pc.connectionState);
          if (pc.connectionState === "connected") {
            setStatus("Connected");
          } else if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
            setStatus("Connection lost — the other person may have left.");
          }
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await postSignal("offer", JSON.stringify(offer));
        setStatus("Ringing… (waiting for the other person to answer)");

        pollTimer = setInterval(() => this._pollSignals(), POLL_MS);
      } catch (err) {
        log("start error:", err);
        setStatus("Could not start the call: " + (err && err.message ? err.message : err));
        this._teardown(false);
      }
    },

    async _pollSignals() {
      try {
        const rows = await fetchJSON(`/exchange/${EXCHANGE_ID}/call/signals/after/${lastSignalId}`);
        if (!rows.length) return;
        for (const sig of rows) {
          lastSignalId = Math.max(lastSignalId, sig.id);
          if (sig.mine) continue; // ignore our own messages
          const payload = JSON.parse(sig.payload);
          if (sig.msg_type === "offer") {
            await pc.setRemoteDescription(payload);
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            await postSignal("answer", JSON.stringify(answer));
            setStatus("Connected");
          } else if (sig.msg_type === "answer") {
            await pc.setRemoteDescription(payload);
            setStatus("Connected");
          } else if (sig.msg_type === "candidate") {
            try { await pc.addIceCandidate(payload); } catch (e) { /* ignore race */ }
          }
        }
      } catch (err) {
        log("poll error:", err);
      }
    },

    _teardown(record) {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      if (signalTimer) { clearTimeout(signalTimer); signalTimer = null; }

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
      if (camBtn) camBtn.style.display = "";
      overlay().hidden = true;

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
    },
  };
})();
