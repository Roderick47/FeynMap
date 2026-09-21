from headers import merge_headers


result = merge_headers(
    {"Content-Type": "application/json", "Accept": "application/json"},
    {"content-type": "text/plain", "X-Trace": "enabled"},
)
assert result == {
    "content-type": "text/plain",
    "Accept": "application/json",
    "X-Trace": "enabled",
}
