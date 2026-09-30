"""One HTTP session shared by every extractor: timeouts, retries and a polite User-Agent."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT_SECONDS = 30
USER_AGENT = "delivery-risk-analytics/0.1 (portfolio project)"


def build_session(total_retries: int = 3, backoff_factor: float = 1.0) -> requests.Session:
    """Return a session that retries rate limits (429) and server errors (5xx) with exponential backoff.

    Client errors such as 404 are not retried: asking again will not fix a wrong URL.
    """
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session
