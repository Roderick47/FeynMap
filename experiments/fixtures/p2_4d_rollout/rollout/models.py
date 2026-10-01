from dataclasses import dataclass


@dataclass
class Release:
    name: str
    remaining_hosts: int
    status: str = "ready"


def health_window_default():
    return 15
