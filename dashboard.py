"""
AutoOps AI — Streamlit Dashboard
==================================
Runs autonomously by streaming events from the FastAPI SSE endpoint.

Start commands:
    # Terminal 1 — Backend
    cd Backend && uvicorn app.main:app --reload --port 8000

    # Terminal 2 — Dashboard
    streamlit run dashboard.py

    # Add your API key in Backend/.env:
    ANTHROPIC_API_KEY=sk-ant-...
"""

import json
import time
import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND = "http://localhost:8000"
STREAM_URL = f"{BACKEND}/workflow/stream"
MEMORY_URL = f"{BACKEND}/workflow/memory/stats"
MEMORY_SEARCH_URL = f"{BACKEND}/workflow/memory/search"

DEMO_TASKS = {
    "💳 Payment Failure": {
        "task": "Customer payment failed but money was deducted. Customer ID: CUST-00123, amount Rs.2999.",
        "context": {"customer_id": "CUST-00123", "amount": 2999, "currency": "INR"},
    },
    "📄 Invoice Generation": {
        "task": "Generate invoice for order ORD-5487 and email to customer.",
        "context": {"order_id": "ORD-5487"},
    },
    "👥 Resume Screening": {
        "task": "Screen 15 resumes for Senior Python Developer position. Need 3+ years Python and FastAPI.",
        "context": {"job_title": "Senior Python Developer", "min_experience": 3},
    },
    "📊 Sales Report": {
        "task": "Generate weekly sales operations report for Q1 2026 and notify management team.",
        "context": {"period": "weekly", "quarter": "Q1-2026"},
    },
    "🚨 Delivery Investigation": {
        "task": "Customer says order ORD-5487 was never delivered but system shows delivered.",
        "context": {"order_id": "ORD-5487"},
    },
}

