import React, { useState, useEffect, useCallback, useRef } from "react";


const API     = (path) => `/api/settings${path}`;
const API_RAW = (path) => `/api${path}`;

async function apiRaw(method, path, body) {
  const needsCsrf = !["GET","HEAD"].includes(method.toUpperCase());
  let token = "";
  if (needsCsrf) {
    const m = document.cookie.split(";").find(c => c.trim().startsWith("csrftoken="));
    token = m ? decodeURIComponent(m.trim().split("=")[1]) : "";
    if (!token) {
      await fetch("/api/auth/csrf/", {credentials:"include"}).catch(()=>{});
      const m2 = document.cookie.split(";").find(c => c.trim().startsWith("csrftoken="));
      token = m2 ? decodeURIComponent(m2.trim().split("=")[1]) : "";
    }
  }
  const opts = {
    method,
    credentials: "include",
    headers: {"Content-Type":"application/json", ...(token ? {"X-CSRFToken":token} : {})},
  };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(API_RAW(path), opts);
  if (!r.ok) {
    const e = await r.json().catch(() => ({error: r.statusText}));
    throw new Error(e.error || r.statusText);
  }
  return r.json();
}


const T = {
  bg0:"#f0f4f8", bg1:"#ffffff", bg2:"#f8fafc", bg3:"#eef2f7",
  border:"#dde3ec", border2:"#c8d2e0",
  text0:"#0f1c2e", text1:"#1e3a5f", text2:"#4a6080", text3:"#8098b4",
  accent:"#1a6ed4", accentDim:"#dbeafe",
  green:"#16a34a",  greenDim:"#dcfce7",
  red:"#dc2626",    redDim:"#fee2e2",
  yellow:"#d97706", yellowDim:"#fef9c3",
  blue:"#2563eb",
};

// Read CSRF token from cookie
function getCsrf() {
  const match = document.cookie.split(";").find(c => c.trim().startsWith("csrftoken="));
  return match ? decodeURIComponent(match.trim().split("=")[1]) : "";
}

// Fetch CSRF token from Django if we don't have one yet
async function ensureCsrf() {
  if (getCsrf()) return;
  try {
    await fetch("/api/auth/csrf/", { credentials: "include" });
  } catch (e) {
    console.warn("Could not fetch CSRF token:", e);
  }
}

async function api(method, path, body, isFile=false) {
  const needsCsrf = !["GET","HEAD","OPTIONS"].includes(method.toUpperCase());
  if (needsCsrf) await ensureCsrf();
  let r;
  try {
    const token = getCsrf();
    const headers = isFile
      ? (token ? {"X-CSRFToken": token} : {})
      : {"Content-Type":"application/json", ...(token ? {"X-CSRFToken": token} : {})};
    const opts = { method, credentials:"include", headers };
    if (body) opts.body = isFile ? body : JSON.stringify(body);
    r = await fetch(API(path), opts);
  } catch (netErr) {
    if (netErr.message?.includes("Failed to fetch") || netErr.message?.includes("NetworkError")) {
      throw new Error("Cannot reach the server. Make sure Dispatch OS is running (docker compose up -d) and try again.");
    }
    throw new Error(`Network error: ${netErr.message}`);
  }
  if (!r.ok) {
    let errMsg;
    try {
      const data = await r.json();
      errMsg = data.error || data.detail || data.message;
    } catch {
      errMsg = null;
    }
    if (!errMsg) {
      const STATUS_MESSAGES = {
        400: "Invalid request. Check your input and try again.",
        401: "Not authenticated. Log in and try again.",
        403: "Permission denied. Admin or manager role required.",
        404: "Not found. The resource may have been deleted.",
        429: "Too many requests. Wait a moment and try again.",
        500: "Server error. Check the Docker logs: docker compose logs api",
        502: "Server unreachable. The API container may be restarting.",
        503: "Service unavailable. Check that all Docker services are running.",
      };
      errMsg = STATUS_MESSAGES[r.status] || `Server returned ${r.status}. Check Docker logs for details.`;
    }
    throw new Error(errMsg);
  }
  return r.json();
}

const Btn = ({onClick,children,variant="ghost",disabled,small,style={}}) => {
  const styles = {
    primary: {background:T.accent,      borderColor:T.accent,     color:"#fff",    fontWeight:600},
    ghost:   {background:T.bg1,         borderColor:T.border,     color:T.text2},
    danger:  {background:T.redDim,      borderColor:T.red+"55",   color:T.red,     fontWeight:500},
    success: {background:T.greenDim,    borderColor:T.green+"55", color:T.green,   fontWeight:500},
    warning: {background:T.yellowDim,   borderColor:T.yellow+"55",color:T.yellow,  fontWeight:500},
  }[variant] || {};
  return <button disabled={disabled} onClick={onClick}
    style={{border:"1px solid",padding:small?"3px 10px":"7px 16px",borderRadius:6,cursor:disabled?"not-allowed":"pointer",
      fontFamily:"inherit",fontSize:small?10:11,letterSpacing:"0.02em",opacity:disabled?0.4:1,
      transition:"all 0.15s",boxShadow:variant==="primary"?"0 1px 3px rgba(26,110,212,0.3)":"none",
      ...styles,...style}}>{children}</button>;
};

const Tag = ({color=T.accent,children}) => <span style={{fontSize:10,fontWeight:600,background:color+"12",color,border:`1px solid ${color}40`,padding:"2px 8px",borderRadius:5,letterSpacing:"0.02em",whiteSpace:"nowrap",display:"inline-block"}}>{children}</span>;
const Dot = ({status}) => { const c={active:T.green,inactive:T.text3,error:T.red,expired:T.yellow}[status]||T.text3; return <span style={{display:"inline-block",width:7,height:7,borderRadius:"50%",background:c,flexShrink:0,boxShadow:`0 0 5px ${c}66`}}/>; };
const Input = ({value,onChange,placeholder,type="text",style={}}) => <input value={value} onChange={onChange} placeholder={placeholder} type={type} style={{background:"#fff",border:`1px solid ${T.border}`,color:T.text0,padding:"9px 12px",borderRadius:6,fontFamily:"inherit",fontSize:12,width:"100%",outline:"none",boxShadow:"inset 0 1px 2px rgba(0,0,0,0.04)",...style}} onFocus={e=>{e.target.style.borderColor=T.accent;e.target.style.boxShadow=`0 0 0 3px ${T.accent}20`;}} onBlur={e=>{e.target.style.borderColor=T.border;e.target.style.boxShadow="inset 0 1px 2px rgba(0,0,0,0.04)";}} />;
const Field = ({label,hint,children}) => <div style={{marginBottom:16}}><div style={{fontSize:10,fontWeight:600,color:T.text2,letterSpacing:"0.03em",marginBottom:6}}>{label}</div>{children}{hint&&<div style={{fontSize:9,color:T.text3,marginTop:4}}>{hint}</div>}</div>;
const Card = ({children,style={},accent}) => <div style={{background:"#fff",border:`1px solid ${accent?accent+"55":T.border}`,borderRadius:8,boxShadow:"0 1px 4px rgba(0,0,0,0.06)",...(accent?{borderTopColor:accent,borderTopWidth:3}:{}),...style}}>{children}</div>;
const Section = ({title,subtitle,action,children}) => <div style={{marginBottom:32}}><div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:16}}><div><div style={{fontSize:15,fontWeight:700,color:T.text0}}>{title}</div>{subtitle&&<div style={{fontSize:10,color:T.text3,marginTop:3}}>{subtitle}</div>}</div>{action}</div>{children}</div>;
const Toast = ({toasts,onDismiss}) => (
  <div style={{position:"fixed",bottom:20,right:20,display:"flex",flexDirection:"column",gap:8,zIndex:999,maxWidth:420}}>
    {toasts.map(t=>{
      const isErr = t.type==="error";
      const isOk  = t.type==="success";
      const bg    = isOk?T.greenDim:isErr?T.redDim:T.accentDim;
      const border= isOk?T.green:isErr?T.red:T.accent;
      const icon  = isOk?"✓":isErr?"✕":"ℹ";
      return (
        <div key={t.id} style={{padding:"10px 14px",borderRadius:4,fontFamily:"inherit",background:bg,border:`1px solid ${border}44`,color:border,display:"flex",gap:10,alignItems:"flex-start",boxShadow:"0 4px 16px #00000066"}}>
          <span style={{fontSize:12,flexShrink:0,marginTop:1}}>{icon}</span>
          <div style={{flex:1}}>
            <div style={{fontSize:10,lineHeight:1.5}}>{t.msg}</div>
            {t.hint&&<div style={{fontSize:9,color:border+"aa",marginTop:4,lineHeight:1.5}}>{t.hint}</div>}
          </div>
          <button onClick={()=>onDismiss&&onDismiss(t.id)} style={{background:"none",border:"none",color:border+"88",cursor:"pointer",fontSize:12,flexShrink:0,padding:0,lineHeight:1}}>x</button>
        </div>
      );
    })}
  </div>
);

