from backoff import retry_delay


assert [retry_delay(index) for index in range(7)] == [1, 2, 4, 8, 16, 30, 30]
assert retry_delay(5, base_seconds=2) == 30
