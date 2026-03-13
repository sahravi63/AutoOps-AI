async def parse_resume(file):

    content = await file.read()
    text = content.decode("utf-8", errors="ignore")

    return text