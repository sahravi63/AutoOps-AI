def evaluate_resume(text):

    skills = ["python", "fastapi", "machine learning", "sql"]

    score = 0

    for skill in skills:
        if skill in text.lower():
            score += 20

    return {
        "candidate_score": score,
        "status": "Shortlisted" if score >= 60 else "Rejected"
    }