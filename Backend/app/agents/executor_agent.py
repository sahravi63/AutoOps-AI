from app.tools.payment_tool import verify_payment
from app.tools.report_tool import generate_report
from app.tools.invoice_tool import generate_invoice
from app.tools.notification_tool import notify_team

def execute_step(step: str):

    if step == "verify_payment":
        return verify_payment()

    if step == "process_refund":
        return "Refund initiated"

    if step == "generate_report":
        return generate_report()

    if step == "generate_invoice":
        return generate_invoice()

    if step == "notify_support":
        return notify_team("Support notified")

    return f"Executed step: {step}"