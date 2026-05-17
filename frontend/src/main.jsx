import React from "react";
import ReactDOM from "react-dom/client";
import DispatchOS from "./DispatchOS.jsx";

// Simple error boundary wrapper
class AppErrorBoundary extends React.Component {
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
          <div style={{fontSize:16,color:"#ef4444",fontWeight:600,marginBottom:12}}>Dispatch OS encountered an error</div>
          <div style={{fontSize:11,color:"#b8c8d8",lineHeight:1.7,marginBottom:20,wordBreak:"break-word"}}>{msg}</div>
          <div style={{background:"#05080d",borderRadius:4,padding:"12px 16px",marginBottom:20}}>
            <div style={{fontSize:9,color:"#3a5068",marginBottom:8,letterSpacing:"0.1em"}}>TROUBLESHOOTING</div>
            {[
              "Backend not running — run: docker compose up -d",
              "Session expired — try refreshing the page",
              "API error — check logs: docker compose logs api",
            ].map(s=>(
              <div key={s} style={{fontSize:10,color:"#7a90a8",marginBottom:5}}>• {s}</div>
            ))}
          </div>
          <button onClick={()=>window.location.reload()} style={{background:"#2d7dd2",border:"none",color:"#fff",padding:"8px 18px",borderRadius:4,cursor:"pointer",fontFamily:"monospace",fontSize:10,marginRight:10}}>
            RELOAD PAGE
          </button>
          <button onClick={()=>this.setState({error:null})} style={{background:"transparent",border:"1px solid #2d7dd244",color:"#7a90a8",padding:"8px 18px",borderRadius:4,cursor:"pointer",fontFamily:"monospace",fontSize:10}}>
            TRY AGAIN
          </button>
        </div>
      </div>
    );
  }
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <AppErrorBoundary>
    <DispatchOS />
  </AppErrorBoundary>
);
