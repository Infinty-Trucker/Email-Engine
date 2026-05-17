import { useState, useEffect, useCallback, useRef } from "react";
import AdminSettings, { SlackTab } from "./AdminSettings.jsx";
// ─── ERROR BOUNDARY ──────────────────────────────────────────────────────────
import React from "react";
class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(e) { return { error: e }; }
  componentDidCatch(e, info) { console.error("Dispatch OS error:", e, info); }
  render() {
    if (!this.state.error) return this.props.children;
    const msg = this.state.error?.message || String(this.state.error);
    return (
      <div style={{minHeight:"100vh",background:"#05080d",display:"flex",alignItems:"center",justifyContent:"center",fontFamily:"monospace"}}>
        <div style={{background:"#0c1220",border:"1px solid #ef444444",borderRadius:8,padding:32,maxWidth:560,width:"90%"}}>
          <div style={{fontSize:28,marginBottom:12}}>⚠</div>
          <div style={{fontSize:16,color:"#ef4444",fontWeight:600,marginBottom:12}}>Dispatch OS crashed</div>
          <div style={{fontSize:11,color:"#b8c8d8",lineHeight:1.7,marginBottom:20}}>{msg}</div>
          <div style={{background:"#05080d",borderRadius:4,padding:"10px 14px",marginBottom:20}}>
            <div style={{fontSize:9,color:"#3a5068",marginBottom:6,letterSpacing:"0.1em"}}>POSSIBLE CAUSES</div>
            {["Backend not running — docker compose up -d","Session expired — try refreshing the page","API returned unexpected data — check docker compose logs api"].map(s=>(
              <div key={s} style={{fontSize:10,color:"#7a90a8",marginBottom:4}}>• {s}</div>
            ))}
          </div>
          <button onClick={()=>window.location.reload()} style={{background:"#2d7dd2",border:"none",color:"#fff",padding:"8px 18px",borderRadius:4,cursor:"pointer",fontFamily:"monospace",fontSize:10}}>RELOAD PAGE</button>
        </div>
      </div>
    );
  }
}



// ─── DESIGN TOKENS ───────────────────────────────────────────────────────────
const T = {
  // Light theme — clean, professional, high contrast
  bg0:    "#f0f4f8",   // page background — soft blue-gray
  bg1:    "#ffffff",   // sidebar / panels — white
  bg2:    "#f8fafc",   // cards — near-white
  bg3:    "#eef2f7",   // hover / selected rows
  border: "#dde3ec",   // standard borders
  border2:"#c8d2e0",   // stronger borders
  text0:  "#0f1c2e",   // headings — near black
  text1:  "#1e3a5f",   // body text — dark navy
  text2:  "#4a6080",   // secondary text
  text3:  "#8098b4",   // muted text / labels
  accent: "#1a6ed4",   // blue accent
  accentDim: "#dbeafe", // accent background tint
  green:  "#16a34a",   greenDim: "#dcfce7",
  red:    "#dc2626",   redDim:   "#fee2e2",
  yellow: "#d97706",   yellowDim:"#fef9c3",
  orange: "#ea580c",
};

const ROLE_META = {
  dispatcher: { color: "#38bdf8", icon: "🚛", label: "Dispatcher", cats: ["LOAD","DRIVER","GENERAL"], canApprove: false, isAdmin: false },
  accountant:  { color: "#34d399", icon: "💳", label: "Accountant", cats: ["BILLING","CLAIMS","INSURANCE","GENERAL"], canApprove: false, isAdmin: false },
  safety:      { color: "#fb923c", icon: "🛡️", label: "Safety Officer", cats: ["SAFETY","AUDIT","GENERAL"], canApprove: true, isAdmin: false },
  manager:     { color: "#a78bfa", icon: "⚙️", label: "Manager", cats: ["LOAD","DRIVER","BILLING","CLAIMS","INSURANCE","SAFETY","AUDIT","GENERAL"], canApprove: true, isAdmin: false },
  admin:       { color: "#f472b6", icon: "🔧", label: "System Admin", cats: ["LOAD","DRIVER","BILLING","CLAIMS","INSURANCE","SAFETY","AUDIT","GENERAL"], canApprove: true, isAdmin: true },
};

const CAT_META = {
  LOAD:      { icon: "🚛", color: "#f97316", label: "Loads" },
  DRIVER:    { icon: "👤", color: "#38bdf8", label: "Drivers" },
  BILLING:   { icon: "💳", color: "#34d399", label: "Billing" },
  CLAIMS:    { icon: "⚠️", color: "#fb7185", label: "Claims" },
  INSURANCE: { icon: "📄", color: "#818cf8", label: "Insurance" },
  SAFETY:    { icon: "🛡️", color: "#fb923c", label: "Safety" },
  AUDIT:     { icon: "📋", color: "#fbbf24", label: "Audit" },
  GENERAL:   { icon: "📧", color: "#94a3b8", label: "General" },
};

// ─── MESSAGE BODY HELPERS ────────────────────────────────────────────────────

// Strip Gmail's quoted reply text ("On Mon, Jan 1 ... wrote:") from message body
function stripQuotedReply(text) {
  if (!text) return "";
  let cleaned = text
    .replace(/\nOn [\s\S]{5,200}?wrote:[\s\S]*/i, "")   // Gmail "On ... wrote:"
    .replace(/\n>+.*$/gm, "")                             // Lines starting with >
    .replace(/\n-{3,}[\s\S]*/i, "")                      // --- separators
    .replace(/\n_{3,}[\s\S]*/i, "")                      // ___ separators
    .replace(/\nFrom:\s+\S[\s\S]*/i, "")                 // "From:" quote header
    .replace(/\n[_\-]{2,}\r?\nFrom:[\s\S]*/i, "")       // Outlook-style separator
    .replace(/[\n\r]{3,}/g, "\n\n");
  return cleaned.trim();
}

// Normalize snake_case mailbox API fields to camelCase used throughout the UI
function normalizeMb(m) {
  return {
    ...m,
    watchStatus:    m.watch_status    ?? m.watchStatus    ?? "expired",
    lastHistoryId:  m.last_history_id ?? m.lastHistoryId  ?? "",
    watchExpiry:    m.watch_expiry    ?? m.watchExpiry    ?? null,
    displayName:    m.display_name   ?? m.displayName    ?? "",
    companyId:      m.company_id     ?? m.companyId      ?? "",
    email:          m.email_address  ?? m.email          ?? "",
  };
}

// Generate a distinct color per company based on its ID
const COMPANY_PALETTE = ["#f97316","#8b5cf6","#ef4444","#22c55e","#ec4899","#14b8a6","#f59e0b","#6366f1","#06b6d4","#84cc16"];
function getCompanyColor(company) {
  if (company?.color && company.color !== "#38bdf8") return company.color;
  const str = String(company?.id || company?.name || "?");
  let h = 5381;
  for (let i = 0; i < str.length; i++) { h = ((h << 5) + h) + str.charCodeAt(i); h = h & h; }
  return COMPANY_PALETTE[Math.abs(h) % COMPANY_PALETTE.length];
}

// Clean HTML body — remove Gmail quote blocks, signatures, and decode entities
function cleanHtmlBody(html) {
  if (!html) return "";
  const div = document.createElement("div");
  div.innerHTML = html;
  // Remove Gmail quote/reply divs and all blockquotes (quoted content)
  div.querySelectorAll(".gmail_quote, .gmail_extra, blockquote, blockquote[type='cite']").forEach(el => el.remove());
  // Remove signature divs
  div.querySelectorAll(".gmail_signature, .signature, [data-smartmail='gmail_signature']").forEach(el => el.remove());
  // Remove <hr> reply separators and everything after them
  const hrs = div.querySelectorAll("hr");
  hrs.forEach(hr => {
    let node = hr.nextSibling;
    while (node) { const next = node.nextSibling; node.parentNode?.removeChild(node); node = next; }
    hr.remove();
  });
  // Remove "On <date> wrote:" paragraphs and everything after
  const allEls = Array.from(div.querySelectorAll("div, p, span"));
  let cutFrom = null;
  for (const el of allEls) {
    const t = el.textContent?.trim() || "";
    if (/^On .{5,200}wrote:/i.test(t) || /^From:\s+\S/i.test(t)) { cutFrom = el; break; }
  }
  if (cutFrom) {
    let node = cutFrom;
    while (node) { const next = node.nextSibling; node.parentNode?.removeChild(node); node = next; }
  }
  return div.innerHTML.trim();
}

// Decode HTML entities for plain text display
function decodeEntities(text) {
  if (!text) return "";
  const el = document.createElement("div");
  el.innerHTML = text;
  return el.textContent || el.innerText || text;
}

// ─── API HELPERS ─────────────────────────────────────────────────────────────
function getCsrfToken() {
  const m = document.cookie.split(";").find(c => c.trim().startsWith("csrftoken="));
  return m ? decodeURIComponent(m.trim().split("=")[1]) : "";
}

async function callApi(method, path, body) {
  const needsCsrf = !["GET","HEAD"].includes(method.toUpperCase());
  let token = getCsrfToken();
  if (needsCsrf && !token) {
    await fetch("/api/auth/csrf/", { credentials: "include" }).catch(() => {});
    token = getCsrfToken();
  }
  const opts = {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
  };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`/api${path}`, opts);
  if (!r.ok) {
    const e = await r.json().catch(() => ({ error: r.statusText }));
    // Handle DRF validation errors like {"username": ["already exists"]}
    let msg = e.error || e.detail || "";
    if (!msg) {
      const fields = Object.entries(e).filter(([k]) => k !== "error" && k !== "detail");
      if (fields.length) msg = fields.map(([k,v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join("; ");
    }
    throw new Error(msg || r.statusText);
  }
  return r.status === 204 ? null : r.json();
}

// Upload FormData (multipart) — used for file attachments
async function callApiForm(method, path, formData) {
  const needsCsrf = !["GET","HEAD"].includes(method.toUpperCase());
  let token = getCsrfToken();
  if (needsCsrf && !token) {
    await fetch("/api/auth/csrf/", { credentials: "include" }).catch(() => {});
    token = getCsrfToken();
  }
  const opts = {
    method,
    credentials: "include",
    headers: token ? { "X-CSRFToken": token } : {},
    body: formData,
  };
  const r = await fetch(`/api${path}`, opts);
  if (!r.ok) {
    const e = await r.json().catch(() => ({ error: r.statusText }));
    throw new Error(e.error || e.detail || r.statusText);
  }
  return r.status === 204 ? null : r.json();
}


// ─── SHARED COMPONENTS ────────────────────────────────────────────────────────
const Btn = ({ onClick, children, variant = "ghost", size = "sm", disabled, style }) => {
  const variants = {
    primary: { bg: T.accent, border: T.accent, color: "#fff" },
    ghost:   { bg: T.bg1, border: T.border, color: T.text2 },
    danger:  { bg: T.redDim, border: T.red + "44", color: T.red },
    success: { bg: T.greenDim, border: T.green + "44", color: T.green },
    warning: { bg: T.yellowDim, border: T.yellow + "44", color: T.yellow },
  };
  const v = variants[variant] || variants.ghost;
  return (
    <button onClick={onClick} disabled={disabled}
      style={{ background: v.bg, border: `1px solid ${v.border}`, color: v.color, padding: size === "xs" ? "2px 8px" : "5px 12px", borderRadius: 3, cursor: disabled ? "not-allowed" : "pointer", fontFamily: "inherit", fontSize: size === "xs" ? 9 : 10, letterSpacing: "0.08em", opacity: disabled ? 0.4 : 1, transition: "all 0.15s", ...style }}>
      {children}
    </button>
  );
};

const Badge = ({ color, children }) => (
  <span style={{ fontSize: 9, fontWeight: 600, background: color + "15", color, border: `1px solid ${color}40`, padding: "2px 8px", borderRadius: 4, letterSpacing: "0.04em", whiteSpace: "nowrap" }}>{children}</span>
);

const StatusDot = ({ status }) => {
  const c = { active: T.green, expired: T.yellow, error: T.red, pending: T.yellow, connected: T.green, disconnected: T.red }[status] || T.text3;
  return <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: c, flexShrink: 0, boxShadow: `0 0 0 2px ${c}25` }} />;
};

const Input = ({ value, onChange, placeholder, type = "text", style }) => (
  <input type={type} value={value} onChange={onChange} placeholder={placeholder}
    style={{ background: "#fff", border: `1px solid ${T.border}`, color: T.text0, padding: "8px 12px", borderRadius: 6, fontFamily: "inherit", fontSize: 12, width: "100%", outline: "none", boxShadow: "inset 0 1px 2px rgba(0,0,0,0.04)", ...style }}
    onFocus={e => { e.target.style.borderColor = T.accent; e.target.style.boxShadow = `0 0 0 3px ${T.accent}18`; }}
    onBlur={e =>  { e.target.style.borderColor = T.border; e.target.style.boxShadow = "inset 0 1px 2px rgba(0,0,0,0.04)"; }} />
);

