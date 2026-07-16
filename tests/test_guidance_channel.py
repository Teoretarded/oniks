"""Pure contracts for sensor-honest missile guidance channels."""

from dataclasses import FrozenInstanceError, fields
import inspect

import pytest

from sim.guidance_channel import (
    ArhChannel,
    ChannelStatus,
    CommandChannel,
    GuidanceMode,
    IrChannel,
    SarhChannel,
    TrackEstimate,
    TrackSource,
    freeze_estimate,
)


def _track(
    t=0.0,
    pos=(0.0, 1000.0, 0.0),
    vel=(10.0, 0.0, 20.0),
    source=TrackSource.DATALINK,
    track_id="target-1",
):
    return TrackEstimate(pos, vel, t, source, track_id, sigma_m=12.0)


def test_track_estimate_is_deeply_immutable_numeric_data():
    pos = [1.0, 2.0, 3.0]
    vel = [4.0, 5.0, 6.0]
    estimate = TrackEstimate(pos, vel, 7.0, "datalink", "track")
    pos[0] = 999.0
    vel[0] = 999.0
    assert estimate.pos == (1.0, 2.0, 3.0)
    assert estimate.vel == (4.0, 5.0, 6.0)
    with pytest.raises(FrozenInstanceError):
        estimate.pos = (0.0, 0.0, 0.0)
    assert [f.name for f in fields(TrackEstimate)] == [
        "pos", "vel", "sample_time", "source", "track_id", "sigma_m"]


def test_track_id_rejects_entity_references():
    class _Entity:
        pass

    with pytest.raises(TypeError, match="entity reference"):
        TrackEstimate((0, 0, 0), (0, 0, 0), 0.0,
                      TrackSource.DATALINK, _Entity())


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(pos=(0, 0), vel=(0, 0, 0)),
        dict(pos=(0, 0, float("nan")), vel=(0, 0, 0)),
        dict(pos=(0, 0, 0), vel=(0, 0, 0), sigma_m=-1.0),
    ],
)
def test_track_estimate_rejects_invalid_numeric_state(kwargs):
    base = dict(sample_time=0.0, source=TrackSource.DATALINK,
                track_id="track")
    with pytest.raises((TypeError, ValueError)):
        TrackEstimate(**kwargs, **base)


def test_dead_reckon_and_freeze_are_pure_and_exact():
    estimate = _track(t=2.0, pos=(10.0, 100.0, -5.0), vel=(3.0, -2.0, 4.0))
    assert estimate.position_at(5.0) == (19.0, 94.0, 7.0)
    frozen = freeze_estimate(estimate, 5.0)
    assert frozen.pos == (19.0, 94.0, 7.0)
    assert frozen.vel == (0.0, 0.0, 0.0)
    assert frozen.sample_time == 5.0
    assert frozen.source is TrackSource.MEMORY
    assert estimate.pos == (10.0, 100.0, -5.0)  # original untouched
    with pytest.raises(ValueError, match="backward"):
        estimate.position_at(1.0)


def test_public_channel_apis_have_no_world_or_entity_parameter():
    for channel_type in (CommandChannel, SarhChannel, ArhChannel, IrChannel):
        parameters = inspect.signature(channel_type.update).parameters
        assert "world" not in parameters
        assert "target" not in parameters
        assert "entity" not in parameters


def test_command_loss_freezes_once_and_reacquires():
    channel = CommandChannel()
    live = channel.update(0.0, _track(), link_ok=True)
    assert live.mode is GuidanceMode.COMMAND
    assert live.status is ChannelStatus.TRACKING
    assert live.estimate.source is TrackSource.COMMAND

    memory = channel.update(2.0, link_ok=False)
    assert memory.status is ChannelStatus.MEMORY
    assert memory.estimate.pos == (20.0, 1000.0, 40.0)
    assert memory.estimate.vel == (0.0, 0.0, 0.0)

    # Repeated loss does not keep extrapolating the memory point.
    same_memory = channel.update(8.0, _track(t=8.0), link_ok=False)
    assert same_memory.estimate == memory.estimate

    reacquired_measurement = _track(
        t=9.0, pos=(100.0, 900.0, 200.0), vel=(1.0, 2.0, 3.0))
    reacquired = channel.update(9.0, reacquired_measurement, link_ok=True)
    assert reacquired.status is ChannelStatus.TRACKING
    assert reacquired.estimate.pos == (100.0, 900.0, 200.0)
    assert reacquired.estimate.source is TrackSource.COMMAND


