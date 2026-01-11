"""
Secret Scrubbing

Detection and removal of sensitive data before embedding.
"""

import re

# Pattern tuples: (regex_pattern, replacement_text)
SECRET_PATTERNS: list[tuple[str, str]] = [
    # AWS
    (r"AKIA[0-9A-Z]{16}", "[AWS_ACCESS_KEY_REDACTED]"),
    (
        r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?",
        "[AWS_SECRET_REDACTED]",
    ),
    # GitHub
    (r"ghp_[a-zA-Z0-9]{36}", "[GITHUB_PAT_REDACTED]"),
    (r"gho_[a-zA-Z0-9]{36}", "[GITHUB_OAUTH_REDACTED]"),
    (r"ghu_[a-zA-Z0-9]{36}", "[GITHUB_USER_REDACTED]"),
    (r"ghs_[a-zA-Z0-9]{36}", "[GITHUB_SERVER_REDACTED]"),
    (r"ghr_[a-zA-Z0-9]{36}", "[GITHUB_REFRESH_REDACTED]"),
    # Stripe
    (r"sk_(live|test)_[0-9a-zA-Z]{24,}", "[STRIPE_SECRET_REDACTED]"),
    (r"pk_(live|test)_[0-9a-zA-Z]{24,}", "[STRIPE_PUBLIC_REDACTED]"),
    # Slack
    (r"xox[bapors]-[0-9a-zA-Z\-]{10,}", "[SLACK_TOKEN_REDACTED]"),
    # Private keys
    (
        r"-----BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----",
        "[PRIVATE_KEY_REDACTED]",
    ),
    # Anthropic
    (r"sk-ant-[a-zA-Z0-9\-]{20,}", "[ANTHROPIC_KEY_REDACTED]"),
    # OpenAI
    (r"sk-[a-zA-Z0-9]{48}", "[OPENAI_KEY_REDACTED]"),
    # Generic API keys/secrets in assignments
    (
        r'(?i)["\']?(?:api[_-]?key|secret|password|token|auth)["\']?\s*[:=]\s*["\'][^"\']{8,}["\']',
        "[SECRET_REDACTED]",
    ),
]


def scrub_secrets(text: str) -> str:
    """
    Remove sensitive data from text before embedding.

    Applies all patterns in SECRET_PATTERNS to redact sensitive information.

    Args:
        text: Text that may contain secrets

    Returns:
        Text with secrets replaced by redaction markers
    """
    for pattern, replacement in SECRET_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text
