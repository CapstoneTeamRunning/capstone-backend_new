import re
from datetime import datetime


def generate_code_prefix(file_name: str) -> str:
    year = str(datetime.now().year)

    year_match = re.search(r"(\d{2,4})[년_]", file_name) or re.search(r"^(\d{4})", file_name)
    if year_match:
        y = year_match.group(1)
        year = f"20{y}" if len(y) == 2 else y

    if "학력평가" in file_name or "학평" in file_name:
        year = str(int(year) + 1)

    grade_match = re.search(r"고([1-3])", file_name) or re.search(r"G([1-3])", file_name, flags=re.IGNORECASE)
    grade = grade_match.group(1) if grade_match else "3"

    exam_type = "TEST"
    if any(keyword in file_name for keyword in ("수능", "대학수학능력시험", "CSAT")):
        exam_type = "CS"
    elif grade == "3" and re.search(r"0?6[월모평]", file_name):
        exam_type = "06M"
    elif grade == "3" and re.search(r"0?9[월모평]", file_name):
        exam_type = "09M"
    else:
        month_match = re.search(r"(\d{1,2})[월모학]", file_name)
        if month_match:
            month = month_match.group(1).zfill(2)
            exam_type = f"{month}G{grade}"

    return f"{year}-{exam_type}"