function Modal({title,onClose,children,width=560}) {
  return <div style={{position:"fixed",inset:0,background:"#000000aa",display:"flex",alignItems:"center",justifyContent:"center",zIndex:400}}>
    <div style={{background:T.bg2,border:`1px solid ${T.border2}`,borderRadius:6,width,maxHeight:"90vh",display:"flex",flexDirection:"column"}}>
      <div style={{padding:"13px 18px",borderBottom:`1px solid ${T.border}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <span style={{fontSize:12,color:T.text0,fontWeight:500}}>{title}</span>
        <button onClick={onClose} style={{background:"none",border:"none",color:T.text3,cursor:"pointer",fontSize:16}}>x</button>
      </div>
      <div style={{overflow:"auto",flex:1}}>{children}</div>
    </div>
  </div>;
}

// ── Main export ───────────────────────────────────────────────────────────────
export default function AdminSettings({ companies: _mockCompanies=[] }) {
  const [tab, setTab]             = useState("diagnostics");
  const [toasts, setToasts]       = useState([]);
  const [companies, setCompanies] = useState([]);

  // Fetch real companies from Django API
  const loadCompanies = useCallback(async () => {
    try {
      const data = await apiRaw("GET", "/companies/");
      const list = Array.isArray(data) ? data : (data.results || []);
      setCompanies(list);
      if (list.length === 0) {
        console.warn("No companies in database — create companies in Admin → Companies first");
      }
    } catch(e) {
      console.warn("Could not fetch companies:", e.message);
      setCompanies([]);
    }
  }, []);

  useEffect(() => { loadCompanies(); }, [loadCompanies]);

  const toast = useCallback((msg, type="info", hint=null) => {
    const id = Date.now();
    setToasts(p=>[...p,{id,msg,type,hint}]);
    const duration = type==="error" ? 10000 : type==="success" ? 4000 : 6000;
    setTimeout(()=>setToasts(p=>p.filter(t=>t.id!==id)), duration);
  },[]);
  const dismissToast = useCallback((id)=>setToasts(p=>p.filter(t=>t.id!==id)),[]);

  const tabs = [
    {id:"diagnostics",icon:"🩺",label:"Diagnostics"},
    {id:"gmail",      icon:"📧",label:"Gmail / Google"},
    {id:"mailboxes",  icon:"📬",label:"Mailboxes"},
    {id:"slack",      icon:"💬",label:"Slack"},
  ];

  return (
    <div style={{fontFamily:"'Plus Jakarta Sans','Segoe UI',system-ui,sans-serif",display:"flex",height:"100%",overflow:"hidden"}}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');*{box-sizing:border-box;}input::placeholder{color:${T.text3}}select{cursor:pointer}.hover-row:hover{background:${T.bg3}!important}`}</style>
      <div style={{width:200,background:"#fff",borderRight:`1px solid ${T.border}`,padding:"20px 0",flexShrink:0,boxShadow:"1px 0 4px rgba(0,0,0,0.04)"}}>
        <div style={{padding:"0 16px 12px",fontSize:9,fontWeight:700,color:T.text3,letterSpacing:"0.15em"}}>INTEGRATIONS</div>
        {tabs.map(t=>(
          <div key={t.id} onClick={()=>setTab(t.id)} style={{padding:"10px 16px",display:"flex",alignItems:"center",gap:10,cursor:"pointer",background:tab===t.id?T.accentDim:"transparent",borderLeft:`3px solid ${tab===t.id?T.accent:"transparent"}`,transition:"all 0.15s",margin:"1px 8px",borderRadius:"0 6px 6px 0"}}>
            <span style={{fontSize:14}}>{t.icon}</span>
            <span style={{fontSize:10,color:tab===t.id?T.accent:T.text2}}>{t.label}</span>
          </div>
        ))}
      </div>
      <div style={{flex:1,overflowY:"auto",padding:28}}>
        {tab==="diagnostics"&& <DiagnosticsTab toast={toast}/>}
        {tab==="gmail"     && <GmailTab     toast={toast} companies={companies}/>}
        {tab==="mailboxes" && <MailboxesTab toast={toast} companies={companies} loadCompanies={loadCompanies}/>}
        {tab==="slack"     && <SlackTab     toast={toast}/>}
      </div>
      <Toast toasts={toasts} onDismiss={dismissToast}/>
    </div>
  );
}

// ── OAuth App Section ─────────────────────────────────────────────────────────
function OAuthAppSection({ toast }) {
  const [apps, setApps]         = useState([]);
  const [editing, setEditing]   = useState(null); // null | "new" | {id,name,...}
  const [form, setForm]         = useState({name:"",client_id:"",client_secret:"",redirect_uri:""});
  const [saving, setSaving]     = useState(false);
  const [showSec, setShowSec]   = useState(false);

  const defaultRedirect = `${window.location.protocol}//${window.location.host}/api/settings/oauth/callback/`;

  const load = useCallback(async()=>{
    try {
      const d = await api("GET","/oauth/app/");
      setApps(Array.isArray(d) ? d : [d].filter(Boolean));
    } catch(e){ toast(e.message,"error"); }
  },[]);
  useEffect(()=>{load();},[load]);

  function openNew() {
    setForm({name:"", client_id:"", client_secret:"", redirect_uri: defaultRedirect});
    setEditing("new");
  }
  function openEdit(app) {
    setForm({name:app.name, client_id:app.client_id, client_secret:"", redirect_uri:app.redirect_uri, id:app.id});
    setEditing(app);
  }

  async function save() {
    if(!form.client_id){toast("Client ID required","error");return;}
    setSaving(true);
    try{
      await api("POST","/oauth/app/save/", form);
      toast(editing==="new" ? "OAuth app added ✓" : "OAuth app updated ✓","success");
      setEditing(null);
      load();
    } catch(e){toast(e.message,"error");}
    setSaving(false);
  }

  async function deleteApp(app) {
    if(!confirm(`Delete OAuth app "${app.name}"? Any mailboxes using it will need to be reconnected.`)) return;
    try{
      await api("DELETE", `/oauth/app/${app.id}/delete/`);
      toast("OAuth app deleted","info");
      load();
    } catch(e){toast(e.message,"error");}
  }

  // keep save() function but update form/editing refs
  const cfg = apps[0]; // for backward compat display

  return (
    <Section title="OAuth 2.0 Apps (for @gmail.com accounts)"
      subtitle="One app per GCP project. Each app can authorize multiple Gmail mailboxes."
      action={<Btn variant="primary" small onClick={openNew}>+ Add OAuth App</Btn>}>

      {/* Apps list */}
      {apps.length === 0 && (
        <div style={{background:T.yellowDim,border:`1px solid ${T.yellow}44`,borderRadius:6,padding:"12px 16px",marginBottom:14,fontSize:11,color:T.yellow}}>
          No OAuth apps configured yet. Click <strong>+ Add OAuth App</strong> to add your GCP credentials.
        </div>
      )}
      {apps.map(app => (
        <Card key={app.id} style={{padding:14,marginBottom:10,display:"flex",alignItems:"center",gap:12}}>
          <Dot status={app.has_credentials?"active":"error"}/>
          <div style={{flex:1}}>
            <div style={{fontSize:12,fontWeight:600,color:T.text0}}>{app.name}</div>
            <div style={{fontSize:10,color:T.text3,marginTop:2,fontFamily:"monospace"}}>{app.client_id ? app.client_id.slice(0,40)+"…" : "No client ID"}</div>
            <div style={{fontSize:10,color:T.text3,marginTop:1}}>{app.redirect_uri}</div>
          </div>
          <div style={{display:"flex",gap:6}}>
            <Btn small onClick={()=>openEdit(app)}>EDIT</Btn>
            <Btn small variant="danger" onClick={()=>deleteApp(app)}>DELETE</Btn>
          </div>
        </Card>
      ))}

      {/* Add/Edit form */}
      {editing && (
        <Card style={{padding:18,marginTop:14,border:`2px solid ${T.accent}44`}}>
          <div style={{fontSize:13,fontWeight:600,color:T.text0,marginBottom:16}}>
            {editing==="new" ? "Add OAuth App" : `Edit — ${editing.name}`}
          </div>

          {/* Instructions */}
          <div style={{background:T.accentDim,border:`1px solid ${T.accent}33`,borderRadius:6,padding:"10px 14px",marginBottom:16,fontSize:10,color:T.text1,lineHeight:1.7}}>
            <strong>How to get credentials:</strong><br/>
            1. <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer" style={{color:T.accent}}>GCP Console → APIs & Services → Credentials</a><br/>
            2. Create Credentials → OAuth client ID → Web application<br/>
            3. Add Authorized redirect URI: <code style={{background:"#fff",padding:"1px 4px",borderRadius:2}}>{defaultRedirect}</code><br/>
            4. Copy Client ID and Client Secret
          </div>

          <Field label="NAME" hint="e.g. RW Freight OAuth App">
            <Input value={form.name} onChange={e=>setForm(p=>({...p,name:e.target.value}))} placeholder="Dispatch OS OAuth App"/>
          </Field>
          <Field label="CLIENT ID" hint="Ends in .apps.googleusercontent.com">
            <Input value={form.client_id} onChange={e=>setForm(p=>({...p,client_id:e.target.value}))}
              placeholder="1023773162723-xxxxxxxx.apps.googleusercontent.com"/>
          </Field>
          <Field label="CLIENT SECRET" hint="Starts with GOCSPX-">
            <div style={{display:"flex",gap:8}}>
              <Input value={form.client_secret} onChange={e=>setForm(p=>({...p,client_secret:e.target.value}))}
                placeholder={editing!=="new" ? "(leave blank to keep existing)" : "GOCSPX-xxxxxxxxxxxxxxxxx"}
                type={showSec?"text":"password"} style={{flex:1}}/>
              <Btn small onClick={()=>setShowSec(p=>!p)}>{showSec?"HIDE":"SHOW"}</Btn>
            </div>
          </Field>
          <Field label="REDIRECT URI" hint="Must match GCP exactly — including the trailing slash">
            <Input value={form.redirect_uri} onChange={e=>setForm(p=>({...p,redirect_uri:e.target.value}))}/>
          </Field>
          <div style={{display:"flex",gap:8,marginTop:8}}>
            <Btn variant="primary" onClick={save} disabled={saving}>{saving?"Saving…":"Save OAuth App"}</Btn>
            <Btn onClick={()=>setEditing(null)}>Cancel</Btn>
          </div>
        </Card>
      )}
    </Section>
  );
}