STEP_COLORS = {
    "THINK":   "#7C3AED",
    "PLAN":    "#0F6E56",
    "EXECUTE": "#1D4ED8",
    "REVIEW":  "#B45309",
    "UPDATE":  "#991B1B",
    "MEMORY":  "#6B21A8",
    "DONE":    "#166534",
}

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AutoOps AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* Header */
    .main-title {
        font-size: 2rem; font-weight: 800;
        background: linear-gradient(135deg, #6B21A8, #0F6E56);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .sub-title { font-size: 0.9rem; color: #6B7280; margin-top: 2px; margin-bottom: 1rem; }

    /* Step cards */
    .step-row { display: flex; gap: 8px; margin: 8px 0; }
    .step-card {
        flex: 1; text-align: center; padding: 10px 6px;
        border-radius: 8px; font-size: 12px; font-weight: 600;
        border: 1.5px solid #E5E7EB; background: #F9FAFB; color: #9CA3AF;
        transition: all 0.3s;
    }
    .step-active  { background: #FEF3C7; border-color: #F59E0B; color: #B45309; }
    .step-done    { background: #ECFDF5; border-color: #10B981; color: #065F46; }
    .step-skipped { background: #F3E8FF; border-color: #8B5CF6; color: #5B21B6; }
    .step-failed  { background: #FEF2F2; border-color: #EF4444; color: #991B1B; }

    /* Log box */
    .log-line { font-family: 'Courier New', monospace; font-size: 12px;
                padding: 2px 0; border-bottom: 1px solid #F3F4F6; }
    .log-think   { color: #7C3AED; }
    .log-plan    { color: #0F6E56; }
    .log-execute { color: #1D4ED8; }
    .log-review  { color: #B45309; }
    .log-update  { color: #991B1B; }
    .log-memory  { color: #6B21A8; }
    .log-done    { color: #166534; font-weight: 600; }
    .log-error   { color: #DC2626; font-weight: 600; }
    .log-gray    { color: #6B7280; }

    /* Result card */
    .result-card {
        background: #F0FDF4; border: 1.5px solid #10B981;
        border-radius: 10px; padding: 16px; margin-top: 8px;
    }
    .result-fail {
        background: #FEF2F2; border-color: #EF4444;
    }

    /* Memory item */
    .mem-item {
        background: #F5F3FF; border-left: 3px solid #7C3AED;
        padding: 6px 10px; margin: 4px 0; border-radius: 4px;
        font-size: 12px;
    }

    /* Loop badge */
    .loop-badge {
        display: inline-block; background: #1E1B4B; color: #A5B4FC;
        font-family: monospace; font-size: 12px; font-weight: 700;
        padding: 4px 14px; border-radius: 20px; margin: 8px 0;
    }

    /* Hide streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "logs"        not in st.session_state: st.session_state.logs = []
if "step_status" not in st.session_state: st.session_state.step_status = {}
if "result"      not in st.session_state: st.session_state.result = None
if "loop_num"    not in st.session_state: st.session_state.loop_num = 0
if "running"     not in st.session_state: st.session_state.running = False
if "memories"    not in st.session_state: st.session_state.memories = []

STEPS = ["THINK", "PLAN", "EXECUTE", "REVIEW", "UPDATE"]

def reset():
    st.session_state.logs        = []
    st.session_state.step_status = {s: "pending" for s in STEPS}
    st.session_state.result      = None
    st.session_state.loop_num    = 0

def set_step(name, status):
    if name in st.session_state.step_status:
        st.session_state.step_status[name] = status

def add_log(msg, category="gray"):
    ts = time.strftime("%H:%M:%S")
    st.session_state.logs.append((ts, msg, category))

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ AutoOps AI")
    st.caption("Autonomous Operations Manager")
    st.divider()

    st.markdown("**Backend**")
    try:
        r = requests.get(f"{BACKEND}/health", timeout=2)
        if r.status_code == 200:
            st.success("✓ Connected to FastAPI backend")
        else:
            st.error("Backend returned non-200")
    except Exception:
        st.error("Cannot reach backend at localhost:8000")
        st.caption("Start with: `uvicorn app.main:app --reload`")

    st.divider()
    st.markdown("**The Autonomy Loop**")
    st.markdown("""
```
THINK   → search memory
PLAN    → generate JSON plan
EXECUTE → run tools
REVIEW  → score quality
UPDATE  → retry if needed
         ↑_____________↓
         (up to 3 loops)
```
""")
    st.divider()

    # Memory stats
    st.markdown("**Memory Store**")
    try:
        stats = requests.get(MEMORY_URL, timeout=2).json()
        st.metric("Total memories", stats.get("total_memories", 0))
        cats = stats.get("categories", {})
        if cats:
            for cat, count in cats.items():
                st.caption(f"  {cat}: {count}")
    except Exception:
        st.caption("(backend offline)")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">⚡ AutoOps AI</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Autonomous Operations Manager — Think · Plan · Execute · Review · Update</div>', unsafe_allow_html=True)

# ── Main layout ───────────────────────────────────────────────────────────────
col_left, col_right = st.columns([2, 3], gap="large")

with col_left:
    st.markdown("#### Submit a Workflow")

    # Workflow selector
    selected = st.selectbox("Choose a demo workflow", list(DEMO_TASKS.keys()))
    demo = DEMO_TASKS[selected]

    # Editable task text
    task_text = st.text_area(
        "Task description",
        value=demo["task"],
        height=90,
        help="Edit the task or type your own",
    )

    # Run button
    run_col, clear_col = st.columns([3, 1])
    with run_col:
        run_btn = st.button(
            "🚀 Run Autonomous Workflow",
            use_container_width=True,
            type="primary",
            disabled=st.session_state.running,
        )
    with clear_col:
        if st.button("Clear", use_container_width=True):
            reset()
            st.rerun()

    # Step status cards
    st.markdown("#### Agent Loop Status")
    steps_html = '<div class="step-row">'
    for s in STEPS:
        status = st.session_state.step_status.get(s, "pending")
        cls = f"step-{status}" if status != "pending" else "step-card"
        icon = {"active": "⚙", "done": "✓", "failed": "✗", "skipped": "↩"}.get(status, "○")
        steps_html += f'<div class="step-card {cls}"><div style="font-size:18px">{icon}</div>{s}</div>'
    steps_html += '</div>'
    st.markdown(steps_html, unsafe_allow_html=True)

    if st.session_state.loop_num > 0:
        st.markdown(
            f'<div class="loop-badge">LOOP {st.session_state.loop_num} of 3</div>',
            unsafe_allow_html=True
        )

    # Result panel
    if st.session_state.result:
        r = st.session_state.result
        passed = r.get("passed", False)
        card_cls = "result-card" if passed else "result-card result-fail"
        icon = "✅" if passed else "⚠️"
        st.markdown(
            f'<div class="{card_cls}">'
            f'<strong>{icon} {"Completed" if passed else "Partial"}</strong><br>'
            f'Loops used: {r.get("loops_used", "—")} / 3<br>'
            f'<em>{r.get("summary", "")[:120]}</em>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if r.get("next_actions"):
            st.caption("Next actions: " + "; ".join(r["next_actions"][:2]))

with col_right:
    st.markdown("#### Live Agent Logs")

    log_placeholder = st.empty()

    def render_logs():
        if not st.session_state.logs:
            log_placeholder.markdown(
                '<div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;'
                'padding:16px;min-height:340px;color:#9CA3AF;font-size:13px;">'
                'Agent logs will stream here...'
                '</div>',
                unsafe_allow_html=True,
            )
            return
        lines = []
        for ts, msg, cat in st.session_state.logs[-60:]:
            cls = f"log-{cat}"
            lines.append(
                f'<div class="log-line {cls}">'
                f'<span style="color:#9CA3AF">[{ts}]</span> {msg}'
                f'</div>'
            )
        log_placeholder.markdown(
            '<div style="background:#0F172A;border-radius:8px;padding:12px;'
            f'min-height:340px;max-height:480px;overflow-y:auto;">'
            + "".join(lines) + '</div>',
            unsafe_allow_html=True,
        )

    render_logs()

    # Memory panel below logs
    st.markdown("#### Memory Store (Self-Learning)")
    mem_placeholder = st.empty()

    def render_memory():
        try:
            result = requests.get(f"{MEMORY_SEARCH_URL}?q=&top_k=5", timeout=2).json()
            items = result.get("results", [])
            if not items:
                mem_placeholder.caption("No memories yet. Run a workflow to see self-learning.")
                return
            html = ""
            for item in items[:5]:
                doc = item.get("document", "")[:120]
                html += f'<div class="mem-item">📌 {doc}...</div>'
            mem_placeholder.markdown(html, unsafe_allow_html=True)
        except Exception:
            mem_placeholder.caption("(backend offline)")

    render_memory()

# ── Run workflow with SSE streaming ──────────────────────────────────────────
if run_btn:
    reset()
    st.session_state.running = True
    st.session_state.step_status = {s: "pending" for s in STEPS}

    payload = {"task": task_text, "context": demo.get("context", {})}
    add_log(f"Starting: {task_text[:60]}...", "gray")

    try:
        with requests.post(STREAM_URL, json=payload, stream=True, timeout=120) as resp:
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8")
                if line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    # will be set from event: line
                if line.startswith("event:"):
                    event = line[6:].strip()
                    continue

                # parse event+data pairs
                event_name = ""
                data = {}
                for raw in raw_line.decode("utf-8").split("\n"):
                    if raw.startswith("event:"):
                        event_name = raw[6:].strip()
                    elif raw.startswith("data:"):
                        try:
                            data = json.loads(raw[5:].strip())
                        except Exception:
                            pass

                if not event_name:
                    continue

                # Process events
                if event_name == "start":
                    set_step("THINK", "active")
                    add_log(f"Workflow started: {data.get('workflow_id','')}", "gray")

                elif event_name == "think":
                    set_step("THINK", "active")
                    add_log("🧠 THINK — Searching memory...", "think")

                elif event_name == "memory_recall":
                    set_step("THINK", "done")
                    add_log(f"🧠 THINK ✓ {data.get('message','')}", "think")
                    hints = data.get("hints", [])
                    for h in hints:
                        if h:
                            add_log(f"   Memory: {h[:80]}", "memory")

                elif event_name == "loop_start":
                    st.session_state.loop_num = data.get("loop", 1)
                    fb = data.get("feedback", "")
                    add_log(f"── Loop {data['loop']} of {data['max_loops']} ──", "gray")
                    if fb:
                        add_log(f"   Feedback: {fb[:100]}", "update")

                elif event_name == "plan":
                    set_step("PLAN", "active")
                    add_log("📋 PLAN — Generating execution plan...", "plan")

                elif event_name == "plan_ready":
                    set_step("PLAN", "done")
                    add_log(
                        f"📋 PLAN ✓ {data.get('steps_count')} steps | "
                        f"type={data.get('workflow_type')} | risk={data.get('risk_level')}",
                        "plan"
                    )
                    for step in data.get("plan", {}).get("steps", []):
                        add_log(
                            f"   {step['step_number']}. {step['tool']}.{step['action']}() — {step.get('description','')[:60]}",
                            "plan"
                        )

                elif event_name == "execute":
                    set_step("EXECUTE", "active")
                    add_log("⚙️ EXECUTE — Running tools...", "execute")

                elif event_name == "step_start":
                    add_log(
                        f"   → Step {data['step']}: {data['tool']}.{data['action']}()",
                        "execute"
                    )

                elif event_name == "step_done":
                    icon = "✓" if data["status"] == "completed" else "✗"
                    out = json.dumps(data.get("output", {}), default=str)[:100]
                    add_log(
                        f"   {icon} Step {data['step']} {data['status']} | {out}",
                        "execute" if data["status"] == "completed" else "error"
                    )

                elif event_name == "review":
                    set_step("EXECUTE", "done")
                    set_step("REVIEW", "active")
                    add_log("🔍 REVIEW — Evaluating results...", "review")

                elif event_name == "review_done":
                    set_step("REVIEW", "done")
                    passed = data.get("passed", False)
                    icon = "✓ PASSED" if passed else "✗ FAILED"
                    add_log(
                        f"🔍 REVIEW {icon} | confidence={data.get('confidence', 0):.0%} | {data.get('summary','')[:80]}",
                        "review"
                    )
                    if data.get("issues"):
                        add_log(f"   Issues: {'; '.join(data['issues'][:2])}", "error")
                    if data.get("recommendations") and not passed:
                        add_log(f"   Fix: {'; '.join(data['recommendations'][:2])}", "update")

                elif event_name == "update":
                    set_step("UPDATE", "active")
                    action = data.get("action", "")
                    if action == "pass":
                        set_step("UPDATE", "skipped")
                        add_log(f"✅ UPDATE — {data['message']}", "done")
                    elif action == "retry":
                        set_step("UPDATE", "done")
                        add_log(f"🔄 UPDATE — Self-correcting: {data.get('feedback','')[:80]}", "update")
                    else:
                        set_step("UPDATE", "done")
                        add_log(f"⚑ UPDATE — {data.get('message','')}", "update")

                elif event_name == "memory_stored":
                    add_log(
                        f"💾 MEMORY — Stored in '{data.get('category','')}' | {data.get('message','')}",
                        "memory"
                    )

                elif event_name == "complete":
                    passed = data.get("passed", False)
                    st.session_state.result = data
                    add_log(
                        f"{'✅ DONE — COMPLETED' if passed else '⚑ DONE — PARTIAL'} | "
                        f"Loops: {data.get('loops_used','?')} | {data.get('summary','')[:80]}",
                        "done"
                    )
                    if data.get("next_actions"):
                        add_log(f"   Next: {'; '.join(data['next_actions'][:2])}", "gray")

                elif event_name == "error":
                    add_log(f"❌ ERROR: {data.get('message','')}", "error")

                # Re-render after each event
                render_logs()

    except requests.exceptions.ConnectionError:
        add_log("❌ Cannot connect to backend. Is FastAPI running on port 8000?", "error")
        add_log("   Start it: cd Backend && uvicorn app.main:app --reload", "gray")
    except Exception as e:
        add_log(f"❌ Error: {str(e)[:100]}", "error")
    finally:
        st.session_state.running = False

    render_logs()
    render_memory()
    st.rerun()
