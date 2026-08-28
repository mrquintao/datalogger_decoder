from __future__ import annotations

import unittest

from decoder import (
    SD_BLOCK_SIZE,
    TIMESTAMP_MODULUS,
    TimestampUnwrapper,
    decode_record,
    signed_16,
)


def make_record(*, timestamp: int, control: int, packet_id: int, payload: int) -> bytes:
    header = (timestamp & (TIMESTAMP_MODULUS - 1)) | ((control & 0x07) << 21) | ((packet_id & 0xFF) << 24)
    return header.to_bytes(4, "little") + (payload & 0xFFFFFFFF).to_bytes(4, "little")


class Signed16Tests(unittest.TestCase):
    def test_signed_16_boundaries(self) -> None:
        self.assertEqual(signed_16(0x0000), 0)
        self.assertEqual(signed_16(0x7FFF), 32767)
        self.assertEqual(signed_16(0x8000), -32768)
        self.assertEqual(signed_16(0xFFFF), -1)


class TimestampTests(unittest.TestCase):
    def test_wrap_is_detected(self) -> None:
        unwrapper = TimestampUnwrapper()
        before, count_before = unwrapper.decode(TIMESTAMP_MODULUS - 5)
        after, count_after = unwrapper.decode(3)
        self.assertEqual(before, TIMESTAMP_MODULUS - 5)
        self.assertEqual(count_before, 0)
        self.assertEqual(after, TIMESTAMP_MODULUS + 3)
        self.assertEqual(count_after, 1)

    def test_ignored_timestamp_does_not_change_state(self) -> None:
        unwrapper = TimestampUnwrapper()
        unwrapper.decode(123)
        ignored, count = unwrapper.decode(0, ignore=True)
        self.assertIsNone(ignored)
        self.assertEqual(count, 0)
        self.assertEqual(unwrapper.last_raw, 123)


class DecodeRecordTests(unittest.TestCase):
    def test_velocity_rpm_fuel_record(self) -> None:
        velocity = 104
        rpm = 2500
        fuel = 511
        payload = (velocity << 22) | (rpm << 10) | fuel
        record = make_record(timestamp=1234, control=2, packet_id=0x01, payload=payload)
        row = decode_record(
            record,
            source_file="data001.bin",
            record_index=0,
            timestamp=TimestampUnwrapper(),
        )
        self.assertEqual(row["record_type"], "VELOCITY_RPM_FUEL")
        self.assertEqual(row["velocity_raw_10bit"], velocity)
        self.assertEqual(row["velocity_m_s_estimated"], 2.0)
        self.assertEqual(row["rpm_raw_12bit"], rpm)
        self.assertEqual(row["fuel_raw_10bit"], fuel)

    def test_imu_negative_gyro_applies_existing_correction(self) -> None:
        accel_u16 = 1000
        gyro_u16 = 0xFFFF
        payload = (accel_u16 << 16) | gyro_u16
        record = make_record(timestamp=10, control=0, packet_id=0x10, payload=payload)
        row = decode_record(
            record,
            source_file="data001.bin",
            record_index=0,
            timestamp=TimestampUnwrapper(),
        )
        self.assertEqual(row["record_type"], "IMU_AX_GX")
        self.assertEqual(row["imu_gyro_s16"], -1)
        self.assertTrue(row["imu_packing_correction_applied"])
        self.assertEqual(row["imu_accel_payload_s16"], 1000)
        self.assertEqual(row["imu_accel_corrected_s16"], 1001)

    def test_padding_last_slot_of_2048_block(self) -> None:
        record_index = (SD_BLOCK_SIZE // 8) - 1
        row = decode_record(
            bytes(8),
            source_file="data001.bin",
            record_index=record_index,
            timestamp=TimestampUnwrapper(),
        )
        self.assertTrue(row["is_padding_candidate"])
        self.assertEqual(row["record_type"], "PADDING_CANDIDATE")
        self.assertIsNone(row["timestamp_unwrapped_ms"])


if __name__ == "__main__":
    unittest.main()
