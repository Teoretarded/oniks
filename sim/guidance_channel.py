"""Sensor-honest target-track channels for missile guidance.

This module is deliberately independent of the game world and of every target
entity type.  A channel receives only immutable numeric :class:`TrackEstimate`
samples plus explicit sensor/link booleans.  It therefore cannot silently read
ground truth when a command link, illuminator, or seeker is unavailable.

The channels own only the small state machine around those samples:

* live measurements replace the current estimate;
* loss freezes the last estimate at the loss time (zero velocity);
* command, SARH, and ARH channels may deterministically reacquire;
* an IR channel is terminally lost after its first lock breaks.

Acquisition geometry (range, cone, terrain, aspect, radar state) stays at the
integration boundary.  Callers evaluate that physics and pass the resulting
boolean here; no ``world`` or target-object reference crosses this API.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Sequence, TypeAlias


Vec3: TypeAlias = tuple[float, float, float]


class GuidanceMode(str, Enum):
    """Physical source of terminal guidance."""

    COMMAND = "command"
    SARH = "sarh"
    ARH = "arh"
    IR = "ir"


class TrackSource(str, Enum):
    """Provenance of a numeric track sample."""

    DATALINK = "datalink"
    COMMAND = "command"
    SARH = "sarh"
    ARH = "arh"
    IR = "ir"
    MEMORY = "memory"


class ChannelStatus(str, Enum):
    """Availability of guidance information."""

    SEARCHING = "searching"  # no estimate has ever been accepted
    TRACKING = "tracking"    # a live, physically permitted measurement
    MEMORY = "memory"        # frozen last estimate; reacquisition allowed
    LOST = "lost"            # terminal loss; reacquisition forbidden


def _vec3(value: Sequence[float], name: str) -> Vec3:
    try:
        result = tuple(float(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a three-number sequence") from exc
    if len(result) != 3:
        raise ValueError(f"{name} must contain exactly three values")
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{name} must contain only finite values")
    return result[0], result[1], result[2]


def _finite_time(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class TrackEstimate:
    """An immutable, entity-free target-state estimate.

    ``pos`` and ``vel`` are converted to tuples, so retaining or mutating an
    input list/array cannot mutate the estimate. ``track_id`` is deliberately a
    string rather than an arbitrary object: identity may cross this boundary,
    but an entity reference may not.
    """

    pos: Vec3
    vel: Vec3
    sample_time: float
    source: TrackSource
    track_id: str
    sigma_m: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "pos", _vec3(self.pos, "pos"))
        object.__setattr__(self, "vel", _vec3(self.vel, "vel"))
        object.__setattr__(
            self, "sample_time", _finite_time(self.sample_time, "sample_time"))
        try:
            source = TrackSource(self.source)
        except ValueError as exc:
            raise ValueError(f"unknown track source: {self.source!r}") from exc
        object.__setattr__(self, "source", source)
        if not isinstance(self.track_id, str):
            raise TypeError("track_id must be a string, never an entity reference")
        if not self.track_id:
            raise ValueError("track_id must not be empty")
        sigma = float(self.sigma_m)
        if not math.isfinite(sigma) or sigma < 0.0:
            raise ValueError("sigma_m must be finite and non-negative")
        object.__setattr__(self, "sigma_m", sigma)

    def position_at(self, now: float) -> Vec3:
        """Dead-reckon this sample to ``now`` without mutating it."""

        now = _finite_time(now, "now")
        dt = now - self.sample_time
        if dt < -1e-12:
            raise ValueError("cannot predict a track backward in time")
        dt = max(dt, 0.0)
        return (
            self.pos[0] + self.vel[0] * dt,
            self.pos[1] + self.vel[1] * dt,
            self.pos[2] + self.vel[2] * dt,
        )

    def with_source(self, source: TrackSource) -> "TrackEstimate":
        """Return the same numeric sample stamped with channel provenance."""

        return replace(self, source=TrackSource(source))


def freeze_estimate(estimate: TrackEstimate, now: float) -> TrackEstimate:
    """Freeze ``estimate`` at its dead-reckoned position at ``now``.

    Repeated channel-loss updates keep this exact sample; they do not continue
    drifting it or accumulate frame-rate-dependent error.
    """

    now = _finite_time(now, "now")
    return TrackEstimate(
        pos=estimate.position_at(now),
        vel=(0.0, 0.0, 0.0),
        sample_time=now,
        source=TrackSource.MEMORY,
        track_id=estimate.track_id,
        sigma_m=estimate.sigma_m,
    )


@dataclass(frozen=True, slots=True)
class ChannelState:
    """Immutable public snapshot of a channel's state."""

    mode: GuidanceMode
    status: ChannelStatus
    estimate: TrackEstimate | None
    updated_at: float | None
    acquired_once: bool
    terminal_committed: bool = False
    active_seeker: bool = False

    @property
    def has_live_track(self) -> bool:
        return self.status is ChannelStatus.TRACKING

    @property
    def has_guidance_estimate(self) -> bool:
        """True for a live track or a frozen inertial-memory point."""

        return self.estimate is not None


