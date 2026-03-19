from dataclasses import dataclass


@dataclass
class ProviderResult:
    reply: str
    error_detail: str | None = None

