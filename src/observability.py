from __future__ import annotations

from collections import Counter, defaultdict
from threading import Lock


class MetricsRegistry:
    """Small in-process Prometheus registry with no external runtime dependency."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._observations: defaultdict[
            tuple[str, tuple[tuple[str, str], ...]], list[float]
        ] = defaultdict(list)

    @staticmethod
    def _key(
        name: str,
        labels: dict[str, object] | None,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        normalized = tuple(
            sorted((key, str(value)) for key, value in (labels or {}).items())
        )
        return name, normalized

    def increment(
        self,
        name: str,
        value: float = 1,
        *,
        labels: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            self._observations[self._key(name, labels)].append(value)

    @staticmethod
    def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        escaped = []
        for key, value in labels:
            safe = value.replace("\\", "\\\\").replace('"', '\\"')
            escaped.append(f'{key}="{safe}"')
        return "{" + ",".join(escaped) + "}"

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            observations = {key: list(values) for key, values in self._observations.items()}
        for (name, labels), value in sorted(counters.items()):
            lines.append(f"{name}_total{self._format_labels(labels)} {value:g}")
        for (name, labels), value in sorted(gauges.items()):
            lines.append(f"{name}{self._format_labels(labels)} {value:g}")
        for (name, labels), values in sorted(observations.items()):
            if not values:
                continue
            suffix = self._format_labels(labels)
            lines.append(f"{name}_count{suffix} {len(values)}")
            lines.append(f"{name}_sum{suffix} {sum(values):g}")
        return "\n".join(lines) + ("\n" if lines else "")


metrics = MetricsRegistry()
