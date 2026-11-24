from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    minimum: int | None
    maximum: int | None
    valid_mask: int
    count: int

    @property
    def nulls(self):
        return self.count - self.valid_mask.bit_count()


@dataclass(frozen=True)
class Page:
    serials: tuple[str, ...]
    power: tuple[int | None, ...]
    power_zone: Zone


def build_page(records):
    serials, powers = zip(*records)
    valid_mask = sum(1 << offset for offset, power in enumerate(powers) if power is not None)
    numeric = [power for power in powers if power is not None]
    zone = Zone(min(numeric, default=None), max(numeric, default=None), valid_mask, len(powers))
    return Page(serials, powers, zone)


def build_pages(records, capacity):
    return [build_page(records[offset:offset + capacity]) for offset in range(0, len(records), capacity)]
