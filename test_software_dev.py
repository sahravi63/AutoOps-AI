#!/usr/bin/env python3
"""
Track 3 test script for campus payment remediation.
This script validates the Bursar Office tuition payment recovery workflow.
"""

import json
import sys

import requests

def test_campus_payment_remediation_workflow():
    """Test the system with a campus tuition payment remediation task."""

    base_url = "http://localhost:8000"

    task_description = """
    Resolve a failed tuition payment for student STU-00123.
    The tuition charge of $2,999 was deducted, but the payment gateway returned a failure status.
    Verify the transaction, detect duplicate charges, create a remediation ticket if needed,
    and initiate refund reconciliation through the campus payment workflow.
    """

    print("🚀 Testing Track 3 campus payment remediation workflow")
    print("=" * 60)
    print(task_description.strip())
    print()

    payload = {
        "task": task_description,
        "context": {
            "tenant_id": "campus-bursar",
            "department": "bursar",
            "priority": "high"
        }
    }

    try:
        print("📡 Starting workflow...")
        response = requests.post(f"{base_url}/workflow/run", json=payload, timeout=180)
        response.raise_for_status()

        workflow_data = response.json()
        workflow_type = workflow_data.get("plan", {}).get("workflow_type", workflow_data.get("workflow_type", "unknown"))
        status = workflow_data.get("status", "unknown")
        review = workflow_data.get("review", {})

        print(f"✅ Workflow completed!")
        print(f"📊 Workflow type: {workflow_type}")
        print(f"📌 Status: {status}")
        print(f"📝 Review passed: {review.get('passed')}")
        print()

        print("📋 Workflow payload preview:")
        print("-" * 30)
        print(json.dumps(workflow_data, indent=2))

        if workflow_type != "payment_failure_remediation":
            print("⚠ Unexpected workflow type for this Track 3 test.")
            return 1
        return 0

    except requests.exceptions.RequestException as exc:
        print(f"❌ API request failed: {exc}")
        if exc.response is not None:
            print("Response:", exc.response.text)
        return 2
    except Exception as exc:
        print(f"❌ Unexpected error: {exc}")
        return 3

if __name__ == "__main__":
    sys.exit(test_campus_payment_remediation_workflow())