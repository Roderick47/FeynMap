from rollout.models import health_window_default


def apply_health_window_default(rows):
    for row in rows:
        if "health_window_minutes" not in row:
            row["health_window_minutes"] = health_window_default()
    return rows
