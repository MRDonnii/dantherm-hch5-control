import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from master_arbitration import MasterArbitrator, RtuFrameStream, crc16


def fc06(slave, register, value):
    body = bytes([slave, 6, register >> 8, register & 0xFF, value >> 8, value & 0xFF])
    return body + crc16(body).to_bytes(2, "little")


def fc03_request(slave=1, start=66, count=2, function=3):
    body = bytes([slave, function, start >> 8, start & 0xFF, count >> 8, count & 0xFF])
    return body + crc16(body).to_bytes(2, "little")


def fc03_response(slave=1, values=(0x1234,)):
    body = bytes([slave, 3, len(values) * 2]) + b"".join(
        value.to_bytes(2, "big") for value in values
    )
    return body + crc16(body).to_bytes(2, "little")


def test_startup_waits_before_pi_master():
    arb = MasterArbitrator(startup_observation=3, release_timeout=3)
    t0 = arb.started_monotonic
    arb.observe_frame(fc03_response(), now=t0 + 0.1)
    arb.evaluate(bus_healthy=True, now=t0 + 2.9)
    assert arb.master == arb.UNKNOWN
    arb.evaluate(bus_healthy=True, now=t0 + 3.1)
    assert arb.master == arb.PI


def test_two_foreign_transactions_detect_hcp4():
    arb = MasterArbitrator(detection_window=2, detection_min_foreign_writes=2)
    t0 = arb.started_monotonic
    arb.observe_frame(fc06(1, 67, 43), now=t0 + 0.2)
    assert arb.master == arb.UNKNOWN
    arb.observe_frame(fc06(1, 66, 55), now=t0 + 0.5)
    assert arb.master == arb.HCP4


def test_pi_yields_on_single_foreign_write():
    arb = MasterArbitrator(startup_observation=3, release_timeout=3)
    t0 = arb.started_monotonic
    arb.observe_frame(fc03_response(), now=t0 + 0.1)
    arb.evaluate(bus_healthy=True, now=t0 + 3.1)
    assert arb.master == arb.PI
    arb.observe_frame(fc06(1, 143, 189), now=t0 + 3.2)
    assert arb.master == arb.HCP4


def test_own_echo_does_not_mark_hcp4():
    arb = MasterArbitrator(startup_observation=3, release_timeout=3, own_echo_ttl=0.2)
    t0 = arb.started_monotonic
    arb.observe_frame(fc03_response(), now=t0 + 0.1)
    arb.evaluate(bus_healthy=True, now=t0 + 3.1)
    assert arb.master == arb.PI
    frame = fc06(1, 67, 43)
    arb.note_own_frame(frame, now=t0 + 3.2)
    assert arb.observe_frame(frame, now=t0 + 3.25) == "own"
    assert arb.master == arb.PI
    assert arb.foreign_write_count == 0


def test_identical_hcp4_write_after_short_echo_window_is_foreign():
    arb = MasterArbitrator(startup_observation=3, release_timeout=3, own_echo_ttl=0.2)
    t0 = arb.started_monotonic
    arb.observe_frame(fc03_response(), now=t0 + 0.1)
    arb.evaluate(bus_healthy=True, now=t0 + 3.1)
    frame = fc06(1, 67, 43)
    arb.note_own_frame(frame, now=t0 + 3.2)
    assert arb.observe_frame(frame, now=t0 + 3.41) == "foreign"
    assert arb.master == arb.HCP4
    assert arb.foreign_write_count == 1


def test_echo_window_is_capped_to_transaction_scale():
    assert MasterArbitrator(own_echo_ttl=9).own_echo_ttl == 0.25


def test_hcp4_release_requires_quiet_timeout():
    arb = MasterArbitrator(
        detection_window=2,
        detection_min_foreign_writes=2,
        release_timeout=5,
        startup_observation=3,
    )
    t0 = arb.started_monotonic
    arb.observe_frame(fc06(1, 67, 43), now=t0 + 0.2)
    arb.observe_frame(fc06(1, 66, 55), now=t0 + 0.5)
    assert arb.master == arb.HCP4
    arb.evaluate(bus_healthy=True, now=t0 + 5.4)
    assert arb.master == arb.HCP4
    arb.evaluate(bus_healthy=True, now=t0 + 5.6)
    assert arb.master == arb.PI


def test_unhealthy_bus_never_becomes_pi_master():
    arb = MasterArbitrator(startup_observation=3)
    t0 = arb.started_monotonic
    arb.observe_frame(fc03_response(), now=t0 + 0.1)
    arb.evaluate(bus_healthy=False, now=t0 + 20)
    assert arb.master == arb.UNKNOWN
    assert not arb.writes_allowed()


def test_foreign_read_request_preempts_pi_until_quiet_timeout():
    arb = MasterArbitrator(startup_observation=3, release_timeout=3)
    t0 = arb.started_monotonic
    arb.observe_frame(fc03_response(), now=t0 + 0.1)
    arb.evaluate(bus_healthy=True, now=t0 + 3.1)
    assert arb.master == arb.PI

    request = fc03_request(slave=0x40, start=180, count=30)
    assert arb.observe_frame(request, now=t0 + 3.2) == "foreign_read"
    assert arb.master == arb.HCP4
    assert arb.last_foreign_activity == t0 + 3.2
    arb.evaluate(bus_healthy=True, now=t0 + 6.1)
    assert arb.master == arb.HCP4
    arb.evaluate(bus_healthy=True, now=t0 + 6.21)
    assert arb.master == arb.PI


def test_own_read_request_echo_does_not_mark_hcp4():
    arb = MasterArbitrator(own_echo_ttl=0.2)
    t0 = arb.started_monotonic
    request = fc03_request(slave=0x40, start=180, count=30)
    arb.note_own_frame(request, now=t0 + 0.1)

    assert arb.observe_frame(request, now=t0 + 0.15) == "own"
    assert arb.master == arb.UNKNOWN
    assert arb.foreign_read_count == 0


def test_fc04_read_request_also_marks_hcp4_active():
    arb = MasterArbitrator()
    request = fc03_request(slave=1, start=0, count=4, function=4)

    assert arb.observe_frame(request) == "foreign_read"
    assert arb.master == arb.HCP4


def test_stream_parser_finds_write_frames_among_reads():
    stream = RtuFrameStream()
    read = fc03_request()
    write1 = fc06(1, 67, 43)
    write2 = fc06(1, 66, 55)
    frames = stream.feed(read[:3])
    assert frames == []
    frames += stream.feed(read[3:] + write1 + write2)
    assert frames == [read, write1, write2]