// ── Gmail Tab ─────────────────────────────────────────────────────────────────
function GmailTab({ toast, companies }) {
  const [accounts, setAccounts] = useState([]);
  const [showAdd, setShowAdd]   = useState(false);
  const [showUpload, setShowUpload] = useState(null);
  const [testing, setTesting]   = useState(null);

  const load = useCallback(async()=>{
    try{setAccounts(await api("GET","/google/accounts/"));}
    catch(e){toast(e.message,"error");}
  },[]);
  useEffect(()=>{load();},[load]);

  async function testAccount(id) {
    setTesting(id);
    try{await api("POST",`/google/accounts/${id}/test/`,{});toast("Verified","success");load();}
    catch(e){toast(`Test failed: ${e.message}`,"error");}
    setTesting(null);
  }
  async function deleteAccount(id) {
    if(!confirm("Delete this service account?")) return;
    try{await api("DELETE",`/google/accounts/${id}/`);toast("Deleted","success");load();}
    catch(e){toast(e.message,"error");}
  }

  return (
    <div style={{maxWidth:820}}>

      {/* OAuth App - shown first since most users have Gmail */}
      <OAuthAppSection toast={toast}/>

      <div style={{borderTop:`1px solid ${T.border}`,margin:"28px 0"}}/>

      {/* Service Accounts - for Workspace domains only */}
      <Section title="Step 2 — Service Accounts (Workspace domains only)"
        subtitle="Only needed if you have emails on a Google Workspace domain YOUR company owns. Skip this if you only have @gmail.com accounts."
        action={<Btn variant="primary" onClick={()=>setShowAdd(true)}>+ ADD SERVICE ACCOUNT</Btn>}>

        <Card style={{padding:14,marginBottom:20}}>
          <div style={{fontSize:9,color:T.text2,marginBottom:10,fontWeight:500,letterSpacing:"0.1em"}}>WHAT THIS IS FOR</div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
            {[["For","dispatch@yourcompany.com — your Workspace domain"],["Not for","@gmail.com — use OAuth above instead"],["Requires","Google Workspace admin access + service account JSON key"],["Benefit","One key covers all emails on the same domain"]].map(([k,v])=>(
              <div key={k} style={{background:T.bg0,borderRadius:3,padding:"8px 10px"}}>
                <div style={{fontSize:8,color:T.accent,marginBottom:2,letterSpacing:"0.1em"}}>{k}</div>
                <div style={{fontSize:9,color:T.text2}}>{v}</div>
              </div>
            ))}
          </div>
        </Card>

        {accounts.length===0 && <div style={{textAlign:"center",padding:"30px 0",color:T.text3,fontSize:10}}>No service accounts yet.</div>}

        <div style={{display:"flex",flexDirection:"column",gap:12}}>
          {accounts.map(sa=>(
            <Card key={sa.id} style={{padding:16}} accent={sa.last_test_ok===true?T.green:sa.last_test_ok===false?T.red:null}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:16}}>
                <div style={{flex:1}}>
                  <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:6}}>
                    <Dot status={sa.has_credentials?(sa.last_test_ok===true?"active":sa.last_test_ok===false?"error":"inactive"):"inactive"}/>
                    <span style={{fontSize:12,color:T.text0,fontWeight:500}}>{sa.name}</span>
                    {sa.has_credentials?<Tag color={T.green}>KEY UPLOADED</Tag>:<Tag color={T.yellow}>NO KEY</Tag>}
                    {sa.last_test_ok===true&&<Tag color={T.green}>VERIFIED</Tag>}
                    {sa.last_test_ok===false&&<Tag color={T.red}>TEST FAILED</Tag>}
                  </div>
                  <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:8}}>
                    {[["Domain",sa.domain],["Client Email",sa.client_email||"—"],["Pub/Sub Topic",sa.pubsub_topic||"Not set"]].map(([l,v])=>(
                      <div key={l} style={{background:T.bg0,borderRadius:3,padding:"7px 10px"}}>
                        <div style={{fontSize:8,color:T.text3,marginBottom:2}}>{l}</div>
                        <div style={{fontSize:9,color:T.text1,wordBreak:"break-all"}}>{v}</div>
                      </div>
                    ))}
                  </div>
                  {sa.last_test_ok===false&&sa.last_test_error&&<div style={{background:T.redDim,border:`1px solid ${T.red}33`,borderRadius:3,padding:"6px 10px",fontSize:9,color:T.red}}>{sa.last_test_error}</div>}
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:5,flexShrink:0}}>
                  <Btn small onClick={()=>setShowUpload(sa.id)}>{sa.has_credentials?"REPLACE KEY":"UPLOAD KEY"}</Btn>
                  {sa.has_credentials&&<Btn small onClick={()=>testAccount(sa.id)} disabled={testing===sa.id}>{testing===sa.id?"...":"TEST"}</Btn>}
                  <Btn small variant="danger" onClick={()=>deleteAccount(sa.id)}>DELETE</Btn>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </Section>

      {showAdd    && <AddSAModal    onClose={()=>setShowAdd(false)}      onSave={()=>{load();setShowAdd(false);}}      toast={toast}/>}
      {showUpload && <UploadKeyModal saId={showUpload} onClose={()=>setShowUpload(null)} onSave={()=>{load();setShowUpload(null);}} toast={toast}/>}
    </div>
  );
}

