def generate_plan(task: str):

    if "payment" in task.lower():
        return [
            "fetch_transaction",
            "verify_payment",
            "process_refund",
            "create_ticket",
            "notify_support"
        ]

    if "report" in task.lower():
        return [
            "fetch_sales_data",
            "analyze_data",
            "generate_report"
        ]

    if "invoice" in task.lower():
        return [
            "retrieve_order",
            "generate_invoice",
            "send_invoice"
        ]

    return ["analyze_request"]