"""
AutoOps AI — Autonomy Proof Trace
===================================
Run this script to generate a live agent trace showing the full
Think → Plan → Execute → Review → Update loop.

This output is your "Autonomy Proof" for CP2 and final submission.

Usage:
    cd Backend
    python trace_demo.py

    # Or pipe to a file for submission:
    python trace_demo.py > agent_trace.txt

Set your ANTHROPIC_API_KEY in .env or as an environment variable.
"""

import asyncio
import json
import os
import sys
from datetime import datetime

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


DEMO_TASKS = [
    {
        "name": "Tuition Payment Failed",
        "task": "Student payment failed but tuition fee was deducted. Student ID: STU-00123, amount $2999.",
        "context": {"student_id": "STU-00123", "amount": 2999, "currency": "USD"},
    },
    {
        "name": "Duplicate Tuition Charge",
        "task": "Student STU-00456 was charged twice for $1499 tuition payment.",
        "context": {"student_id": "STU-00456", "amount": 1499},
    },
    {
        "name": "Bursar Refund Request",
        "task": "Process refund for failed tuition payment TXN-AB12CD34.",
        "context": {"transaction_id": "TXN-AB12CD34", "reason": "Payment gateway failure"},
    },
]
    },
]

DIVIDER = "═" * 70
THIN    = "─" * 70


def ts():
    return datetime.now().strftime("%H:%M:%S")


def header(text):
    print(f"\n{DIVIDER}")
    print(f"  {text}")
    print(DIVIDER)


def section(label, value=""):
    print(f"\n  [{ts()}] {label}")
    if value:
        print(f"           {value}")


def step_line(step_num, tool, action, status, output=None, error=None):
    icon = "✓" if status == "completed" else "✗"
    print(f"    {icon} Step {step_num}: {tool}.{action}() → {status}")
    if output:
        preview = json.dumps(output, default=str)[:120]
        print(f"             Output: {preview}...")
    if error:
        print(f"             Error:  {error}")


async def run_trace():
    # Check for API key
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("\n⚠  ANTHROPIC_API_KEY not set.")
        print("   Set it in Backend/.env:  ANTHROPIC_API_KEY=sk-ant-...")
        print("   Running in MOCK MODE — showing trace structure only.\n")
        run_mock_trace()
        return

    from app.services.agent_service import run_autonomous_workflow_streaming

    print(f"\n{'╔' + '═'*68 + '╗'}")
    print(f"{'║':1}{'AutoOps AI — Live Autonomy Proof Trace':^68}{'║':1}")
    print(f"{'║':1}{'Think → Plan → Execute → Review → Update Loop':^68}{'║':1}")
    print(f"{'╚' + '═'*68 + '╝'}")

    for demo in DEMO_TASKS:
        header(f"SCENARIO: {demo['name']}")
        print(f"  Task: {demo['task']}")

        loop_num = 0
        try:
            async for event, data in run_autonomous_workflow_streaming(
                demo["task"], demo.get("context")
            ):
                if event == "think":
                    section("THINK", "Searching memory for similar workflows...")
                elif event == "memory_recall":
                    section("THINK ✓", f"Memory: {data['message']}")
                elif event == "loop_start":
                    loop_num = data["loop"]
                    print(f"\n  {THIN}")
                    print(f"  LOOP {loop_num} of {data['max_loops']}", end="")
                    if data.get("feedback"):
                        print(f"  ← Retrying with feedback")
                        print(f"    Feedback: {data['feedback'][:100]}")
                    else:
                        print()
                elif event == "plan_ready":
                    section("PLAN ✓", f"Generated {data['steps_count']} steps | type={data['workflow_type']} | risk={data['risk_level']}")
                    for i, step in enumerate(data["plan"].get("steps", []), 1):
                        print(f"    {i}. {step['tool']}.{step['action']}() — {step.get('description','')}")
                elif event == "step_done":
                    step_line(
                        data["step"], "", "",
                        data["status"],
                        data.get("output"),
                        data.get("error"),
                    )
                elif event == "review_done":
                    icon = "✓ PASSED" if data["passed"] else "✗ FAILED"
                    section(f"REVIEW {icon}",
                            f"confidence={data.get('confidence', 0):.0%} | {data.get('summary','')[:80]}")
                    if data.get("issues"):
                        print(f"    Issues: {'; '.join(data['issues'][:2])}")
                    if data.get("recommendations") and not data["passed"]:
                        print(f"    Fix:    {'; '.join(data['recommendations'][:2])}")
                elif event == "update":
                    action = data.get("action", "")
                    if action == "pass":
                        section("UPDATE ✓", data["message"])
                    elif action == "retry":
                        section("UPDATE ↻", f"Self-correcting — {data.get('feedback','')[:80]}")
                    elif action == "max_loops":
                        section("UPDATE ⚑", data["message"])
                elif event == "memory_stored":
                    section("MEMORY ✓", f"Stored in '{data['category']}' — future runs will be smarter")
                elif event == "complete":
                    status = "COMPLETED ✓" if data["passed"] else "PARTIAL ⚑"
                    section(f"DONE — {status}",
                            f"Loops used: {data['loops_used']} | {data.get('summary','')[:80]}")
                    if data.get("next_actions"):
                        print(f"    Next: {'; '.join(data['next_actions'][:2])}")
                elif event == "error":
                    section("ERROR ✗", data["message"])
                    break

        except Exception as e:
            print(f"\n  ⚠  Error during trace: {e}")
            print("     Check your ANTHROPIC_API_KEY and internet connection.")

        print(f"\n  {THIN}\n")

    print(f"\n{DIVIDER}")
    print(f"  Trace complete. This output is your CP2 Autonomy Proof.")
    print(f"  Save it: python trace_demo.py > agent_trace.txt")
    print(DIVIDER)