class _ChannelBase:
    """Shared deterministic state transitions; not part of the public API."""

    __slots__ = ("_state",)

    def __init__(self, mode: GuidanceMode) -> None:
        self._state = ChannelState(
            mode=mode,
            status=ChannelStatus.SEARCHING,
            estimate=None,
            updated_at=None,
            acquired_once=False,
        )

    @property
    def state(self) -> ChannelState:
        return self._state

    def _time(self, now: float) -> float:
        now = _finite_time(now, "now")
        previous = self._state.updated_at
        if previous is not None and now < previous - 1e-12:
            raise ValueError("channel updates must use monotonic simulation time")
        return now

    def _track(
        self,
        now: float,
        measurement: TrackEstimate,
        source: TrackSource,
        *,
        terminal_committed: bool | None = None,
        active_seeker: bool | None = None,
    ) -> ChannelState:
        if not isinstance(measurement, TrackEstimate):
            raise TypeError("measurement must be a TrackEstimate")
        if measurement.sample_time > now + 1e-12:
            raise ValueError("measurement sample_time cannot be in the future")
        old = self._state
        self._state = ChannelState(
            mode=old.mode,
            status=ChannelStatus.TRACKING,
            estimate=measurement.with_source(source),
            updated_at=now,
            acquired_once=True,
            terminal_committed=(old.terminal_committed
                                if terminal_committed is None
                                else bool(terminal_committed)),
            active_seeker=(old.active_seeker
                           if active_seeker is None
                           else bool(active_seeker)),
        )
        return self._state

    def _lose(
        self,
        now: float,
        *,
        terminal: bool = False,
        terminal_committed: bool | None = None,
        active_seeker: bool | None = None,
    ) -> ChannelState:
        old = self._state
        estimate = old.estimate
        # Freeze exactly once, on the live->lost edge. A MEMORY/LOST estimate
        # is already stationary and remains byte-identical on later updates.
        if old.status is ChannelStatus.TRACKING and estimate is not None:
            estimate = freeze_estimate(estimate, now)
        if terminal and old.acquired_once:
            status = ChannelStatus.LOST
        elif estimate is not None:
            status = ChannelStatus.MEMORY
        else:
            status = ChannelStatus.SEARCHING
        self._state = ChannelState(
            mode=old.mode,
            status=status,
            estimate=estimate,
            updated_at=now,
            acquired_once=old.acquired_once,
            terminal_committed=(old.terminal_committed
                                if terminal_committed is None
                                else bool(terminal_committed)),
            active_seeker=(old.active_seeker
                           if active_seeker is None
                           else bool(active_seeker)),
        )
        return self._state


class CommandChannel(_ChannelBase):
    """Radio-command guidance: no onboard truth/seeker fallback.

    A live controller measurement is usable only while ``link_ok``. Loss
    freezes the last commanded point; a later valid link may reacquire.
    """

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(GuidanceMode.COMMAND)

    def update(
        self,
        now: float,
        measurement: TrackEstimate | None = None,
        *,
        link_ok: bool = False,
    ) -> ChannelState:
        now = self._time(now)
        if link_ok and measurement is not None:
            return self._track(now, measurement, TrackSource.COMMAND)
        return self._lose(now)


