"""
AutoOps AI — Redesigned Dashboard v2
======================================
Dark industrial terminal aesthetic. Three-column live layout.
API key input panel built in — keys injected at runtime.

Start:
    Terminal 1:  cd Backend && uvicorn app.main:app --reload --port 8000
    Terminal 2:  streamlit run dashboard.py
"""

import json
import time
import requests
import streamlit as st

BACKEND           = "http://localhost:8000"
STREAM_URL        = f"{BACKEND}/workflow/stream"
MEMORY_URL        = f"{BACKEND}/workflow/memory/stats"
MEMORY_SEARCH_URL = f"{BACKEND}/workflow/memory/search"

DEMO_TASKS = {
    "💳  Payment Failure": {
        "task": "Customer payment failed but money was deducted. Customer ID: CUST-00123, amount Rs.2999.",
        "context": {"customer_id": "CUST-00123", "amount": 2999, "currency": "INR"},
        "tag": "PAYMENT",
    },
    "📄  Invoice Generation": {
        "task": "Generate invoice for order ORD-5487 and email to customer.",
        "context": {"order_id": "ORD-5487"},
        "tag": "INVOICE",
    },
    "👥  Resume Screening": {
        "task": "Screen 15 resumes for Senior Python Developer. Need 3+ yrs Python and FastAPI.",
        "context": {"job_title": "Senior Python Developer", "min_experience": 3},
        "tag": "HR",
    },
    "📊  Sales Report": {
        "task": "Generate weekly sales report for Q1 2026 and notify management.",
        "context": {"period": "weekly", "quarter": "Q1-2026"},
        "tag": "REPORT",
    },
    "🚨  Delivery Investigation": {
        "task": "Customer says order ORD-5487 was never delivered but system shows delivered.",
        "context": {"order_id": "ORD-5487"},
        "tag": "DELIVERY",
    },
    "🔄  Duplicate Charge": {
        "task": "Customer CUST-00456 was charged twice for Rs.1499 on the same transaction.",
        "context": {"customer_id": "CUST-00456", "amount": 1499},
        "tag": "BILLING",
    },
    "🛑  Server Incident": {
        "task": "URGENT: Production API is down. 500 errors since 10 minutes. P1 incident.",
        "context": {"priority": "high", "service": "api"},
        "tag": "INCIDENT",
    },
}

AGENT_STEPS = ["THINK", "PLAN", "EXECUTE", "REVIEW", "UPDATE"]
STEP_ICONS  = {"THINK": "🧠", "PLAN": "📋", "EXECUTE": "⚙️", "REVIEW": "🔍", "UPDATE": "🔄"}
LOG_COLORS  = {
    "think": "#B57BFF", "plan": "#00C987", "execute": "#4DA6FF",
    "review": "#FFB347", "update": "#FF6B6B", "memory": "#C77DFF",
    "done": "#00A855", "error": "#FF4444", "gray": "#6E7A8A", "system": "#0090CC",
}
TAG_COLORS = {
    "PAYMENT": "#4DA6FF", "INVOICE": "#00C987", "HR": "#B57BFF",
    "REPORT": "#FFB347", "DELIVERY": "#FF6B6B", "BILLING": "#FB923C", "INCIDENT": "#FF4444",
}
TOOL_COLORS = {
    "payment_tool": "#4DA6FF", "database_tool": "#00C987",
    "notification_tool": "#FFB347", "ticket_tool": "#FF6B6B",
    "report_tool": "#B57BFF", "invoice_tool": "#00C987",
    "knowledge_tool": "#C77DFF", "resume_tool": "#FB923C", "delivery_tool": "#FF6B6B",
}