const Select = ({ value, onChange, options, style }) => (
  <select value={value} onChange={onChange}
    style={{ background: "#fff", border: `1px solid ${T.border}`, color: T.text0, padding: "8px 12px", borderRadius: 6, fontFamily: "inherit", fontSize: 12, width: "100%", cursor: "pointer", ...style }}>
    {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
  </select>
);

const Card = ({ children, style }) => (
  <div style={{ background: "#fff", border: `1px solid ${T.border}`, borderRadius: 8, boxShadow: "0 1px 3px rgba(0,0,0,0.06)", ...style }}>{children}</div>
);

// ─── EMAIL FORMATTING ────────────────────────────────────────────────────────
// Light markdown-ish syntax → HTML for outbound emails.
// Supports: **bold**, *italic*, __underline__, links, bullets (- ), numbers (1. ), blank lines as paragraphs.
function markdownToEmailHtml(text) {
  if (!text) return "";
  const escape = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  const blocks = text.split(/\n\s*\n/);
  const html = blocks.map(block => {
    const lines = block.split("\n");
    // Bullet list
    if (lines.every(l => /^\s*[-*]\s+/.test(l))) {
      return "<ul>" + lines.map(l => "<li>" + inline(l.replace(/^\s*[-*]\s+/,"")) + "</li>").join("") + "</ul>";
    }
    // Numbered list
    if (lines.every(l => /^\s*\d+\.\s+/.test(l))) {
      return "<ol>" + lines.map(l => "<li>" + inline(l.replace(/^\s*\d+\.\s+/,"")) + "</li>").join("") + "</ol>";
    }
    // Paragraph with line breaks
    return "<p>" + lines.map(inline).join("<br>") + "</p>";
  }).join("");
  return html;

  function inline(s) {
    s = escape(s);
    // [label](url)
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
    // bare URLs
    s = s.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1">$1</a>');
    // **bold**
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // *italic*
    s = s.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
    // __underline__
    s = s.replace(/__([^_\n]+)__/g, "<u>$1</u>");
    return s;
  }
}

// Wrap or insert formatting markers around the current textarea selection
function applyFormat(textareaRef, value, setValue, kind) {
  const el = textareaRef.current;
  if (!el) return;
  const start = el.selectionStart;
  const end   = el.selectionEnd;
  const sel   = value.substring(start, end);
  const before = value.substring(0, start);
  const after  = value.substring(end);

  let inserted = "", caret = 0;
  switch(kind) {
    case "bold":      inserted = `**${sel || "bold text"}**`;       caret = sel ? inserted.length : 2 + (sel ? 0 : "bold text".length); break;
    case "italic":    inserted = `*${sel || "italic"}*`;            caret = sel ? inserted.length : 1 + (sel ? 0 : "italic".length); break;
    case "underline": inserted = `__${sel || "underlined"}__`;      caret = sel ? inserted.length : 2 + (sel ? 0 : "underlined".length); break;
    case "bullet": {
      const lines = (sel || "item").split("\n").map(l => l.trim() ? `- ${l}` : l).join("\n");
      inserted = lines; caret = inserted.length; break;
    }
    case "number": {
      const lines = (sel || "item").split("\n").map((l,i) => l.trim() ? `${i+1}. ${l}` : l).join("\n");
      inserted = lines; caret = inserted.length; break;
    }
    case "link": {
      const url = window.prompt("Enter URL:", "https://");
      if (!url) return;
      inserted = `[${sel || "link text"}](${url})`; caret = inserted.length; break;
    }
    case "linebreak": inserted = "\n\n"; caret = 2; break;
    default: return;
  }
  const next = before + inserted + after;
  setValue(next);
  // Restore selection after React re-renders
  requestAnimationFrame(() => {
    el.focus();
    const pos = start + caret;
    el.setSelectionRange(pos, pos);
  });
}

const RichTextArea = ({ value, onChange, placeholder, rows = 9, signature = "" }) => {
  const ref = useRef(null);
  const tools = [
    { key: "bold",      icon: "B",     style: { fontWeight: 700 } },
    { key: "italic",    icon: "I",     style: { fontStyle: "italic" } },
    { key: "underline", icon: "U",     style: { textDecoration: "underline" } },
    { key: "bullet",    icon: "• List" },
    { key: "number",    icon: "1. List" },
    { key: "link",      icon: "🔗 Link" },
  ];
  function insertSignature() {
    const sig = signature || "\n\nBest regards,\n[Your Name]";
    onChange({ target: { value: (value || "") + sig } });
  }
  return (
    <div style={{ border: `1px solid ${T.border}`, borderRadius: 6, overflow: "hidden", background: "#fff" }}>
      <div style={{ display: "flex", gap: 4, padding: "6px 8px", borderBottom: `1px solid ${T.border}`, background: T.bg2, alignItems: "center", flexWrap: "wrap" }}>
        {tools.map(t => (
          <button key={t.key} type="button" onMouseDown={e => e.preventDefault()}
            onClick={() => applyFormat(ref, value, v => onChange({ target: { value: v } }), t.key)}
            title={t.key}
            style={{ background: "transparent", border: `1px solid ${T.border}`, borderRadius: 4, padding: "3px 8px",
              cursor: "pointer", fontFamily: "inherit", fontSize: 11, color: T.text1, ...t.style }}>
            {t.icon}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        {signature !== null && (
          <button type="button" onMouseDown={e => e.preventDefault()} onClick={insertSignature}
            style={{ background: "transparent", border: `1px solid ${T.border}`, borderRadius: 4, padding: "3px 8px",
              cursor: "pointer", fontFamily: "inherit", fontSize: 10, color: T.text2 }}>
            ✍ Signature
          </button>
        )}
        <span style={{ fontSize: 9, color: T.text3, marginLeft: 8 }}>
          *bold*, _italic_, [link](url) supported
        </span>
      </div>
      <textarea ref={ref} value={value || ""} onChange={onChange} rows={rows} placeholder={placeholder}
        style={{ width: "100%", border: "none", padding: "10px 12px", fontFamily: "inherit", fontSize: 12,
          lineHeight: 1.7, resize: "vertical", boxSizing: "border-box", outline: "none", color: T.text1 }} />
    </div>
  );
};

// ─── INLINE ATTACHMENT PREVIEW ────────────────────────────────────────────────
// Shows a chip with file info; click to expand into an inline viewer
// (PDF iframe / image tag / text snippet). Falls back to download for unknowns.
const AttachmentPreview = ({ att }) => {
  const [open, setOpen] = useState(false);
  const mime = (att.mime_type || "").toLowerCase();
  const fn   = (att.filename || "").toLowerCase();
  const url  = att.url || "#";
  const isPdf   = mime.includes("pdf") || fn.endsWith(".pdf");
  const isImage = mime.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(fn);
  const isText  = mime.startsWith("text/") || /\.(txt|csv|json|log|md)$/i.test(fn);
  const previewable = isPdf || isImage || isText;

  const icon = isPdf ? "📄" : isImage ? "🖼️" : isText ? "📝" : "📎";
  const sizeStr = att.size > 0
    ? (att.size < 1048576 ? `${(att.size/1024).toFixed(0)} KB` : `${(att.size/1048576).toFixed(1)} MB`)
    : "";

  return (
    <div style={{ border: `1px solid ${T.border}`, borderRadius: 6, overflow: "hidden", background: T.bg1 }}>
      {/* Chip header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: T.bg2 }}>
        <span style={{ fontSize: 14 }}>{icon}</span>
        <span style={{ flex: 1, fontSize: 11, color: T.text0, fontWeight: 500, wordBreak: "break-all" }}>
          {att.filename}
        </span>
        {sizeStr && <span style={{ fontSize: 9, color: T.text3 }}>{sizeStr}</span>}
        {previewable && (
          <button onClick={() => setOpen(o => !o)}
            style={{ background: T.accent, border: "none", color: "#fff", padding: "3px 9px",
              borderRadius: 3, cursor: "pointer", fontFamily: "inherit", fontSize: 10, fontWeight: 600 }}>
            {open ? "✕ Hide" : "👁 Preview"}
          </button>
        )}
        <a href={url + (url.includes("?") ? "&" : "?") + "download=1"}
          download={att.filename} target="_blank" rel="noopener noreferrer"
          style={{ background: "transparent", border: `1px solid ${T.border}`, color: T.text2,
            padding: "3px 9px", borderRadius: 3, fontFamily: "inherit", fontSize: 10, fontWeight: 600,
            textDecoration: "none" }}>
          ⬇ Download
        </a>
      </div>
      {/* Inline preview */}
      {open && previewable && (
        <div style={{ borderTop: `1px solid ${T.border}`, background: "#fff" }}>
          {isPdf && (
            <iframe src={url} title={att.filename}
              style={{ width: "100%", height: 600, border: "none", display: "block" }} />
          )}
          {isImage && (
            <div style={{ padding: 8, textAlign: "center", background: T.bg2 }}>
              <img src={url} alt={att.filename}
                style={{ maxWidth: "100%", maxHeight: 600, height: "auto", borderRadius: 4 }} />
            </div>
          )}
          {isText && <TextPreview url={url} />}
        </div>
      )}
    </div>
  );
};

const TextPreview = ({ url }) => {
  const [content, setContent] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let cancelled = false;
    fetch(url, { credentials: "include" })
      .then(r => r.ok ? r.text() : Promise.reject(r.statusText))
      .then(txt => { if (!cancelled) setContent(txt.slice(0, 50000)); })
      .catch(e => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [url]);
  if (error) return <div style={{ padding: 12, fontSize: 11, color: T.red }}>Failed to load: {error}</div>;
  if (content === null) return <div style={{ padding: 12, fontSize: 11, color: T.text3 }}>Loading…</div>;
  return (
    <pre style={{ margin: 0, padding: 12, fontSize: 11, lineHeight: 1.5, color: T.text1,
      maxHeight: 500, overflow: "auto", whiteSpace: "pre-wrap", fontFamily: "ui-monospace,Menlo,monospace" }}>
      {content}
    </pre>
  );
};

const SectionHeader = ({ title, subtitle, action }) => (
  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
    <div>
      <div style={{ fontSize: 16, fontWeight: 700, color: T.text0 }}>{title}</div>
      {subtitle && <div style={{ fontSize: 12, color: T.text3, marginTop: 3 }}>{subtitle}</div>}
    </div>
    {action}
  </div>
);

// ─── ROOT ─────────────────────────────────────────────────────────────────────
function DispatchOSApp() {
  const [currentUser, setCurrentUser] = useState(null);
  const [view, setView] = useState("operator");
  const [companies, setCompanies] = useState([]);
  const [mailboxes, setMailboxes] = useState([]);
  const [users, setUsers] = useState([]);

  const [emails, setEmails] = useState([]);
  const [complianceLog, setComplianceLog] = useState([]);
  const [approvalQueue, setApprovalQueue] = useState([]);

  // Capture ?conversation=<id> from the URL immediately on page load, before
  // login or any redirect strips it. OperatorUI will pick it up after mount.
  const [pendingDeepLinkConvId] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("conversation");
    if (id) {
      const url = new URL(window.location.href);
      url.searchParams.delete("conversation");
      window.history.replaceState({}, "", url);
    }
    return id;
  });
  const [notifications, setNotifications] = useState([]);
  const [emailsLoading, setEmailsLoading] = useState(false);

  // Fetch real conversations from Django API
  const fetchConversations = useCallback(async (user) => {
    if (!user) return;
    setEmailsLoading(true);
    try {
      // Limit to recent 200 conversations — full list crashes the browser
      const r = await fetch("/api/conversations/?limit=200", { credentials: "include" });
      if (!r.ok) {
        console.error("Conversations API error:", r.status, r.statusText);
        setEmailsLoading(false);
        return;
      }
      const data = await r.json();
      const convs = Array.isArray(data) ? data : (data.results || []);
      // Map Django conversation shape → UI email shape
      const mapped = convs.map(c => {
        const lastMsg = c.messages?.filter(m => m.direction === "inbound").slice(-1)[0];
        const cls     = c.latest_classification;
        return {
          id:          c.id,
          companyId:   String(c.company_id || ''),
          mailboxId:   c.mailbox_email,
          from:        lastMsg?.sender_email || "",
          subject:     lastMsg?.subject || c.messages?.[0]?.subject || "(no subject)",
          body:        lastMsg?.body_text || lastMsg?.snippet || "",
          body_html:   lastMsg?.body_html || "",
          snippet:     lastMsg?.snippet || "",
          time: (() => {
            if (!c.last_message_at) return "";
            const d = new Date(c.last_message_at);
            const now = new Date();
            const diffMs  = now - d;
            const diffMin = Math.floor(diffMs / 60000);
            const diffHr  = Math.floor(diffMs / 3600000);
            const diffDay = Math.floor(diffMs / 86400000);
            // Relative for recent, absolute for older
            if (diffMin < 1)   return "just now";
            if (diffMin < 60)  return `${diffMin}m ago`;
            if (diffHr  < 24)  return `${diffHr}h ago`;
            if (diffDay === 1) return "yesterday " + d.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});
            if (diffDay < 7)   return `${diffDay}d ago`;
            const isThisYear = d.getFullYear() === now.getFullYear();
            if (isThisYear)    return d.toLocaleDateString([], {month:"short",day:"numeric"});
            return d.toLocaleDateString([], {month:"short",day:"numeric",year:"2-digit"});
          })(),
          gmailThreadId: c.gmail_thread_id,
          category:    c.category || (cls?.category ?? null),
          priority:    c.priority || (cls?.priority ?? null),
          summary:     cls?.ai_summary || null,
          status:      c.status || "open",
          messages:    (c.messages || []).map(m => ({
            id:        m.id,
            direction: m.direction,
            body:      m.body_text || m.snippet || "",
            body_html: m.body_html || "",
            sender:    m.direction === "inbound" ? m.sender_email : "You",
            time:      m.created_at ? new Date(m.created_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}) : "",
          })),
          companyName:  c.company_name,
          mailboxEmail: c.mailbox_email,
          attachments:  (c.messages || []).flatMap(m => (m.attachments || []).map(a => ({...a, msgId: m.id}))),
        };
      });
      setEmails(mapped.length > 0 ? mapped : []);
      // Refresh selected email if open
      if (window.__selectedEmailId) {
        const fresh = mapped.find(m => m.id === window.__selectedEmailId);
        if (fresh) window.dispatchEvent(new CustomEvent("conversation-refreshed", { detail: fresh }));
      }
    } catch (e) {
      console.error("Failed to load conversations:", e);
      setEmails([]);
    }
    setEmailsLoading(false);
  }, []);

  const addNotification = useCallback((msg, type = "info") => {
    const id = Date.now();
    setNotifications(p => [...p, { id, msg, type }]);
    setTimeout(() => setNotifications(p => p.filter(n => n.id !== id)), 4000);
  }, []);

  // Check existing session on first load
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/auth/me/", { credentials: "include" });
        if (r.ok) {
          const data = await r.json();
          const role = data.role || "dispatcher";
          const user = {
            id: data.id, name: data.first_name ? `${data.first_name} ${data.last_name}`.trim() : data.username,
            role, username: data.username, email: data.email,
            assignedMCs: (data.assigned_companies || []),
            avatar: (data.first_name?.[0] || data.username?.[0] || "?").toUpperCase(),
            active: true,
          };
          setCurrentUser(user);
          setView(["admin","manager"].includes(role) ? "admin" : "operator");
          fetchConversations(user);
          // Load real companies from DB
          callApi("GET", "/companies/").then(d => setCompanies(Array.isArray(d) ? d : (d?.results || []))).catch(() => setCompanies([]));
        }
      } catch { /* not logged in */ }
    })();
  }, [fetchConversations]);

  // Auto-refresh inbox every 60 seconds — skipped if the tab is hidden so
  // background tabs don't keep loading data and ballooning memory.
  useEffect(() => {
    const interval = setInterval(() => {
      if (currentUser && !document.hidden) fetchConversations(currentUser);
    }, 60000);
    return () => clearInterval(interval);
  }, [currentUser, fetchConversations]);

  // If a deep link was captured, force the view into the operator UI
  // (admins normally land on admin dashboard but email links should open the thread)
  useEffect(() => {
    if (pendingDeepLinkConvId && currentUser) setView("operator");
  }, [pendingDeepLinkConvId, currentUser]);

  // Logout handler
  async function handleLogout() {
    try {
      const m = document.cookie.split(";").find(c => c.trim().startsWith("csrftoken="));
      const token = m ? decodeURIComponent(m.trim().split("=")[1]) : "";
      await fetch("/api/auth/logout/", { method:"POST", credentials:"include", headers:{"X-CSRFToken":token} });
    } catch {}
    setCurrentUser(null);
    setView("operator");
  }

  if (!currentUser) return (
    <LoginScreen onLogin={u => {
      setCurrentUser(u);
      setView(["admin","manager"].includes(u.role) ? "admin" : "operator");
      fetchConversations(u);
      // Load companies
      callApi("GET", "/companies/")
        .then(d => setCompanies(Array.isArray(d) ? d : (d?.results || [])))
        .catch(() => setCompanies([]));
      // Load mailboxes so compose modal From dropdown works immediately
      callApi("GET", "/settings/mailboxes/")
        .then(mbs => setMailboxes(Array.isArray(mbs) ? mbs.map(normalizeMb) : []))
        .catch(() => setMailboxes([]));
    }} />
  );

  const role = ROLE_META[currentUser.role];

  return (
    <div style={{ fontFamily: "'Plus Jakarta Sans','Segoe UI',system-ui,sans-serif", background: T.bg0, color: T.text1, height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; scrollbar-width: thin; scrollbar-color: ${T.border2} ${T.bg0}; }
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-thumb { background: ${T.border2}; border-radius: 4px; }
        .hover-row:hover { background: ${T.bg3} !important; cursor: pointer; }
        .nav-item:hover { background: ${T.accentDim} !important; }
        button { transition: all 0.15s ease; }
        button:hover:not(:disabled) { filter: brightness(0.92); }
        .hover-item:hover { background: ${T.bg2}; cursor: pointer; }
        input::placeholder, textarea::placeholder { color: ${T.text3}; }
        select option { background: ${T.bg2}; }
        .fade-in { animation: fadeIn 0.2s ease-out; }
        @keyframes fadeIn { from{opacity:0;transform:translateY(3px)} to{opacity:1;transform:translateY(0)} }
        .pulse { animation: pulse 2s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
      `}</style>

      {/* Top Bar */}
      <div style={{ height: 44, background: T.bg1, borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", padding: "0 14px", gap: 12, flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginRight: 8 }}>
          <span style={{ fontSize: 16 }}>📡</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: T.text0, letterSpacing: "0.2em" }}>DISPATCH OS</span>
        </div>

        {/* View switcher */}
        {(role.isAdmin || currentUser.role === "manager") && (
          <div style={{ display: "flex", gap: 2 }}>
            {["operator","admin"].map(v => (
              <button key={v} onClick={() => setView(v)} style={{ background: view === v ? T.accentDim : "transparent", border: `1px solid ${view === v ? T.accent + "66" : "transparent"}`, color: view === v ? T.accent : T.text3, padding: "3px 12px", borderRadius: 3, cursor: "pointer", fontFamily: "inherit", fontSize: 9, letterSpacing: "0.12em", transition: "all 0.15s" }}>
                {v === "operator" ? "OPS" : "ADMIN"}
              </button>
            ))}
          </div>
        )}

        <div style={{ flex: 1 }} />

        {/* Notifications */}
        {notifications.map(n => (
          <div key={n.id} className="fade-in" style={{ fontSize: 9, padding: "3px 10px", borderRadius: 3, background: n.type === "success" ? T.greenDim : n.type === "error" ? T.redDim : T.accentDim, color: n.type === "success" ? T.green : n.type === "error" ? T.red : T.accent, border: `1px solid currentColor`, opacity: 0.9 }}>
            {n.msg}
          </div>
        ))}

        {approvalQueue.length > 0 && (
          <div style={{ fontSize: 9, background: T.yellowDim, border: `1px solid ${T.yellow}44`, color: T.yellow, padding: "3px 10px", borderRadius: 3 }}>
            ⏳ {approvalQueue.length} PENDING
          </div>
        )}

        {/* User badge */}
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <div style={{ width: 24, height: 24, borderRadius: "50%", background: role.color + "22", border: `1px solid ${role.color}44`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, color: role.color, fontWeight: 500 }}>
            {currentUser.avatar}
          </div>
          <div>
            <div style={{ fontSize: 10, color: T.text0, lineHeight: 1.2 }}>{currentUser.name}</div>
            <div style={{ fontSize: 8, color: role.color, letterSpacing: "0.1em" }}>{role.label.toUpperCase()}</div>
          </div>
          <button onClick={handleLogout} style={{ background: "transparent", border: `1px solid ${T.border}`, color: T.text3, cursor: "pointer", fontSize: 9, padding: "3px 8px", borderRadius: 3, fontFamily: "inherit", letterSpacing: "0.08em" }}>LOGOUT</button>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {view === "operator" ? (
          <OperatorUI
            currentUser={currentUser}
            companies={companies}
            mailboxes={mailboxes}
            emails={emails}
            setEmails={setEmails}
            emailsLoading={emailsLoading}
            onRefresh={async () => {
              // Pull new emails from Gmail then refresh the inbox
              try {
                const mbs = await callApi("GET", "/settings/mailboxes/");
                if (mbs && mbs.length > 0) {
                  await Promise.all(
                    mbs.filter(m => m.is_authorized).map(m =>
                      callApi("POST", `/settings/mailboxes/${m.id}/sync/`, {limit: 50})
                        .catch(() => {}) // don't block if one fails
                    )
                  );
                }
              } catch(e) { /* ignore, still refresh from DB */ }
              fetchConversations(currentUser);
            }}
            complianceLog={complianceLog}
            setComplianceLog={setComplianceLog}
            approvalQueue={approvalQueue}
            setApprovalQueue={setApprovalQueue}
            addNotification={addNotification}
            pendingDeepLinkConvId={pendingDeepLinkConvId}
          />
        ) : (
          <AdminUI
            companies={companies} setCompanies={setCompanies}
            mailboxes={mailboxes} setMailboxes={setMailboxes}
            users={users} setUsers={setUsers}
            complianceLog={complianceLog}
            addNotification={addNotification}
          />
        )}
      </div>
    </div>
  );
}

// ─── LOGIN ────────────────────────────────────────────────────────────────────
function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState("");

  async function getCsrf() {
    try { await fetch("/api/auth/csrf/", { credentials: "include" }); } catch {}
    const m = document.cookie.split(";").find(c => c.trim().startsWith("csrftoken="));
    return m ? decodeURIComponent(m.trim().split("=")[1]) : "";
  }

  async function handleSubmit(e) {
    e && e.preventDefault();
    if (!username || !password) { setError("Enter your username and password."); return; }
    setLoading(true); setError("");
    try {
      const token = await getCsrf();
      const r = await fetch("/api/auth/login/", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "X-CSRFToken": token },
        body: JSON.stringify({ username, password }),
      });
      const data = await r.json();
      if (!r.ok) {
        setError(data.error || "Invalid username or password.");
        setLoading(false); return;
      }
      // Map Django role to UI role/view
      const ROLE_MAP = { dispatcher:"dispatcher", accountant:"accountant", safety:"safety", manager:"manager", admin:"admin" };
      const role = ROLE_MAP[data.role] || "dispatcher";
      onLogin({
        id:   data.id,
        name: data.first_name ? `${data.first_name} ${data.last_name}`.trim() : data.username,
        role,
        username: data.username,
        email:    data.email,
        assignedMCs: (data.assigned_companies || []).map(c => c),
        avatar: (data.first_name?.[0] || data.username?.[0] || "?").toUpperCase(),
        active: true,
      });
    } catch (err) {
      setError("Cannot reach the server. Make sure Docker is running: docker compose up -d");
      setLoading(false);
    }
  }

  return (
    <div style={{ fontFamily:"'Plus Jakarta Sans','Segoe UI',system-ui,sans-serif", background:"linear-gradient(135deg, #f0f4f8 0%, #e8eef5 100%)", color:T.text1, height:"100vh", display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center" }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap'); * { box-sizing:border-box; }`}</style>
      <div style={{ fontSize:36, marginBottom:12 }}>📡</div>
      <div style={{ fontSize:22, fontWeight:700, color:T.text0, marginBottom:4 }}>Dispatch OS</div>
      <div style={{ fontSize:12, color:T.text3, marginBottom:28 }}>Multi-MC Freight Operations Platform</div>

      <div style={{background:"#fff",borderRadius:12,padding:32,boxShadow:"0 4px 24px rgba(0,0,0,0.08)",width:360,marginTop:8}}>
      <form onSubmit={handleSubmit} style={{ display:"flex", flexDirection:"column", gap:14 }}>
        <div>
          <div style={{ fontSize:12, fontWeight:600, color:T.text2, marginBottom:6 }}>Username</div>
          <input
            value={username} onChange={e => setUsername(e.target.value)}
            placeholder="Enter your username"
            autoFocus autoComplete="username"
            style={{ width:"100%", background:"#fff", border:`1px solid ${T.border}`, color:T.text0, padding:"11px 14px", borderRadius:8, fontFamily:"inherit", fontSize:13, outline:"none", boxShadow:"inset 0 1px 2px rgba(0,0,0,0.04)" }}
            onFocus={e => e.target.style.borderColor = T.accent}
            onBlur={e  => e.target.style.borderColor = T.border}
          />
        </div>
        <div>
          <div style={{ fontSize:12, fontWeight:600, color:T.text2, marginBottom:6 }}>Password</div>
          <input
            value={password} onChange={e => setPassword(e.target.value)}
            type="password" placeholder="Enter your password"
            autoComplete="current-password"
            style={{ width:"100%", background:"#fff", border:`1px solid ${T.border}`, color:T.text0, padding:"11px 14px", borderRadius:8, fontFamily:"inherit", fontSize:13, outline:"none", boxShadow:"inset 0 1px 2px rgba(0,0,0,0.04)" }}
            onFocus={e => e.target.style.borderColor = T.accent}
            onBlur={e  => e.target.style.borderColor = T.border}
          />
        </div>

        {error && (
          <div style={{ background:T.redDim, border:`1px solid ${T.red}44`, borderRadius:4, padding:"10px 14px", fontSize:10, color:T.red, lineHeight:1.5 }}>
            {error}
          </div>
        )}

        <button type="submit" disabled={loading}
          style={{ background:T.accent, border:"none", color:"#fff", padding:"12px", borderRadius:8, cursor:loading?"not-allowed":"pointer", fontFamily:"inherit", fontSize:13, fontWeight:600, opacity:loading?0.7:1, marginTop:4, boxShadow:"0 2px 8px rgba(26,110,212,0.35)" }}>
          {loading ? "Signing in…" : "Sign In"}
        </button>
      </form>
      </div>

      <div style={{ marginTop:20, padding:"14px 20px", background:"#fff", border:`1px solid ${T.border}`, borderRadius:8, width:360, boxShadow:"0 1px 4px rgba(0,0,0,0.06)" }}>
        <div style={{ fontSize:11, fontWeight:600, color:T.text2, marginBottom:8 }}>First time? Create your admin account:</div>
        <div style={{ fontSize:11, color:T.text2, lineHeight:1.7 }}>
          Create your admin account by running:<br/>
          <span style={{ color:T.accent, fontFamily:"monospace" }}>docker compose exec api python manage.py createsuperuser</span>
        </div>
      </div>

      <div style={{ marginTop:12, fontSize:9, color:T.text3 }}>
        Forgot password? Ask your Dispatch OS admin.
      </div>
    </div>
  );
}