class SarhChannel(_ChannelBase):
    """SARH/TVM channel with datalink midcourse and illuminated terminal.

    Once ``terminal_phase`` is requested it is committed: the channel cannot
    silently fall back to a launcher datalink and call that terminal SARH.
    Illumination loss freezes the last permitted estimate; valid paint may
    reacquire later.
    """

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(GuidanceMode.SARH)

    def update(
        self,
        now: float,
        *,
        midcourse: TrackEstimate | None = None,
        terminal_measurement: TrackEstimate | None = None,
        terminal_phase: bool = False,
        datalink_ok: bool = False,
        illuminator_ok: bool = False,
    ) -> ChannelState:
        now = self._time(now)
        committed = self._state.terminal_committed or bool(terminal_phase)
        if committed:
            if illuminator_ok and terminal_measurement is not None:
                return self._track(
                    now, terminal_measurement, TrackSource.SARH,
                    terminal_committed=True)
            return self._lose(now, terminal_committed=True)
        if datalink_ok and midcourse is not None:
            return self._track(now, midcourse, TrackSource.DATALINK)
        return self._lose(now)


class ArhChannel(_ChannelBase):
    """Active-radar channel with datalink midcourse and autonomous terminal.

    ``request_acquire`` is an estimate-driven request from the flight computer;
    ``seeker_ok`` is the integration layer's physical range/cone/LOS result.
    After the first valid seeker acquisition, datalink state is ignored. Own-
    seeker loss freezes the estimate, and a later valid seeker sample reacquires.
    """

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(GuidanceMode.ARH)

    def update(
        self,
        now: float,
        *,
        midcourse: TrackEstimate | None = None,
        seeker_measurement: TrackEstimate | None = None,
        datalink_ok: bool = False,
        seeker_ok: bool = False,
        request_acquire: bool = False,
    ) -> ChannelState:
        now = self._time(now)
        active = self._state.active_seeker
        if active:
            if seeker_ok and seeker_measurement is not None:
                return self._track(
                    now, seeker_measurement, TrackSource.ARH,
                    terminal_committed=True, active_seeker=True)
            # Active seeker remains the selected source while in memory; a
            # launcher datalink cannot resurrect dependence on the launcher.
            return self._lose(
                now, terminal_committed=True, active_seeker=True)
        if request_acquire and seeker_ok and seeker_measurement is not None:
            return self._track(
                now, seeker_measurement, TrackSource.ARH,
                terminal_committed=True, active_seeker=True)
        # A failed acquisition attempt may continue honest midcourse guidance.
        if datalink_ok and midcourse is not None:
            return self._track(now, midcourse, TrackSource.DATALINK)
        return self._lose(now)


class IrChannel(_ChannelBase):
    """Passive IR seeker channel with permanent loss after lock break.

    It may search until its first accepted sample. Once an acquired lock is
    lost, later samples are ignored: this preserves the current AIM-9X
    no-reacquire contract without exposing a target entity to guidance code.
    """

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(GuidanceMode.IR)

    def update(
        self,
        now: float,
        measurement: TrackEstimate | None = None,
        *,
        seeker_ok: bool = False,
    ) -> ChannelState:
        now = self._time(now)
        if self._state.status is ChannelStatus.LOST:
            # Terminal means terminal. Advance only the observation clock.
            self._state = replace(self._state, updated_at=now)
            return self._state
        if seeker_ok and measurement is not None:
            return self._track(
                now, measurement, TrackSource.IR,
                terminal_committed=True, active_seeker=True)
        if self._state.acquired_once:
            return self._lose(
                now, terminal=True,
                terminal_committed=True, active_seeker=True)
        return self._lose(now)


__all__ = [
    "ArhChannel",
    "ChannelState",
    "ChannelStatus",
    "CommandChannel",
    "GuidanceMode",
    "IrChannel",
    "SarhChannel",
    "TrackEstimate",
    "TrackSource",
    "freeze_estimate",
]