def test_sarh_midcourse_then_terminal_paint_loss_and_reacquire():
    channel = SarhChannel()
    mid = channel.update(
        0.0, midcourse=_track(), datalink_ok=True)
    assert mid.status is ChannelStatus.TRACKING
    assert mid.estimate.source is TrackSource.DATALINK
    assert not mid.terminal_committed

    lost = channel.update(2.0, terminal_phase=True, illuminator_ok=False)
    assert lost.status is ChannelStatus.MEMORY
    assert lost.terminal_committed
    assert lost.estimate.pos == (20.0, 1000.0, 40.0)

    terminal_measurement = _track(
        t=3.0, pos=(30.0, 950.0, 60.0), source=TrackSource.DATALINK)
    reacquired = channel.update(
        3.0, terminal_measurement=terminal_measurement,
        illuminator_ok=True)
    assert reacquired.status is ChannelStatus.TRACKING
    assert reacquired.estimate.source is TrackSource.SARH

    # Once committed, a datalink sample cannot masquerade as terminal SARH.
    lost_again = channel.update(
        4.0, midcourse=_track(t=4.0), datalink_ok=True,
        terminal_phase=False, illuminator_ok=False)
    assert lost_again.status is ChannelStatus.MEMORY
    assert lost_again.estimate.source is TrackSource.MEMORY


def test_arh_failed_acquisition_keeps_honest_midcourse_track():
    channel = ArhChannel()
    state = channel.update(
        1.0,
        midcourse=_track(t=1.0),
        datalink_ok=True,
        request_acquire=True,
        seeker_ok=False,
    )
    assert state.status is ChannelStatus.TRACKING
    assert state.estimate.source is TrackSource.DATALINK
    assert not state.active_seeker


def test_arh_becomes_launcher_independent_and_reacquires_own_seeker():
    channel = ArhChannel()
    channel.update(0.0, midcourse=_track(), datalink_ok=True)
    seeker = _track(
        t=1.0, pos=(50.0, 1100.0, 100.0), source=TrackSource.DATALINK)
    locked = channel.update(
        1.0, seeker_measurement=seeker,
        request_acquire=True, seeker_ok=True)
    assert locked.active_seeker
    assert locked.terminal_committed
    assert locked.estimate.source is TrackSource.ARH

    # Datalink/launcher state is irrelevant after active acquisition.
    own_update = _track(t=2.0, pos=(55.0, 1090.0, 120.0))
    independent = channel.update(
        2.0, seeker_measurement=own_update,
        seeker_ok=True, datalink_ok=False)
    assert independent.status is ChannelStatus.TRACKING
    assert independent.estimate.source is TrackSource.ARH

    memory = channel.update(
        3.0, midcourse=_track(t=3.0, pos=(999, 999, 999)),
        datalink_ok=True, seeker_ok=False)
    assert memory.status is ChannelStatus.MEMORY
    assert memory.active_seeker
    assert memory.estimate.pos == (65.0, 1090.0, 140.0)

    reacquired = channel.update(
        4.0,
        seeker_measurement=_track(t=4.0, pos=(70, 1080, 160)),
        seeker_ok=True)
    assert reacquired.status is ChannelStatus.TRACKING
    assert reacquired.estimate.pos == (70.0, 1080.0, 160.0)
    assert reacquired.estimate.source is TrackSource.ARH


def test_ir_searches_until_first_lock_then_loss_is_permanent():
    channel = IrChannel()
    searching = channel.update(0.0, seeker_ok=False)
    assert searching.status is ChannelStatus.SEARCHING

    locked = channel.update(1.0, _track(t=1.0), seeker_ok=True)
    assert locked.status is ChannelStatus.TRACKING
    assert locked.estimate.source is TrackSource.IR

    lost = channel.update(2.0, seeker_ok=False)
    assert lost.status is ChannelStatus.LOST
    assert lost.estimate.pos == (10.0, 1000.0, 20.0)
    frozen = lost.estimate

    ignored = channel.update(
        3.0, _track(t=3.0, pos=(999, 999, 999)), seeker_ok=True)
    assert ignored.status is ChannelStatus.LOST
    assert ignored.estimate == frozen
    assert not ignored.has_live_track
    assert ignored.has_guidance_estimate


def test_updates_reject_non_monotonic_time_and_future_measurements():
    channel = CommandChannel()
    channel.update(2.0, _track(t=2.0), link_ok=True)
    with pytest.raises(ValueError, match="monotonic"):
        channel.update(1.0, link_ok=False)
    with pytest.raises(ValueError, match="future"):
        channel.update(3.0, _track(t=4.0), link_ok=True)


def test_identical_input_sequences_produce_identical_channel_states():
    def run():
        channel = ArhChannel()
        states = [channel.update(0.0, midcourse=_track(), datalink_ok=True)]
        states.append(channel.update(
            1.0, midcourse=_track(t=1.0), datalink_ok=True,
            request_acquire=True, seeker_ok=False))
        states.append(channel.update(
            2.0, seeker_measurement=_track(t=2.0),
            request_acquire=True, seeker_ok=True))
        states.append(channel.update(3.0, seeker_ok=False))
        states.append(channel.update(
            4.0, seeker_measurement=_track(t=4.0), seeker_ok=True))
        return states

    assert run() == run()
