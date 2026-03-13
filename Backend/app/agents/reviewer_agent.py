def review_results(results):

    failures = [r for r in results if "error" in r.lower()]

    if failures:
        return "Workflow failed"

    return "Workflow completed successfully"