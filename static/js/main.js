// Skill Exchange — small enhancements (no dependencies)

// Animate progress bars when they scroll into view
document.addEventListener("DOMContentLoaded", () => {
  const bars = document.querySelectorAll(".progress-fill");
  const apply = (bar) => {
    const w = bar.getAttribute("data-width") || bar.style.width || "0%";
    bar.style.width = "0%";
    requestAnimationFrame(() => requestAnimationFrame(() => { bar.style.width = w; }));
  };
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { apply(e.target); io.unobserve(e.target); } });
    }, { threshold: 0.3 });
    bars.forEach((b) => io.observe(b));
  } else {
    bars.forEach(apply);
  }

  // ---------- Dark / light theme toggle ----------
  const themeBtn = document.getElementById("themeToggle");
  const applyTheme = (t) => {
    document.documentElement.setAttribute("data-theme", t);
    themeBtn.textContent = t === "dark" ? "☀️" : "🌙";
    try { localStorage.setItem("se-theme", t); } catch (e) {}
  };
  if (themeBtn) {
    let current = "light";
    try { current = localStorage.getItem("se-theme") || "light"; } catch (e) {}
    applyTheme(current);
    themeBtn.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
    });
  }

  // ---------- Mobile nav menu ----------
  const navToggle = document.getElementById("navToggle");
  const navLinks = document.getElementById("navLinks");
  if (navToggle && navLinks) {
    navToggle.addEventListener("click", () => navLinks.classList.toggle("open"));
  }

  // ---------- Exchange page: composer tabs ----------
  document.querySelectorAll(".composer-tabs").forEach((tabs) => {
    tabs.addEventListener("click", (e) => {
      const btn = e.target.closest(".ctab");
      if (!btn) return;
      tabs.querySelectorAll(".ctab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".composer-form").forEach((f) => {
        f.style.display = (f.id === tab + "Form") ? "flex" : "none";
      });
    });
  });

  // ---------- Exchange page: turn YouTube links into embeds ----------
  const ytId = (url) => {
    try {
      const m = url.match(/(?:youtu\.be\/|v=|embed\/|shorts\/)([\w-]{11})/);
      return m ? m[1] : null;
    } catch (e) { return null; }
  };
  document.querySelectorAll(".yt-bubble a").forEach((a) => {
    const id = ytId(a.textContent);
    if (id) {
      const iframe = document.createElement("iframe");
      iframe.className = "yt-embed";
      iframe.src = "https://www.youtube.com/embed/" + id;
      iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
      iframe.allowFullscreen = true;
      a.after(iframe);
    }
  });

  // ---------- Exchange page: poll for new messages ----------
  const chatLog = document.getElementById("chatLog");
  if (chatLog && window.EXCHANGE_ID) {
    const emptyBox = document.getElementById("chatEmpty");
    const lastMsg = () => {
      const nodes = chatLog.querySelectorAll(".msg");
      return nodes.length ? Math.max(...Array.from(nodes).map((n) => n.dataset.id || 0)) : 0;
    };
    const scrollBottom = () => { chatLog.scrollTop = chatLog.scrollHeight; };
    scrollBottom();

    const poll = async () => {
      try {
        const res = await fetch(`/exchange/${window.EXCHANGE_ID}/messages/after/${lastMsg()}`);
        const rows = await res.json();
        if (!rows.length) return;
        if (emptyBox) emptyBox.remove();
        const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
          (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
        rows.forEach((m) => {
          const mine = m.sender_id === window.ME_ID;
          const wrap = document.createElement("div");
          wrap.className = "msg" + (mine ? " mine" : "");
          wrap.dataset.id = m.id;
          if (m.message_type === "text") {
            const bubble = document.createElement("div");
            bubble.className = "msg-bubble";
            bubble.textContent = m.content;
            wrap.appendChild(bubble);
          } else if (m.message_type === "file") {
            const bubble = document.createElement("div");
            bubble.className = "msg-bubble file-bubble";
            const ico = document.createElement("span");
            ico.className = "file-ico";
            ico.textContent = "📎";
            const info = document.createElement("div");
            const name = document.createElement("div");
            name.textContent = m.file_name || "Shared file";
            const link = document.createElement("a");
            link.className = "file-link";
            link.href = `/uploads/${m.file_path}`;
            link.download = "";
            link.textContent = "Download";
            info.append(name, link);
            bubble.append(ico, info);
            wrap.appendChild(bubble);
          } else {
            const bubble = document.createElement("div");
            bubble.className = "msg-bubble yt-bubble";
            const a = document.createElement("a");
            a.href = m.youtube_url;
            a.target = "_blank";
            a.rel = "noopener";
            a.textContent = m.youtube_url;
            bubble.appendChild(a);
            const id = ytId(m.youtube_url);
            if (id) {
              const iframe = document.createElement("iframe");
              iframe.className = "yt-embed";
              iframe.src = "https://www.youtube.com/embed/" + id;
              iframe.allow = "accelerometer; autoplay; encrypted-media";
              iframe.allowFullscreen = true;
              bubble.appendChild(iframe);
            }
            wrap.appendChild(bubble);
          }
          const meta = document.createElement("div");
          meta.className = "msg-meta";
          meta.textContent = `${m.sender_name} · ${m.created_at}`;
          wrap.appendChild(meta);
          chatLog.appendChild(wrap);
        });
        scrollBottom();
      } catch (e) { /* server temporarily unavailable */ }
    };
    setInterval(poll, 3000);
  }

  // ---------- Certificate lightbox ----------
  const lightbox = document.createElement("div");
  lightbox.className = "lightbox";
  lightbox.style.display = "none";
  lightbox.innerHTML = '<img alt=""><div class="lb-title"></div><button class="lb-close">✕</button>';
  document.body.appendChild(lightbox);
  const closeLb = () => { lightbox.style.display = "none"; };
  lightbox.addEventListener("click", closeLb);
  document.querySelectorAll(".cert-view").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      lightbox.querySelector("img").src = btn.dataset.src;
      lightbox.querySelector(".lb-title").textContent = btn.dataset.title || "";
      lightbox.style.display = "flex";
    });
  });
});