// ─── OPERATOR UI ──────────────────────────────────────────────────────────────
function OperatorUI({ currentUser, companies, mailboxes, emails, setEmails, emailsLoading, onRefresh, complianceLog, setComplianceLog, approvalQueue, setApprovalQueue, addNotification, pendingDeepLinkConvId }) {
  const [tab, setTab] = useState("inbox");
  const [folder, setFolder] = useState("ALL");
  const [mcFilter, setMcFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [selectedEmail, setSelectedEmail] = useState(null);
  const classifying = false; // classification is now server-side
  const [replyOpen, setReplyOpen]   = useState(false);
  const [composeOpen, setCompose]   = useState(false);
  const [instruction, setInstruction] = useState("");
  const [replyCC, setReplyCC]       = useState("");
  const [draft, setDraft]           = useState("");
  const [draftLoading, setDraftLoading] = useState(false);
  const [sending, setSending]       = useState(false);
  // Compose new email state
  const [composeTo, setComposeTo]   = useState("");
  const [composeCC, setComposeCC]   = useState("");
  const [composeSub, setComposeSub] = useState("");
  const [composeDraft, setComposeDraft] = useState("");
  const [composeSending, setComposeSending] = useState(false);
  const [selectedMailboxId, setSelectedMailboxId] = useState("");
  // Attachment state for reply and compose
  const [replyFiles, setReplyFiles]     = useState([]);
  const [composeFiles, setComposeFiles] = useState([]);

  const role = ROLE_META[currentUser.role];
  const isAdminRole = ["admin","manager"].includes(currentUser.role);
  // admins see all companies; others see only assigned ones
  const myMCs = isAdminRole
    ? companies.map(c => String(c.id))
    : (currentUser.assignedMCs || []).map(String);

  // Mailboxes the current user is allowed to send from. Admins/managers see
  // every connected mailbox; everyone else only sees mailboxes that belong to
  // a company they are assigned to.
  const availableMailboxes = mailboxes.filter(m => {
    const connected = m.is_authorized || m.sa_authorized || m.oauth_authorized || m.oauth_valid;
    if (!connected) return false;
    if (isAdminRole) return true;
    return myMCs.includes(String(m.company_id));
  });

  // The default "from" mailbox to use when composing. For non-admins this is
  // the mailbox of their first assigned company.
  function defaultMailboxId() {
    return availableMailboxes[0]?.id || "";
  }

  function openCompose() {
    // Always re-validate: if the current selection isn't in the user's available
    // list (e.g. they were unassigned from that company), fall back to default.
    const ids = new Set(availableMailboxes.map(m => m.id));
    if (!selectedMailboxId || !ids.has(selectedMailboxId)) {
      setSelectedMailboxId(defaultMailboxId());
    }
    setCompose(true);
  }

  // Keep selectedMailboxId in sync if mailboxes/assignments change while the
  // app is open (e.g. after admin reassigns a user).
  useEffect(() => {
    if (!availableMailboxes.length) return;
    const ids = new Set(availableMailboxes.map(m => m.id));
    if (selectedMailboxId && !ids.has(selectedMailboxId)) {
      setSelectedMailboxId(availableMailboxes[0].id);
    } else if (!selectedMailboxId) {
      setSelectedMailboxId(availableMailboxes[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableMailboxes.length]);

  // Classification now happens server-side during ingestion (keyword-based, instant, free)
  // No client-side Claude API calls needed

  // Deep link: ?conversation=<id> was captured at page load time and passed
  // down as a prop. On mount, open it — use cache if available, otherwise
  // fetch it directly so older threads still open.
  useEffect(() => {
    if (!pendingDeepLinkConvId) return;

    const cached = emails.find(e => String(e.id) === String(pendingDeepLinkConvId));
    if (cached) {
      setSelectedEmail(cached);
      return;
    }

    (async () => {
      try {
        const c = await callApi("GET", `/conversations/${pendingDeepLinkConvId}/`);
        if (!c) return;
        const lastMsg = c.messages?.filter(m => m.direction === "inbound").slice(-1)[0];
        const cls = c.latest_classification;
        const mapped = {
          id:          c.id,
          companyId:   String(c.company_id || ''),
          mailboxId:   c.mailbox_email,
          from:        lastMsg?.sender_email || "",
          subject:     lastMsg?.subject || c.messages?.[0]?.subject || "(no subject)",
          body:        lastMsg?.body_text || lastMsg?.snippet || "",
          body_html:   lastMsg?.body_html || "",
          snippet:     lastMsg?.snippet || "",
          time:        c.last_message_at ? new Date(c.last_message_at).toLocaleString() : "",
          category:    c.category || (cls?.category ?? null),
          priority:    c.priority || (cls?.priority ?? null),
          summary:     cls?.ai_summary || null,
          status:      c.status || "open",
          messages:    (c.messages || []).map(m => ({
            id:        m.id,
            direction: m.direction,
            body:      m.body_text || m.snippet || "",
            body_html: m.body_html || "",
            sender:    m.direction === "inbound" ? m.sender_email : "You",
            time:      m.created_at ? new Date(m.created_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}) : "",
          })),
          companyName:  c.company_name,
          mailboxEmail: c.mailbox_email,
          attachments:  (c.messages || []).flatMap(m => (m.attachments || []).map(a => ({...a, msgId: m.id}))),
        };
        setSelectedEmail(mapped);
        setEmails(p => p.find(e => e.id === mapped.id) ? p : [mapped, ...p]);
      } catch(e) {
        addNotification("Could not open conversation: " + e.message, "error");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingDeepLinkConvId]);

  // admins/managers see all; others filtered by assigned company UUIDs
  const visible = emails.filter(e => {
    const isAdminRole = ["admin","manager"].includes(currentUser.role);
    const mcOk    = isAdminRole || myMCs.length === 0 || myMCs.map(String).includes(String(e.companyId));
    const catOk   = folder === "SENT" || !e.category || role.cats.includes(e.category);
    const mcF     = mcFilter === "ALL" || String(e.companyId) === String(mcFilter);
    const isSent  = e.messages?.some(m => m.direction === "outbound");
    const folderF = folder === "ALL"  ? true
                  : folder === "SENT" ? isSent
                  : e.category === folder;
    const q       = search.toLowerCase().trim();
    const searchF = !q || [e.subject, e.from, e.snippet, e.companyName, e.body].some(s => s?.toLowerCase().includes(q));
    return mcOk && catOk && mcF && folderF && searchF;
  });

  const folderCounts = {};
  emails.forEach(e => {
    if (myMCs.includes(e.companyId) && e.category && role.cats.includes(e.category))
      folderCounts[e.category] = (folderCounts[e.category] || 0) + 1;
  });
  const sentCount = emails.filter(e => {
    const isAdminRole = ["admin","manager"].includes(currentUser.role);
    const mcOk = isAdminRole || myMCs.length === 0 || myMCs.map(String).includes(String(e.companyId));
    return mcOk && e.messages?.some(m => m.direction === "outbound");
  }).length;

  async function handleDraft() {
    setDraftLoading(true); setDraft("");
    try {
      const result = await callApi("POST", `/conversations/${selectedEmail.id}/draft/`, { instruction });
      setDraft(result.draft || "");
    } catch(e) {
      addNotification("Draft failed: " + e.message, "error");
    }
    setDraftLoading(false);
  }

  async function handleSend() {
    if (!draft.trim()) return;
    setSending(true);
    try {
      let result;
      const bodyHtml = markdownToEmailHtml(draft);
      if (replyFiles.length > 0) {
        const fd = new FormData();
        fd.append("body", draft);
        fd.append("body_html", bodyHtml);
        if (instruction) fd.append("instruction", instruction);
        if (replyCC.trim()) fd.append("cc", replyCC.trim());
        replyFiles.forEach(f => fd.append("attachments", f));
        result = await callApiForm("POST", `/conversations/${selectedEmail.id}/reply/`, fd);
      } else {
        result = await callApi("POST", `/conversations/${selectedEmail.id}/reply/`, {
          body: draft,
          body_html: bodyHtml,
          instruction,
          cc: replyCC.trim() || undefined,
        });
      }

      const newMsg = {
        id:        result.message_id || `m${Date.now()}`,
        direction: "outbound",
        body:      draft,
        body_html: "",
        sender:    currentUser.name,
        time:      new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        pending:   result.status === "pending_approval",
      };

      const newStatus = result.status === "pending_approval" ? "pending_approval" : "replied";

      if (result.status === "pending_approval") {
        addNotification("Submitted for manager approval ⏳", "info");
      } else {
        addNotification("✓ Email sent via Gmail", "success");
      }

      // Optimistically add to UI immediately
      setEmails(p => p.map(e => e.id === selectedEmail.id
        ? { ...e, status: newStatus, messages: [...e.messages, newMsg] } : e));
      setSelectedEmail(p => p ? { ...p, status: newStatus, messages: [...p.messages, newMsg] } : p);
      setReplyOpen(false); setDraft(""); setInstruction(""); setReplyCC(""); setReplyFiles([]);

      // Re-fetch this conversation from DB after a short delay to get the real saved message
      setTimeout(async () => {
        try {
          const r = await fetch(`/api/conversations/`, { credentials: "include" });
          if (!r.ok) return;
          const data = await r.json();
          const convs = Array.isArray(data) ? data : (data.results || []);
          const updated = convs.find(c => c.id === selectedEmail.id);
          if (updated) {
            const mappedMsgs = (updated.messages || []).map(m => ({
              id: m.id, direction: m.direction,
              body: m.body_text || m.snippet || "",
              body_html: m.body_html || "",
              sender: m.direction === "inbound" ? m.sender_email : "You",
              time: m.created_at ? new Date(m.created_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}) : "",
              attachments: m.attachments || [],
            }));
            setSelectedEmail(p => p ? { ...p, status: updated.status, messages: mappedMsgs } : p);
            setEmails(p => p.map(e => e.id === selectedEmail.id ? { ...e, status: updated.status, messages: mappedMsgs } : e));
          }
        } catch(e) { /* silent */ }
      }, 2000);

    } catch(e) {
      addNotification("Send failed: " + e.message, "error");
    }
    setSending(false);
  }

  async function handleComposeSend() {
    if (!composeTo.trim())  { addNotification("Recipient is required", "error"); return; }
    if (!composeSub.trim()) { addNotification("Subject is required", "error"); return; }
    if (!composeDraft.trim()) { addNotification("Body is required", "error"); return; }
    setComposeSending(true);
    try {
      const bodyHtml = markdownToEmailHtml(composeDraft.trim());
      if (composeFiles.length > 0) {
        const fd = new FormData();
        fd.append("to", composeTo.trim());
        if (composeCC.trim()) fd.append("cc", composeCC.trim());
        fd.append("subject", composeSub.trim());
        fd.append("body", composeDraft.trim());
        fd.append("body_html", bodyHtml);
        if (selectedMailboxId) fd.append("mailbox_id", selectedMailboxId);
        composeFiles.forEach(f => fd.append("attachments", f));
        await callApiForm("POST", "/conversations/compose/", fd);
      } else {
        await callApi("POST", "/conversations/compose/", {
          to:         composeTo.trim(),
          cc:         composeCC.trim() || undefined,
          subject:    composeSub.trim(),
          body:       composeDraft.trim(),
          body_html:  bodyHtml,
          mailbox_id: selectedMailboxId || undefined,
        });
      }
      addNotification("✓ Email sent via Gmail", "success");
      setCompose(false);
      setComposeTo(""); setComposeCC(""); setComposeSub(""); setComposeDraft(""); setComposeFiles([]);
      // Refresh email list so the sent email appears in Sent folder
      setTimeout(() => onRefresh(), 2000);
    } catch(e) {
      addNotification("Send failed: " + e.message, "error");
    }
    setComposeSending(false);
  }

  const tabs = ["inbox", ...(role.canApprove || approvalQueue.length > 0 ? ["approvals"] : []), ...(currentUser.role === "manager" || currentUser.role === "admin" ? ["compliance"] : [])];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Sub-tab bar */}
      <div style={{ height: 34, background: T.bg1, borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "flex-end", padding: "0 14px", gap: 0, flexShrink: 0 }}>
        {tabs.map(t => (
          <div key={t} onClick={() => setTab(t)} style={{ padding: "5px 14px", cursor: "pointer", fontSize: 9, letterSpacing: "0.12em", borderBottom: `2px solid ${tab === t ? role.color : "transparent"}`, color: tab === t ? role.color : T.text3, transition: "all 0.15s", display: "flex", alignItems: "center", gap: 5 }}>
            {t.toUpperCase()}
            {t === "approvals" && approvalQueue.length > 0 && <span style={{ background: T.red, color: "#fff", borderRadius: 8, padding: "0 4px", fontSize: 8 }}>{approvalQueue.length}</span>}
            {t === "compliance" && complianceLog.filter(c => !c.is_clean).length > 0 && <span style={{ background: T.red, color: "#fff", borderRadius: 8, padding: "0 4px", fontSize: 8 }}>{complianceLog.filter(c => !c.is_clean).length}</span>}
          </div>
        ))}
        <div style={{ flex: 1 }} />
        {/* MC filter pills */}
        <div style={{ display: "flex", gap: 3, paddingBottom: 4 }}>
          {["ALL", ...myMCs].map(id => {
            const co = companies.find(c => String(c.id) === String(id));
            const label = id === "ALL" ? "All" : co?.mc_number?.split("-")[1] || co?.mc_number;
            const color = co?.color || T.text3;
            return (
              <button key={id} onClick={() => setMcFilter(id)} style={{ background: mcFilter === id ? color + "18" : "transparent", border: `1px solid ${mcFilter === id ? color + "55" : "transparent"}`, color: mcFilter === id ? color : T.text3, padding: "2px 9px", borderRadius: 3, cursor: "pointer", fontFamily: "inherit", fontSize: 9, transition: "all 0.15s" }}>
                {label}
              </button>
            );
          })}
        </div>
        {classifying && <div style={{ fontSize: 9, color: T.accent, padding: "0 10px 4px", display: "flex", alignItems: "center", gap: 4 }} className="pulse">⚡ classifying</div>}
      </div>

      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {tab === "inbox" && (
          <>
            {/* Folder sidebar */}
            <div style={{ width: 176, borderRight: `1px solid ${T.border}`, flexShrink: 0, padding: "8px 0", overflowY: "auto" }}>
              <div style={{ padding: "2px 10px 6px", fontSize: 8, color: T.text3, letterSpacing: "0.15em" }}>FOLDERS</div>
              {[
                { val: "ALL",  icon: "📥", label: "All Mail", count: emails.filter(e => { const isAdminRole = ["admin","manager"].includes(currentUser.role); return isAdminRole || myMCs.map(String).includes(String(e.companyId)); }).length, color: role.color },
                { val: "SENT", icon: "📤", label: "Sent",     count: sentCount, color: T.accent },
                ...role.cats.filter(c => folderCounts[c]).map(c => ({ val: c, ...CAT_META[c], count: folderCounts[c] }))
              ].map(f => (
                <div key={f.val} className="hover-item" onClick={() => setFolder(f.val)} style={{ padding: "5px 10px", display: "flex", alignItems: "center", gap: 6, margin: "1px 5px", borderRadius: 3, background: folder === f.val ? f.color + "15" : "transparent" }}>
                  <span style={{ fontSize: 11 }}>{f.icon}</span>
                  <span style={{ fontSize: 10, color: folder === f.val ? f.color : T.text2, flex: 1 }}>{f.label}</span>
                  <span style={{ fontSize: 9, color: T.text3 }}>{f.count}</span>
                </div>
              ))}
              <div style={{ margin: "10px 0 6px", borderTop: `1px solid ${T.border}` }} />
              <div style={{ padding: "4px 10px 5px", fontSize: 8, color: T.text3, letterSpacing: "0.15em" }}>COMPANIES</div>
              {myMCs.map(id => {
                const co = companies.find(c => String(c.id) === String(id));
                const coColor = getCompanyColor(co);
                const cnt = emails.filter(e => e.companyId === id).length;
                return (
                  <div key={id} className="hover-item" onClick={() => setMcFilter(mcFilter === id ? "ALL" : id)} style={{ padding: "4px 10px", display: "flex", alignItems: "center", gap: 6, margin: "1px 5px", borderRadius: 3, background: mcFilter === id ? coColor + "15" : "transparent" }}>
                    <div style={{ width: 5, height: 5, borderRadius: "50%", background: coColor, flexShrink: 0 }} />
                    <span style={{ fontSize: 9, color: mcFilter === id ? coColor : T.text2, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{co?.name?.split(" ")[0]}</span>
                    <span style={{ fontSize: 8, color: T.text3 }}>{cnt}</span>
                  </div>
                );
              })}
            </div>

            {/* Email list */}
            <div style={{ width: 300, borderRight: `1px solid ${T.border}`, display: "flex", flexDirection: "column", flexShrink: 0, overflow: "hidden" }}>
              <div style={{ padding: "6px 10px", borderBottom: `1px solid ${T.border}`, background: T.bg1 }}>
                <input
                  value={search} onChange={e => setSearch(e.target.value)}
                  placeholder="🔍  Search emails…"
                  style={{ width: "100%", background: T.bg0, border: `1px solid ${T.border}`, color: T.text1,
                    padding: "5px 10px", borderRadius: 5, fontFamily: "inherit", fontSize: 11, outline: "none",
                    boxSizing: "border-box" }}
                />
              </div>
              <div style={{ padding: "5px 11px", borderBottom: `1px solid ${T.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 10, color: T.text2, fontWeight: 600 }}>
                  {emailsLoading ? "Loading…" : (folder === "ALL" ? "All Mail" : CAT_META[folder]?.label)}
                  <span style={{ fontSize: 9, color: T.text3, fontWeight: 400, marginLeft: 6 }}>({visible.length})</span>
                </span>
                <button onClick={openCompose}
                style={{ background: role.color, color:"#fff", border:"none", borderRadius:4,
                  padding:"6px 14px", fontSize:10, fontWeight:600, cursor:"pointer", marginRight:6 }}>
                ✉ NEW EMAIL
              </button>
              <button onClick={onRefresh} disabled={emailsLoading}
                  title="Refresh inbox from database"
                  style={{ background: "none", border: "none", cursor: emailsLoading ? "not-allowed" : "pointer", fontSize: 14, opacity: emailsLoading ? 0.4 : 0.7, padding: "2px 4px", borderRadius: 3 }}>
                  {emailsLoading ? "⟳" : "↻"}
                </button>
              </div>
              <div style={{ flex: 1, overflowY: "auto" }}>
                {!emailsLoading && visible.length === 0 && (
                  <div style={{ padding: "40px 16px", textAlign: "center" }}>
                    <div style={{ fontSize: 24, marginBottom: 8 }}>📭</div>
                    <div style={{ fontSize: 12, color: T.text2, fontWeight: 600, marginBottom: 6 }}>No emails yet</div>
                    <div style={{ fontSize: 11, color: T.text3, lineHeight: 1.6 }}>
                      Go to Admin → Credentials → Mailboxes<br/>
                      and click <strong>Sync Emails Now</strong>
                    </div>
                  </div>
                )}
                {emailsLoading && (
                  <div style={{ padding: "40px 16px", textAlign: "center", color: T.text3, fontSize: 12 }}>
                    Loading emails…
                  </div>
                )}
                {visible.map(email => {
                  const co = companies.find(c => String(c.id) === String(email.companyId));
                  const coColor = getCompanyColor(co);
                  const cat = email.category ? CAT_META[email.category] : null;
                  const sel = selectedEmail?.id === email.id;
                  const lastOut = email.messages?.slice().reverse().find(m => m.direction === "outbound");
                  const isSentFolder = folder === "SENT";
                  const displayFrom = isSentFolder && lastOut
                    ? `To: ${lastOut.sender === "You" ? email.messages?.find(m=>m.direction==="inbound")?.sender || email.from : email.from}`
                    : email.from;
                  return (
                    <div key={email.id} className="hover-row" onClick={() => setSelectedEmail(email)}
                      style={{ padding: "12px 14px", borderBottom: `1px solid ${T.border}`, background: sel ? T.accentDim : "transparent", borderLeft: `3px solid ${sel ? coColor : "transparent"}`, cursor: "pointer" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                          <span style={{ fontSize: 9, fontWeight: 700, color: "#fff",
                            background: coColor, borderRadius: 3, padding: "1px 7px", letterSpacing: "0.04em" }}>
                            {co?.mc_number || "?"}
                          </span>
                          <span style={{ fontSize: 9, color: T.text2, maxWidth: 90, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500 }}>
                            {co?.name?.split(" ")[0] || email.companyName?.split(" ")[0] || ""}
                          </span>
                          {isSentFolder && <span style={{ fontSize: 8, color: T.accent, fontWeight: 600 }}>↗</span>}
                        </div>
                        <span style={{ fontSize: 9, color: T.text3 }}>{email.time}</span>
                      </div>
                      <div style={{ fontSize: 11, color: T.text0, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 2 }}>{email.subject}</div>
                      <div style={{ fontSize: 9, color: T.text2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 4 }}>{displayFrom}</div>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        {cat ? <Badge color={cat.color}>{cat.icon} {email.category}</Badge> : (!isSentFolder && <Badge color={T.text3}>GENERAL</Badge>)}
                        {email.priority && <Badge color={email.priority === "HIGH" ? T.red : email.priority === "MEDIUM" ? T.yellow : T.green}>{email.priority}</Badge>}
                        {email.status === "replied" && <span style={{ fontSize: 8, color: T.green, marginLeft: "auto" }}>✓ SENT</span>}
                        {email.status === "pending_approval" && <span style={{ fontSize: 8, color: T.yellow, marginLeft: "auto" }}>⏳</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Email detail */}
            {selectedEmail ? (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }} className="fade-in">
                <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.border}`, background: "#fff", flexShrink: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, color: T.text0, fontWeight: 500, marginBottom: 3 }}>{selectedEmail.subject}</div>
                      <div style={{ fontSize: 9, color: T.text2 }}>From: {selectedEmail.from} · {selectedEmail.time}</div>
                    </div>
                    <div style={{ display:"flex", gap:6 }}>
                      <Btn onClick={openCompose}>✉ NEW EMAIL</Btn>
                      <Btn variant="primary" onClick={() => setReplyOpen(true)}>↩ REPLY</Btn>
                    </div>
                  </div>
                  {selectedEmail.category && (
                    <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <Badge color={CAT_META[selectedEmail.category]?.color}>{CAT_META[selectedEmail.category]?.icon} {selectedEmail.category}</Badge>
                      {selectedEmail.priority && <Badge color={selectedEmail.priority === "HIGH" ? T.red : selectedEmail.priority === "MEDIUM" ? T.yellow : T.green}>{selectedEmail.priority} PRIORITY</Badge>}
                      {selectedEmail.summary && <span style={{ fontSize: 9, color: T.text2, fontStyle: "italic" }}>{selectedEmail.summary}</span>}
                    </div>
                  )}
                </div>
                <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", background: T.bg0 }}>
                  {(() => {
                    const co = companies.find(c => String(c.id) === String(selectedEmail.companyId));
                    const coColor = getCompanyColor(co);
                    const allMsgs = selectedEmail.messages || [];
                    const attsByMsg = {};
                    (selectedEmail.attachments || []).forEach(a => {
                      if (!attsByMsg[a.msgId]) attsByMsg[a.msgId] = [];
                      attsByMsg[a.msgId].push(a);
                    });
                    return allMsgs.map((m, idx) => {
                      const isOut = m.direction === "outbound";
                      const avatarColor = isOut ? role.color : coColor;
                      const avatarLetter = (isOut ? (currentUser.name || "Y") : (m.sender || "?"))[0].toUpperCase();
                      const msgAtts = attsByMsg[m.id] || [];
                      const isLast = idx === allMsgs.length - 1;
                      return (
                        <div key={m.id} style={{ display:"flex", gap:0, marginBottom: isLast ? 16 : 0 }}>
                          {/* Thread spine */}
                          <div style={{ display:"flex", flexDirection:"column", alignItems:"center", width:44, flexShrink:0 }}>
                            <div style={{ width:32, height:32, borderRadius:"50%", flexShrink:0,
                              background: avatarColor+"22", border:`2px solid ${avatarColor}66`,
                              display:"flex", alignItems:"center", justifyContent:"center",
                              fontSize:12, color:avatarColor, fontWeight:700, marginTop:10 }}>
                              {avatarLetter}
                            </div>
                            {!isLast && <div style={{ width:2, flex:1, minHeight:12, background:T.border, margin:"4px 0" }} />}
                          </div>
                          {/* Message card */}
                          <div style={{ flex:1, minWidth:0, marginBottom: isLast ? 0 : 8 }}>
                            {/* Header */}
                            <div style={{ display:"flex", alignItems:"center", gap:8, padding:"10px 14px 6px",
                              background:"#fff", borderRadius:"8px 8px 0 0",
                              border:`1px solid ${T.border}`, borderBottom:"none" }}>
                              <div style={{ flex:1, minWidth:0 }}>
                                <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
                                  <span style={{ fontSize:12, fontWeight:700, color:T.text0 }}>
                                    {isOut ? (currentUser.name || "You") : m.sender}
                                  </span>
                                  {!isOut && co && (
                                    <span style={{ fontSize:9, fontWeight:700, color:"#fff",
                                      background:coColor, borderRadius:3, padding:"1px 6px" }}>
                                      {co.mc_number}
                                    </span>
                                  )}
                                  {isOut && <span style={{ fontSize:9, color:role.color, fontWeight:600 }}>↑ Sent</span>}
                                  {m.pending && <span style={{ fontSize:9, color:T.yellow, fontWeight:600 }}>⏳ Pending</span>}
                                </div>
                                <div style={{ fontSize:10, color:T.text3, marginTop:1 }}>
                                  {isOut ? `To: ${selectedEmail.from}` : m.sender}
                                  {m.time && <span style={{ marginLeft:8 }}>{m.time}</span>}
                                </div>
                              </div>
                            </div>
                            {/* Body */}
                            <div style={{ padding:"12px 14px", fontSize:13, color:"#1a1a1a", lineHeight:1.7,
                              background:"#fff", border:`1px solid ${T.border}`,
                              borderTop:`1px solid ${T.border}`, borderRadius: msgAtts.length ? "0" : "0 0 8px 8px" }}>
                              {m.body_html
                                ? <div style={{ fontFamily:"Arial,sans-serif", fontSize:13, color:"#1a1a1a", maxWidth:"100%", overflowX:"auto" }}
                                       dangerouslySetInnerHTML={{ __html: cleanHtmlBody(m.body_html) }} />
                                : <div style={{ whiteSpace:"pre-wrap" }}>
                                    {isOut ? (m.body || "") : stripQuotedReply(decodeEntities(m.body || m.snippet || ""))}
                                  </div>
                              }
                            </div>
                            {/* Attachments — inline preview for PDFs and images */}
                            {msgAtts.length > 0 && (
                              <div style={{ padding:"8px 14px 10px", background:"#fff",
                                border:`1px solid ${T.border}`, borderTop:`1px solid ${T.border}2`,
                                borderRadius:"0 0 8px 8px" }}>
                                <div style={{ fontSize:10, color:T.text3, marginBottom:8 }}>
                                  📎 {msgAtts.length} attachment{msgAtts.length>1?"s":""}
                                </div>
                                <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
                                  {msgAtts.map((a, ai) => (
                                    <AttachmentPreview key={ai} att={a} />
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    });
                  })()}
                </div>
                {/* DB strip */}
                <div style={{ borderTop: `1px solid ${T.border}`, padding: "5px 18px", background: T.bg0 }}>
                  <div style={{ fontSize: 8, color: T.text3, fontFamily: "monospace" }}>
                    stored · thread={selectedEmail.gmailThreadId} · mc={selectedEmail.companyId} · cat={selectedEmail.category || "null"} · status={selectedEmail.status}
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 6 }}>
                <div style={{ fontSize: 24, opacity: 0.1 }}>📡</div>
                <div style={{ fontSize: 9, color: T.text3, letterSpacing: "0.15em" }}>SELECT A THREAD</div>
              </div>
            )}
          </>
        )}

        {tab === "approvals" && (
          <ApprovalsTab approvalQueue={approvalQueue} setApprovalQueue={setApprovalQueue} setEmails={setEmails} addNotification={addNotification} setComplianceLog={setComplianceLog} />
        )}

        {tab === "compliance" && (
          <ComplianceTab log={complianceLog} />
        )}
      </div>

      {/* Reply Modal */}
      {/* ── Compose New Email Modal ── */}
      {composeOpen && (
        <Modal onClose={() => { setCompose(false); setComposeTo(""); setComposeCC(""); setComposeSub(""); setComposeDraft(""); setComposeFiles([]); }} width={580}>
          <div style={{ padding:"16px 20px", borderBottom:`1px solid ${T.border}`, display:"flex", justifyContent:"space-between", alignItems:"center" }}>
            <div style={{ fontSize:14, fontWeight:700, color:T.text0 }}>✉ New Email</div>
            <Btn size="xs" onClick={() => { setCompose(false); setComposeTo(""); setComposeCC(""); setComposeSub(""); setComposeDraft(""); setComposeFiles([]); }}>✕</Btn>
          </div>
          <div style={{ padding:"18px 20px", flex:1, overflowY:"auto", display:"flex", flexDirection:"column", gap:12 }}>
            {/* From mailbox selector */}
            <div>
              <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>
                FROM <span style={{ color:T.red }}>*</span>
                {!isAdminRole && availableMailboxes.length === 1 && (
                  <span style={{ fontSize:9, fontWeight:400, color:T.text3, marginLeft:6 }}>
                    (your assigned mailbox)
                  </span>
                )}
              </div>
              {availableMailboxes.length === 0 ? (
                <div style={{ background:T.redDim, border:`1px solid ${T.red}44`, borderRadius:4,
                  padding:"8px 12px", fontSize:11, color:T.red }}>
                  {isAdminRole
                    ? "No connected mailboxes — go to Admin → Credentials → Mailboxes."
                    : "You're not assigned to any company with a connected mailbox. Ask your admin to assign you."}
                </div>
              ) : isAdminRole ? (
                // Admins/managers: dropdown to choose any company's mailbox
                <select value={selectedMailboxId} onChange={e => setSelectedMailboxId(e.target.value)}
                  style={{ width:"100%", background:T.bg1, border:`1px solid ${T.border}`, color:T.text0,
                    padding:"8px 10px", borderRadius:4, fontFamily:"inherit", fontSize:11 }}>
                  {availableMailboxes.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.company_name} ({m.company_mc}) — {m.email_address}
                    </option>
                  ))}
                </select>
              ) : availableMailboxes.length === 1 ? (
                // Non-admin with one assigned mailbox: locked default
                <div style={{ background:T.bg0, border:`1px solid ${T.border}`, borderRadius:4,
                  padding:"8px 12px", fontSize:11, color:T.text1 }}>
                  {availableMailboxes[0].company_name} ({availableMailboxes[0].company_mc}) — {availableMailboxes[0].email_address}
                </div>
              ) : (
                // Non-admin assigned to multiple companies: dropdown of just those
                <select value={selectedMailboxId} onChange={e => setSelectedMailboxId(e.target.value)}
                  style={{ width:"100%", background:T.bg1, border:`1px solid ${T.border}`, color:T.text0,
                    padding:"8px 10px", borderRadius:4, fontFamily:"inherit", fontSize:11 }}>
                  {availableMailboxes.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.company_name} ({m.company_mc}) — {m.email_address}
                    </option>
                  ))}
                </select>
              )}
            </div>
            {/* To */}
            <div>
              <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>TO <span style={{ color:T.red }}>*</span></div>
              <Input value={composeTo} onChange={e => setComposeTo(e.target.value)}
                placeholder="recipient@company.com" />
            </div>
            {/* CC */}
            <div>
              <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>CC <span style={{ fontWeight:400, color:T.text3 }}>(optional)</span></div>
              <Input value={composeCC} onChange={e => setComposeCC(e.target.value)}
                placeholder="cc1@example.com, cc2@example.com" />
            </div>
            {/* Subject */}
            <div>
              <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>SUBJECT <span style={{ color:T.red }}>*</span></div>
              <Input value={composeSub} onChange={e => setComposeSub(e.target.value)}
                placeholder="Rate confirmation - Load #12345" />
            </div>
            {/* Body */}
            <div>
              <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>MESSAGE <span style={{ color:T.red }}>*</span></div>
              <RichTextArea value={composeDraft} onChange={e => setComposeDraft(e.target.value)} rows={10}
                placeholder="Write your email here…"
                signature={`\n\nBest regards,\n${currentUser.name || ""}`} />
            </div>
            {/* Attachments */}
            <div>
              <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:6 }}>
                <div style={{ fontSize:10, fontWeight:600, color:T.text2 }}>ATTACHMENTS <span style={{ fontWeight:400, color:T.text3 }}>(optional)</span></div>
                <label style={{ fontSize:10, color:T.accent, cursor:"pointer", fontWeight:600 }}>
                  + Add files
                  <input type="file" multiple style={{ display:"none" }}
                    onChange={e => { setComposeFiles(p => [...p, ...Array.from(e.target.files)]); e.target.value = ""; }} />
                </label>
              </div>
              {composeFiles.length > 0 && (
                <div style={{ display:"flex", gap:5, flexWrap:"wrap" }}>
                  {composeFiles.map((f, i) => (
                    <div key={i} style={{ display:"flex", alignItems:"center", gap:5, background:T.bg0,
                      border:`1px solid ${T.border}`, borderRadius:4, padding:"4px 8px", fontSize:10, color:T.text1 }}>
                      📎 {f.name}
                      <span style={{ fontSize:9, color:T.text3 }}>{f.size < 1048576 ? `${(f.size/1024).toFixed(0)}KB` : `${(f.size/1048576).toFixed(1)}MB`}</span>
                      <span onClick={() => setComposeFiles(p => p.filter((_, j) => j !== i))}
                        style={{ cursor:"pointer", color:T.red, fontSize:12, marginLeft:2 }}>×</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div style={{ background:T.bg0, border:`1px solid ${T.border}`, borderRadius:4,
              padding:"6px 12px", fontSize:9, color:T.text3 }}>
              🔍 Outbound emails are automatically audited for compliance.
            </div>
          </div>
          <div style={{ padding:"12px 20px", borderTop:`1px solid ${T.border}`, display:"flex", gap:8, alignItems:"center" }}>
            <Btn variant="primary" onClick={handleComposeSend} disabled={composeSending || !composeTo.trim() || !composeSub.trim() || !composeDraft.trim()}>
              {composeSending ? "Sending…" : "↗ Send Email"}
            </Btn>
            <Btn onClick={() => { setCompose(false); setComposeTo(""); setComposeCC(""); setComposeSub(""); setComposeDraft(""); setComposeFiles([]); }}>Cancel</Btn>
            {(!composeTo.trim() || !composeSub.trim() || !composeDraft.trim()) && (
              <span style={{ fontSize:9, color:T.text3, marginLeft:4 }}>Fill in To, Subject and Message to send</span>
            )}
          </div>
        </Modal>
      )}

      {replyOpen && selectedEmail && (
        <Modal onClose={() => { setReplyOpen(false); setDraft(""); setInstruction(""); setReplyCC(""); }}>
          <div style={{ padding: "14px 18px", borderBottom: `1px solid ${T.border}`, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: T.text0 }}>↩ Reply</div>
              <div style={{ fontSize: 11, color: T.text2, marginTop: 3 }}>To: <span style={{ color: T.text0 }}>{selectedEmail.from}</span></div>
              <div style={{ fontSize: 10, color: T.text3, marginTop: 2 }}>
                From: <span style={{ color: T.text1 }}>{selectedEmail.mailboxEmail}</span>
                {selectedEmail.companyName && <span style={{ marginLeft: 6, fontWeight: 600,
                  color: companies.find(c => String(c.id) === String(selectedEmail.companyId))?.color || T.accent }}>
                  · {selectedEmail.companyName}
                </span>}
              </div>
            </div>
            <Btn size="xs" onClick={() => { setReplyOpen(false); setDraft(""); setInstruction(""); setReplyCC(""); }}>✕</Btn>
          </div>
          <div style={{ padding: "14px 18px", flex: 1, overflowY: "auto" }}>
            {/* CC field */}
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: T.text2, marginBottom: 4 }}>CC <span style={{ fontWeight: 400, color: T.text3 }}>(optional — comma-separated)</span></div>
              <Input value={replyCC} onChange={e => setReplyCC(e.target.value)}
                placeholder="cc@example.com, another@example.com" />
            </div>
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: T.text2, marginBottom: 4 }}>AI INSTRUCTION <span style={{ fontWeight: 400, color: T.text3 }}>(optional)</span></div>
              <Input value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="e.g. counter at $2,400 · request BOL · accept the load" />
            </div>
            <div style={{ marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <div style={{ fontSize: 10, color: T.text2, letterSpacing: "0.03em" }}>REPLY BODY</div>
                <Btn size="xs" variant="primary" onClick={handleDraft} disabled={draftLoading}>{draftLoading ? "⚡ drafting…" : "⚡ AI DRAFT"}</Btn>
              </div>
              <RichTextArea value={draft} onChange={e => setDraft(e.target.value)} rows={9}
                placeholder="Write or AI draft…"
                signature={`\n\nBest regards,\n${currentUser.name || ""}`} />
            </div>
            {/* Attachments */}
            <div style={{ marginBottom: 12 }}>
              <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:6 }}>
                <div style={{ fontSize:10, fontWeight:600, color:T.text2 }}>ATTACHMENTS <span style={{ fontWeight:400, color:T.text3 }}>(optional)</span></div>
                <label style={{ fontSize:10, color:T.accent, cursor:"pointer", fontWeight:600 }}>
                  + Add files
                  <input type="file" multiple style={{ display:"none" }}
                    onChange={e => { setReplyFiles(p => [...p, ...Array.from(e.target.files)]); e.target.value = ""; }} />
                </label>
              </div>
              {replyFiles.length > 0 && (
                <div style={{ display:"flex", gap:5, flexWrap:"wrap" }}>
                  {replyFiles.map((f, i) => (
                    <div key={i} style={{ display:"flex", alignItems:"center", gap:5, background:T.bg0,
                      border:`1px solid ${T.border}`, borderRadius:4, padding:"4px 8px", fontSize:10, color:T.text1 }}>
                      📎 {f.name}
                      <span style={{ fontSize:9, color:T.text3 }}>{f.size < 1048576 ? `${(f.size/1024).toFixed(0)}KB` : `${(f.size/1048576).toFixed(1)}MB`}</span>
                      <span onClick={() => setReplyFiles(p => p.filter((_, j) => j !== i))}
                        style={{ cursor:"pointer", color:T.red, fontSize:12, marginLeft:2 }}>×</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {["SAFETY","AUDIT","CLAIMS"].includes(selectedEmail.category) && !role.canApprove && (
              <div style={{ background: T.yellowDim, border: `1px solid ${T.yellow}33`, borderRadius: 3, padding: "7px 11px", fontSize: 9, color: T.yellow, marginBottom: 10 }}>
                ⚠ {selectedEmail.category} emails require manager approval before sending.
              </div>
            )}
            <div style={{ background: T.bg0, border: `1px solid ${T.border}`, borderRadius: 3, padding: "5px 10px", fontSize: 8, color: T.text3 }}>
              🔍 All outbound emails are automatically audited by AI for compliance.
            </div>
          </div>
          <div style={{ padding: "10px 16px", borderTop: `1px solid ${T.border}`, display: "flex", gap: 7 }}>
            <Btn variant="primary" onClick={handleSend} disabled={!draft.trim() || sending}>
              {sending ? "SENDING…" : ["SAFETY","AUDIT","CLAIMS"].includes(selectedEmail.category) && !role.canApprove ? "↗ SUBMIT FOR APPROVAL" : "↗ SEND VIA GMAIL"}
            </Btn>
            <Btn onClick={() => { setReplyOpen(false); setDraft(""); setInstruction(""); setReplyCC(""); setReplyFiles([]); }}>CANCEL</Btn>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ApprovalsTab({ approvalQueue, setApprovalQueue, setEmails, addNotification }) {
  return (
    <div style={{ flex: 1, padding: 20, overflowY: "auto" }}>
      <SectionHeader title="Pending Approvals" subtitle={`${approvalQueue.length} items awaiting review`} />
      {approvalQueue.length === 0 && <div style={{ fontSize: 10, color: T.text3 }}>Queue is empty.</div>}
      {approvalQueue.map(item => (
        <Card key={item.id} style={{ padding: 16, marginBottom: 12 }} className="fade-in">
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 11, color: T.text0, marginBottom: 2 }}>{item.email.subject}</div>
              <div style={{ fontSize: 9, color: T.text2 }}>Reply to {item.email.from} · by {item.msg.sender} · {item.msg.time}</div>
            </div>
            <Badge color={T.yellow}>NEEDS APPROVAL</Badge>
          </div>
          <div style={{ background: T.bg0, border: `1px solid ${T.border}`, borderRadius: 3, padding: 10, marginBottom: 12 }}>
            <div style={{ fontSize: 8, color: T.text3, marginBottom: 5, letterSpacing: "0.1em" }}>DRAFT</div>
            <div style={{ fontSize: 10, color: T.text1, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{item.msg.body}</div>
          </div>
          <div style={{ display: "flex", gap: 7 }}>
            <Btn variant="success" onClick={() => {
              setApprovalQueue(p => p.filter(a => a.id !== item.id));
              setEmails(p => p.map(e => e.id === item.email.id ? { ...e, status: "replied", messages: e.messages.map(m => m.pending ? { ...m, pending: false } : m) } : e));
              addNotification("Reply approved and sent", "success");
            }}>✓ APPROVE & SEND</Btn>
            <Btn variant="danger" onClick={() => {
              setApprovalQueue(p => p.filter(a => a.id !== item.id));
              setEmails(p => p.map(e => e.id === item.email.id ? { ...e, status: "open", messages: e.messages.filter(m => !m.pending) } : e));
              addNotification("Reply rejected", "error");
            }}>✗ REJECT</Btn>
          </div>
        </Card>
      ))}
    </div>
  );
}

function ComplianceTab({ log }) {
  const riskColor = r => ({ HIGH: T.red, MEDIUM: T.yellow, LOW: T.green }[r] || T.text3);
  return (
    <div style={{ flex: 1, padding: 20, overflowY: "auto" }}>
      <SectionHeader title="AI Compliance Audit" subtitle="Every outbound email is automatically scanned for policy violations" />
      {log.length === 0 && <div style={{ fontSize: 10, color: T.text3 }}>No outbound emails audited yet.</div>}
      {log.map((e, i) => (
        <Card key={i} style={{ padding: 14, marginBottom: 10, borderColor: e.is_clean ? T.border : riskColor(e.risk_level) + "44" }} className="fade-in">
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 11, color: T.text0, marginBottom: 2 }}>{e.subject}</div>
              <div style={{ fontSize: 9, color: T.text2 }}>{e.company} · {e.sender} · {e.time}</div>
            </div>
            <div style={{ display: "flex", gap: 5 }}>
              <Badge color={riskColor(e.risk_level)}>{e.risk_level} RISK</Badge>
              {e.is_clean ? <Badge color={T.green}>✓ CLEAN</Badge> : <Badge color={T.red}>⚠ FLAGGED</Badge>}
            </div>
          </div>
          {e.flags?.length > 0 && <div style={{ marginBottom: 6 }}>{e.flags.map((f, i) => <div key={i} style={{ fontSize: 9, color: T.yellow }}>• {f}</div>)}</div>}
          <div style={{ fontSize: 9, color: T.text2 }}>Recommendation: {e.recommendation}</div>
          <details style={{ marginTop: 8 }}>
            <summary style={{ fontSize: 8, color: T.text3, cursor: "pointer" }}>VIEW SENT BODY</summary>
            <div style={{ marginTop: 6, background: T.bg0, borderRadius: 3, padding: 8, fontSize: 9, color: T.text2, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{e.draft}</div>
          </details>
        </Card>
      ))}
    </div>
  );
}

// ─── ADMIN UI ─────────────────────────────────────────────────────────────────
function AdminUI({ companies, setCompanies, mailboxes, setMailboxes, users, setUsers, complianceLog, addNotification }) {
  const [tab, setTab] = useState("dashboard");

  const tabs = [
    { id: "dashboard", icon: "◈", label: "Dashboard" },
    { id: "companies", icon: "🏢", label: "Companies" },
    { id: "gmail",     icon: "📧", label: "Gmail" },
    { id: "slack",     icon: "💬", label: "Slack" },
    { id: "users",     icon: "👥", label: "Users" },
    { id: "settings",  icon: "🔑", label: "Credentials" },
  ];

  return (
    <div style={{ display: "flex", height: "100%" }}>
      {/* Admin sidebar */}
      <div style={{ width: 200, background: T.bg1, borderRight: `1px solid ${T.border}`, display: "flex", flexDirection: "column", padding: "12px 0", flexShrink: 0 }}>
        <div style={{ padding: "4px 14px 12px", fontSize: 8, color: T.text3, letterSpacing: "0.2em" }}>ADMINISTRATION</div>
        {tabs.map(t => (
          <div key={t.id} className="hover-item" onClick={() => setTab(t.id)}
            style={{ padding: "8px 14px", display: "flex", alignItems: "center", gap: 9, cursor: "pointer", background: tab === t.id ? T.accent + "18" : "transparent", borderLeft: `3px solid ${tab === t.id ? T.accent : "transparent"}` }}>
            <span style={{ fontSize: 13 }}>{t.icon}</span>
            <span style={{ fontSize: 10, color: tab === t.id ? T.accent : T.text2 }}>{t.label}</span>
          </div>
        ))}
        <div style={{ flex: 1 }} />
        <div style={{ padding: "10px 14px", borderTop: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 8, color: T.text3, marginBottom: 6, letterSpacing: "0.1em" }}>SYSTEM STATUS</div>
          {[
            { label: "Gmail Watches", ok: mailboxes.filter(m => m.watchStatus === "active").length, total: mailboxes.length },
          ].map(s => (
            <div key={s.label} style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
              <span style={{ fontSize: 9, color: T.text2 }}>{s.label}</span>
              <span style={{ fontSize: 9, color: s.ok === s.total ? T.green : s.ok > 0 ? T.yellow : T.red }}>{s.ok}/{s.total}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Admin content */}
      <div style={{ flex: 1, overflowY: "auto", padding: 24 }} className="fade-in">
        {tab === "dashboard" && <AdminDashboard companies={companies} mailboxes={mailboxes} users={users} complianceLog={complianceLog} />}
        {tab === "companies" && <AdminCompanies companies={companies} setCompanies={setCompanies} addNotification={addNotification} />}
        {tab === "gmail"     && <AdminGmail mailboxes={mailboxes} setMailboxes={setMailboxes} companies={companies} addNotification={addNotification} />}
        {tab === "slack"     && <SlackTab toast={addNotification} />}
        {tab === "users"     && <AdminUsers users={users} setUsers={setUsers} companies={companies} addNotification={addNotification} />}
        {tab === "settings"  && <AdminSettings companies={companies} />}
      </div>
    </div>
  );
}

// ── Admin Dashboard ───────────────────────────────────────────────────────────
function AdminDashboard({ companies, mailboxes, users, complianceLog }) {
  const watchIssues = mailboxes.filter(m => m.watchStatus !== "active");
  const stats = [
    { label: "Companies", value: companies.filter(c => c.status === "active").length, sub: `${companies.length} total`, color: T.accent },
    { label: "Mailboxes", value: mailboxes.filter(m => m.watchStatus === "active").length, sub: `${watchIssues.length} need attention`, color: watchIssues.length ? T.yellow : T.green },
    { label: "Active Users", value: users.filter(u => u.active).length, sub: `${users.length} registered`, color: T.accent },
    { label: "Compliance Flags", value: complianceLog.filter(c => !c.is_clean).length, sub: "last 24h", color: complianceLog.filter(c => !c.is_clean).length ? T.red : T.green },
  ];

  return (
    <div>
      <SectionHeader title="System Dashboard" subtitle="Dispatch OS health overview" />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 24 }}>
        {stats.map(s => (
          <Card key={s.label} style={{ padding: 16 }}>
            <div style={{ fontSize: 24, fontWeight: 600, color: s.color, marginBottom: 4 }}>{s.value}</div>
            <div style={{ fontSize: 10, color: T.text0, marginBottom: 2 }}>{s.label}</div>
            <div style={{ fontSize: 9, color: T.text3 }}>{s.sub}</div>
          </Card>
        ))}
      </div>

      <SectionHeader title="Gmail Watch Status" subtitle="All registered mailbox watches" />
      <Card>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${T.border}` }}>
              {["Mailbox","Company","Watch Status","History ID","Expires"].map(h => (
                <th key={h} style={{ padding: "8px 12px", fontSize: 9, color: T.text3, textAlign: "left", letterSpacing: "0.1em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {mailboxes.map(mb => {
              const co = companies.find(c => String(c.id) === String(mb.companyId));
              return (
                <tr key={mb.id} style={{ borderBottom: `1px solid ${T.border}` }}>
                  <td style={{ padding: "9px 12px", fontSize: 10, color: T.text1 }}>{mb.email}</td>
                  <td style={{ padding: "9px 12px" }}><Badge color={co?.color || T.text3}>{co?.mc_number}</Badge></td>
                  <td style={{ padding: "9px 12px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                      <StatusDot status={mb.watchStatus} />
                      <span style={{ fontSize: 9, color: mb.watchStatus === "active" ? T.green : mb.watchStatus === "expired" ? T.yellow : T.red, letterSpacing: "0.08em" }}>{(mb.watchStatus || "unknown").toUpperCase()}</span>
                    </div>
                  </td>
                  <td style={{ padding: "9px 12px", fontSize: 9, color: T.text2, fontFamily: "monospace" }}>{mb.lastHistoryId || "—"}</td>
                  <td style={{ padding: "9px 12px", fontSize: 9, color: T.text2 }}>{mb.watchExpiry || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ── Admin Companies ───────────────────────────────────────────────────────────
function AdminCompanies({ companies, setCompanies, addNotification }) {
  const [editing, setEditing]   = useState(null);
  const [form, setForm]         = useState({});
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState("");
  const [slackChannels, setSlackChannels] = useState([]);

  // Reload companies from real DB
  async function reload() {
    try {
      const d = await callApi("GET", "/companies/");
      const list = Array.isArray(d) ? d : (d?.results || []);
      setCompanies(list);
      if (list.length === 0) addNotification("DB has 0 companies — add one using the form", "info");
    } catch(e) { addNotification("Load failed: " + e.message, "error"); }
  }

  // Load Slack channels once for the dropdown
  useEffect(() => {
    callApi("GET", "/settings/slack/channels/list/")
      .then(d => setSlackChannels(d.channels || []))
      .catch(() => setSlackChannels([]));
  }, []);

  function openEdit(co) {
    setError("");
    setEditing(co?.id || "new");
    setForm(co
      ? { name: co.name, mc_number: co.mc_number, dot_number: co.dot_number || "", status: co.status || "active", rate_floor: co.rate_floor || "", slack_channel: co.slack_channel || "", slack_channel_id: co.slack_channel_id || "", slack_channel_loads_name: co.slack_channel_loads_name || "", slack_channel_paperwork_name: co.slack_channel_paperwork_name || "", ai_auto_reply_enabled: co.ai_auto_reply_enabled || false, slack_alerts_enabled: co.slack_alerts_enabled || false, color: co.color || "#38bdf8" }
      : { name: "", mc_number: "", dot_number: "", status: "active", rate_floor: "", slack_channel: "", slack_channel_id: "", slack_channel_loads_name: "", slack_channel_paperwork_name: "", ai_auto_reply_enabled: false, slack_alerts_enabled: false, color: "#38bdf8" }
    );
  }

  async function save() {
    if (!form.name || !form.mc_number) { setError("Company name and MC number are required."); return; }
    setSaving(true); setError("");
    try {
      // Look up channel IDs from the selected channel names
      const loadsCh = slackChannels.find(c => c.name === form.slack_channel_loads_name);
      const paperCh = slackChannels.find(c => c.name === form.slack_channel_paperwork_name);
      const payload = {
        ...form,
        slack_channel_loads_id: loadsCh?.id || "",
        slack_channel_paperwork_id: paperCh?.id || "",
      };
      if (editing === "new") {
        await callApi("POST", "/companies/", payload);
        addNotification("Company created ✓", "success");
      } else {
        await callApi("PATCH", `/companies/${editing}/`, payload);
        addNotification("Company updated ✓", "success");
      }
      await reload();
      setEditing(null);
    } catch(e) {
      const msg = e.message || "Save failed — check docker compose logs api";
      setError(msg);
      addNotification("Error: " + msg, "error");
    }
    setSaving(false);
  }

  async function deleteCompany(id) {
    if (!confirm("Delete this company? This cannot be undone.")) return;
    try {
      await callApi("DELETE", `/companies/${id}/`);
      addNotification("Company deleted", "info");
      await reload();
    } catch(e) { addNotification("Delete failed: " + e.message, "error"); }
  }

  return (
    <div>
      <SectionHeader
        title="Companies / Motor Carriers"
        subtitle={`${companies.length} MC${companies.length !== 1 ? "s" : ""} in database`}
        action={
          <div style={{ display: "flex", gap: 8 }}>
            <Btn onClick={reload}>↻ Refresh</Btn>
            <Btn variant="primary" onClick={() => openEdit(null)}>+ ADD COMPANY</Btn>
          </div>
        }
      />

      {companies.length === 0 && (
        <div style={{ background: T.yellowDim, border: `1px solid ${T.yellow}44`, borderRadius: 8, padding: "16px 20px", marginBottom: 16, fontSize: 12, color: T.yellow, lineHeight: 1.7 }}>
          No companies yet. Click <strong>+ ADD COMPANY</strong> to add your first MC.
        </div>
      )}

      <Card>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: `1px solid ${T.border}`, background: T.bg2 }}>
            {["MC Number","Company Name","DOT","Slack Channels","Alerts","AI","Status",""].map(h => (
              <th key={h} style={{ padding: "10px 12px", fontSize: 10, fontWeight: 600, color: T.text3, textAlign: "left" }}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {companies.map(co => {
              const hasSlack = co.slack_channel_loads_id && co.slack_channel_paperwork_id;
              return (
              <tr key={co.id} className="hover-row" style={{ borderBottom: `1px solid ${T.border}` }}>
                <td style={{ padding: "10px 12px" }}><Badge color={co.color || "#38bdf8"}>{co.mc_number}</Badge></td>
                <td style={{ padding: "10px 12px", fontSize: 11, color: T.text0, fontWeight: 500 }}>{co.name}</td>
                <td style={{ padding: "10px 12px", fontSize: 10, color: T.text2 }}>{co.dot_number || "—"}</td>
                <td style={{ padding: "10px 12px" }}>
                  {hasSlack ? (
                    <div style={{ display:"flex", flexDirection:"column", gap:2 }}>
                      <span style={{ fontSize:9, color:T.green, fontWeight:600 }}>✓ {co.slack_channel_loads_name || "load-ops"}</span>
                      <span style={{ fontSize:9, color:T.green, fontWeight:600 }}>✓ {co.slack_channel_paperwork_name || "paperwork-ops"}</span>
                    </div>
                  ) : (
                    <Btn size="xs" variant="primary" onClick={async () => {
                      try {
                        const r = await callApi("POST", `/companies/${co.id}/create-slack-channels/`);
                        addNotification(`Slack channels created: #${r.load_ops}, #${r.paperwork_ops}`, "success");
                        reload();
                      } catch(e) { addNotification("Failed: " + e.message, "error"); }
                    }}>+ CREATE CHANNELS</Btn>
                  )}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <Btn size="xs" variant={co.slack_alerts_enabled ? "success" : "ghost"}
                    title={co.slack_alerts_enabled ? "Click to disable Slack alerts" : "Click to enable Slack alerts"}
                    onClick={async () => {
                      try {
                        await callApi("PATCH", `/companies/${co.id}/`, { slack_alerts_enabled: !co.slack_alerts_enabled });
                        addNotification(`Slack alerts ${!co.slack_alerts_enabled ? "enabled" : "disabled"} for ${co.name}`, "success");
                        reload();
                      } catch(e) { addNotification("Toggle failed: " + e.message, "error"); }
                    }}>
                    {co.slack_alerts_enabled ? "💬 ON" : "OFF"}
                  </Btn>
                </td>
                <td style={{ padding: "10px 12px" }}>
                  {co.ai_auto_reply_enabled
                    ? <span style={{ fontSize:9, color:T.green, fontWeight:600 }} title="AI agent enabled">🤖 ON</span>
                    : <span style={{ fontSize:9, color:T.text3 }} title="AI agent disabled">OFF</span>}
                </td>
                <td style={{ padding: "10px 12px" }}><StatusDot status={co.status === "active" ? "active" : "error"} /></td>
                <td style={{ padding: "10px 12px" }}>
                  <div style={{ display: "flex", gap: 5 }}>
                    <Btn size="xs" onClick={() => openEdit(co)}>EDIT</Btn>
                    <Btn size="xs" variant="danger" onClick={() => deleteCompany(co.id)}>DEL</Btn>
                  </div>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </Card>

      {editing && (
        <Modal onClose={() => setEditing(null)} width={520}>
          <div style={{ padding: "14px 18px", borderBottom: `1px solid ${T.border}`, fontSize: 13, fontWeight: 600, color: T.text0 }}>
            {editing === "new" ? "Add Company" : "Edit Company"}
          </div>
          <div style={{ padding: 18, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            {[
              ["Company Name *", "name", "text", "RW Freight Line LLC"],
              ["MC Number *",    "mc_number", "text", "MC-281940"],
              ["DOT Number",     "dot_number", "text", "DOT-1829301"],
              ["Rate Floor ($)", "rate_floor", "number", "1800"],
            ].map(([label, key, type, placeholder]) => (
              <div key={key}>
                <div style={{ fontSize: 10, fontWeight: 600, color: T.text2, marginBottom: 5 }}>{label}</div>
                <Input type={type} value={form[key] || ""} placeholder={placeholder}
                  onChange={e => setForm(p => ({ ...p, [key]: e.target.value }))} />
              </div>
            ))}
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: T.text2, marginBottom: 5 }}>COLOR</div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input type="color" value={form.color || "#38bdf8"} onChange={e => setForm(p => ({ ...p, color: e.target.value }))}
                  style={{ width: 40, height: 34, borderRadius: 4, border: `1px solid ${T.border}`, cursor: "pointer", padding: 2 }} />
                <Input value={form.color || ""} onChange={e => setForm(p => ({ ...p, color: e.target.value }))} style={{ flex: 1 }} />
              </div>
            </div>
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: T.text2, marginBottom: 5 }}>STATUS</div>
              <Select value={form.status || "active"} onChange={e => setForm(p => ({ ...p, status: e.target.value }))}
                options={[{ value: "active", label: "Active" }, { value: "inactive", label: "Inactive" }]} />
            </div>
            {/* Slack Channels — pick from real Slack workspace */}
            <div style={{ gridColumn:"1/-1", background:T.bg0, border:`1px solid ${T.border}`, borderRadius:6, padding:"14px 16px" }}>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:10 }}>
                <div style={{ fontSize:9, fontWeight:700, color:T.text3, letterSpacing:"0.1em" }}>SLACK ALERT CHANNELS</div>
                <span style={{ fontSize:9, color:T.text3 }}>{slackChannels.length} channels found</span>
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10 }}>
                <div>
                  <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:4, display:"flex", alignItems:"center", gap:4 }}>
                    <span>🚛</span> Load Ops Channel
                    <span style={{ fontSize:8, color:T.text3, fontWeight:400 }}>Loads, Drivers</span>
                  </div>
                  <Select value={form.slack_channel_loads_name || ""}
                    onChange={e => setForm(p => ({ ...p, slack_channel_loads_name: e.target.value }))}
                    options={[{ value:"", label:"— Select a channel —" }, ...slackChannels.map(c => ({ value: c.name, label: `#${c.name}${c.is_private ? " 🔒" : ""}` }))]} />
                </div>
                <div>
                  <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:4, display:"flex", alignItems:"center", gap:4 }}>
                    <span>📄</span> Paperwork Ops Channel
                    <span style={{ fontSize:8, color:T.text3, fontWeight:400 }}>Billing, Safety, Claims</span>
                  </div>
                  <Select value={form.slack_channel_paperwork_name || ""}
                    onChange={e => setForm(p => ({ ...p, slack_channel_paperwork_name: e.target.value }))}
                    options={[{ value:"", label:"— Select a channel —" }, ...slackChannels.map(c => ({ value: c.name, label: `#${c.name}${c.is_private ? " 🔒" : ""}` }))]} />
                </div>
              </div>
              {slackChannels.length === 0 && (
                <div style={{ fontSize:9, color:T.yellow, marginTop:8 }}>
                  ⚠ No Slack channels loaded. Configure the bot token in Admin → Slack and make sure the bot is a member of the channels.
                </div>
              )}
            </div>
            {/* Slack alerts toggle */}
            <div style={{ gridColumn:"1/-1", background:T.bg0, border:`1px solid ${T.border}`, borderRadius:6, padding:"14px 16px" }}>
              <div style={{ fontSize:9, fontWeight:700, color:T.text3, letterSpacing:"0.1em", marginBottom:10 }}>SLACK ALERTS</div>
              <label style={{ display:"flex", alignItems:"flex-start", gap:10, cursor:"pointer" }}>
                <input type="checkbox" checked={!!form.slack_alerts_enabled}
                  onChange={e => setForm(p => ({ ...p, slack_alerts_enabled: e.target.checked }))}
                  style={{ marginTop:3, width:16, height:16, cursor:"pointer" }} />
                <div>
                  <div style={{ fontSize:11, color:T.text0, fontWeight:600 }}>
                    💬 Enable Slack alerts for this company
                  </div>
                  <div style={{ fontSize:10, color:T.text2, marginTop:3, lineHeight:1.5 }}>
                    When ON, urgent emails and the hourly task digest are posted to this company's
                    Load Ops / Paperwork Ops Slack channels. When OFF, Dispatch OS silently skips
                    all Slack posts for this MC.
                  </div>
                </div>
              </label>
            </div>
            {/* AI Agent toggle */}
            <div style={{ gridColumn:"1/-1", background:T.bg0, border:`1px solid ${T.border}`, borderRadius:6, padding:"14px 16px" }}>
              <div style={{ fontSize:9, fontWeight:700, color:T.text3, letterSpacing:"0.1em", marginBottom:10 }}>AI AGENT</div>
              <label style={{ display:"flex", alignItems:"flex-start", gap:10, cursor:"pointer" }}>
                <input type="checkbox" checked={!!form.ai_auto_reply_enabled}
                  onChange={e => setForm(p => ({ ...p, ai_auto_reply_enabled: e.target.checked }))}
                  style={{ marginTop:3, width:16, height:16, cursor:"pointer" }} />
                <div>
                  <div style={{ fontSize:11, color:T.text0, fontWeight:600 }}>
                    🤖 Enable AI auto-reply
                  </div>
                  <div style={{ fontSize:10, color:T.text2, marginTop:3, lineHeight:1.5 }}>
                    The agent will read unanswered emails and auto-reply to <strong>routine items only</strong>:
                    status updates, acknowledgments, courtesy messages.
                    <br/>
                    It will <strong>never</strong> touch rate offers, disputes, billing, claims, safety, or contracts —
                    those always go to a human.
                  </div>
                  <div style={{ fontSize:9, color:T.text3, marginTop:4, fontStyle:"italic" }}>
                    Every AI reply is logged and posted to the Slack channel so you can audit what it did.
                  </div>
                </div>
              </label>
            </div>
          </div>
          {error && (
            <div style={{ margin: "0 18px 12px", background: T.redDim, border: `1px solid ${T.red}44`, borderRadius: 6, padding: "10px 14px", fontSize: 11, color: T.red }}>
              {error}
            </div>
          )}
          <div style={{ padding: "12px 18px", borderTop: `1px solid ${T.border}`, display: "flex", gap: 8 }}>
            <Btn variant="primary" onClick={save} disabled={saving}>{saving ? "Saving…" : editing === "new" ? "Create Company" : "Save Changes"}</Btn>
            <Btn onClick={() => setEditing(null)}>Cancel</Btn>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── Admin Gmail ───────────────────────────────────────────────────────────────
