"""Motor de decodificacao do protocolo binario do datalogger STM32.

Esta camada nao conhece interface grafica nem formato de exportacao. O arquivo
.bin e aberto somente para leitura e processado em streaming, um registro por vez.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator


RECORD_SIZE = 8
SD_BLOCK_SIZE = 2048
TIMESTAMP_BITS = 21
TIMESTAMP_MODULUS = 1 << TIMESTAMP_BITS
TIMESTAMP_MASK = TIMESTAMP_MODULUS - 1
TIMESTAMP_HALF_RANGE = TIMESTAMP_MODULUS // 2

# Limites superiores (exclusivos) do ADC de 12 bits para cada nivel discreto,
# espelhando Read_COMB() do firmware MDA_R26_KALMAN. ADC menor = tanque mais cheio.
FUEL_LEVEL_ADC_THRESHOLDS = (
    (390, 7),
    (1010, 6),
    (1630, 5),
    (2280, 4),
    (2900, 3),
    (3500, 2),
)
FUEL_LEVEL_MIN = 1

# A ordem desta lista define as colunas do modo estendido de debug.
FIELDNAMES = [
    "source_file",
    "record_index",
    "byte_offset",
    "block_index",
    "slot_in_block",
    "record_hex",
    "header_bytes_le_hex",
    "header_raw_u32",
    "header_hex",
    "payload_bytes_le_hex",
    "payload_raw_u32",
    "payload_hex",
    "timestamp_raw_ms",
    "timestamp_unwrapped_ms",
    "time_unwrapped_s",
    "timestamp_wrap_count",
    "control",
    "id_u8",
    "id_hex",
    "record_type",
    "is_padding_candidate",
    "velocity_raw_10bit",
    "velocity_m_s_estimated",
    "velocity_km_h_estimated",
    "rpm_raw_12bit",
    "fuel_raw_10bit",
    "imu_accel_field",
    "imu_accel_source_axis",
    "imu_accel_payload_s16",
    "imu_accel_corrected_s16",
    "imu_gyro_field",
    "imu_gyro_source_axis",
    "imu_gyro_s16",
    "imu_packing_correction_applied",
    # Colunas novas ficam no final para nao deslocar as preexistentes.
    "fuel_adc_raw_u16",
    "fuel_adc_filtered_u16",
    "fuel_level_from_adc_raw",
    "fuel_level_from_adc_filtered",
]


def signed_16(value: int) -> int:
    """Interpreta os 16 bits menos significativos como int16_t."""
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def fuel_level_from_adc(adc_value: int) -> int:
    """Converte uma leitura de ADC no nivel discreto (1 a 7) usado pelo firmware."""
    for upper_limit, level in FUEL_LEVEL_ADC_THRESHOLDS:
        if adc_value < upper_limit:
            return level
    return FUEL_LEVEL_MIN


class TimestampUnwrapper:
    """Estende o timestamp de 21 bits sem confundir o padding com overflow."""

    def __init__(self) -> None:
        self.last_raw: int | None = None
        self.wrap_count = 0

    def decode(self, raw: int, *, ignore: bool = False) -> tuple[int | None, int]:
        """Retorna o timestamp estendido e a quantidade de wraps observados."""
        if ignore:
            return None, self.wrap_count

        if (
            self.last_raw is not None
            and raw < self.last_raw
            and self.last_raw - raw > TIMESTAMP_HALF_RANGE
        ):
            self.wrap_count += 1

        self.last_raw = raw
        return raw + self.wrap_count * TIMESTAMP_MODULUS, self.wrap_count


def empty_decoded_fields() -> dict[str, Any]:
    """Cria uma linha com todas as colunas conhecidas inicializadas como None."""
    return {name: None for name in FIELDNAMES}


def decode_record(
    record: bytes,
    *,
    source_file: str,
    record_index: int,
    timestamp: TimestampUnwrapper,
) -> dict[str, Any]:
    """Decodifica um registro sem alterar nenhum de seus valores brutos."""
    if len(record) != RECORD_SIZE:
        raise ValueError(f"Registro deve ter {RECORD_SIZE} bytes, recebeu {len(record)}")

    byte_offset = record_index * RECORD_SIZE
    header_raw = int.from_bytes(record[0:4], byteorder="little", signed=False)
    payload_raw = int.from_bytes(record[4:8], byteorder="little", signed=False)

    timestamp_raw = header_raw & TIMESTAMP_MASK
    control = (header_raw >> 21) & 0x07
    packet_id = (header_raw >> 24) & 0xFF

    # O firmware atual deixa zerado o ultimo slot de cada buffer de 2048 bytes.
    is_padding = record == bytes(RECORD_SIZE) and byte_offset % SD_BLOCK_SIZE == 2040
    timestamp_unwrapped, wrap_count = timestamp.decode(
        timestamp_raw, ignore=is_padding
    )

    row = empty_decoded_fields()
    row.update(
        {
            "source_file": source_file,
            "record_index": record_index,
            "byte_offset": byte_offset,
            "block_index": byte_offset // SD_BLOCK_SIZE,
            "slot_in_block": (byte_offset % SD_BLOCK_SIZE) // RECORD_SIZE,
            "record_hex": record.hex(" ").upper(),
            "header_bytes_le_hex": record[0:4].hex(" ").upper(),
            "header_raw_u32": header_raw,
            "header_hex": f"0x{header_raw:08X}",
            "payload_bytes_le_hex": record[4:8].hex(" ").upper(),
            "payload_raw_u32": payload_raw,
            "payload_hex": f"0x{payload_raw:08X}",
            "timestamp_raw_ms": timestamp_raw,
            "timestamp_unwrapped_ms": timestamp_unwrapped,
            "time_unwrapped_s": (
                timestamp_unwrapped / 1000.0
                if timestamp_unwrapped is not None
                else None
            ),
            "timestamp_wrap_count": wrap_count,
            "control": control,
            "id_u8": packet_id,
            "id_hex": f"0x{packet_id:02X}",
            "is_padding_candidate": is_padding,
        }
    )

    if is_padding:
        row["record_type"] = "PADDING_CANDIDATE"
    elif control == 0 and packet_id == 0x00 and payload_raw == 0:
        row["record_type"] = "SESSION_MARKER"
    elif packet_id == 0x01:
        velocity = (payload_raw >> 22) & 0x3FF
        rpm = (payload_raw >> 10) & 0xFFF
        fuel = payload_raw & 0x3FF
        row.update(
            {
                "record_type": "VELOCITY_RPM_FUEL",
                "velocity_raw_10bit": velocity,
                # O firmware atual avalia (uint32_t)52.6 antes da multiplicacao,
                # portanto os arquivos existentes foram codificados com fator 52.
                "velocity_m_s_estimated": velocity / 52.0,
                "velocity_km_h_estimated": (velocity / 52.0) * 3.6,
                "rpm_raw_12bit": rpm,
                "fuel_raw_10bit": fuel,
            }
        )
    elif packet_id == 0x02:
        # (adc_raw << 16) + adc_filtered: ADC do combustivel antes e depois do
        # filtro de Kalman, gravados no mesmo tick do pacote 0x01.
        adc_raw = (payload_raw >> 16) & 0xFFFF
        adc_filtered = payload_raw & 0xFFFF
        row.update(
            {
                "record_type": "FUEL_ADC",
                "fuel_adc_raw_u16": adc_raw,
                "fuel_adc_filtered_u16": adc_filtered,
                "fuel_level_from_adc_raw": fuel_level_from_adc(adc_raw),
                "fuel_level_from_adc_filtered": fuel_level_from_adc(adc_filtered),
            }
        )
    elif packet_id in (0x10, 0x14, 0x18):
        accel_u16 = (payload_raw >> 16) & 0xFFFF
        gyro_u16 = payload_raw & 0xFFFF
        accel_from_payload = signed_16(accel_u16)
        gyro = signed_16(gyro_u16)

        # No C original, um gyro negativo sofre extensao de sinal na soma e
        # decrementa os 16 bits superiores. Esta coluna reverte esse efeito;
        # imu_accel_payload_s16 continua preservando a interpretacao literal.
        correction_applied = gyro < 0
        corrected_accel = signed_16(
            accel_u16 + 1 if correction_applied else accel_u16
        )

        imu_layout = {
            0x10: ("AX", "X", "GX", "X"),
            # O callback do firmware troca Y e Z somente no acelerometro.
            0x14: ("AY_LOGICAL", "Z", "GY", "Y"),
            0x18: ("AZ_LOGICAL", "Y", "GZ", "Z"),
        }
        accel_field, accel_axis, gyro_field, gyro_axis = imu_layout[packet_id]
        row.update(
            {
                "record_type": f"IMU_{accel_field}_{gyro_field}",
                "imu_accel_field": accel_field,
                "imu_accel_source_axis": accel_axis,
                "imu_accel_payload_s16": accel_from_payload,
                "imu_accel_corrected_s16": corrected_accel,
                "imu_gyro_field": gyro_field,
                "imu_gyro_source_axis": gyro_axis,
                "imu_gyro_s16": gyro,
                "imu_packing_correction_applied": correction_applied,
            }
        )
    else:
        row["record_type"] = "UNKNOWN"

    return row


def iter_decoded_records(input_path: Path) -> Iterator[dict[str, Any]]:
    """Itera pelos registros decodificados sem carregar o arquivo inteiro na RAM."""
    timestamp = TimestampUnwrapper()
    with input_path.open("rb") as binary_file:
        record_index = 0
        while True:
            record = binary_file.read(RECORD_SIZE)
            if not record:
                break
            if len(record) != RECORD_SIZE:
                raise ValueError(
                    f"{input_path.name}: sobraram {len(record)} bytes no final; "
                    "o tamanho do arquivo nao e multiplo de 8."
                )
            yield decode_record(
                record,
                source_file=input_path.name,
                record_index=record_index,
                timestamp=timestamp,
            )
            record_index += 1