# ── Page ─────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="AutoOps AI", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=DM+Sans:wght@300;400;500;600&display=swap');
*,*::before,*::after{box-sizing:border-box}
html,body,[data-testid="stAppViewContainer"]{background:#f8f9fa!important;color:#212529;font-family:'DM Sans',sans-serif}
[data-testid="stHeader"]{display:none!important}
[data-testid="stSidebar"]{display:none!important}
#MainMenu,footer,header{visibility:hidden}
.block-container{padding:1.2rem 1.6rem 2rem!important;max-width:100%!important}
[data-testid="stAppViewContainer"]::before{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:linear-gradient(rgba(0,123,255,.02)1px,transparent 1px),linear-gradient(90deg,rgba(0,123,255,.02)1px,transparent 1px);
  background-size:48px 48px}
[data-testid="stAppViewContainer"]::after{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,0,0,.01)3px,rgba(0,0,0,.01)4px)}
[data-testid="column"]{position:relative;z-index:1}

/* Cards */
.ao-card{background:#ffffff;border:1px solid #dee2e6;border-radius:12px;
  padding:16px 18px;margin-bottom:14px;position:relative;overflow:hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1)}
.ao-card::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,#007bff,transparent)}

/* Section labels */
.ao-lbl{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600;
  letter-spacing:2px;text-transform:uppercase;color:#6c757d;
  margin-bottom:10px;padding-bottom:7px;border-bottom:1px solid #e9ecef}

/* Header */
.ao-hdr{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.ao-logo{width:36px;height:36px;background:linear-gradient(135deg,#28a745,#007bff);
  border-radius:8px;display:flex;align-items:center;justify-content:center;
  font-size:18px;font-weight:700;color:#ffffff;flex-shrink:0}
.ao-title{font-family:'IBM Plex Mono',monospace;font-size:1.35rem;font-weight:600;
  color:#495057;letter-spacing:-.5px}
.ao-title span{color:#007bff}
.ao-sub{font-size:.68rem;color:#6c757d;letter-spacing:2px;text-transform:uppercase}
.ao-badge{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600;
  letter-spacing:1.5px;text-transform:uppercase;padding:4px 10px;border-radius:20px;
  border:1px solid;white-space:nowrap}

/* Agent strip */
.ag-strip{display:flex;align-items:center;gap:0;padding:6px 0;margin-bottom:2px}
.ag-node{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 2px}
.ag-circle{width:40px;height:40px;border-radius:50%;border:2px solid #dee2e6;
  background:#f8f9fa;display:flex;align-items:center;justify-content:center;
  font-size:14px;transition:all .3s;position:relative;z-index:1}
.ag-lbl{font-family:'IBM Plex Mono',monospace;font-size:8.5px;font-weight:600;
  letter-spacing:1.5px;color:#6c757d;text-transform:uppercase;transition:color .3s}
.ag-conn{flex:0 0 16px;height:1px;background:#dee2e6;margin-top:-20px}
.ag-node.active .ag-circle{border-color:#007bff;background:#e7f3ff;
  box-shadow:0 0 14px rgba(0,123,255,.4),0 0 35px rgba(0,123,255,.1);
  animation:pulse-nd 1.3s ease-in-out infinite}
.ag-node.done .ag-circle{border-color:#28a745;background:#d4edda}
.ag-node.failed .ag-circle{border-color:#dc3545;background:#f8d7da;
  box-shadow:0 0 10px rgba(220,53,69,.2)}
.ag-node.active .ag-lbl{color:#007bff}
.ag-node.done .ag-lbl{color:#28a745}
.ag-node.failed .ag-lbl{color:#dc3545}
.ag-node.active .ag-conn{background:linear-gradient(90deg,#007bff,rgba(0,123,255,.1))}

/* Loop badge */
.loop-ring{display:inline-flex;align-items:center;gap:7px;background:#f8f9fa;
  border:1px solid #007bff;border-radius:20px;padding:4px 13px;
  font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:#007bff}
.loop-dot{width:6px;height:6px;border-radius:50%;background:#007bff;
  animation:pulse-dot 1.4s ease-in-out infinite}

/* Terminal */
.terminal{background:#ffffff;border:1px solid #dee2e6;border-radius:10px;
  padding:12px 14px;min-height:340px;max-height:420px;overflow-y:auto;
  font-family:'IBM Plex Mono',monospace;font-size:11px;line-height:1.8;position:relative}
.terminal::before{content:'▌ AGENT LOG  ●  LIVE';display:block;font-size:8.5px;
  letter-spacing:2px;font-weight:600;color:#007bff;
  margin-bottom:9px;padding-bottom:7px;border-bottom:1px solid #e9ecef}
.tl{display:flex;gap:7px;align-items:baseline;padding:.5px 0}
.tl-ts{color:#6c757d;font-size:9.5px;flex-shrink:0}
.tl-badge{font-size:8.5px;font-weight:700;letter-spacing:1px;padding:1px 5px;
  border-radius:3px;flex-shrink:0;min-width:48px;text-align:center}
.tl-msg{flex:1;overflow-wrap:anywhere}
.tl-indent{padding-left:10px;opacity:.75}
.b-think{background:#e2e3ff;color:#6f42c1}
.b-plan{background:#d1ecf1;color:#0c5460}
.b-execute{background:#d4edda;color:#155724}
.b-review{background:#fff3cd;color:#856404}
.b-update{background:#f8d7da;color:#721c24}
.b-memory{background:#e2e3ff;color:#6f42c1}
.b-done{background:#d4edda;color:#155724}
.b-error{background:#f8d7da;color:#721c24}
.b-sys{background:#f8f9fa;color:#495057}

/* Result */
.res-panel{border-radius:10px;padding:13px 15px;margin-top:10px;border:1px solid}
.res-pass{background:#d4edda;border-color:#28a745}
.res-fail{background:#f8d7da;border-color:#dc3545}
.res-hdr{font-family:'IBM Plex Mono',monospace;font-size:12.5px;font-weight:600;margin-bottom:5px}
.res-pass .res-hdr{color:#155724}
.res-fail .res-hdr{color:#721c24}
.res-meta{font-size:10.5px;color:#6c757d;line-height:1.6}
.res-sum{font-size:11.5px;color:#495057;margin-top:4px;line-height:1.5}

/* Plan step */
.ps-row{display:flex;align-items:center;gap:8px;background:#f8f9fa;
  border-radius:6px;padding:6px 10px;margin-bottom:4px}
.ps-num{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:700;flex-shrink:0;width:18px}
.ps-tool{font-family:'IBM Plex Mono',monospace;font-size:9.5px;flex-shrink:0;opacity:.7}
.ps-desc{font-size:10.5px;color:#6c757d;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}

/* Memory */
.mem-entry{background:#f8f9fa;border-left:2px solid #6f42c1;
  border-radius:0 6px 6px 0;padding:6px 10px;margin-bottom:5px;font-size:10.5px;color:#495057;line-height:1.45}
.mem-cat{font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:1px;
  text-transform:uppercase;color:#6f42c1;margin-bottom:2px}

/* Stats */
.stats-row{display:flex;gap:8px;margin-bottom:12px}
.stat-box{flex:1;background:#f8f9fa;border:1px solid #dee2e6;
  border-radius:8px;padding:9px 10px;text-align:center}
.stat-val{font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:600;color:#28a745;line-height:1}
.stat-lbl{font-size:9.5px;color:#6c757d;letter-spacing:1px;text-transform:uppercase;margin-top:2px}

/* Key panel */
.key-bar{background:#f8f9fa;border:1px solid #007bff;
  border-radius:10px;padding:13px 15px;margin-bottom:12px}
.key-status{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#6c757d;
  padding-top:8px;margin-top:6px;border-top:1px solid #e9ecef}

/* Streamlit overrides */
.stTextArea textarea{background:#ffffff!important;
  border:1px solid #dee2e6!important;border-radius:8px!important;
  color:#495057!important;font-family:'IBM Plex Mono',monospace!important;font-size:11.5px!important}
.stTextArea textarea:focus{border-color:#007bff!important;
  box-shadow:0 0 0 2px rgba(0,123,255,.25)!important}
.stTextInput input{background:#ffffff!important;
  border:1px solid #dee2e6!important;border-radius:8px!important;
  color:#495057!important;font-family:'IBM Plex Mono',monospace!important;font-size:11.5px!important}
.stTextInput input:focus{border-color:#007bff!important}
.stSelectbox>div>div{background:#ffffff!important;
  border:1px solid #dee2e6!important;color:#495057!important}
div[data-testid="stButton"] button{font-family:'IBM Plex Mono',monospace!important;
  font-weight:600!important;letter-spacing:1px!important;border-radius:8px!important;transition:all .2s!important}
div[data-testid="stButton"] button[kind="primary"]{
  background:linear-gradient(135deg,#28a745,#007bff)!important;border:none!important;
  color:#ffffff!important;font-size:11.5px!important}
div[data-testid="stButton"] button[kind="primary"]:hover{
  filter:brightness(1.1);box-shadow:0 0 18px rgba(0,123,255,.25)!important}
div[data-testid="stButton"] button:not([kind="primary"]){
  background:#f8f9fa!important;border:1px solid #dee2e6!important;
  color:#495057!important;font-size:11px!important}
label,.stLabel{color:#6c757d!important;font-size:10.5px!important}
p{color:#495057}

@keyframes pulse-nd{0%,100%{box-shadow:0 0 12px rgba(0,123,255,.35),0 0 30px rgba(0,123,255,.09)}
  50%{box-shadow:0 0 20px rgba(0,123,255,.55),0 0 50px rgba(0,123,255,.17)}}
@keyframes pulse-dot{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.65)}}
@keyframes sl-in{from{opacity:0;transform:translateX(-5px)}to{opacity:1;transform:translateX(0)}}
.tl{animation:sl-in .12s ease forwards}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in {
    "logs": [], "step_status": {s: "pending" for s in AGENT_STEPS},
    "result": None, "loop_num": 0, "running": False,
    "runs_total": 0, "runs_passed": 0,
    "selected_task": list(DEMO_TASKS.keys())[0],
    "rt_anthropic": "", "rt_groq": "", "rt_hf": "",
    "current_plan": {},
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def reset_run():
    st.session_state.logs = []
    st.session_state.step_status = {s: "pending" for s in AGENT_STEPS}
    st.session_state.result = None
    st.session_state.loop_num = 0
    st.session_state.current_plan = {}

def set_step(name, status):
    if name in st.session_state.step_status:
        st.session_state.step_status[name] = status

def add_log(msg, cat="gray", indent=False):
    st.session_state.logs.append((time.strftime("%H:%M:%S"), msg, cat, indent))

def _provider():
    if st.session_state.rt_anthropic.strip(): return "ANTHROPIC", "#A78BFA"
    if st.session_state.rt_groq.strip():      return "GROQ", "#FB923C"
    if st.session_state.rt_hf.strip():        return "HUGGINGFACE", "#FCD34D"
    return "MOCK", "#4A6880"

def _backend_online():
    try: return requests.get(f"{BACKEND}/health", timeout=2).status_code == 200
    except: return False

def _agent_strip_html():
    html = '<div class="ag-strip">'
    for i, s in enumerate(AGENT_STEPS):
        st2 = st.session_state.step_status.get(s, "pending")
        icon = {"done": "✓", "failed": "✗"}.get(st2, STEP_ICONS[s])
        html += (f'<div class="ag-node {st2}">'
                 f'<div class="ag-circle">{icon}</div>'
                 f'<div class="ag-lbl">{s}</div></div>')
        if i < len(AGENT_STEPS) - 1:
            html += '<div class="ag-conn"></div>'
    html += '</div>'
    return html

def _terminal_html():
    if not st.session_state.logs:
        return ('<div class="terminal" style="display:flex;align-items:center;'
                'justify-content:center;color:#1A2E3A;">'
                '// awaiting workflow execution…</div>')
    badge_map = {"think":"THINK","plan":"PLAN","execute":"EXEC","review":"REVIEW",
                 "update":"UPDATE","memory":"MEM","done":"DONE","error":"ERR","gray":"SYS","system":"SYS"}
    lines = []
    for ts, msg, cat, indent in st.session_state.logs[-90:]:
        bc  = f"b-{cat}" if cat in ("think","plan","execute","review","update","memory","done","error") else "b-sys"
        bt  = badge_map.get(cat, "SYS")
        col = LOG_COLORS.get(cat, "#6E7A8A")
        ic  = "tl-indent" if indent else ""
        lines.append(
            f'<div class="tl"><span class="tl-ts">{ts}</span>'
            f'<span class="tl-badge {bc}">{bt}</span>'
            f'<span class="tl-msg {ic}" style="color:{col}">{msg}</span></div>'
        )
    return f'<div class="terminal">{"".join(lines)}</div>'

def _plan_html():
    steps = st.session_state.current_plan.get("steps", [])
    if not steps:
        return ('<div style="color:#1A2E3A;font-size:10.5px;'
                'font-family:IBM Plex Mono,monospace;">// plan will appear after PLAN phase</div>')
    html = ""
    for ps in steps:
        tc   = TOOL_COLORS.get(ps.get("tool",""), "#2A4055")
        desc = ps.get("description","")[:52]
        deps = ps.get("depends_on",[])
        dep_txt = f" ← [{','.join(map(str,deps))}]" if deps else ""
        html += (f'<div class="ps-row">'
                 f'<span class="ps-num" style="color:{tc}">[{ps.get("step_number")}]</span>'
                 f'<span class="ps-tool" style="color:{tc}">{ps.get("tool","")}.{ps.get("action","")}</span>'
                 f'<span class="ps-desc">{desc}{dep_txt}</span>'
                 f'</div>')
    return html

def _memory_html():
    try:
        data  = requests.get(f"{MEMORY_SEARCH_URL}?q=&top_k=6", timeout=2).json()
        items = data.get("results", [])
        if not items:
            return '<div style="color:#1A2E3A;font-size:10.5px;">// no memories yet</div>'
        html = ""
        for item in items[:5]:
            doc = item.get("document","")
            cat = doc.split("]")[0].replace("[","").strip() if doc.startswith("[") else "general"
            txt = doc[doc.find("]")+1:].strip()[:95] if "]" in doc else doc[:95]
            html += (f'<div class="mem-entry"><div class="mem-cat">{cat}</div>{txt}…</div>')
        return html
    except:
        return '<div style="color:#1A2E3A;font-size:10.5px;">// backend offline</div>'

# ── HEADER ────────────────────────────────────────────────────────────────────
online = _backend_online()
prov, pcol = _provider()
st.markdown(f"""
<div class="ao-hdr">
  <div class="ao-logo">⚡</div>
  <div>
    <div class="ao-title">Auto<span>Ops</span> AI</div>
    <div class="ao-sub">Autonomous Operations Manager · Think · Plan · Execute · Review · Update</div>
  </div>
  <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
    <div class="ao-badge" style="color:{pcol};border-color:{pcol}40;background:{pcol}10">LLM: {prov}</div>
    <div class="ao-badge" style="color:{'#00E5A0' if online else '#FF6B6B'};
      border-color:{'rgba(0,229,160,.3)' if online else 'rgba(255,107,107,.3)'};
      background:{'rgba(0,229,160,.07)' if online else 'rgba(255,107,107,.07)'}">
      {'● ONLINE' if online else '○ OFFLINE'}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── THREE COLUMNS ─────────────────────────────────────────────────────────────
col_l, col_m, col_r = st.columns([1.1, 1.65, 1.25], gap="medium")

# ── LEFT ─────────────────────────────────────────────────────────────────────
with col_l:
    # API Keys
    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">🔑 API Keys — Runtime</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:10px;color:#2A4055;margin-bottom:8px;line-height:1.55">'
                'All optional · provide any one to enable real LLM.<br>'
                'Anthropic → Groq → HuggingFace → Mock (fallback)</div>', unsafe_allow_html=True)

    ant = st.text_input("Anthropic  (sk-ant-…)", value=st.session_state.rt_anthropic,
                         type="password", placeholder="sk-ant-api03-…", key="in_ant")
    st.session_state.rt_anthropic = ant

    groq = st.text_input("Groq  (gsk_… · free)", value=st.session_state.rt_groq,
                          type="password", placeholder="gsk_…", key="in_groq")
    st.session_state.rt_groq = groq

    hf = st.text_input("HuggingFace  (hf_… · free)", value=st.session_state.rt_hf,
                        type="password", placeholder="hf_…", key="in_hf")
    st.session_state.rt_hf = hf

    prov2, pcol2 = _provider()
    st.markdown(f'<div class="key-status">Active: <span style="color:{pcol2};font-weight:600">'
                f'{prov2}</span></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Task selector
    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">📂 Workflow</div>', unsafe_allow_html=True)

    task_keys = list(DEMO_TASKS.keys())
    idx = task_keys.index(st.session_state.selected_task) if st.session_state.selected_task in task_keys else 0
    sel = st.selectbox("Select workflow", task_keys, index=idx, label_visibility="collapsed")
    st.session_state.selected_task = sel
    demo = DEMO_TASKS[sel]
    tc2  = TAG_COLORS.get(demo["tag"], "#00E5A0")

    st.markdown(
        f'<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);'
        f'border-radius:7px;padding:9px 11px;margin:6px 0">'
        f'<span style="font-family:IBM Plex Mono,monospace;font-size:8.5px;font-weight:700;'
        f'letter-spacing:1.5px;color:{tc2};opacity:.85">{demo["tag"]}</span>'
        f'<div style="font-size:11px;color:#5A7A8A;margin-top:4px;line-height:1.45">'
        f'{demo["task"][:95]}{"…" if len(demo["task"])>95 else ""}</div></div>',
        unsafe_allow_html=True
    )

    task_text = st.text_area("Edit task", value=demo["task"], height=76,
                              key=f"txt_{sel}", label_visibility="visible")
    st.markdown('</div>', unsafe_allow_html=True)

    # Stats
    t = st.session_state.runs_total
    p = st.session_state.runs_passed
    r_pct = int(p/t*100) if t else 0
    st.markdown(
        f'<div class="stats-row">'
        f'<div class="stat-box"><div class="stat-val">{t}</div><div class="stat-lbl">Runs</div></div>'
        f'<div class="stat-box"><div class="stat-val">{p}</div><div class="stat-lbl">Passed</div></div>'
        f'<div class="stat-box"><div class="stat-val">{r_pct}%</div><div class="stat-lbl">Rate</div></div>'
        f'</div>',
        unsafe_allow_html=True
    )

    bc1, bc2 = st.columns([3, 1])
    with bc1:
        run_btn = st.button("▶  RUN WORKFLOW", use_container_width=True, type="primary",
                             disabled=st.session_state.running or not online)
    with bc2:
        if st.button("↺", use_container_width=True):
            reset_run(); st.rerun()

    if not online:
        st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:9.5px;color:#FF6B6B;'
                    'margin-top:5px">⚠ Backend offline<br>'
                    '<span style="color:#3A5068">cd Backend && uvicorn app.main:app --reload</span></div>',
                    unsafe_allow_html=True)

# ── MIDDLE ────────────────────────────────────────────────────────────────────
with col_m:
    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">🤖 Agent Loop Status</div>', unsafe_allow_html=True)
    agent_ph = st.empty()
    agent_ph.markdown(_agent_strip_html(), unsafe_allow_html=True)

    if st.session_state.loop_num > 0:
        st.markdown(
            f'<div class="loop-ring"><div class="loop-dot"></div>'
            f'Self-correction loop {st.session_state.loop_num} / 3</div>',
            unsafe_allow_html=True
        )
    st.markdown('</div>', unsafe_allow_html=True)

    terminal_ph = st.empty()
    terminal_ph.markdown(_terminal_html(), unsafe_allow_html=True)

    result_ph = st.empty()
    if st.session_state.result:
        rv = st.session_state.result
        rp = rv.get("passed", False)
        rc = rv.get("confidence", 0)
        result_ph.markdown(
            f'<div class="res-panel {"res-pass" if rp else "res-fail"}">'
            f'<div class="res-hdr">{"✓  WORKFLOW COMPLETED" if rp else "⚑  PARTIAL RESULT"}</div>'
            f'<div class="res-meta">Loops: {rv.get("loops_used","—")}/3 &nbsp;·&nbsp; '
            f'Confidence: {int(rc*100)}%</div>'
            f'<div class="res-sum">{rv.get("summary","")[:160]}</div>'
            f'</div>', unsafe_allow_html=True
        )

# ── RIGHT ─────────────────────────────────────────────────────────────────────
with col_r:
    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">📋 Execution Plan (live)</div>', unsafe_allow_html=True)
    plan_ph = st.empty()
    plan_ph.markdown(_plan_html(), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">💾 Memory Store (self-learning)</div>', unsafe_allow_html=True)
    mem_ph = st.empty()
    mem_ph.markdown(_memory_html(), unsafe_allow_html=True)

    try:
        ms = requests.get(MEMORY_URL, timeout=2).json()
        tm = ms.get("total_memories", 0)
        cats_str = " · ".join(f"{c}:{n}" for c, n in list(ms.get("categories",{}).items())[:4])
        st.markdown(
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:9.5px;color:#1A2E3A;'
            f'margin-top:6px">{tm} memories · {cats_str}</div>',
            unsafe_allow_html=True
        )
    except: pass
    st.markdown('</div>', unsafe_allow_html=True)


# ── RUN ───────────────────────────────────────────────────────────────────────
if run_btn:
    reset_run()
    st.session_state.running = True
    st.session_state.runs_total += 1

    ctx = dict(demo.get("context", {}))
    if st.session_state.rt_anthropic.strip():
        ctx["_anthropic_key"] = st.session_state.rt_anthropic.strip()
    elif st.session_state.rt_groq.strip():
        ctx["_groq_key"] = st.session_state.rt_groq.strip()
    elif st.session_state.rt_hf.strip():
        ctx["_hf_key"] = st.session_state.rt_hf.strip()

    payload = {"task": task_text, "context": ctx}
    add_log(f"Task: {task_text[:65]}…", "system")
    prov3, _ = _provider()
    add_log(f"Provider: {prov3}  ·  Workflow: {demo['tag']}", "system", indent=True)

    def _refresh():
        agent_ph.markdown(_agent_strip_html(), unsafe_allow_html=True)
        terminal_ph.markdown(_terminal_html(), unsafe_allow_html=True)
        plan_ph.markdown(_plan_html(), unsafe_allow_html=True)

    try:
        with requests.post(STREAM_URL, json=payload, stream=True, timeout=180) as resp:
            ev, data = "", {}
            for raw in resp.iter_lines():
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if line.startswith("event:"): ev = line[6:].strip(); continue
                if line.startswith("data:"):
                    try: data = json.loads(line[5:].strip())
                    except: data = {}
                else: continue
                if not ev: continue

                if ev == "start":
                    set_step("THINK", "active")
                    add_log(f"Workflow {data.get('workflow_id','')} started", "system")

                elif ev == "think":
                    set_step("THINK", "active")
                    add_log("Searching memory for similar workflows…", "think")

                elif ev == "memory_recall":
                    set_step("THINK", "done")
                    add_log(f"Memory scan complete — {data.get('count',0)} hint(s)", "think")
                    for h in data.get("hints", [])[:2]:
                        if h: add_log(h[:85], "memory", indent=True)

                elif ev == "loop_start":
                    st.session_state.loop_num = data.get("loop", 1)
                    add_log(f"─── Loop {data['loop']} / {data['max_loops']} ───", "gray")
                    fb = data.get("feedback","")
                    if fb: add_log(f"Feedback → {fb[:95]}", "update", indent=True)

                elif ev == "plan":
                    set_step("THINK", "done"); set_step("PLAN", "active")
                    add_log("Generating execution plan…", "plan")

                elif ev == "plan_ready":
                    set_step("PLAN", "done")
                    st.session_state.current_plan = data.get("plan", {})
                    add_log(f"{data.get('steps_count')} steps · type={data.get('workflow_type')} · risk={data.get('risk_level')}", "plan")
                    for ps in st.session_state.current_plan.get("steps",[]):
                        deps = ps.get("depends_on",[])
                        dep_s = f" ← [{','.join(map(str,deps))}]" if deps else ""
                        add_log(f"{ps.get('step_number')}. {ps.get('tool')}.{ps.get('action')}(){dep_s}", "plan", indent=True)

                elif ev == "execute":
                    set_step("PLAN","done"); set_step("EXECUTE","active")
                    add_log("Dispatching tools…", "execute")

                elif ev == "step_start":
                    add_log(f"Step {data.get('step','?')} → {data.get('tool')}.{data.get('action')}()", "execute")
                    if data.get("description"):
                        add_log(data["description"][:65], "execute", indent=True)

                elif ev == "step_done":
                    sn = data.get("step","?"); st2 = data.get("status","")
                    out = json.dumps(data.get("output",{}), default=str)[:80]
                    if st2 == "completed":
                        add_log(f"Step {sn} ✓  {out}", "execute", indent=True)
                    else:
                        err = (data.get("error","") or "")[:75]
                        add_log(f"Step {sn} ✗  {err}", "error", indent=True)

                elif ev == "review":
                    set_step("EXECUTE","done"); set_step("REVIEW","active")
                    add_log("Evaluating execution quality…", "review")

                elif ev == "review_done":
                    set_step("REVIEW","done")
                    rpass = data.get("passed",False)
                    conf  = data.get("confidence",0)
                    add_log(f"{'PASSED ✓' if rpass else 'FAILED ✗'}  conf={conf:.0%}  {data.get('summary','')[:70]}", "review")
                    for iss in data.get("issues",[])[:2]:
                        add_log(iss[:75], "error", indent=True)
                    if not rpass:
                        for rec in data.get("recommendations",[])[:1]:
                            add_log(rec[:75], "update", indent=True)

                elif ev == "update":
                    set_step("UPDATE","active")
                    action = data.get("action","")
                    if action == "pass":
                        set_step("UPDATE","done")
                        add_log("Quality gate passed — persisting to memory", "done")
                    elif action == "retry":
                        set_step("UPDATE","done")
                        set_step("EXECUTE","pending"); set_step("REVIEW","pending")
                        add_log(f"Self-correcting → {data.get('feedback','')[:85]}", "update")
                    else:
                        set_step("UPDATE","done")
                        add_log(data.get("message","")[:75], "update")

                elif ev == "memory_stored":
                    add_log(f"Stored in memory · category={data.get('category','general')}", "memory")
                    mem_ph.markdown(_memory_html(), unsafe_allow_html=True)

                elif ev == "complete":
                    rpass = data.get("passed",False)
                    st.session_state.result = data
                    if rpass: st.session_state.runs_passed += 1
                    add_log(f"{'COMPLETE ✓' if rpass else 'PARTIAL ⚑'}  loops={data.get('loops_used','?')}", "done")
                    for na in data.get("next_actions",[])[:2]:
                        add_log(na[:65], "gray", indent=True)
                    rc2 = data.get("confidence", 0)
                    result_ph.markdown(
                        f'<div class="res-panel {"res-pass" if rpass else "res-fail"}">'
                        f'<div class="res-hdr">{"✓  WORKFLOW COMPLETED" if rpass else "⚑  PARTIAL RESULT"}</div>'
                        f'<div class="res-meta">Loops: {data.get("loops_used","—")}/3 &nbsp;·&nbsp; Confidence: {int(rc2*100)}%</div>'
                        f'<div class="res-sum">{data.get("summary","")[:155]}</div>'
                        f'</div>', unsafe_allow_html=True
                    )

                elif ev == "error":
                    add_log(f"ERROR: {data.get('message','')[:95]}", "error")

                ev = ""; data = {}
                _refresh()

    except requests.exceptions.ConnectionError:
        add_log("Cannot connect to backend on :8000", "error")
        add_log("cd Backend && uvicorn app.main:app --reload --port 8000", "gray", indent=True)
    except Exception as e:
        add_log(f"Stream error: {str(e)[:90]}", "error")
    finally:
        st.session_state.running = False

    _refresh()
    mem_ph.markdown(_memory_html(), unsafe_allow_html=True)
    st.rerun()