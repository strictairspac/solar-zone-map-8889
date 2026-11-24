from dataclasses import dataclass


@dataclass(frozen=True)
class Predicate:
    mode: str
    low: int | None = None
    high: int | None = None

    def page_may_match(self, zone):
        if self.mode == "null":
            return zone.nulls > 0
        return zone.valid_mask != 0 and zone.minimum <= self.high and zone.maximum >= self.low

    def select_offsets(self, power, zone):
        if self.mode == "null":
            return [offset for offset in range(zone.count) if not zone.valid_mask & (1 << offset)]
        return [
            offset for offset, watts in enumerate(power)
            if zone.valid_mask & (1 << offset) and self.low <= watts <= self.high
        ]

    def matches_row(self, power):
        if self.mode == "null":
            return power is None
        return power is not None and self.low <= power <= self.high