// ── Mailboxes Tab ─────────────────────────────────────────────────────────────
function MailboxesTab({ toast, companies, loadCompanies }) {
  const [mailboxes, setMailboxes] = useState([]);
  const [accounts, setAccounts]   = useState([]);
  const [showAdd, setShowAdd]     = useState(false);
  const [editMb, setEditMb]       = useState(null);
  const [registering, setReg]     = useState(null);
  const [connecting, setConn]     = useState(null);
  const [testing, setTesting]     = useState(null);
  const [syncing, setSyncing]     = useState(null);
  const [testResults, setTestResults] = useState({});
  const [syncResults, setSyncResults] = useState({});
  const [workerOk, setWorkerOk]   = useState(null);

  useEffect(() => {
    fetch("/api/system/worker-status/", {credentials:"include"})
      .then(r=>r.json()).then(d=>setWorkerOk(d.ok)).catch(()=>setWorkerOk(false));
  }, []);

  const load = useCallback(async()=>{
    try {
      const [mbs,sas] = await Promise.all([api("GET","/mailboxes/"),api("GET","/google/accounts/")]);
      setMailboxes(mbs); setAccounts(sas);
    } catch(e){toast(e.message,"error");}
  },[]);
  useEffect(()=>{load();},[load]);

  const [oauthPicker, setOauthPicker] = useState(null); // {mbId, apps:[]}

  async function connectOAuth(mb) {
    setConn(mb.id);
    try {
      const oauthApps = await api("GET","/oauth/app/").catch(()=>[]);
      const appList = Array.isArray(oauthApps) ? oauthApps : [];
      if (appList.length === 0) {
        toast("No OAuth apps configured. Go to Credentials tab → OAuth Apps → add your Google Client ID and Secret first.", "error");
        setConn(null); return;
      }
      if (appList.length === 1) {
        startOAuthFlow(mb, appList[0].id);
      } else {
        // Show picker instead of prompt()
        setOauthPicker({ mb, apps: appList });
        setConn(null);
      }
    } catch(e) {
      toast("OAuth error: " + e.message, "error");
      setConn(null);
    }
  }

  function startOAuthFlow(mb, oauthAppId) {
    (async () => {
      try {
        const payload = { email_address: mb.email_address };
        if (oauthAppId) payload.oauth_app_id = oauthAppId;
        const { auth_url } = await api("POST", "/oauth/begin/", payload);
        if (!auth_url) { toast("No auth URL returned — check OAuth app credentials", "error"); setConn(null); return; }
        const popup = window.open(auth_url, "oauth_popup", "width=520,height=620,scrollbars=yes");
        if (!popup) { toast("Popup blocked — allow popups for this site and try again", "error"); setConn(null); return; }
        const handleMsg = (e) => {
          if (e.data?.type === "oauth_success") { toast(`Connected: ${e.data.email}`, "success"); load(); }
          else if (e.data?.type === "oauth_error") {
            const err = e.data.error || "Unknown error";
            toast(`OAuth failed: ${err}`, "error");
          }
          window.removeEventListener("message", handleMsg);
          setConn(null);
        };
        window.addEventListener("message", handleMsg);
        const check = setInterval(() => {
          if (popup?.closed) { clearInterval(check); setConn(null); window.removeEventListener("message", handleMsg); }
        }, 500);
      } catch(e) {
        const msg = e.message || "Unknown error";
        let hint = "";
        if (msg.includes("redirect_uri")) hint = " — Check that the redirect URI in Google Cloud Console matches your app URL.";
        else if (msg.includes("invalid_client")) hint = " — Client ID or Secret is wrong. Re-check in Credentials → OAuth Apps.";
        else if (msg.includes("access_denied")) hint = " — User denied access. Try again and click 'Allow'.";
        toast(`OAuth error: ${msg}${hint}`, "error");
        setConn(null);
      }
    })();
  }

  async function testConnection(mb) {
    setTesting(mb.id);
    setTestResults(p => ({ ...p, [mb.id]: null }));
    try {
      const r = await api("POST", `/mailboxes/${mb.id}/test/`);
      setTestResults(p => ({ ...p, [mb.id]: { ok: true, email: r.email, messages: r.messages_total, threads: r.threads_total, method: r.auth_method } }));
      toast(`Connected! ${r.email} — ${r.messages_total?.toLocaleString()} messages`, "success");
    } catch(e) {
      setTestResults(p => ({ ...p, [mb.id]: { ok: false, error: e.message } }));
      toast(e.message, "error");
    }
    setTesting(null);
  }

  async function syncEmails(mb, limit=50) {
    setSyncing(mb.id);
    setSyncResults(p => ({ ...p, [mb.id]: { running: true, logs: [{level:"info", msg:`Fetching last ${limit} emails from ${mb.email_address}…`}] } }));
    try {
      console.log("Syncing mailbox:", mb.id, mb.email_address, "limit:", limit);
      const r = await api("POST", `/mailboxes/${mb.id}/sync/`, { limit });
      console.log("Sync result:", r);
      setSyncResults(p => ({ ...p, [mb.id]: { ...r, running: false } }));
      if (r.ok) {
        toast(r.imported > 0 ? `✓ Imported ${r.imported} emails` : "All emails already imported", r.errors ? "error" : "success");
      } else {
        toast(r.error || "Sync failed — check logs below", "error");
      }
    } catch(e) {
      console.error("Sync error:", e);
      setSyncResults(p => ({ ...p, [mb.id]: { running: false, ok: false, error: e.message, logs: [{level:"error", msg: e.message}] } }));
      toast("Sync failed: " + e.message, "error");
    }
    setSyncing(null);
  }

  async function registerWatch(mb) {
    setReg(mb.id);
    try {
      const r = await api("POST", `/mailboxes/${mb.id}/watch/register/`);
      toast(`✓ Watch active for ${mb.email_address} — expires ${new Date(r.expiry).toLocaleDateString()}`, "success");
      load();
    } catch(e) {
      let hint = "";
      if (e.message.includes("topic") || e.message.includes("Pub/Sub"))
        hint = "Set GOOGLE_PUBSUB_TOPIC in .env and add a Push subscription in GCP → Pub/Sub → Subscriptions.";
      else if (mb.auth_method === "service_account")
        hint = "Check: (1) Service account JSON key is uploaded, (2) Domain-wide delegation is set up in Google Workspace Admin, (3) gmail-api-push@system.gserviceaccount.com has Pub/Sub Publisher role on the topic.";
      else
        hint = "Make sure the mailbox is connected via OAuth — click Connect OAuth first.";
      toast(`Watch failed: ${e.message}`, "error", hint);
    }
    setReg(null);
  }

  async function stopWatch(mb) {
    try{await api("POST",`/mailboxes/${mb.id}/watch/stop/`);toast("Watch stopped","info");load();}
    catch(e){toast(e.message,"error");}
  }

  async function deleteMb(mb) {
    if(!confirm(`Delete ${mb.email_address}?`)) return;
    try{await api("DELETE",`/mailboxes/${mb.id}/`);toast("Removed","success");load();}
    catch(e){toast(e.message,"error");}
  }

  const watchColor = s=>({active:T.green,inactive:T.text3,error:T.red,expired:T.yellow}[s]||T.text3);

  return (
    <div style={{maxWidth:940}}>
      {companies.length===0&&(
        <div style={{background:T.yellowDim,border:`1px solid ${T.yellow}44`,borderRadius:6,padding:"14px 18px",marginBottom:16,fontSize:11,color:T.yellow,lineHeight:1.8}}>
          <strong>⚠ No companies loaded yet.</strong><br/>
          If you already added companies in Admin → Companies, click the button below to reload them.<br/>
          If you haven't added companies yet, go to <strong>Admin panel → Companies tab → Add Company</strong> first.
          <div style={{marginTop:10}}>
            <Btn small onClick={loadCompanies} variant="warning">↻ Reload Companies</Btn>
          </div>
        </div>
      )}
      {workerOk===false&&(
        <div style={{background:T.redDim,border:`1px solid ${T.red}44`,borderRadius:6,padding:"12px 16px",marginBottom:16,fontSize:11,color:T.red,lineHeight:1.7}}>
          ⚠ <strong>Celery worker is not running.</strong> Email classification and background tasks won't work. Fix: <code style={{background:T.redDim,padding:"1px 5px",borderRadius:3}}>docker compose up worker -d</code> — then refresh this page.
        </div>
      )}
      {workerOk===true&&(
        <div style={{background:T.greenDim,border:`1px solid ${T.green}33`,borderRadius:6,padding:"8px 14px",marginBottom:12,fontSize:10,color:T.green,display:"flex",alignItems:"center",gap:8}}>
          <Dot status="active"/> Worker running — emails will be classified automatically after sync.
        </div>
      )}
      <Section title="Mailboxes" subtitle="One row per MC email address. Connect via OAuth (personal Gmail) or link to a service account (Workspace)."
        action={<Btn variant="primary" onClick={()=>setShowAdd(true)} disabled={companies.length===0}>+ ADD MAILBOX</Btn>}>

        {/* Stats */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:20}}>
          {[["Total",mailboxes.length,T.accent],["Active",mailboxes.filter(m=>m.watch_status==="active").length,T.green],["Error",mailboxes.filter(m=>m.watch_status==="error").length,T.red],["Not watching",mailboxes.filter(m=>m.watch_status==="inactive").length,T.yellow]].map(([l,v,c])=>(
            <Card key={l} style={{padding:14,textAlign:"center"}}>
              <div style={{fontSize:22,fontWeight:600,color:c}}>{v}</div>
              <div style={{fontSize:9,color:T.text3,marginTop:3,letterSpacing:"0.1em"}}>{l.toUpperCase()}</div>
            </Card>
          ))}
        </div>

        {/* Table */}
        <Card>
          <table style={{width:"100%",borderCollapse:"collapse"}}>
            <thead>
              <tr style={{borderBottom:`1px solid ${T.border}`}}>
                {["MAILBOX","COMPANY","AUTH / CONNECT","WATCH","ACTIONS"].map(h=>(
                  <th key={h} style={{padding:"9px 12px",fontSize:8,color:T.text3,textAlign:"left",letterSpacing:"0.1em",fontWeight:400}}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {mailboxes.length===0&&<tr><td colSpan={6} style={{padding:"30px 12px",textAlign:"center",fontSize:10,color:T.text3}}>No mailboxes yet. Click + ADD MAILBOX to get started.</td></tr>}
              {mailboxes.map(mb=>{
                // Determine auth type — explicitly check for service_account
                const isOauth    = mb.auth_method !== "service_account";
                // Use explicit per-type auth status from API
                const authorized = isOauth
                  ? (mb.oauth_authorized === true || mb.oauth_connected === true || mb.oauth_valid === true)
                  : (mb.sa_authorized === true || mb.is_authorized === true);
                const tr = testResults[mb.id];
                const sr = syncResults[mb.id];
                return (
                  <React.Fragment key={mb.id}>
                  <tr className="hover-row" style={{borderBottom:tr||sr?`1px solid ${T.border2}`:`1px solid ${T.border}`}}>
                    <td style={{padding:"10px 12px"}}>
                      <div style={{fontSize:10,color:T.text0}}>{mb.email_address}</div>
                      {mb.display_name&&<div style={{fontSize:9,color:T.text3}}>{mb.display_name}</div>}
                      <Tag color={isOauth?T.accent:T.blue} style={{marginTop:4}}>{isOauth?"OAuth 2.0":"Service Acct"}</Tag>
                    </td>
                    <td style={{padding:"10px 12px"}}>
                      <Tag color={mb.company_color||T.accent}>{mb.company_mc}</Tag>
                      <div style={{fontSize:9,color:T.text2,marginTop:3}}>{mb.company_name}</div>
                    </td>
                    <td style={{padding:"10px 12px"}}>
                      {/* Auth status badge */}
                      {authorized
                        ? <Tag color={T.green}>✓ CONNECTED</Tag>
                        : <Tag color={T.red}>✗ NOT CONNECTED</Tag>
                      }
                      {/* OAuth connect button — always visible for oauth mailboxes */}
                      {isOauth && (
                        <div style={{marginTop:6}}>
                          <button
                            disabled={connecting===mb.id}
                            onClick={()=>connectOAuth(mb)}
                            style={{
                              background: authorized ? "#fff" : T.accent,
                              color: authorized ? T.text2 : "#fff",
                              border: `1px solid ${authorized ? T.border : T.accent}`,
                              borderRadius: 5, padding: "5px 12px",
                              cursor: connecting===mb.id ? "not-allowed" : "pointer",
                              fontFamily: "inherit", fontSize: 10, fontWeight: 600,
                              width: "100%", opacity: connecting===mb.id ? 0.5 : 1,
                              boxShadow: authorized ? "none" : "0 1px 4px rgba(26,110,212,0.3)",
                            }}>
                            {connecting===mb.id ? "Connecting…" : authorized ? "↺ Reconnect" : "🔗 Connect OAuth"}
                          </button>
                        </div>
                      )}
                      {!isOauth && !mb.service_account_name && (
                        <div style={{marginTop:6,padding:"6px 10px",background:T.redDim,border:`1px solid ${T.red}33`,borderRadius:4,fontSize:10,color:T.red}}>
                          ⚠ No service account linked.<br/>
                          <span style={{fontSize:9}}>Go to Gmail tab → Service Accounts → upload JSON key, then edit this mailbox to link it.</span>
                        </div>
                      )}
                      {!isOauth && mb.service_account_name && (
                        <div style={{marginTop:6,padding:"5px 10px",background:T.greenDim,border:`1px solid ${T.green}33`,borderRadius:4,fontSize:10,color:T.green}}>
                          ✓ {mb.service_account_name}
                          <div style={{fontSize:9,color:T.text3,marginTop:2}}>Domain-wide delegation — no OAuth needed</div>
                        </div>
                      )}
                    </td>
                    <td style={{padding:"10px 12px"}}>
                      <div style={{display:"flex",alignItems:"center",gap:5,marginBottom:4}}>
                        <Dot status={mb.watch_status==="active"?"active":mb.watch_status==="error"?"error":"inactive"}/>
                        <span style={{fontSize:9,color:watchColor(mb.watch_status)}}>{(mb.watch_status||"inactive").toUpperCase()}</span>
                      </div>
                      {mb.pubsub_topic && <div style={{fontSize:8,color:T.text3,marginBottom:4,wordBreak:"break-all"}}>Topic: {mb.pubsub_topic}</div>}
                      <div style={{display:"flex",gap:3,flexWrap:"wrap"}}>
                        {mb.watch_status!=="active"
                          ?<Btn small variant="success" disabled={!authorized||registering===mb.id} onClick={()=>registerWatch(mb)}>{registering===mb.id?"...":"REGISTER WATCH"}</Btn>
                          :<Btn small disabled={registering===mb.id} onClick={()=>registerWatch(mb)}>{registering===mb.id?"...":"RENEW"}</Btn>}
                        {mb.watch_status==="active"&&<Btn small variant="warning" onClick={()=>stopWatch(mb)}>STOP</Btn>}
                      </div>
                    </td>
                    <td style={{padding:"10px 12px"}}>
                      <div style={{display:"flex",flexDirection:"column",gap:5}}>
                        <Btn small onClick={()=>testConnection(mb)} disabled={testing===mb.id||!authorized}>
                          {testing===mb.id?"TESTING...":"TEST CONNECTION"}
                        </Btn>
                        <div style={{display:"flex",gap:3}}>
                          <Btn small variant="primary" onClick={()=>syncEmails(mb,50)} disabled={syncing===mb.id||!authorized}
                            title="Pull last 50 emails from Gmail">
                            {syncing===mb.id?"SYNCING...":"SYNC 50"}
                          </Btn>
                          <Btn small onClick={()=>syncEmails(mb,200)} disabled={syncing===mb.id||!authorized}
                            title="Pull last 200 emails from Gmail (slower)">
                            200
                          </Btn>
                        </div>
                        <Btn small onClick={()=>setEditMb(mb)}>EDIT</Btn>
                        <Btn small variant="danger" onClick={()=>deleteMb(mb)}>DELETE</Btn>
                      </div>
                    </td>
                  </tr>
                  {(tr||sr)&&(
                    <tr style={{borderBottom:`1px solid ${T.border}`}}>
                      <td colSpan={5} style={{padding:"0 12px 10px"}}>
                        {tr&&(
                          <div style={{background:tr.ok?T.greenDim:T.redDim,border:`1px solid ${tr.ok?T.green:T.red}33`,borderRadius:3,padding:"8px 12px",marginBottom:sr?6:0}}>
                            {tr.ok?(
                              <div style={{display:"flex",gap:20,alignItems:"center"}}>
                                <span style={{fontSize:9,color:T.green,fontWeight:500}}>✓ CONNECTION VERIFIED</span>
                                <span style={{fontSize:9,color:T.text2}}>Email: <span style={{color:T.text0}}>{tr.email}</span></span>
                                <span style={{fontSize:9,color:T.text2}}>Messages: <span style={{color:T.text0}}>{tr.messages?.toLocaleString()}</span></span>
                                <span style={{fontSize:9,color:T.text2}}>Threads: <span style={{color:T.text0}}>{tr.threads?.toLocaleString()}</span></span>
                                <span style={{fontSize:9,color:T.text2}}>Auth: <span style={{color:T.accent}}>{tr.method}</span></span>
                              </div>
                            ):(
                              <span style={{fontSize:9,color:T.red}}>✗ {tr.error}</span>
                            )}
                          </div>
                        )}
                        {sr&&(
                          <div style={{background: sr.running ? T.accentDim : (sr.errors ? T.redDim : (sr.ok ? T.greenDim : T.accentDim)),border:`1px solid ${sr.running?T.accent:sr.errors?T.red:sr.ok?T.green:T.accent}33`,borderRadius:6,padding:"10px 14px"}}>
                            {/* Summary bar */}
                            <div style={{display:"flex",gap:16,alignItems:"center",marginBottom:sr.logs?.length?8:0}}>
                              {sr.running
                                ? <span style={{fontSize:10,color:T.accent,fontWeight:600}}>⟳ Syncing emails…</span>
                                : sr.ok
                                ? <span style={{fontSize:10,color:T.green,fontWeight:600}}>✓ Sync complete</span>
                                : <span style={{fontSize:10,color:T.red,fontWeight:600}}>✗ Sync failed</span>}
                              {!sr.running && sr.imported!==undefined && <>
                                <span style={{fontSize:10,color:T.text1}}>Imported: <b style={{color:T.green}}>{sr.imported}</b></span>
                                <span style={{fontSize:10,color:T.text1}}>Skipped: <b>{sr.skipped||0}</b></span>
                                {sr.errors>0&&<span style={{fontSize:10,color:T.red}}>Errors: <b>{sr.errors}</b></span>}
                              </>}
                              {sr.imported>0 && <span style={{fontSize:9,color:T.text2,marginLeft:"auto"}}>Check Operator inbox now →</span>}
                            </div>
                            {/* Step-by-step log */}
                            {sr.logs?.length>0&&(
                              <div style={{background:"rgba(0,0,0,0.04)",borderRadius:4,padding:"8px 10px",maxHeight:200,overflowY:"auto",fontFamily:"'JetBrains Mono','Fira Code',monospace"}}>
                                {sr.logs.map((l,i)=>{
                                  const c = l.level==="error"?T.red : l.level==="success"?T.green : l.level==="warn"?T.yellow : T.text2;
                                  return <div key={i} style={{fontSize:10,color:c,lineHeight:1.7,paddingLeft:4}}>{l.msg}</div>;
                                })}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </Card>
      </Section>
      {showAdd&&<AddMailboxModal onClose={()=>setShowAdd(false)} onSave={()=>{load();setShowAdd(false);}} toast={toast} companies={companies} accounts={accounts}/>}
      {editMb&&<EditMailboxModal mb={editMb} onClose={()=>setEditMb(null)} onSave={()=>{load();setEditMb(null);}} toast={toast} accounts={accounts}/>}
      {oauthPicker && (
        <Modal title="Select OAuth App" onClose={() => setOauthPicker(null)} width={420}>
          <div style={{padding:20}}>
            <div style={{fontSize:11,color:T.text2,marginBottom:14}}>
              Multiple OAuth apps found. Select which one to use for <strong>{oauthPicker.mb.email_address}</strong>:
            </div>
            <div style={{display:"flex",flexDirection:"column",gap:8}}>
              {oauthPicker.apps.map(app => (
                <button key={app.id} onClick={() => {
                  setConn(oauthPicker.mb.id);
                  startOAuthFlow(oauthPicker.mb, app.id);
                  setOauthPicker(null);
                }}
                  style={{display:"flex",alignItems:"center",gap:10,padding:"12px 16px",
                    background:T.bg1,border:`1px solid ${T.border}`,borderRadius:6,cursor:"pointer",
                    fontFamily:"inherit",fontSize:12,color:T.text0,textAlign:"left",
                    transition:"all 0.15s"}}
                  onMouseOver={e=>e.currentTarget.style.borderColor=T.accent}
                  onMouseOut={e=>e.currentTarget.style.borderColor=T.border}>
                  <span style={{fontSize:16}}>🔑</span>
                  <div>
                    <div style={{fontWeight:600}}>{app.name}</div>
                    <div style={{fontSize:10,color:T.text3}}>{app.client_id?.slice(0,30)}...</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
          <div style={{padding:"12px 20px",borderTop:`1px solid ${T.border}`,display:"flex",justifyContent:"flex-end"}}>
            <Btn onClick={() => setOauthPicker(null)}>CANCEL</Btn>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── Slack Tab ─────────────────────────────────────────────────────────────────
export function SlackTab({ toast }) {
  const [cfg, setCfg]         = useState(null);
  const [token, setToken]     = useState("");
  const [tokenVis, setTokenVis] = useState(false);
  const [saving, setSaving]   = useState(false);
  const [testing, setTesting] = useState(false);
  const [companies, setCompanies] = useState([]);
  const [creatingCh, setCreatingCh] = useState(null);
  const [registry, setRegistry] = useState([]);
  const [newChName, setNewChName] = useState("");
  const [newChDesc, setNewChDesc] = useState("");
  const [addingCh, setAddingCh] = useState(false);

  const load = useCallback(async()=>{
    try{const d=await api("GET","/slack/");setCfg(d);}
    catch(e){toast(e.message,"error");}
    try{const r=await fetch("/api/companies/",{credentials:"include"});const d=await r.json();setCompanies(Array.isArray(d)?d:(d.results||[]));}catch(e){}
    try{const r=await api("GET","/slack/channels/registry/");setRegistry(Array.isArray(r)?r:[]);}catch(e){}
  },[]);
  useEffect(()=>{load();},[load]);

  async function addChannel() {
    if (!newChName.trim()) return;
    setAddingCh(true);
    try {
      const r = await api("POST", "/slack/channels/registry/", {
        name: newChName.trim(),
        description: newChDesc.trim(),
      });
      if (r.joined) toast(`Added #${r.name} and joined the channel ✓`, "success");
      else if (r.resolved) toast(`Added #${r.name} — ${r.join_error || "needs manual invite"}`, "info");
      else toast(`Added #${r.name} — bot can't see it yet. Invite the bot in Slack with /invite @<bot-name>`, "info");
      setNewChName(""); setNewChDesc("");
      load();
    } catch(e) { toast(e.message, "error"); }
    setAddingCh(false);
  }

  async function removeChannel(id) {
    try {
      await api("DELETE", `/slack/channels/registry/${id}/`);
      toast("Channel removed", "success");
      load();
    } catch(e) { toast(e.message, "error"); }
  }

  async function testRegistryChannel(id, name) {
    try {
      const r = await api("POST", `/slack/channels/registry/${id}/test/`);
      if (r.ok) toast(`✓ Test message sent to #${name}`, "success");
      else toast(r.error || "Test failed", "error");
    } catch(e) { toast(e.message, "error"); }
  }

  async function createCompanyChannels(co) {
    setCreatingCh(co.id);
    try {
      const r = await fetch(`/api/companies/${co.id}/create-slack-channels/`, {
        method:"POST", credentials:"include",
        headers:{"Content-Type":"application/json","X-CSRFToken":document.cookie.split(";").find(c=>c.trim().startsWith("csrftoken="))?.trim().split("=")[1]||""},
      });
      const d = await r.json();
      if (d.ok) { toast(`Channels created: #${d.load_ops}, #${d.paperwork_ops}`, "success"); load(); }
      else toast(d.error || "Failed", "error");
    } catch(e) { toast(e.message, "error"); }
    setCreatingCh(null);
  }

  async function saveToken() {
    if(!token.startsWith("xoxb-")){toast("Token must start with xoxb-","error");return;}
    setSaving(true);
    try{await api("POST","/slack/token/",{token});toast("Bot token saved","success");setToken("");load();}
    catch(e){toast(e.message,"error","Get the token from api.slack.com/apps → your app → OAuth & Permissions → Bot User OAuth Token");}
    setSaving(false);
  }
  async function testConn() {
    setTesting(true);
    try{const r=await api("POST","/slack/test/connection/");toast(`Connected: ${r.team} / @${r.bot}`,"success");}
    catch(e){toast(`Failed: ${e.message}`,"error","Make sure the Dispatch OS bot has been added to this channel in Slack: open channel → channel name → Integrations → Add an App");}
    setTesting(false);
  }

  return (
    <div style={{maxWidth:760}}>
      <Section title="Bot Token" subtitle="From Slack API dashboard: OAuth & Permissions > Bot User OAuth Token (starts with xoxb-)">
        <Card style={{padding:18}}>
          <div style={{display:"flex",gap:8,marginBottom:12}}>
            {cfg?.bot_token_set&&!token
              ?<div style={{flex:1,background:T.bg1,border:`1px solid ${T.border}`,borderRadius:3,padding:"7px 11px",fontSize:11,color:T.text2,fontFamily:"monospace"}}>{cfg.bot_token_preview}</div>
              :<Input value={token} onChange={e=>setToken(e.target.value)} placeholder="xoxb-your-slack-bot-token" type={tokenVis?"text":"password"} style={{flex:1}}/>}
            <Btn small onClick={()=>setTokenVis(p=>!p)}>{tokenVis?"HIDE":"SHOW"}</Btn>
            {token&&<Btn variant="primary" onClick={saveToken} disabled={saving}>{saving?"SAVING...":"SAVE TOKEN"}</Btn>}
            {cfg?.bot_token_set&&!token&&<Btn small onClick={()=>setToken(" ")}>REPLACE</Btn>}
          </div>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <Dot status={cfg?.bot_token_set?"active":"inactive"}/>
            <span style={{fontSize:9,color:cfg?.bot_token_set?T.green:T.text3}}>{cfg?.bot_token_set?"Token configured":"No token — Slack notifications disabled"}</span>
            {cfg?.bot_token_set&&<Btn small onClick={testConn} disabled={testing}>{testing?"testing...":"TEST CONNECTION"}</Btn>}
          </div>
        </Card>
      </Section>

      {/* Global alert channels removed — all routing is per-company.
          See "Available Channels" + "Company Channels" sections below. */}

      <Section title="Available Channels"
        subtitle="Register Slack channels manually. They'll appear in the dropdown when assigning channels to companies — even if the bot isn't a member yet.">
        <Card style={{padding:16}}>
          <div style={{display:"flex",gap:8,alignItems:"flex-end",marginBottom:14}}>
            <div style={{flex:1}}>
              <div style={{fontSize:9,color:T.text3,marginBottom:4,letterSpacing:"0.1em"}}>CHANNEL NAME</div>
              <Input value={newChName} onChange={e=>setNewChName(e.target.value)}
                placeholder="rw-load-ops" />
            </div>
            <div style={{flex:1}}>
              <div style={{fontSize:9,color:T.text3,marginBottom:4,letterSpacing:"0.1em"}}>DESCRIPTION (optional)</div>
              <Input value={newChDesc} onChange={e=>setNewChDesc(e.target.value)}
                placeholder="RW Freight load dispatch" />
            </div>
            <Btn variant="primary" onClick={addChannel} disabled={addingCh||!newChName.trim()}>
              {addingCh?"ADDING...":"+ ADD CHANNEL"}
            </Btn>
          </div>
          {registry.length===0 ? (
            <div style={{fontSize:10,color:T.text3,padding:"10px 4px"}}>
              No manually registered channels. Add one above, or rely on auto-discovery from channels the bot is already in.
            </div>
          ) : (
            <table style={{width:"100%",borderCollapse:"collapse"}}>
              <thead><tr style={{borderBottom:`1px solid ${T.border}`}}>
                {["Channel","Description","Status",""].map(h=>
                  <th key={h} style={{padding:"8px 10px",fontSize:9,color:T.text3,textAlign:"left",letterSpacing:"0.1em"}}>{h}</th>
                )}
              </tr></thead>
              <tbody>
                {registry.map(ch=>(
                  <tr key={ch.id} style={{borderBottom:`1px solid ${T.border}`}}>
                    <td style={{padding:"8px 10px",fontSize:11,color:T.text0,fontFamily:"monospace"}}>
                      #{ch.name} {ch.is_private && <span title="Private">🔒</span>}
                    </td>
                    <td style={{padding:"8px 10px",fontSize:10,color:T.text2}}>{ch.description || "—"}</td>
                    <td style={{padding:"8px 10px"}}>
                      {ch.channel_id
                        ? <Tag color={T.green}>✓ RESOLVED</Tag>
                        : <Tag color={T.yellow}>INVITE BOT</Tag>}
                    </td>
                    <td style={{padding:"8px 10px",textAlign:"right"}}>
                      <div style={{display:"flex",gap:4,justifyContent:"flex-end"}}>
                        <Btn small variant="success" onClick={()=>testRegistryChannel(ch.id, ch.name)}>TEST</Btn>
                        <Btn small variant="danger" onClick={()=>removeChannel(ch.id)}>REMOVE</Btn>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </Section>

      <Section title="Company Channels" subtitle="Per-company Slack channels for email alerts. Unanswered emails (10+ min) are routed to the matching channel.">
        <Card style={{padding:0}}>
          <table style={{width:"100%",borderCollapse:"collapse"}}>
            <thead><tr style={{borderBottom:`1px solid ${T.border}`,background:T.bg2}}>
              {["Company","🚛 Load Ops","📄 Paperwork Ops",""].map(h=>
                <th key={h} style={{padding:"10px 12px",fontSize:10,fontWeight:600,color:T.text3,textAlign:"left"}}>{h}</th>
              )}
            </tr></thead>
            <tbody>
              {companies.length===0&&<tr><td colSpan={4} style={{padding:20,textAlign:"center",fontSize:11,color:T.text3}}>No companies yet — add companies in the Companies tab first.</td></tr>}
              {companies.map(co=>{
                const hasLoads=Boolean(co.slack_channel_loads_id);
                const hasPaper=Boolean(co.slack_channel_paperwork_id);
                const hasAll=hasLoads&&hasPaper;
                const slug=co.name.toLowerCase().trim().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
                return (
                  <tr key={co.id} style={{borderBottom:`1px solid ${T.border}`}}>
                    <td style={{padding:"10px 12px"}}>
                      <div style={{display:"flex",alignItems:"center",gap:6}}>
                        <div style={{width:8,height:8,borderRadius:"50%",background:co.color||T.accent,flexShrink:0}}/>
                        <span style={{fontSize:11,color:T.text0,fontWeight:500}}>{co.name}</span>
                        <span style={{fontSize:9,color:T.text3}}>{co.mc_number}</span>
                      </div>
                    </td>
                    <td style={{padding:"10px 12px"}}>
                      {hasLoads
                        ?<span style={{fontSize:10,color:T.green,fontWeight:600}}>✓ #{co.slack_channel_loads_name||`${slug}-load-ops`}</span>
                        :<span style={{fontSize:10,color:T.text3,fontFamily:"monospace"}}>#{slug}-load-ops</span>}
                    </td>
                    <td style={{padding:"10px 12px"}}>
                      {hasPaper
                        ?<span style={{fontSize:10,color:T.green,fontWeight:600}}>✓ #{co.slack_channel_paperwork_name||`${slug}-paperwork-ops`}</span>
                        :<span style={{fontSize:10,color:T.text3,fontFamily:"monospace"}}>#{slug}-paperwork-ops</span>}
                    </td>
                    <td style={{padding:"10px 12px",textAlign:"right"}}>
                      {hasAll
                        ?<Tag color={T.green}>ACTIVE</Tag>
                        :<Btn small variant="primary" disabled={!cfg?.bot_token_set||creatingCh===co.id}
                          onClick={()=>createCompanyChannels(co)}>
                          {creatingCh===co.id?"CREATING...":"CREATE CHANNELS"}
                        </Btn>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
        {companies.length>0&&!cfg?.bot_token_set&&(
          <div style={{marginTop:10,background:T.yellowDim,border:`1px solid ${T.yellow}33`,borderRadius:4,padding:"8px 12px",fontSize:10,color:T.yellow}}>
            ⚠ Configure the bot token above before creating channels.
          </div>
        )}
      </Section>
    </div>
  );
}

// ── Modals ────────────────────────────────────────────────────────────────────
function AddSAModal({onClose,onSave,toast}) {
  const [form,setForm]=useState({name:"",domain:"",pubsub_topic:""});
  const [file,setFile]=useState(null);
  const [saving,setSaving]=useState(false);
  const fileRef=useRef();
  async function save(){
    if(!form.name||!form.domain){toast("Name and domain required","error");return;}
    setSaving(true);
    try{const fd=new FormData();fd.append("name",form.name);fd.append("domain",form.domain);fd.append("pubsub_topic",form.pubsub_topic);if(file)fd.append("json_file",file);await api("POST","/google/accounts/create/",fd,true);toast("Service account created","success");onSave();}
    catch(e){toast(e.message,"error");}
    setSaving(false);
  }
  return (
    <Modal title="Add Google Service Account" onClose={onClose}>
      <div style={{padding:20}}>
        <Field label="NAME"><Input value={form.name} onChange={e=>setForm(p=>({...p,name:e.target.value}))} placeholder="RW Freight Workspace"/></Field>
        <Field label="WORKSPACE DOMAIN" hint="e.g. rwfreight.com (NOT an email address, just the domain)"><Input value={form.domain} onChange={e=>setForm(p=>({...p,domain:e.target.value}))} placeholder="yourcompany.com"/></Field>
        <Field label="PUB/SUB TOPIC"><Input value={form.pubsub_topic} onChange={e=>setForm(p=>({...p,pubsub_topic:e.target.value}))} placeholder="projects/email-app-490123/topics/gmail-dispatch-push"/></Field>
        <Field label="SERVICE ACCOUNT JSON KEY" hint="Download from GCP > IAM > Service Accounts > Keys > Add Key > JSON">
          <div style={{display:"flex",gap:8,alignItems:"center"}}>
            <div style={{flex:1,background:T.bg1,border:`1px solid ${file?T.green:T.border}`,borderRadius:3,padding:"7px 11px",fontSize:10,color:file?T.green:T.text3}}>{file?`✓ ${file.name}`:"No file selected"}</div>
            <Btn small onClick={()=>fileRef.current.click()}>BROWSE</Btn>
            <input ref={fileRef} type="file" accept=".json" style={{display:"none"}} onChange={e=>setFile(e.target.files[0])}/>
          </div>
        </Field>
      </div>
      <div style={{padding:"12px 20px",borderTop:`1px solid ${T.border}`,display:"flex",gap:8}}>
        <Btn variant="primary" onClick={save} disabled={saving}>{saving?"CREATING...":"CREATE"}</Btn>
        <Btn onClick={onClose}>CANCEL</Btn>
      </div>
    </Modal>
  );
}

function UploadKeyModal({saId,onClose,onSave,toast}) {
  const [file,setFile]=useState(null);
  const [saving,setSaving]=useState(false);
  const fileRef=useRef();
  async function upload(){
    if(!file){toast("Select a JSON file","error");return;}
    setSaving(true);
    try{const fd=new FormData();fd.append("json_file",file);await api("POST",`/google/accounts/${saId}/upload/`,fd,true);toast("Key uploaded","success");onSave();}
    catch(e){toast(e.message,"error");}
    setSaving(false);
  }
  return (
    <Modal title="Upload Service Account JSON Key" onClose={onClose} width={480}>
      <div style={{padding:20}}>
        <div style={{background:T.bg0,borderRadius:3,padding:12,marginBottom:16,fontSize:9,color:T.text3,lineHeight:1.7}}>GCP Console → IAM & Admin → Service Accounts → your account → Keys tab → Add Key → Create new key → JSON</div>
        <Field label="JSON KEY FILE">
          <div style={{display:"flex",gap:8}}>
            <div style={{flex:1,background:T.bg1,border:`1px solid ${file?T.green:T.border}`,borderRadius:3,padding:"7px 11px",fontSize:10,color:file?T.green:T.text3}}>{file?`✓ ${file.name}`:"Select JSON key file..."}</div>
            <Btn small onClick={()=>fileRef.current.click()}>BROWSE</Btn>
            <input ref={fileRef} type="file" accept=".json" style={{display:"none"}} onChange={e=>setFile(e.target.files[0])}/>
          </div>
        </Field>
      </div>
      <div style={{padding:"12px 20px",borderTop:`1px solid ${T.border}`,display:"flex",gap:8}}>
        <Btn variant="primary" onClick={upload} disabled={saving||!file}>{saving?"UPLOADING...":"UPLOAD"}</Btn>
        <Btn onClick={onClose}>CANCEL</Btn>
      </div>
    </Modal>
  );
}

function EditMailboxModal({mb, onClose, onSave, toast, accounts}) {
  const [form, setForm] = useState({
    display_name:       mb.display_name || "",
    auth_method:        mb.auth_method || "oauth",
    service_account_id: mb.service_account_id || "",
    pubsub_topic:       mb.pubsub_topic || "",
  });
  const [saving, setSaving] = useState(false);
  const sel = (val, onChange, opts) => (
    <select value={val} onChange={onChange} style={{background:T.bg1,border:`1px solid ${T.border}`,color:T.text1,padding:"7px 11px",borderRadius:3,fontFamily:"inherit",fontSize:11,width:"100%"}}>
      {opts}
    </select>
  );
  async function save() {
    setSaving(true);
    try {
      await api("PATCH", `/mailboxes/${mb.id}/`, form);
      toast("Mailbox updated", "success");
      onSave();
    } catch(e) { toast(e.message, "error"); }
    setSaving(false);
  }
  return (
    <Modal title={`Edit — ${mb.email_address}`} onClose={onClose} width={480}>
      <div style={{padding:20}}>
        <Field label="DISPLAY NAME">
          <Input value={form.display_name} onChange={e=>setForm(p=>({...p,display_name:e.target.value}))} placeholder="e.g. Jovani Dispatch"/>
        </Field>
        <Field label="AUTH METHOD" hint="OAuth 2.0 = personal Gmail / any domain. Service Account = Google Workspace you own.">
          {sel(form.auth_method, e=>setForm(p=>({...p,auth_method:e.target.value})), [
            <option key="oauth" value="oauth">OAuth 2.0 — Personal Gmail / any domain</option>,
            <option key="sa" value="service_account">Service Account — Google Workspace</option>,
          ])}
        </Field>
        {form.auth_method === "service_account" && (
          <Field label="SERVICE ACCOUNT" hint="Must be uploaded in the Gmail → Service Accounts tab first.">
            {sel(form.service_account_id, e=>setForm(p=>({...p,service_account_id:e.target.value})), [
              <option key="" value="">— None —</option>,
              ...accounts.map(a=><option key={a.id} value={a.id}>{a.name} ({a.email})</option>),
            ])}
          </Field>
        )}
        <Field label="PUB/SUB TOPIC" hint="Gmail push notifications topic. Overrides SA and .env defaults.">
          <Input value={form.pubsub_topic} onChange={e=>setForm(p=>({...p,pubsub_topic:e.target.value}))} placeholder="projects/your-project/topics/gmail-dispatch-push"/>
        </Field>
        <div style={{display:"flex",justifyContent:"flex-end",gap:8,marginTop:8}}>
          <Btn onClick={onClose}>CANCEL</Btn>
          <Btn variant="primary" onClick={save} disabled={saving}>{saving?"SAVING…":"SAVE"}</Btn>
        </div>
      </div>
    </Modal>
  );
}

function AddMailboxModal({onClose,onSave,toast,companies,accounts}) {
  const [form,setForm]=useState({email_address:"",display_name:"",company_id:companies[0]?.id||"",service_account_id:"",auth_method:"oauth",purpose:"dispatch",pubsub_topic:""});
  const [saving,setSaving]=useState(false);
  const sel=(val,onChange,opts)=><select value={val} onChange={onChange} style={{background:T.bg1,border:`1px solid ${T.border}`,color:T.text1,padding:"7px 11px",borderRadius:3,fontFamily:"inherit",fontSize:11,width:"100%"}}>{opts}</select>;
  async function save(){
    if(!form.email_address||!form.company_id){toast("Email and company required","error");return;}
    setSaving(true);
    try{await api("POST","/mailboxes/create/",form);toast("Mailbox added","success");onSave();}
    catch(e){toast(e.message,"error");}
    setSaving(false);
  }
  return (
    <Modal title="Add Mailbox" onClose={onClose} width={500}>
      <div style={{padding:20}}>
        <Field label="EMAIL ADDRESS"><Input value={form.email_address} onChange={e=>setForm(p=>({...p,email_address:e.target.value}))} placeholder="rwfreightline@gmail.com"/></Field>
        <Field label="DISPLAY NAME"><Input value={form.display_name} onChange={e=>setForm(p=>({...p,display_name:e.target.value}))} placeholder="RW Freight Dispatch"/></Field>
        <Field label="COMPANY">{sel(form.company_id,e=>setForm(p=>({...p,company_id:e.target.value})),companies.map(c=><option key={c.id} value={c.id}>{c.mc_number} — {c.name}</option>))}</Field>
        <Field label="AUTH METHOD" hint="OAuth 2.0 = personal Gmail. Service Account = Workspace domain you own.">
          {sel(form.auth_method,e=>setForm(p=>({...p,auth_method:e.target.value})),[<option key="oauth" value="oauth">OAuth 2.0 — Personal Gmail / any domain</option>,<option key="sa" value="service_account">Service Account — Google Workspace</option>])}
        </Field>
        {form.auth_method==="service_account"&&(
          <Field label="SERVICE ACCOUNT">
            {sel(form.service_account_id,e=>setForm(p=>({
              ...p,
              service_account_id: e.target.value,
              auth_method: "service_account",
            })),[<option key="" value="">— None —</option>,...accounts.map(a=><option key={a.id} value={a.id}>{a.name} ({a.domain})</option>)])}
          </Field>
        )}
        <Field label="PURPOSE">{sel(form.purpose,e=>setForm(p=>({...p,purpose:e.target.value})),[["dispatch","Dispatch"],["safety","Safety"],["billing","Billing"],["general","General"]].map(([v,l])=><option key={v} value={v}>{l}</option>))}</Field>
        <Field label="PUB/SUB TOPIC" hint="Gmail push notifications topic. Overrides SA and .env defaults.">
          <Input value={form.pubsub_topic} onChange={e=>setForm(p=>({...p,pubsub_topic:e.target.value}))} placeholder="projects/your-project/topics/gmail-dispatch-push"/>
        </Field>
      </div>
      <div style={{padding:"12px 20px",borderTop:`1px solid ${T.border}`,display:"flex",gap:8}}>
        <Btn variant="primary" onClick={save} disabled={saving}>{saving?"ADDING...":"ADD MAILBOX"}</Btn>
        <Btn onClick={onClose}>CANCEL</Btn>
      </div>
    </Modal>
  );
}

// ── DIAGNOSTICS TAB ───────────────────────────────────────────────────────────
function DiagnosticsTab({ toast }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [slackTest, setSlackTest]   = useState(null);
  const [slackTesting, setSlackTesting] = useState(false);
  const [expanded, setExpanded] = useState({});

  async function runDiagnostics() {
    setLoading(true); setData(null);
    try {
      const r = await api("GET", "/diagnostics/");
      setData(r);
      const errors = r.summary.error;
      const warns  = r.summary.warn;
      if (errors > 0) toast(`${errors} error(s) found — see details below`, "error");
      else if (warns > 0) toast(`${warns} warning(s) — some features may not work`, "warn");
      else toast("All systems operational ✓", "success");
    } catch(e) { toast(e.message, "error"); }
    setLoading(false);
  }

  async function testSlack() {
    setSlackTesting(true); setSlackTest(null);
    try {
      const r = await api("POST", "/slack/test/all/");
      setSlackTest(r);
      const failed = Object.values(r.channels||{}).filter(c=>!c.ok).length;
      if (failed) toast(`${failed} Slack channel(s) failed — see details`, "error");
      else toast("All Slack channels working ✓", "success");
    } catch(e) { toast(e.message, "error"); }
    setSlackTesting(false);
  }

  useEffect(() => { runDiagnostics(); }, []);

  const levelStyle = (l) => ({
    ok:    { icon:"✓", color: T.green,  bg: T.greenDim },
    warn:  { icon:"⚠", color: T.yellow, bg: T.yellowDim },
    error: { icon:"✗", color: T.red,    bg: T.redDim },
    info:  { icon:"ℹ", color: T.accent, bg: T.accentDim },
  }[l] || { icon:"•", color: T.text2, bg: T.bg2 });

  const overallColor = data ? (data.overall==="ok"?T.green:data.overall==="warn"?T.yellow:T.red) : T.text3;

  return (
    <div style={{maxWidth:860}}>
      {/* Header */}
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:24}}>
        <div>
          <div style={{fontSize:18,fontWeight:700,color:T.text0}}>Integration Diagnostics</div>
          <div style={{fontSize:12,color:T.text3,marginTop:4}}>Tests all connections and shows exactly how to fix any problems</div>
        </div>
        <div style={{display:"flex",gap:8}}>
          <Btn onClick={testSlack} disabled={slackTesting} variant="ghost">
            {slackTesting ? "Testing Slack…" : "💬 Test All Slack Channels"}
          </Btn>
          <Btn onClick={runDiagnostics} disabled={loading} variant="primary">
            {loading ? "Running checks…" : "🔄 Run Diagnostics"}
          </Btn>
        </div>
      </div>

      {/* Overall status banner */}
      {data && (
        <div style={{background: data.overall==="ok"?T.greenDim:data.overall==="warn"?T.yellowDim:T.redDim,
          border:`1px solid ${overallColor}44`,borderRadius:8,padding:"14px 18px",marginBottom:20,
          display:"flex",alignItems:"center",gap:16}}>
          <span style={{fontSize:28}}>
            {data.overall==="ok"?"✅":data.overall==="warn"?"⚠️":"❌"}
          </span>
          <div style={{flex:1}}>
            <div style={{fontSize:14,fontWeight:700,color:overallColor}}>
              {data.overall==="ok" ? "All systems operational"
                : data.overall==="warn" ? "Some issues need attention"
                : "Critical issues found — fix before using the system"}
            </div>
            <div style={{fontSize:11,color:T.text2,marginTop:3}}>
              {data.summary.ok} passed · {data.summary.warn} warning{data.summary.warn!==1?"s":""} · {data.summary.error} error{data.summary.error!==1?"s":""}
            </div>
          </div>
          <div style={{fontSize:10,color:T.text3}}>
            Last checked: {new Date().toLocaleTimeString()}
          </div>
        </div>
      )}

      {loading && (
        <div style={{textAlign:"center",padding:"40px 0",color:T.text3,fontSize:13}}>
          🔍 Checking all connections…
        </div>
      )}

      {/* Sections */}
      {data?.sections.map(sec => {
        const isOpen = expanded[sec.title] !== false; // default open
        const statusColor = sec.status==="ok"?T.green:sec.status==="warn"?T.yellow:T.red;
        const statusBg    = sec.status==="ok"?T.greenDim:sec.status==="warn"?T.yellowDim:T.redDim;
        return (
          <Card key={sec.title} style={{marginBottom:12,overflow:"hidden"}}>
            {/* Section header */}
            <div onClick={()=>setExpanded(p=>({...p,[sec.title]:!isOpen}))}
              style={{padding:"14px 18px",display:"flex",alignItems:"center",gap:12,cursor:"pointer",
                background: sec.status!=="ok" ? statusBg+"88" : "#fff",
                borderBottom: isOpen ? `1px solid ${T.border}` : "none"}}>
              <span style={{fontSize:18}}>{sec.icon}</span>
              <span style={{fontSize:13,fontWeight:600,color:T.text0,flex:1}}>{sec.title}</span>
              <div style={{display:"flex",gap:8,alignItems:"center"}}>
                {sec.error>0  && <Tag color={T.red}>{sec.error} Error{sec.error!==1?"s":""}</Tag>}
                {sec.warn>0   && <Tag color={T.yellow}>{sec.warn} Warning{sec.warn!==1?"s":""}</Tag>}
                {sec.ok>0     && <Tag color={T.green}>{sec.ok} OK</Tag>}
              </div>
              <span style={{fontSize:12,color:T.text3,marginLeft:4}}>{isOpen?"▲":"▼"}</span>
            </div>

            {/* Issues list */}
            {isOpen && (
              <div style={{padding:"8px 0"}}>
                {sec.issues.map((issue, i) => {
                  const s = levelStyle(issue.level);
                  return (
                    <div key={i} style={{padding:"10px 18px",borderBottom:i<sec.issues.length-1?`1px solid ${T.border}`:"none",
                      background: issue.level==="error"?T.redDim+"66":issue.level==="warn"?T.yellowDim+"66":"transparent"}}>
                      <div style={{display:"flex",gap:10,alignItems:"flex-start"}}>
                        <span style={{fontSize:14,flexShrink:0,width:20,textAlign:"center",paddingTop:1,color:s.color}}>{s.icon}</span>
                        <div style={{flex:1}}>
                          <div style={{fontSize:12,color: issue.level==="ok"?T.text1:issue.level==="error"?T.red:issue.level==="warn"?T.yellow:T.text1,lineHeight:1.5,fontWeight:issue.level!=="ok"?500:400}}>
                            {issue.msg}
                          </div>
                          {issue.fix && (
                            <div style={{marginTop:6,padding:"8px 12px",background:"#fff",border:`1px solid ${T.border}`,
                              borderLeft:`3px solid ${s.color}`,borderRadius:4}}>
                              <div style={{fontSize:9,fontWeight:700,color:T.text3,letterSpacing:"0.08em",marginBottom:3}}>HOW TO FIX</div>
                              <div style={{fontSize:11,color:T.text1,lineHeight:1.6}}>{issue.fix}</div>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        );
      })}

      {/* Slack channel test results */}
      {slackTest && (
        <Card style={{marginTop:20}}>
          <div style={{padding:"14px 18px",borderBottom:`1px solid ${T.border}`,fontWeight:600,fontSize:13,color:T.text0,display:"flex",gap:10,alignItems:"center"}}>
            <span>💬</span> Slack Channel Test Results
          </div>
          <div style={{padding:"8px 0"}}>
            {Object.entries(slackTest.channels||{}).map(([key,res],i,arr)=>{
              const labels = {safety:"Safety Alerts",approvals:"Approvals",compliance:"Compliance Alerts",system:"System Alerts"};
              return (
                <div key={key} style={{padding:"10px 18px",borderBottom:i<arr.length-1?`1px solid ${T.border}`:"none",
                  background:res.ok?"transparent":T.redDim+"44"}}>
                  <div style={{display:"flex",gap:10,alignItems:"flex-start"}}>
                    <span style={{fontSize:14,color:res.ok?T.green:T.red,width:20,textAlign:"center"}}>{res.ok?"✓":"✗"}</span>
                    <div style={{flex:1}}>
                      <div style={{fontSize:12,fontWeight:500,color:res.ok?T.green:T.red}}>
                        #{labels[key]} {res.ok ? `— message sent to ${res.channel}` : `— ${res.error}`}
                      </div>
                      {res.fix && (
                        <div style={{marginTop:6,padding:"7px 10px",background:"#fff",border:`1px solid ${T.border}`,
                          borderLeft:`3px solid ${T.red}`,borderRadius:4,fontSize:11,color:T.text1}}>{res.fix}</div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
            {slackTest.error && (
              <div style={{padding:"12px 18px"}}>
                <div style={{fontSize:12,color:T.red,marginBottom:6}}>{slackTest.error}</div>
                {slackTest.fix && <div style={{padding:"8px 12px",background:"#fff",border:`1px solid ${T.border}`,borderLeft:`3px solid ${T.red}`,borderRadius:4,fontSize:11,color:T.text1}}>{slackTest.fix}</div>}
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Quick reference */}
      {data && data.summary.error===0 && data.summary.warn===0 && (
        <div style={{marginTop:20,padding:"16px 20px",background:T.greenDim,border:`1px solid ${T.green}33`,borderRadius:8}}>
          <div style={{fontSize:13,fontWeight:600,color:T.green,marginBottom:8}}>✅ Everything is configured correctly</div>
          <div style={{fontSize:11,color:T.text2,lineHeight:1.8}}>
            • Gmail mailboxes are connected and watches are active — new emails will arrive automatically<br/>
            • Go to Admin → Credentials → Mailboxes → click <strong>SYNC EMAILS NOW</strong> to pull existing emails<br/>
            • Emails appear in the Operator inbox within 15–30 seconds after sync<br/>
            • Slack alerts will fire for HIGH priority and SAFETY/AUDIT emails
          </div>
        </div>
      )}
    </div>
  );
}
