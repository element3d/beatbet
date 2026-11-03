import time

RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT_SECONDS = 10


def with_retry(fetch, *args):
    """Call fetch, waiting and retrying when API-Football reports its per-minute rate limit."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return fetch(*args)
        except RuntimeError as error:
            if "rateLimit" not in str(error) or attempt == RATE_LIMIT_RETRIES:
                raise
            time.sleep(RATE_LIMIT_WAIT_SECONDS)