def run_mock_trace():
    """
    Shows the trace structure without real API calls.
    Use this to verify the loop is wired correctly before adding your API key.
    """
    print(f"\n{'╔' + '═'*68 + '╗'}")
    print(f"{'║':1}{'AutoOps AI — MOCK Trace (no API key)':^68}{'║':1}")
    print(f"{'╚' + '═'*68 + '╝'}")

    task = "Customer payment failed but money was deducted."
    print(f"\n  Task: {task}\n")

    print("  [THINK]  Searching memory...")
    print("  [THINK ✓] Found 1 relevant memory: [payment] Problem: Customer payment failed...")

    print(f"\n  {THIN}")
    print("  LOOP 1 of 3")
    print(f"\n  [PLAN ✓]  3 steps | type=payment | risk=high")
    print("    1. payment_tool.get_transaction() — Retrieve transaction details")
    print("    2. payment_tool.refund()          — Initiate refund")
    print("    3. notification_tool.send_email() — Notify customer")

    print("\n  [EXECUTE]")
    print("    ✓ Step 1: payment_tool.get_transaction() → completed")
    print("             Output: {\"transaction_id\": \"TXN-AB12CD34\", \"status\": \"completed\"...")
    print("    ✓ Step 2: payment_tool.refund() → completed")
    print("             Output: {\"status\": \"refunded\", \"refund_id\": \"REF-XY98ZW76\"...")
    print("    ✓ Step 3: notification_tool.send_email() → completed")
    print("             Output: {\"status\": \"sent\", \"message_id\": \"MSG-12AB34CD\"...")

    print("\n  [REVIEW ✓ PASSED]  confidence=92% | Refund initiated and customer notified")
    print("  [UPDATE ✓]  Quality check passed on loop 1")
    print("  [MEMORY ✓]  Stored in 'payment' — future runs will be smarter")
    print("  [DONE — COMPLETED ✓]  Loops used: 1")

    print(f"\n  {THIN}")
    print("\n  Now try with a real API key to see live traces!")
    print(f"  Add ANTHROPIC_API_KEY to Backend/.env and re-run.\n")


if __name__ == "__main__":
    asyncio.run(run_trace())