function AdminGmail({ mailboxes, setMailboxes, companies, addNotification }) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ email: "", displayName: "", companyId: companies[0]?.id || "" });
  const [testing, setTesting] = useState({});
  const [renewing, setRenewing] = useState({});

  function simulateWatch(mbId, action) {
    if (action === "renew") {
      setRenewing(p => ({ ...p, [mbId]: true }));
      setTimeout(() => {
        setMailboxes(p => p.map(m => m.id === mbId ? { ...m, watchStatus: "active", lastHistoryId: String(8800000 + Math.floor(Math.random() * 99999)), watchExpiry: "2026-03-15" } : m));
        setRenewing(p => ({ ...p, [mbId]: false }));
        addNotification("Gmail watch renewed successfully", "success");
      }, 1500);
    }
    if (action === "stop") {
      setMailboxes(p => p.map(m => m.id === mbId ? { ...m, watchStatus: "expired", watchExpiry: null } : m));
      addNotification("Gmail watch stopped", "info");
    }
  }

  function simulateTest(mbId) {
    setTesting(p => ({ ...p, [mbId]: true }));
    setTimeout(() => {
      setTesting(p => ({ ...p, [mbId]: false }));
      const mb = mailboxes.find(m => m.id === mbId);
      if (mb?.watchStatus === "active") addNotification(`✓ Connection OK: ${mb.email}`, "success");
      else addNotification(`✗ Connection failed: ${mb?.email}`, "error");
    }, 1200);
  }

  function addMailbox() {
    const newMb = { id: `mb${Date.now()}`, ...form, watchStatus: "expired", lastHistoryId: "", watchExpiry: null, gmailUserId: form.email };
    setMailboxes(p => [...p, newMb]);
    addNotification("Mailbox added — register Gmail watch to activate", "info");
    setAdding(false);
    setForm({ email: "", displayName: "", companyId: companies[0]?.id || "" });
  }

  return (
    <div>
      <SectionHeader title="Gmail Mailbox Configuration"
        subtitle="Connect Google Workspace mailboxes via service account. One mailbox per MC role."
        action={<Btn variant="primary" onClick={() => setAdding(true)}>+ ADD MAILBOX</Btn>} />

      {/* Service Account Status */}
      <Card style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 10, color: T.text0, marginBottom: 4, fontWeight: 500 }}>Google Service Account</div>
            <div style={{ fontSize: 9, color: T.text2 }}>secrets/service_account.json · Domain-wide delegation enabled</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StatusDot status="active" />
            <span style={{ fontSize: 9, color: T.green }}>CONNECTED</span>
          </div>
        </div>
        <div style={{ marginTop: 12, padding: "8px 12px", background: T.bg0, borderRadius: 3, display: "flex", gap: 20 }}>
          {[["Gmail API", "Enabled"],["Pub/Sub Topic", "gmail-push"],["Scopes", "gmail.modify · gmail.send"]].map(([k, v]) => (
            <div key={k}>
              <div style={{ fontSize: 8, color: T.text3, marginBottom: 2 }}>{k}</div>
              <div style={{ fontSize: 9, color: T.text1 }}>{v}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* Pub/Sub Webhook */}
      <Card style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 10, color: T.text0, marginBottom: 10, fontWeight: 500 }}>Gmail Push Webhook</div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <div style={{ flex: 1, background: T.bg0, border: `1px solid ${T.border}`, borderRadius: 3, padding: "7px 11px", fontSize: 10, color: T.text2, fontFamily: "monospace" }}>
            POST https://api.yourdomain.com/webhooks/google/gmail/push
          </div>
          <Badge color={T.green}>ACTIVE</Badge>
        </div>
        <div style={{ fontSize: 9, color: T.text3, marginTop: 8 }}>
          Pub/Sub push subscription delivers notifications here within ~2 seconds of new email.
        </div>
      </Card>

      {/* Mailboxes */}
      <SectionHeader title="Registered Mailboxes" subtitle={`${mailboxes.filter(m => m.watchStatus === "active").length}/${mailboxes.length} watches active`} />
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {mailboxes.map(mb => {
          const co = companies.find(c => String(c.id) === String(mb.companyId));
          return (
            <Card key={mb.id} style={{ padding: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <StatusDot status={mb.watchStatus} />
                    <span style={{ fontSize: 11, color: T.text0 }}>{mb.email}</span>
                    <Badge color={co?.color || T.text3}>{co?.mc_number}</Badge>
                    <Badge color={mb.watchStatus === "active" ? T.green : mb.watchStatus === "expired" ? T.yellow : T.red}>
                      {(mb.watchStatus || "unknown").toUpperCase()}
                    </Badge>
                  </div>
                  <div style={{ display: "flex", gap: 16, fontSize: 9, color: T.text3 }}>
                    <span>Display: {mb.displayName}</span>
                    <span>Company: {co?.name}</span>
                    {mb.lastHistoryId && <span style={{ fontFamily: "monospace" }}>historyId: {mb.lastHistoryId}</span>}
                    {mb.watchExpiry && <span>Expires: {mb.watchExpiry}</span>}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <Btn size="xs" onClick={() => simulateTest(mb.id)} disabled={testing[mb.id]}>{testing[mb.id] ? "testing…" : "TEST"}</Btn>
                  {mb.watchStatus !== "active"
                    ? <Btn size="xs" variant="success" onClick={() => simulateWatch(mb.id, "renew")} disabled={renewing[mb.id]}>{renewing[mb.id] ? "registering…" : "REGISTER WATCH"}</Btn>
                    : <Btn size="xs" onClick={() => simulateWatch(mb.id, "renew")} disabled={renewing[mb.id]}>{renewing[mb.id] ? "renewing…" : "RENEW"}</Btn>
                  }
                  {mb.watchStatus === "active" && <Btn size="xs" variant="danger" onClick={() => simulateWatch(mb.id, "stop")}>STOP</Btn>}
                </div>
              </div>
              {mb.watchStatus !== "active" && (
                <div style={{ marginTop: 10, padding: "7px 11px", background: T.yellowDim, borderRadius: 3, fontSize: 9, color: T.yellow }}>
                  ⚠ No active Gmail watch — inbound emails will not be processed until you register a watch.
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {/* Add mailbox modal */}
      {adding && (
        <Modal onClose={() => setAdding(false)} width={460}>
          <div style={{ padding: "12px 16px", borderBottom: `1px solid ${T.border}`, fontSize: 11, color: T.text0 }}>Add Gmail Mailbox</div>
          <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <div style={{ fontSize: 9, color: T.text3, marginBottom: 4, letterSpacing: "0.1em" }}>EMAIL ADDRESS</div>
              <Input value={form.email} onChange={e => setForm(p => ({ ...p, email: e.target.value }))} placeholder="dispatch@yourmc.com" />
            </div>
            <div>
              <div style={{ fontSize: 9, color: T.text3, marginBottom: 4, letterSpacing: "0.1em" }}>DISPLAY NAME</div>
              <Input value={form.displayName} onChange={e => setForm(p => ({ ...p, displayName: e.target.value }))} placeholder="MC Dispatch" />
            </div>
            <div>
              <div style={{ fontSize: 9, color: T.text3, marginBottom: 4, letterSpacing: "0.1em" }}>COMPANY</div>
              <Select value={form.companyId} onChange={e => setForm(p => ({ ...p, companyId: e.target.value }))} options={companies.map(c => ({ value: c.id, label: `${c.mc_number} — ${c.name}` }))} />
            </div>
            <div style={{ background: T.bg0, borderRadius: 3, padding: "8px 11px", fontSize: 9, color: T.text3 }}>
              The service account must have domain-wide delegation and gmail.modify scope granted in Google Workspace Admin before this mailbox can receive push notifications.
            </div>
          </div>
          <div style={{ padding: "10px 16px", borderTop: `1px solid ${T.border}`, display: "flex", gap: 7 }}>
            <Btn variant="primary" onClick={addMailbox} disabled={!form.email}>ADD MAILBOX</Btn>
            <Btn onClick={() => setAdding(false)}>CANCEL</Btn>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── Admin Users ───────────────────────────────────────────────────────────────
function AdminUsers({ users, setUsers, companies, addNotification }) {
  const [editing, setEditing] = useState(null);
  const [form, setForm]       = useState({});
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  async function reload() {
    setLoading(true);
    try {
      const data = await callApi("GET", "/users/");
      const list = Array.isArray(data) ? data : (data.results || []);
      setUsers(list.map(u => ({
        id:          String(u.id),
        name:        `${u.first_name || ""} ${u.last_name || ""}`.trim() || u.username,
        username:    u.username,
        email:       u.email,
        role:        u.role,
        avatar:      ((u.first_name?.[0] || u.username?.[0] || "?") + (u.last_name?.[0] || "")).toUpperCase(),
        assignedMCs: (u.assigned_companies || []).map(String),
        active:      u.is_active,
      })));
    } catch(e) { addNotification("Failed to load users: " + e.message, "error"); }
    setLoading(false);
  }

  useEffect(() => { reload(); }, []);

  function openEdit(u) {
    setError("");
    if (u) {
      setEditing(u.id);
      setForm({
        username:    u.username,
        first_name:  u.name?.split(" ")[0] || "",
        last_name:   u.name?.split(" ").slice(1).join(" ") || "",
        email:       u.email,
        role:        u.role,
        assignedMCs: u.assignedMCs || [],
        is_active:   u.active,
        password:    "",
      });
    } else {
      setEditing("new");
      setForm({ username:"", first_name:"", last_name:"", email:"", role:"dispatcher", assignedMCs:[], is_active:true, password:"" });
    }
  }

  function toggleMC(id) {
    const sid = String(id);
    setForm(p => ({
      ...p,
      assignedMCs: p.assignedMCs.includes(sid)
        ? p.assignedMCs.filter(m => m !== sid)
        : [...p.assignedMCs, sid]
    }));
  }

  async function save() {
    if (!form.username) { setError("Username is required."); return; }
    if (editing === "new" && !form.password) { setError("Password is required for new users."); return; }
    setSaving(true); setError("");
    try {
      const payload = {
        username:            form.username,
        first_name:          form.first_name || "",
        last_name:           form.last_name  || "",
        email:               form.email      || "",
        role:                form.role,
        is_active:           form.is_active,
        assigned_company_ids: form.assignedMCs,
        ...(form.password ? { password: form.password } : {}),
      };
      if (editing === "new") {
        await callApi("POST", "/users/", payload);
        addNotification("User created ✓", "success");
      } else {
        await callApi("PATCH", `/users/${editing}/`, payload);
        addNotification("User updated ✓", "success");
      }
      await reload();
      setEditing(null);
    } catch(e) {
      setError(e.message || "Save failed");
    }
    setSaving(false);
  }

  async function deactivate(u) {
    if (!confirm(`Deactivate ${u.name}? They won't be able to log in.`)) return;
    try {
      await callApi("POST", `/users/${u.id}/deactivate/`);
      addNotification(`${u.name} deactivated`, "info");
      await reload();
    } catch(e) { addNotification("Error: " + e.message, "error"); }
  }

  async function resetPassword(u) {
    const pw = prompt(`New password for ${u.name} (min 8 chars):`);
    if (!pw || pw.length < 8) { addNotification("Password must be at least 8 characters", "error"); return; }
    try {
      await callApi("PATCH", `/users/${u.id}/`, { password: pw });
      addNotification(`Password reset for ${u.name} ✓`, "success");
    } catch(e) { addNotification("Reset failed: " + e.message, "error"); }
  }

  return (
    <div>
      <SectionHeader
        title="User Management"
        subtitle={`${users.filter(u => u.active).length} active · ${users.filter(u => !u.active).length} inactive`}
        action={
          <div style={{ display:"flex", gap:8 }}>
            <Btn onClick={reload} disabled={loading}>↻ Refresh</Btn>
            <Btn variant="primary" onClick={() => openEdit(null)}>+ ADD USER</Btn>
          </div>
        }
      />

      <Card>
        <table style={{ width:"100%", borderCollapse:"collapse" }}>
          <thead><tr style={{ borderBottom:`1px solid ${T.border}`, background:T.bg2 }}>
            {["User","Role","Assigned Companies","Status","Actions"].map(h => (
              <th key={h} style={{ padding:"10px 12px", fontSize:10, fontWeight:600, color:T.text3, textAlign:"left" }}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {loading && (
              <tr><td colSpan={5} style={{ padding:"30px", textAlign:"center", color:T.text3, fontSize:11 }}>Loading users…</td></tr>
            )}
            {!loading && users.length === 0 && (
              <tr><td colSpan={5} style={{ padding:"30px", textAlign:"center", color:T.text3, fontSize:11 }}>
                No users yet. Click + ADD USER to create the first dispatcher.
              </td></tr>
            )}
            {users.map(u => {
              const rm = ROLE_META[u.role] || ROLE_META.dispatcher;
              return (
                <tr key={u.id} className="hover-row" style={{ borderBottom:`1px solid ${T.border}`, opacity: u.active ? 1 : 0.5 }}>
                  <td style={{ padding:"10px 12px" }}>
                    <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                      <div style={{ width:32, height:32, borderRadius:"50%", background:rm.color+"22",
                        border:`1px solid ${rm.color}44`, display:"flex", alignItems:"center",
                        justifyContent:"center", fontSize:11, color:rm.color, fontWeight:600, flexShrink:0 }}>
                        {u.avatar}
                      </div>
                      <div>
                        <div style={{ fontSize:11, fontWeight:600, color:T.text0 }}>{u.name || u.username}</div>
                        <div style={{ fontSize:10, color:T.text3 }}>{u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding:"10px 12px" }}>
                    <Badge color={rm.color}>{rm.icon} {rm.label}</Badge>
                  </td>
                  <td style={{ padding:"10px 12px" }}>
                    <div style={{ display:"flex", gap:4, flexWrap:"wrap" }}>
                      {(u.assignedMCs || []).map(id => {
                        const co = companies.find(c => String(c.id) === String(id));
                        return co
                          ? <Badge key={id} color={co.color || T.accent}>{co.mc_number}</Badge>
                          : null;
                      })}
                      {(u.assignedMCs || []).length === 0 && (
                        <span style={{ fontSize:10, color:T.text3 }}>None assigned</span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding:"10px 12px" }}>
                    <StatusDot status={u.active ? "active" : "error"} />
                    <span style={{ fontSize:10, color:T.text2, marginLeft:6 }}>{u.active ? "Active" : "Inactive"}</span>
                  </td>
                  <td style={{ padding:"10px 12px" }}>
                    <div style={{ display:"flex", gap:5 }}>
                      <Btn size="xs" onClick={() => openEdit(u)}>EDIT</Btn>
                      <Btn size="xs" onClick={() => resetPassword(u)}>RESET PW</Btn>
                      {u.active && <Btn size="xs" variant="danger" onClick={() => deactivate(u)}>DEACTIVATE</Btn>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>

      {editing && (
        <Modal onClose={() => setEditing(null)} width={560}>
          <div style={{ padding:"14px 18px", borderBottom:`1px solid ${T.border}`, fontSize:13, fontWeight:600, color:T.text0 }}>
            {editing === "new" ? "Add User" : "Edit User"}
          </div>
          <div style={{ padding:18, display:"flex", flexDirection:"column", gap:14, overflowY:"auto" }}>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:14 }}>
              {[["Username *","username","text","jsmith"],["Email","email","email","john@company.com"],
                ["First Name","first_name","text","John"],["Last Name","last_name","text","Smith"]
              ].map(([label,key,type,placeholder]) => (
                <div key={key}>
                  <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>{label}</div>
                  <Input type={type} value={form[key]||""} placeholder={placeholder}
                    onChange={e => setForm(p => ({...p, [key]:e.target.value}))} />
                </div>
              ))}
              <div>
                <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>
                  {editing === "new" ? "Password *" : "New Password (leave blank to keep)"}
                </div>
                <Input type="password" value={form.password||""} placeholder="min 8 characters"
                  onChange={e => setForm(p => ({...p, password:e.target.value}))} />
              </div>
              <div>
                <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>Role</div>
                <Select value={form.role||"dispatcher"}
                  onChange={e => setForm(p => ({...p, role:e.target.value}))}
                  options={Object.entries(ROLE_META).map(([v,m]) => ({value:v, label:`${m.icon} ${m.label}`}))} />
              </div>
            </div>

            {/* Company assignment */}
            <div>
              <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:8 }}>
                Assigned Companies
                <span style={{ fontSize:9, fontWeight:400, color:T.text3, marginLeft:8 }}>
                  (dispatchers only see emails from assigned companies)
                </span>
              </div>
              {companies.length === 0 ? (
                <div style={{ fontSize:11, color:T.text3 }}>No companies found — add companies first</div>
              ) : (
                <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
                  {companies.map(co => {
                    const selected = (form.assignedMCs||[]).includes(String(co.id));
                    return (
                      <button key={co.id} onClick={() => toggleMC(co.id)}
                        style={{ background: selected ? (co.color||T.accent)+"20" : T.bg0,
                          border: `1px solid ${selected ? (co.color||T.accent)+"66" : T.border}`,
                          color: selected ? (co.color||T.accent) : T.text2,
                          padding:"7px 14px", borderRadius:6, cursor:"pointer",
                          fontFamily:"inherit", fontSize:11, fontWeight:selected?600:400,
                          transition:"all 0.15s" }}>
                        {selected ? "✓ " : ""}{co.mc_number} — {co.name}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div>
              <div style={{ fontSize:10, fontWeight:600, color:T.text2, marginBottom:5 }}>Account Status</div>
              <Select value={form.is_active ? "true" : "false"}
                onChange={e => setForm(p => ({...p, is_active: e.target.value === "true"}))}
                options={[{value:"true",label:"Active"},{value:"false",label:"Inactive"}]} />
            </div>
          </div>

          {error && (
            <div style={{ margin:"0 18px 12px", background:T.redDim, border:`1px solid ${T.red}44`,
              borderRadius:6, padding:"10px 14px", fontSize:11, color:T.red }}>
              {error}
            </div>
          )}
          <div style={{ padding:"12px 18px", borderTop:`1px solid ${T.border}`, display:"flex", gap:8 }}>
            <Btn variant="primary" onClick={save} disabled={saving}>
              {saving ? "Saving…" : editing === "new" ? "Create User" : "Save Changes"}
            </Btn>
            <Btn onClick={() => setEditing(null)}>Cancel</Btn>
          </div>
        </Modal>
      )}
    </div>
  );
}


// ─── MODAL ────────────────────────────────────────────────────────────────────
function Modal({ children, onClose, width = 560 }) {
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "#00000088", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: T.bg2, border: `1px solid ${T.border2}`, borderRadius: 6, width, maxHeight: "85vh", display: "flex", flexDirection: "column" }} className="fade-in">
        {children}
      </div>
    </div>
  );
}

// Wrap with ErrorBoundary
export default function DispatchOS() {
  return <ErrorBoundary><DispatchOSApp /></ErrorBoundary>;
}
