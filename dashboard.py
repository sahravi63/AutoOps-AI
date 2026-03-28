"""
Campus Payment Recovery AI — Bursar Office Tuition Payment Recovery
===================================================================
Updated dashboard with features from StudAI LaunchPad:
  - Tabbed results view (Summary | Step Breakdown | Tool Outputs | Raw Log)
  - Per-step score / status cards with detailed breakdowns
  - Tool pipeline visualization
  - Autonomy explainer expander
  - Download result as Markdown
  - Enhanced activity log with color-coded categories
  - Pre-filled example quick-launch buttons
  - Post-run education expander
"""

import json
import time
import datetime
import requests
import streamlit as st

BACKEND           = "http://localhost:8000"
STREAM_URL        = f"{BACKEND}/workflow/stream"
MEMORY_URL        = f"{BACKEND}/workflow/memory/stats"
MEMORY_SEARCH_URL = f"{BACKEND}/workflow/memory/search"

DEMO_TASKS = {
    "💳  Tuition Payment Failed": {
        "task": "Student payment failed but tuition fee was deducted. Student ID: STU-00123, amount $2999.",
        "context": {"student_id": "STU-00123", "amount": 2999, "currency": "USD"},
        "tag": "PAYMENT",
    },
    "🔁  Duplicate Tuition Charge": {
        "task": "Student STU-00456 was charged twice for $1499 tuition payment.",
        "context": {"student_id": "STU-00456", "amount": 1499},
        "tag": "PAYMENT",
    },
    "📄  Refund Reconciliation": {
        "task": "Process refund for failed tuition payment TXN-AB12CD34 and confirm ledger balance.",
        "context": {"transaction_id": "TXN-AB12CD34", "reason": "Payment gateway failure"},
        "tag": "PAYMENT",
    },
}

AGENT_STEPS = ["THINK", "PLAN", "EXECUTE", "REVIEW", "UPDATE"]
STEP_ICONS  = {"THINK": "🧠", "PLAN": "📋", "EXECUTE": "⚙️", "REVIEW": "🔍", "UPDATE": "🔄"}
STEP_DESCRIPTIONS = {
    "THINK":   "Memory scan & goal parse",
    "PLAN":    "Build execution plan",
    "EXECUTE": "Dispatch tools",
    "REVIEW":  "Evaluate quality",
    "UPDATE":  "Self-correct / persist",
}

LOG_COLORS = {
    "think": "#B57BFF", "plan": "#00C987", "execute": "#4DA6FF",
    "review": "#FFB347", "update": "#FF6B6B", "memory": "#C77DFF",
    "done": "#00A855", "error": "#FF4444", "gray": "#6E7A8A", "system": "#0090CC",
}
TAG_COLORS  = {"PAYMENT": "#4DA6FF"}
TOOL_COLORS = {
    "payment_tool": "#4DA6FF", "database_tool": "#00C987",
    "notification_tool": "#FFB347", "ticket_tool": "#FF6B6B",
}

