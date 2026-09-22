import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "gateway"))

from passivelink_parser import DanthermDecoder, RtuStreamParser, crc16


def frame(body: bytes) -> bytes:
    return body + crc16(body).to_bytes(2, "little")


def test_bus_frame_rate_counts_recent_frames():
    decoder = DanthermDecoder(lambda _: None)
    for _ in range(3):
        decoder.decode(frame(bytes.fromhex("010600420019")))
    assert decoder.data["bus_frame_rate"] == 3
    assert decoder.data["bus_traffic"] is True


def test_fragmented_temperature_response():
    updates = []
    decoder = DanthermDecoder(updates.append)
    parser = RtuStreamParser(decoder.decode)
    body = bytes.fromhex("0104080576094c083705a2")
    message = frame(body)
    parser.feed(message[:4])
    parser.feed(message[4:])
    assert decoder.data["outdoor_temperature"] == 13.98
    assert decoder.data["supply_temperature"] == 23.80
    assert decoder.data["extract_temperature"] == 21.03
    assert decoder.data["exhaust_temperature"] == 14.42


def test_humidity_uses_input_register_4_byte_scaling():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("0104080831084909240869")))
    decoder.decode(frame(bytes.fromhex("01040a008d0a24090c00400002")))
    assert decoder.data["measured_relative_humidity"] == 55.3
    assert decoder.data["relative_humidity"] == 49.4


def test_disconnected_humidity_sensor_is_unavailable():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("01040a00000a24090c00ff0002")))
    assert decoder.data.get("relative_humidity") is None
    assert decoder.data.get("measured_relative_humidity") is None


def test_fan_registers_and_mode():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("010600420019")))
    decoder.decode(frame(bytes.fromhex("01060043000d")))
    assert decoder.data["extract_fan_percent"] == 25
    assert decoder.data["supply_fan_percent"] == 13
    assert decoder.data["current_level"] == "level_1"


def test_register_68_is_bypass_request_not_afterheat():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("0106004400ff")))
    assert decoder.data["bypass_request_raw"] == 255
    assert decoder.data["bypass_request"] == "ON"
    assert "afterheat_raw" not in decoder.data
    decoder.decode(frame(bytes.fromhex("010600440000")))
    assert decoder.data["bypass_request"] == "OFF"


def test_repeated_manual_command_does_not_reclassify_unchanged_auto_pair():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("010600420055")))
    decoder.decode(frame(bytes.fromhex("010600430049")))
    decoder.decode(frame(bytes.fromhex("0106008f00bd")))
    decoder.decode(frame(bytes.fromhex("010600420055")))
    decoder.decode(frame(bytes.fromhex("010600430049")))
    assert decoder.data["operating_mode"] == "auto_or_scheduled"


def test_manual_command_requires_changed_fan_pair():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("010600420037")))
    decoder.decode(frame(bytes.fromhex("01060043002b")))
    decoder.decode(frame(bytes.fromhex("0106008f00bd")))
    decoder.decode(frame(bytes.fromhex("010600420055")))
    decoder.decode(frame(bytes.fromhex("010600430049")))
    assert decoder.data["operating_mode"] == "manual_3"


def test_auto_sequence_overrides_manual_level_fan_pair():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("010600420037")))
    decoder.decode(frame(bytes.fromhex("01060043002b")))
    decoder.decode(frame(bytes.fromhex("0106008f00c8")))
    decoder.decode(frame(bytes.fromhex("0106008f00ac")))
    assert decoder.data["operating_mode"] == "auto_or_scheduled"


def test_lone_172_followed_by_level_2_pair_selects_manual_2():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("01060042003c")))
    decoder.decode(frame(bytes.fromhex("010600430030")))
    decoder.decode(frame(bytes.fromhex("0106008f00ac")))
    decoder.decode(frame(bytes.fromhex("010600420037")))
    decoder.decode(frame(bytes.fromhex("01060043002b")))
    assert decoder.data["operating_mode"] == "manual_2"


def test_hac1_connected_bitfield():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("010600920003")))
    assert decoder.data["hac1_connected"] is True


def test_night_mode_waits_for_both_fan_registers():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("0106008f00ac")))
    decoder.decode(frame(bytes.fromhex("010600420019")))
    assert "night_mode" not in decoder.data
    decoder.decode(frame(bytes.fromhex("01060043000d")))
    assert decoder.data["night_mode"] is True


def test_night_mode_can_switch_off():
    decoder = DanthermDecoder(lambda _: None)
    decoder.decode(frame(bytes.fromhex("0106008f00ac")))
    decoder.decode(frame(bytes.fromhex("010600420019")))
    decoder.decode(frame(bytes.fromhex("01060043000d")))
    decoder._last_explicit_command = float("-inf")
    decoder.decode(frame(bytes.fromhex("0106008f00ac")))
    decoder.decode(frame(bytes.fromhex("010600420033")))
    decoder.decode(frame(bytes.fromhex("010600430027")))
    assert decoder.data["night_mode"] is False


def test_bad_crc_is_ignored():
    decoder = DanthermDecoder(lambda _: None)
    parser = RtuStreamParser(decoder.decode)
    parser.feed(bytes.fromhex("0106004200190000"))
    assert "extract_fan_percent" not in decoder.data


def test_write_multiple_request_is_kept_as_one_frame():
    frames = []
    parser = RtuStreamParser(frames.append)
    body = bytes.fromhex("401000b400050a00150016800080000000")
    message = frame(body)
    parser.feed(message[:8])
    parser.feed(message[8:])
    assert frames == [message]


def test_optional_afterheat_setpoints_decode_off():
    decoder = DanthermDecoder(lambda _: None)
    body = bytes.fromhex("401000b400050a00150016800080000000")
    decoder.decode(frame(body))
    assert decoder.data["afterheat_room_setpoint"] == "off"
    assert decoder.data["afterheat_extract_setpoint"] == "off"


def test_optional_afterheat_setpoints_decode_temperatures():
    decoder = DanthermDecoder(lambda _: None)
    body = bytes.fromhex("401000b400050a001500160014000f0000")
    decoder.decode(frame(body))
    assert decoder.data["afterheat_room_setpoint"] == "20"
    assert decoder.data["afterheat_extract_setpoint"] == "15"


def test_optional_afterheat_off_states_from_periodic_read():
    decoder = DanthermDecoder(lambda _: None)
    body = bytes.fromhex("40030a0aa20989800080000000")
    decoder.decode(frame(body))
    assert decoder.data["afterheat_room_setpoint"] == "off"
    assert decoder.data["afterheat_extract_setpoint"] == "off"


def test_supply_air_setpoint_from_hac1_write_block():
    decoder = DanthermDecoder(lambda _: None)
    body = bytes.fromhex("401000b900050aff011600000f18fee201")
    decoder.decode(frame(body))
    assert decoder.data["afterheat_setpoint"] == 22
