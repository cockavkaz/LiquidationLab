from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    timestamp: int  # UTC milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def validate(self) -> None:
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError('Prices must be positive')
        if self.high < max(self.open, self.close, self.low):
            raise ValueError('Invalid candle high')
        if self.low > min(self.open, self.close, self.high):
            raise ValueError('Invalid candle low')
        if self.volume < 0:
            raise ValueError('Negative volume')


@dataclass(frozen=True)
class Cluster:
    price: float
    intensity: float
    source: str  # 'demo' or 'imported'; this is never automatically measured market depth


@dataclass(frozen=True)
class Setup:
    impulse_direction: str
    impulse_size: float
    bottom: float
    top: float
    midpoint: float
    width_pct: float
    impulse_start: int
    impulse_end: int
    range_start: int
    range_end: int