PIPELINE_TOOLS = [
    ("💳", "Payment\nVerifier",  "Stripe sandbox"),
    ("🗃️", "DB\nLookup",        "Ledger check"),
    ("🎫", "Ticket\nCreator",    "ServiceNow"),
    ("🔔", "Notifier",           "Webhook / email"),
]

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Campus Payment Recovery AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=DM+Sans:wght@300;400;500;600&display=swap');
*,*::before,*::after{box-sizing:border-box}
html,body,[data-testid="stAppViewContainer"]{background:#f8f9fa!important;color:#111!important;font-family:'DM Sans',sans-serif}
[data-testid="stHeader"]{display:none!important}
[data-testid="stSidebar"]{display:none!important}
#MainMenu,footer,header{visibility:hidden}
.block-container{padding:1.2rem 1.6rem 2rem!important;max-width:100%!important}
[data-testid="stAppViewContainer"]::before{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:linear-gradient(rgba(0,123,255,.02)1px,transparent 1px),linear-gradient(90deg,rgba(0,123,255,.02)1px,transparent 1px);
  background-size:48px 48px}
[data-testid="column"]{position:relative;z-index:1}

/* ── Cards ── */
.ao-card{background:#ffffff;border:1px solid #dee2e6;border-radius:12px;
  padding:16px 18px;margin-bottom:14px;position:relative;overflow:hidden;box-shadow:0 2px 4px rgba(0,0,0,.08)}
.ao-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,#007bff,transparent)}
.ao-lbl{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600;
  letter-spacing:2px;text-transform:uppercase;color:#333;
  margin-bottom:10px;padding-bottom:7px;border-bottom:1px solid #e9ecef}

/* ── Header ── */
.ao-hdr{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.ao-logo{width:36px;height:36px;background:linear-gradient(135deg,#28a745,#007bff);
  border-radius:8px;display:flex;align-items:center;justify-content:center;
  font-size:18px;font-weight:700;color:#fff;flex-shrink:0}
.ao-title{font-family:'IBM Plex Mono',monospace;font-size:1.35rem;font-weight:600;
  color:#111;letter-spacing:-.5px}
.ao-title span{color:#0b5ed7}
.ao-sub{font-size:.68rem;color:#555;letter-spacing:2px;text-transform:uppercase}
.ao-badge{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600;
  letter-spacing:1.5px;text-transform:uppercase;padding:4px 10px;border-radius:20px;
  border:1px solid;white-space:nowrap}

/* ── Step cards (StudAI style) ── */
.step-card{border-radius:10px;padding:14px 6px;text-align:center;margin:2px;
  font-size:13px;min-height:120px;transition:all .3s ease}
.step-pending{background:#f0f0f0;border:2px solid #ccc;color:#888}
.step-active{background:#e8f3ff;border:2px solid #007bff;color:#0047ab;
  animation:pulse-step 1.5s ease-in-out infinite}
.step-done{background:#e8f5e9;border:2px solid #28a745;color:#155724}
.step-failed{background:#ffebee;border:2px solid #dc3545;color:#721c24}
@keyframes pulse-step{
  0%,100%{box-shadow:0 0 0 0 rgba(0,123,255,.25)}
  50%{box-shadow:0 0 14px 4px rgba(0,123,255,.25)}}

/* ── Loop badge ── */
.loop-counter{text-align:center;background:#1E1E2E;color:#7dd3fc;
  padding:8px 16px;border-radius:8px;font-family:'IBM Plex Mono',monospace;
  font-weight:700;font-size:13px;margin:8px 0}

/* ── Terminal ── */
.terminal{background:#fff;border:1px solid #c8c8c8;border-radius:10px;
  padding:12px 14px;min-height:280px;max-height:380px;overflow-y:auto;
  font-family:'IBM Plex Mono',monospace;font-size:11px;line-height:1.8;color:#111}
.terminal::before{content:'▌ AGENT LOG  ●  LIVE';display:block;font-size:8.5px;
  letter-spacing:2px;font-weight:600;color:#007bff;
  margin-bottom:9px;padding-bottom:7px;border-bottom:1px solid #e9ecef}
.tl{display:flex;gap:7px;align-items:baseline;padding:.5px 0;animation:sl-in .12s ease forwards}
.tl-ts{color:#555;font-size:9.5px;flex-shrink:0}
.tl-badge{font-size:8.5px;font-weight:700;letter-spacing:1px;padding:1px 5px;
  border-radius:3px;flex-shrink:0;min-width:48px;text-align:center}
.tl-msg{flex:1;overflow-wrap:anywhere}
.tl-indent{padding-left:10px;opacity:.75}
.b-think{background:#e2e3ff;color:#6f42c1}.b-plan{background:#d1ecf1;color:#0c5460}
.b-execute{background:#d4edda;color:#155724}.b-review{background:#fff3cd;color:#856404}
.b-update{background:#f8d7da;color:#721c24}.b-memory{background:#e2e3ff;color:#6f42c1}
.b-done{background:#d4edda;color:#155724}.b-error{background:#f8d7da;color:#721c24}
.b-sys{background:#f8f9fa;color:#555}
@keyframes sl-in{from{opacity:0;transform:translateX(-4px)}to{opacity:1;transform:translateX(0)}}

/* ── Result panel ── */
.res-panel{border-radius:10px;padding:13px 15px;margin-top:10px;border:1px solid}
.res-pass{background:#f7fcf8;border-color:#28a745}
.res-fail{background:#fff1f0;border-color:#dc3545}
.res-hdr{font-family:'IBM Plex Mono',monospace;font-size:12.5px;font-weight:600;margin-bottom:5px}
.res-pass .res-hdr{color:#155724}.res-fail .res-hdr{color:#721c24}
.res-meta{font-size:10.5px;color:#444;line-height:1.6}
.res-sum{font-size:11.5px;color:#111;margin-top:4px;line-height:1.5}

/* ── Score card (StudAI style) ── */
.score-card{text-align:center;padding:20px;border-radius:12px;font-weight:bold}
.score-pass{background:linear-gradient(135deg,#e8f5e9,#c8e6c9);border:2px solid #28a745;color:#155724}
.score-fail{background:linear-gradient(135deg,#ffebee,#ffcdd2);border:2px solid #dc3545;color:#721c24}

/* ── Field badge ── */
.field-badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;margin-left:8px}
.badge-pass{background:#e8f5e9;color:#2e7d32;border:1px solid #a5d6a7}
.badge-needs{background:#fff8e1;color:#f57f17;border:1px solid #ffe082}
.badge-fail{background:#ffebee;color:#c62828;border:1px solid #ef9a9a}

/* ── Pipeline card ── */
.pipeline-card{background:#f8f9fa;border:1px solid #dee2e6;border-radius:8px;
  padding:12px;text-align:center;font-size:13px}

/* ── Plan step ── */
.ps-row{display:flex;align-items:center;gap:8px;background:#fff;
  border:1px solid #e3e3e3;border-radius:6px;padding:8px 11px;margin-bottom:6px}
.ps-num{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:700;flex-shrink:0;width:18px}
.ps-tool{font-family:'IBM Plex Mono',monospace;font-size:9.5px;flex-shrink:0;color:#555}
.ps-desc{font-size:10.5px;color:#111;overflow-wrap:anywhere;white-space:normal;flex:1}

/* ── Memory ── */
.mem-entry{background:#fff;border-left:2px solid #0b5ed7;
  border-radius:0 6px 6px 0;padding:8px 10px;margin-bottom:8px;font-size:10.5px;color:#111;line-height:1.45}
.mem-cat{font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:1px;
  text-transform:uppercase;color:#0b5ed7;margin-bottom:2px}

/* ── Stats ── */
.stats-row{display:flex;gap:8px;margin-bottom:12px}
.stat-box{flex:1;background:#fff;border:1px solid #e3e3e3;border-radius:8px;padding:10px 11px;text-align:center}
.stat-val{font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:600;color:#111;line-height:1}
.stat-lbl{font-size:9.5px;color:#555;letter-spacing:1px;text-transform:uppercase;margin-top:2px}

/* ── Streamlit overrides ── */
.stTextArea textarea{background:#fff!important;border:1px solid #dee2e6!important;
  border-radius:8px!important;color:#111!important;font-family:'IBM Plex Mono',monospace!important;font-size:11.5px!important}
.stTextArea textarea:focus{border-color:#007bff!important;box-shadow:0 0 0 2px rgba(0,123,255,.2)!important}
.stTextInput input{background:#fff!important;border:1px solid #dee2e6!important;
  border-radius:8px!important;color:#111!important;font-family:'IBM Plex Mono',monospace!important;font-size:11.5px!important}
.stSelectbox>div>div{background:#fff!important;border:1px solid #dee2e6!important;color:#111!important}
div[data-testid="stButton"] button{font-family:'IBM Plex Mono',monospace!important;
  font-weight:600!important;letter-spacing:1px!important;border-radius:8px!important;transition:all .2s!important}
div[data-testid="stButton"] button[kind="primary"]{
  background:linear-gradient(135deg,#28a745,#007bff)!important;border:none!important;
  color:#fff!important;font-size:11.5px!important}
div[data-testid="stButton"] button[kind="primary"]:hover{
  filter:brightness(1.1);box-shadow:0 0 18px rgba(0,123,255,.25)!important}
div[data-testid="stButton"] button:not([kind="primary"]){
  background:#f8f9fa!important;border:1px solid #dee2e6!important;color:#111!important;font-size:11px!important}
label,.stLabel{color:#111!important;font-size:10.5px!important}
p{color:#111}
[data-testid="stTab"]{font-family:'IBM Plex Mono',monospace!important;font-size:11px!important}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in {
    "logs": [], "step_status": {s: "pending" for s in AGENT_STEPS},
    "result": None, "loop_num": 0, "running": False,
    "runs_total": 0, "runs_passed": 0,
    "selected_task": list(DEMO_TASKS.keys())[0],
    "rt_anthropic": "", "rt_groq": "", "rt_hf": "",
    "current_plan": {}, "tool_outputs": {},
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


def reset_run():
    st.session_state.logs = []
    st.session_state.step_status = {s: "pending" for s in AGENT_STEPS}
    st.session_state.result = None
    st.session_state.loop_num = 0
    st.session_state.current_plan = {}
    st.session_state.tool_outputs = {}


def set_step(name, status):
    if name in st.session_state.step_status:
        st.session_state.step_status[name] = status


def add_log(msg, cat="gray", indent=False):
    st.session_state.logs.append((time.strftime("%H:%M:%S"), msg, cat, indent))


def _provider():
    if st.session_state.rt_anthropic.strip(): return "ANTHROPIC", "#A78BFA"
    if st.session_state.rt_groq.strip():      return "GROQ",      "#FB923C"
    if st.session_state.rt_hf.strip():        return "HUGGINGFACE","#FCD34D"
    return "MOCK", "#4A6880"


def _backend_online():
    try:
        return requests.get(f"{BACKEND}/health", timeout=2).status_code == 200
    except:
        return False


# ── Render helpers ────────────────────────────────────────────────────────────

def _step_cards_html():
    """Render 5 step cards (StudAI style) with current statuses."""
    status_icon = {"pending": "○", "active": "⚙", "done": "✔", "failed": "✖"}
    cols_html = ""
    for s in AGENT_STEPS:
        st2 = st.session_state.step_status.get(s, "pending")
        icon = status_icon.get(st2, "○")
        desc = STEP_DESCRIPTIONS[s]
        cols_html += (
            f'<div style="flex:1;padding:2px">'
            f'<div class="step-card step-{st2}">'
            f'<div style="font-size:22px">{STEP_ICONS[s]}</div>'
            f'<div style="font-weight:700;margin-top:4px;font-size:12px">{s}</div>'
            f'<div style="font-size:10px;margin-top:2px;opacity:.8">{desc}</div>'
            f'<div style="font-size:11px;margin-top:4px;font-family:\'IBM Plex Mono\',monospace">'
            f'{icon} {st2.upper()}</div>'
            f'</div></div>'
        )
    return f'<div style="display:flex;gap:0">{cols_html}</div>'


def _terminal_html():
    if not st.session_state.logs:
        return ('<div class="terminal" style="display:flex;align-items:center;'
                'justify-content:center;color:#aaa;">// awaiting workflow execution…</div>')
    badge_map = {
        "think": "THINK", "plan": "PLAN", "execute": "EXEC",
        "review": "REVIEW", "update": "UPDATE", "memory": "MEM",
        "done": "DONE", "error": "ERR", "gray": "SYS", "system": "SYS",
    }
    lines = []
    for ts, msg, cat, indent in st.session_state.logs[-90:]:
        bc  = f"b-{cat}" if cat in badge_map else "b-sys"
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
        return '<div style="color:#aaa;font-size:10.5px;font-family:IBM Plex Mono,monospace">// plan will appear after PLAN phase</div>'
    html = ""
    for ps in steps:
        tc   = TOOL_COLORS.get(ps.get("tool", ""), "#2A4055")
        desc = ps.get("description", "")[:55]
        deps = ps.get("depends_on", [])
        dep_txt = f" ← [{','.join(map(str, deps))}]" if deps else ""
        html += (
            f'<div class="ps-row">'
            f'<span class="ps-num" style="color:{tc}">[{ps.get("step_number")}]</span>'
            f'<span class="ps-tool" style="color:{tc}">{ps.get("tool","")}.{ps.get("action","")}</span>'
            f'<span class="ps-desc">{desc}{dep_txt}</span>'
            f'</div>'
        )
    return html


def _memory_html():
    try:
        data  = requests.get(f"{MEMORY_SEARCH_URL}?q=&top_k=6", timeout=2).json()
        items = data.get("results", [])
        if not items:
            return '<div style="color:#aaa;font-size:10.5px">// no memories yet</div>'
        html = ""
        for item in items[:5]:
            doc = item.get("document", "")
            cat = doc.split("]")[0].replace("[", "").strip() if doc.startswith("[") else "general"
            txt = doc[doc.find("]") + 1:].strip()[:95] if "]" in doc else doc[:95]
            html += f'<div class="mem-entry"><div class="mem-cat">{cat}</div>{txt}…</div>'
        return html
    except:
        return '<div style="color:#aaa;font-size:10.5px">// backend offline</div>'


def _result_markdown():
    """Build a Markdown string of the run result for download."""
    rv = st.session_state.result
    if not rv:
        return ""
    lines = [
        "# Campus Payment Recovery — Run Report",
        f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Status:** {'✅ PASSED' if rv.get('passed') else '⚠️ PARTIAL'}",
        f"**Confidence:** {int(rv.get('confidence', 0) * 100)}%",
        f"**Loops used:** {rv.get('loops_used', '—')}/3",
        "",
        "## Summary",
        rv.get("summary", ""),
        "",
        "## Next Actions",
    ]
    for na in rv.get("next_actions", []):
        lines.append(f"- {na}")
    lines += ["", "## Activity Log", "```"]
    for ts, msg, cat, _ in st.session_state.logs:
        lines.append(f"[{ts}] [{cat.upper():8s}] {msg}")
    lines.append("```")
    return "\n".join(lines)


# ── AUTONOMY EXPLAINER (from StudAI) ─────────────────────────────────────────
with st.expander("🤖 What makes this AUTONOMOUS (not a chatbot)?", expanded=False):
    st.markdown("""
**A chatbot** takes your input → calls an LLM once → returns whatever it gets. One shot. Done. No quality check.

**This autonomous agent** takes a remediation goal and then:

| Step | What the Agent Does | Why It Matters |
|------|-------------------|----------------|
| **THINK** | Scans memory for similar past workflows + parses the goal | Context awareness — avoids repeating past mistakes |
| **PLAN** | Asks the LLM to create a JSON action plan | Self-directed — it decides *which tools* to run, not you |
| **EXECUTE** | Runs each tool in sequence (payment → DB → ticket → notify) | Tool use — each tool does one job, outputs chain together |
| **REVIEW** | Scores its own output against remediation criteria | **Self-evaluation — THIS is what makes it autonomous** |
| **UPDATE** | If confidence < threshold, carries feedback into the next loop | Self-correction — it learns from its own run |

The loop runs up to **3 times**. Each retry uses specific feedback to improve. This is the same architecture used in production AI agents.

**4-Tool Pipeline:**
1. **Payment Verifier** → Checks Stripe sandbox for charge status
2. **DB Lookup** → Queries ledger for transaction record
3. **Ticket Creator** → Opens ServiceNow incident for tracking
4. **Notifier** → Sends webhook / email confirmation to student & bursar

> **The one rule: THE LOOP NEVER CHANGES. THE TOOLS DO.**
""")

# ── HEADER ────────────────────────────────────────────────────────────────────
online = _backend_online()
prov, pcol = _provider()

st.markdown(f"""
<div class="ao-hdr">
  <div class="ao-logo">⚡</div>
  <div>
    <div class="ao-title">Campus Payment<span> Recovery</span> AI</div>
    <div class="ao-sub">Track 3 — Bursar Office Tuition Payment Remediation</div>
  </div>
  <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
    <div class="ao-badge" style="color:{pcol};border-color:{pcol}40;background:{pcol}10">LLM: {prov}</div>
    <div class="ao-badge" style="color:{'#00a855' if online else '#FF6B6B'};
      border-color:{'rgba(0,168,85,.3)' if online else 'rgba(255,107,107,.3)'};
      background:{'rgba(0,168,85,.07)' if online else 'rgba(255,107,107,.07)'}">
      {'● ONLINE' if online else '○ OFFLINE'}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── THREE COLUMNS ─────────────────────────────────────────────────────────────
col_l, col_m, col_r = st.columns([1.1, 1.65, 1.25], gap="medium")

# ════════════════════════════════════════════════════════════════════════════
# LEFT COLUMN
# ════════════════════════════════════════════════════════════════════════════
with col_l:
    # API Keys
    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">🔑 API Keys — Runtime</div>', unsafe_allow_html=True)
    ant  = st.text_input("Anthropic  (sk-ant-…)", value=st.session_state.rt_anthropic,
                          type="password", placeholder="sk-ant-api03-…", key="in_ant")
    st.session_state.rt_anthropic = ant
    groq = st.text_input("Groq  (gsk_… · free)", value=st.session_state.rt_groq,
                          type="password", placeholder="gsk_…", key="in_groq")
    st.session_state.rt_groq = groq
    hf   = st.text_input("HuggingFace  (hf_… · free)", value=st.session_state.rt_hf,
                          type="password", placeholder="hf_…", key="in_hf")
    st.session_state.rt_hf = hf
    prov2, pcol2 = _provider()
    st.markdown(f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;color:#555;'
                f'margin-top:4px">Active: <span style="color:{pcol2};font-weight:600">'
                f'{prov2}</span></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Task selector
    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">📂 Workflow Selection</div>', unsafe_allow_html=True)
    task_keys = list(DEMO_TASKS.keys())
    idx = task_keys.index(st.session_state.selected_task) if st.session_state.selected_task in task_keys else 0
    sel = st.selectbox("Select workflow", task_keys, index=idx, label_visibility="collapsed")
    st.session_state.selected_task = sel
    demo = DEMO_TASKS[sel]
    tc2  = TAG_COLORS.get(demo["tag"], "#007bff")

    st.markdown(
        f'<div style="background:#f8f9fa;border:1px solid #e9ecef;border-radius:7px;padding:9px 11px;margin:6px 0">'
        f'<span style="font-family:IBM Plex Mono,monospace;font-size:8.5px;font-weight:700;'
        f'letter-spacing:1.5px;color:{tc2}">{demo["tag"]}</span>'
        f'<div style="font-size:11px;color:#111;margin-top:4px;line-height:1.45">'
        f'{demo["task"][:95]}{"…" if len(demo["task"]) > 95 else ""}</div></div>',
        unsafe_allow_html=True,
    )

    task_text = st.text_area("Edit remediation task", value=demo["task"], height=76,
                              key=f"txt_{sel}", label_visibility="visible")

    # Quick-launch examples (StudAI feature)
    st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:9px;color:#555;margin:6px 0 4px">💡 QUICK EXAMPLES</div>', unsafe_allow_html=True)
    ex_cols = st.columns(3)
    if ex_cols[0].button("STU-00123", use_container_width=True):
        st.session_state.selected_task = task_keys[0]; st.rerun()
    if ex_cols[1].button("STU-00456", use_container_width=True):
        st.session_state.selected_task = task_keys[1]; st.rerun()
    if ex_cols[2].button("TXN-AB12", use_container_width=True):
        st.session_state.selected_task = task_keys[2]; st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    # Stats
    t = st.session_state.runs_total
    p = st.session_state.runs_passed
    r_pct = int(p / t * 100) if t else 0
    st.markdown(
        f'<div class="stats-row">'
        f'<div class="stat-box"><div class="stat-val">{t}</div><div class="stat-lbl">Runs</div></div>'
        f'<div class="stat-box"><div class="stat-val">{p}</div><div class="stat-lbl">Passed</div></div>'
        f'<div class="stat-box"><div class="stat-val">{r_pct}%</div><div class="stat-lbl">Rate</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    bc1, bc2 = st.columns([3, 1])
    with bc1:
        run_btn = st.button("▶  RUN RECOVERY WORKFLOW", use_container_width=True, type="primary",
                             disabled=st.session_state.running or not online)
    with bc2:
        if st.button("↺", use_container_width=True):
            reset_run(); st.rerun()

    if not online:
        st.markdown(
            '<div style="font-family:IBM Plex Mono,monospace;font-size:9.5px;color:#dc3545;margin-top:5px">'
            '⚠ Backend offline<br>'
            '<span style="color:#888">cd Backend && uvicorn app.main:app --reload</span></div>',
            unsafe_allow_html=True,
        )

# ════════════════════════════════════════════════════════════════════════════
# MIDDLE COLUMN
# ════════════════════════════════════════════════════════════════════════════
with col_m:
    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">🤖 Agent Loop — Step Tracker</div>', unsafe_allow_html=True)
    step_ph = st.empty()
    step_ph.markdown(_step_cards_html(), unsafe_allow_html=True)

    loop_ph = st.empty()
    if st.session_state.loop_num > 0:
        loop_ph.markdown(
            f'<div class="loop-counter">AUTONOMOUS LOOP: {st.session_state.loop_num} / 3</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

    terminal_ph = st.empty()
    terminal_ph.markdown(_terminal_html(), unsafe_allow_html=True)

    # ── TABBED RESULTS (StudAI feature) ──────────────────────────────────────
    result_ph = st.empty()

    if st.session_state.result:
        rv    = st.session_state.result
        rpass = rv.get("passed", False)
        rc    = rv.get("confidence", 0)

        st.markdown("---")
        st.markdown("### 📊 Run Results")

        tab_summary, tab_steps, tab_tools, tab_raw = st.tabs(
            ["✅ Summary", "🔍 Step Breakdown", "⚙️ Tool Outputs", "📋 Raw Log"]
        )

        # TAB 1 — Summary (score card)
        with tab_summary:
            score_class = "score-pass" if rpass else "score-fail"
            score_emoji = "✅" if rpass else "🔄"
            st.markdown(
                f'<div class="score-card {score_class}">'
                f'<div style="font-size:34px">{score_emoji}</div>'
                f'<div style="font-size:26px;margin-top:4px">{int(rc * 100)}% Confidence</div>'
                f'<div style="font-size:13px;margin-top:4px">'
                f'{"WORKFLOW PASSED — Ready to close ticket" if rpass else "PARTIAL — Agent self-correcting"}'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**Loops used:** {rv.get('loops_used', '—')} / 3")
            st.markdown(f"**Summary:** {rv.get('summary', '')}")

            if rv.get("next_actions"):
                st.markdown("**Recommended next actions:**")
                for na in rv.get("next_actions", [])[:4]:
                    st.markdown(f"- {na}")

            # Download button (StudAI feature)
            md_text = _result_markdown()
            st.download_button(
                label="📥 Download Run Report (.md)",
                data=md_text,
                file_name=f"payment-recovery-report-{time.strftime('%Y%m%d-%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True,
            )

        # TAB 2 — Step Breakdown (per-step confidence bars)
        with tab_steps:
            st.markdown("**Per-step execution status:**")
            for s in AGENT_STEPS:
                st2 = st.session_state.step_status.get(s, "pending")
                bar_color = "#28a745" if st2 == "done" else "#dc3545" if st2 == "failed" else "#dee2e6"
                badge_cls = "badge-pass" if st2 == "done" else "badge-fail" if st2 == "failed" else "badge-needs"
                st.markdown(
                    f'<div style="margin:6px 0;padding:8px 12px;background:#f8f9fa;'
                    f'border-radius:8px;border-left:4px solid {bar_color}">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center">'
                    f'<span><strong>{STEP_ICONS[s]} {s}</strong>'
                    f'<span class="field-badge {badge_cls}">{st2.upper()}</span></span>'
                    f'<span style="font-size:11px;color:#666">{STEP_DESCRIPTIONS[s]}</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            st.markdown("---")
            st.markdown("**Execution Plan:**")
            st.markdown(_plan_html(), unsafe_allow_html=True)

        # TAB 3 — Tool Outputs
        with tab_tools:
            st.markdown("**4-Tool Pipeline used in this run:**")
            p_cols = st.columns(4)
            for i, col in enumerate(p_cols):
                icon, name, sub = PIPELINE_TOOLS[i]
                col.markdown(
                    f'<div class="pipeline-card">'
                    f'<div style="font-size:22px">{icon}</div>'
                    f'<div style="font-weight:700;margin-top:4px;font-size:12px">{name}</div>'
                    f'<div style="font-size:10px;color:#666;margin-top:2px">{sub}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            st.markdown("---")
            tool_outputs = st.session_state.tool_outputs
            if tool_outputs:
                for tool_name, output in tool_outputs.items():
                    tc_color = TOOL_COLORS.get(tool_name, "#555")
                    st.markdown(
                        f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;'
                        f'font-weight:700;color:{tc_color};margin:10px 0 4px">{tool_name}</div>',
                        unsafe_allow_html=True,
                    )
                    st.json(output)
            else:
                st.markdown("*Tool outputs will appear here after execution.*")

        # TAB 4 — Raw Log
        with tab_raw:
            st.markdown(
                "Full activity log from this run. Each line shows timestamp, "
                "category badge, and agent message."
            )
            lines = []
            for ts, msg, cat, indent in st.session_state.logs:
                prefix = "  " if indent else ""
                lines.append(f"[{ts}] [{cat.upper():8s}] {prefix}{msg}")
            st.code("\n".join(lines), language="text")

# ════════════════════════════════════════════════════════════════════════════
# RIGHT COLUMN
# ════════════════════════════════════════════════════════════════════════════
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
        cats_str = " · ".join(f"{c}:{n}" for c, n in list(ms.get("categories", {}).items())[:4])
        st.markdown(
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:9.5px;color:#555;margin-top:6px">'
            f'{tm} memories · {cats_str}</div>',
            unsafe_allow_html=True,
        )
    except:
        pass
    st.markdown('</div>', unsafe_allow_html=True)

    # Focus info card
    st.markdown('<div class="ao-card">', unsafe_allow_html=True)
    st.markdown('<div class="ao-lbl">🎯 Track 3 Focus</div>', unsafe_allow_html=True)
    st.markdown(
        '<ul style="padding-left:16px;margin:6px 0;color:#111;line-height:1.7;font-size:11px">'
        '<li>Workflow: <strong>payment_failure_remediation</strong></li>'
        '<li>Tooling: Stripe sandbox, ServiceNow, webhooks</li>'
        '<li>Safety: structured plan validation, tool allowlists, review gate</li>'
        '<li>Demo mode: one campus use case only</li>'
        '</ul>',
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# RUN WORKFLOW
# ════════════════════════════════════════════════════════════════════════════
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
        step_ph.markdown(_step_cards_html(), unsafe_allow_html=True)
        terminal_ph.markdown(_terminal_html(), unsafe_allow_html=True)
        plan_ph.markdown(_plan_html(), unsafe_allow_html=True)
        if st.session_state.loop_num > 0:
            loop_ph.markdown(
                f'<div class="loop-counter">AUTONOMOUS LOOP: {st.session_state.loop_num} / 3</div>',
                unsafe_allow_html=True,
            )

    try:
        with requests.post(STREAM_URL, json=payload, stream=True, timeout=180) as resp:
            ev, data = "", {}
            for raw in resp.iter_lines():
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if line.startswith("event:"):
                    ev = line[6:].strip(); continue
                if line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                    except:
                        data = {}
                else:
                    continue
                if not ev:
                    continue

                if ev == "start":
                    set_step("THINK", "active")
                    add_log(f"Workflow {data.get('workflow_id', '')} started", "system")

                elif ev == "think":
                    set_step("THINK", "active")
                    add_log("Scanning memory for similar workflows…", "think")

                elif ev == "memory_recall":
                    set_step("THINK", "done")
                    add_log(f"Memory scan complete — {data.get('count', 0)} hint(s)", "think")
                    for h in data.get("hints", [])[:2]:
                        if h:
                            add_log(h[:85], "memory", indent=True)

                elif ev == "loop_start":
                    st.session_state.loop_num = data.get("loop", 1)
                    add_log(f"─── Loop {data['loop']} / {data['max_loops']} ───", "gray")
                    fb = data.get("feedback", "")
                    if fb:
                        add_log(f"Feedback → {fb[:95]}", "update", indent=True)

                elif ev == "plan":
                    set_step("THINK", "done"); set_step("PLAN", "active")
                    add_log("Generating execution plan…", "plan")

                elif ev == "plan_ready":
                    set_step("PLAN", "done")
                    st.session_state.current_plan = data.get("plan", {})
                    add_log(f"{data.get('steps_count')} steps · type={data.get('workflow_type')} · risk={data.get('risk_level')}", "plan")
                    for ps in st.session_state.current_plan.get("steps", []):
                        deps  = ps.get("depends_on", [])
                        dep_s = f" ← [{','.join(map(str, deps))}]" if deps else ""
                        add_log(f"{ps.get('step_number')}. {ps.get('tool')}.{ps.get('action')}(){dep_s}", "plan", indent=True)

                elif ev == "execute":
                    set_step("PLAN", "done"); set_step("EXECUTE", "active")
                    add_log("Dispatching tools…", "execute")

                elif ev == "step_start":
                    add_log(f"Step {data.get('step', '?')} → {data.get('tool')}.{data.get('action')}()", "execute")
                    if data.get("description"):
                        add_log(data["description"][:65], "execute", indent=True)

                elif ev == "step_done":
                    sn  = data.get("step", "?")
                    st2 = data.get("status", "")
                    out = data.get("output", {})
                    out_str = json.dumps(out, default=str)[:80]
                    # Store tool output for TAB 3
                    tool_name = data.get("tool", f"step_{sn}")
                    if out:
                        st.session_state.tool_outputs[tool_name] = out
                    if st2 == "completed":
                        add_log(f"Step {sn} ✓  {out_str}", "execute", indent=True)
                    else:
                        err = (data.get("error", "") or "")[:75]
                        add_log(f"Step {sn} ✗  {err}", "error", indent=True)

                elif ev == "review":
                    set_step("EXECUTE", "done"); set_step("REVIEW", "active")
                    add_log("Evaluating execution quality…", "review")

                elif ev == "review_done":
                    set_step("REVIEW", "done")
                    rpass = data.get("passed", False)
                    conf  = data.get("confidence", 0)
                    add_log(
                        f"{'PASSED ✓' if rpass else 'FAILED ✗'}  conf={conf:.0%}  "
                        f"{data.get('summary', '')[:70]}",
                        "review",
                    )
                    for iss in data.get("issues", [])[:2]:
                        add_log(iss[:75], "error", indent=True)
                    if not rpass:
                        for rec in data.get("recommendations", [])[:1]:
                            add_log(rec[:75], "update", indent=True)

                elif ev == "update":
                    set_step("UPDATE", "active")
                    action = data.get("action", "")
                    if action == "pass":
                        set_step("UPDATE", "done")
                        add_log("Quality gate passed — persisting to memory", "done")
                    elif action == "retry":
                        set_step("UPDATE", "done")
                        set_step("EXECUTE", "pending"); set_step("REVIEW", "pending")
                        add_log(f"Self-correcting → {data.get('feedback', '')[:85]}", "update")
                    else:
                        set_step("UPDATE", "done")
                        add_log(data.get("message", "")[:75], "update")

                elif ev == "memory_stored":
                    add_log(f"Stored in memory · category={data.get('category', 'general')}", "memory")
                    mem_ph.markdown(_memory_html(), unsafe_allow_html=True)

                elif ev == "complete":
                    rpass = data.get("passed", False)
                    st.session_state.result = data
                    if rpass:
                        st.session_state.runs_passed += 1
                    add_log(f"{'COMPLETE ✓' if rpass else 'PARTIAL ⚑'}  loops={data.get('loops_used', '?')}", "done")
                    for na in data.get("next_actions", [])[:2]:
                        add_log(na[:65], "gray", indent=True)

                elif ev == "error":
                    add_log(f"ERROR: {data.get('message', '')[:95]}", "error")

                ev = ""; data = {}
                _refresh()

    except requests.exceptions.ConnectionError:
        add_log("Cannot connect to backend on :8000", "error")
        add_log("cd Backend && uvicorn app.main:app --reload --port 8000", "gray", indent=True)
        for s in AGENT_STEPS:
            if st.session_state.step_status[s] == "active":
                set_step(s, "failed")
    except Exception as e:
        add_log(f"Stream error: {str(e)[:90]}", "error")
    finally:
        st.session_state.running = False

    _refresh()
    mem_ph.markdown(_memory_html(), unsafe_allow_html=True)

    # ── Post-run education expander (StudAI feature) ──────────────────────
    st.rerun()


# ── Post-run education (shown after a result is stored) ──────────────────────
if st.session_state.result and not st.session_state.running:
    loops_used = st.session_state.loop_num or st.session_state.result.get("loops_used", 1)
    with st.expander("🎓 What just happened? (The autonomy explained)", expanded=False):
        st.markdown(f"""
**The agent ran {loops_used} loop{'s' if loops_used > 1 else ''}** to remediate this payment failure. Here's what happened:

1. **THINK** — Scanned memory for similar past payment failures. On retries, incorporated reviewer feedback on which steps to improve.

2. **PLAN** — Created a JSON execution plan: run payment_verifier → db_lookup → ticket_creator → notifier. It decided this order itself.

3. **EXECUTE** — Ran **4 tools** in sequence:
   - **Payment Verifier** → Stripe sandbox: confirmed charge status
   - **DB Lookup** → Ledger: validated transaction record
   - **Ticket Creator** → ServiceNow: opened incident ticket
   - **Notifier** → Webhook/email: confirmed to student & bursar

4. **REVIEW** — Scored each step against remediation criteria. Checked: tool success, data consistency, notification delivery, refund eligibility.

5. **UPDATE** — {'Quality gate passed. Result stored to memory.' if loops_used == 1 else f'Self-corrected {loops_used - 1} time(s) based on reviewer feedback before passing.'}

**Next step:** Review the Summary tab, download the report, and close the ServiceNow ticket.
        """)