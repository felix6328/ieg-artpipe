"""Calculate milestone and issue duration metrics from the local catalog."""
from datetime import datetime
import statistics


def milestones(db):
    rows = db.execute("SELECT * FROM milestone ORDER BY id").fetchall()
    work = db.execute("SELECT created_at, closed_at FROM issue WHERE state = 'closed' AND closed_at IS NOT NULL").fetchall()
    ages = sorted(_days(row["created_at"], row["closed_at"]) for row in work)
    durations = [dict(row) | {"delay_days": _days(row["due_on"], row["closed_at"])} for row in rows]
    return {"milestones": durations, "closed_art_issues": len(ages), "median": statistics.median(ages) if ages else None,
            "p75": statistics.quantiles(ages, n=4, method="inclusive")[2] if len(ages) >= 2 else None}


def markdown(report):
    text = ["# 美术项目里程碑", "",
            "计划日期采用上游当前记录的最终计划日期，可能经历过编辑。延期天数按关闭时刻减最终计划时刻计算。", "",
            f"已关闭美术 Issue {report['closed_art_issues']} 个，关闭耗时中位数 {report['median']} 天，"
            f"P75 {report['p75']} 天。", "",
            "| 里程碑 | 最终计划日期 | 关闭日期 | 延期天数 | 关闭 Issue |",
            "| --- | --- | --- | ---: | ---: |"]
    for row in report["milestones"]:
        delay = row["delay_days"]
        text.append(f"| {row['title']} | {_date(row['due_on'])} | {_date(row['closed_at'])} | "
                    f"{'—' if delay is None else f'{delay:+}'} | {row['closed_issues']} |")
    return "\n".join(text) + "\n"


def _days(start, end):
    if not (start and end):
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days


def _date(value):
    return value[:10] if value else "—"
