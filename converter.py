"""Conversao dos registros decodificados para CSV e/ou XLSX."""

from __future__ import annotations

import csv
import logging
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from decoder import FIELDNAMES, RECORD_SIZE, iter_decoded_records


EXCEL_MAX_ROWS = 1_048_576
DEFAULT_PROGRESS_INTERVAL_RECORDS = 10_000
ProgressCallback = Callable[[int, int], None]

LOGGER = logging.getLogger(__name__)

ANALYSIS_FIELDNAMES = [
    "source_file",
    "byte_offset",
    "timestamp_raw_ms",
    "time_s",
    "record_type",
    "signal",
    "value",
    "unit",
    "source_axis",
    "raw_value",
    "flags",
]


@dataclass(frozen=True)
class ConversionResult:
    """Resumo de uma conversao concluida."""

    counts: Counter[str]
    csv_path: Path | None
    xlsx_path: Path | None
    elapsed_seconds: float

    @property
    def records(self) -> int:
        return self.counts["records"]

    @property
    def output_files(self) -> tuple[Path, ...]:
        return tuple(path for path in (self.csv_path, self.xlsx_path) if path is not None)


class XlsxStreamWriter:
    """Grava XLSX em streaming e abre nova aba ao atingir o limite do Excel."""

    def __init__(self, output_path: Path, fieldnames: list[str]) -> None:
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise RuntimeError(
                "Para gerar XLSX, instale openpyxl: pip install openpyxl"
            ) from exc

        self.output_path = output_path
        self.fieldnames = fieldnames
        self.workbook = Workbook(write_only=True)
        self.sheet_number = 0
        self.rows_in_sheet = 0
        self.sheet: Any = None
        self._new_sheet()

    def _new_sheet(self) -> None:
        self.sheet_number += 1
        self.sheet = self.workbook.create_sheet(f"records_{self.sheet_number:03d}")
        self.sheet.append(self.fieldnames)
        self.rows_in_sheet = 1

    def append(self, row: dict[str, Any]) -> None:
        if self.rows_in_sheet >= EXCEL_MAX_ROWS:
            self._new_sheet()
        self.sheet.append([row[name] for name in self.fieldnames])
        self.rows_in_sheet += 1

    def close(self) -> None:
        self.workbook.save(self.output_path)


def validate_input_file(input_path: Path) -> int:
    """Valida a entrada e retorna o total de registros esperados."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Arquivo de entrada nao encontrado: {input_path}")

    file_size = input_path.stat().st_size
    if file_size == 0:
        raise ValueError("O arquivo de entrada esta vazio.")
    if file_size % RECORD_SIZE:
        raise ValueError(
            f"O arquivo possui {file_size} bytes; "
            f"o tamanho precisa ser multiplo de {RECORD_SIZE}."
        )
    return file_size // RECORD_SIZE


def output_paths(
    input_path: Path,
    output_arg: Path | None,
    output_format: str,
    extended_debug: bool = False,
) -> tuple[Path | None, Path | None]:
    """Calcula caminhos distintos para as saidas reduzida e de debug."""
    normalized_format = output_format.lower()
    if normalized_format not in {"csv", "xlsx", "both"}:
        raise ValueError(f"Formato de saida invalido: {output_format}")

    if output_arg is None:
        suffix = "_decoded_debug" if extended_debug else "_decoded"
        base = input_path.with_name(f"{input_path.stem}{suffix}")
    elif output_arg.suffix.lower() in (".csv", ".xlsx"):
        base = output_arg.with_suffix("")
    else:
        base = output_arg

    csv_path = base.with_suffix(".csv") if normalized_format in ("csv", "both") else None
    xlsx_path = base.with_suffix(".xlsx") if normalized_format in ("xlsx", "both") else None
    return csv_path, xlsx_path


def paths_for_directory(
    input_path: Path,
    output_directory: Path,
    output_format: str,
    extended_debug: bool = False,
) -> tuple[Path | None, Path | None]:
    """Calcula saidas dentro da pasta escolhida pela GUI."""
    suffix = "_decoded_debug" if extended_debug else "_decoded"
    base = output_directory / f"{input_path.stem}{suffix}"
    return output_paths(input_path, base, output_format)


def _analysis_flags(row: dict[str, Any], *, timestamp_wrap: bool) -> str:
    """Resume condicoes especiais do pacote em um unico campo."""
    flags: list[str] = []
    if timestamp_wrap:
        flags.append("TIMESTAMP_WRAP")
    if row["imu_packing_correction_applied"]:
        flags.append("PACKING_CORRECTED")
    if row["is_padding_candidate"]:
        flags.append("PADDING")
    if row["record_type"] == "UNKNOWN":
        flags.append("INVALID_PACKET")
    return "|".join(flags) if flags else "OK"


def iter_analysis_rows(
    row: dict[str, Any], *, timestamp_wrap: bool = False
) -> Iterator[dict[str, Any]]:
    """Converte um registro ja decodificado em linhas longas para analise."""
    base = {
        "source_file": row["source_file"],
        "byte_offset": row["byte_offset"],
        "timestamp_raw_ms": row["timestamp_raw_ms"],
        "time_s": row["time_unwrapped_s"],
        "record_type": row["record_type"],
        "signal": None,
        "value": None,
        "unit": None,
        "source_axis": None,
        "raw_value": None,
        "flags": _analysis_flags(row, timestamp_wrap=timestamp_wrap),
    }

    if row["record_type"] == "VELOCITY_RPM_FUEL":
        signals = (
            ("velocity", row["velocity_m_s_estimated"], "m/s", row["velocity_raw_10bit"]),
            ("rpm", row["rpm_raw_12bit"], "rpm", row["rpm_raw_12bit"]),
            ("fuel", row["fuel_raw_10bit"], "raw_10bit", row["fuel_raw_10bit"]),
        )
        for signal, value, unit, raw_value in signals:
            yield {
                **base,
                "signal": signal,
                "value": value,
                "unit": unit,
                "raw_value": raw_value,
            }
        return

    if str(row["record_type"]).startswith("IMU_"):
        accel_signal = str(row["imu_accel_field"]).removesuffix("_LOGICAL")
        signals = (
            (
                accel_signal,
                row["imu_accel_corrected_s16"],
                row["imu_accel_source_axis"],
                row["imu_accel_payload_s16"],
            ),
            (
                row["imu_gyro_field"],
                row["imu_gyro_s16"],
                row["imu_gyro_source_axis"],
                row["imu_gyro_s16"],
            ),
        )
        for signal, value, source_axis, raw_value in signals:
            yield {
                **base,
                "signal": signal,
                "value": value,
                "unit": "LSB",
                "source_axis": source_axis,
                "raw_value": raw_value,
            }
        return

    # Marcadores, padding e pacotes desconhecidos continuam rastreaveis, mas
    # sem inventar uma grandeza ou um valor que o decoder nao fornece.
    yield base


def convert_file(
    input_path: Path,
    *,
    csv_path: Path | None,
    xlsx_path: Path | None,
    delimiter: str = ";",
    extended_debug: bool = False,
    progress_callback: ProgressCallback | None = None,
    progress_interval_records: int = DEFAULT_PROGRESS_INTERVAL_RECORDS,
) -> ConversionResult:
    """Converte um .bin em streaming para CSV e/ou XLSX.

    Por padrao, cada registro decodificado e formatado em linhas de analise.
    ``extended_debug=True`` preserva a linha completa usada anteriormente.
    O callback recebe ``(registros_processados, total_de_registros)`` e e chamado
    de forma limitada para evitar custo excessivo em arquivos grandes.
    """
    input_path = Path(input_path)
    csv_path = Path(csv_path) if csv_path is not None else None
    xlsx_path = Path(xlsx_path) if xlsx_path is not None else None

    total_records = validate_input_file(input_path)
    if csv_path is None and xlsx_path is None:
        raise ValueError("Selecione pelo menos um formato de saida.")
    if len(delimiter) != 1:
        raise ValueError("O delimitador CSV precisa ter exatamente um caractere.")
    if progress_interval_records < 1:
        raise ValueError("O intervalo de progresso precisa ser maior que zero.")

    for path in (csv_path, xlsx_path):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if path.resolve() == input_path.resolve():
                    raise ValueError("O arquivo de saida nao pode ser o arquivo .bin de entrada.")
            except FileNotFoundError:
                # ``resolve`` pode depender da existencia em versões/ambientes antigos.
                pass

    LOGGER.info(
        "Conversao iniciada: input=%s total_records=%d csv=%s xlsx=%s",
        input_path,
        total_records,
        csv_path,
        xlsx_path,
    )
    start = time.perf_counter()

    fieldnames = FIELDNAMES if extended_debug else ANALYSIS_FIELDNAMES

    # Inicializa o XLSX antes do CSV para falhar cedo se openpyxl estiver ausente.
    xlsx_writer = XlsxStreamWriter(xlsx_path, fieldnames) if xlsx_path else None
    csv_file = None
    csv_writer = None
    counts: Counter[str] = Counter()
    success = False
    previous_wrap_count = 0

    try:
        if csv_path:
            # utf-8-sig facilita a abertura direta pelo Excel no Windows.
            csv_file = csv_path.open("w", newline="", encoding="utf-8-sig")
            csv_writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
                delimiter=delimiter,
                extrasaction="raise",
            )
            csv_writer.writeheader()

        if progress_callback:
            progress_callback(0, total_records)

        for row in iter_decoded_records(input_path):
            wrap_count = int(row["timestamp_wrap_count"] or 0)
            timestamp_wrap = wrap_count > previous_wrap_count
            previous_wrap_count = wrap_count

            export_rows = (
                (row,)
                if extended_debug
                else iter_analysis_rows(row, timestamp_wrap=timestamp_wrap)
            )
            for export_row in export_rows:
                if csv_writer:
                    csv_writer.writerow(export_row)
                if xlsx_writer:
                    xlsx_writer.append(export_row)
                counts["output_rows"] += 1

            counts["records"] += 1
            counts[str(row["record_type"])] += 1
            if row["is_padding_candidate"]:
                counts["padding_candidates"] += 1

            current = counts["records"]
            if progress_callback and (
                current % progress_interval_records == 0 or current == total_records
            ):
                progress_callback(current, total_records)

        if csv_file:
            csv_file.close()
            csv_file = None
        if xlsx_writer:
            xlsx_writer.close()

        success = True
    finally:
        if csv_file:
            csv_file.close()
        if not success:
            # CSV pode ter sido criado parcialmente. O XLSX normalmente so e criado
            # no save(), mas removemos qualquer saida parcial se existir.
            for path in (csv_path, xlsx_path):
                if path is not None:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        LOGGER.warning("Nao foi possivel remover saida parcial: %s", path)

    elapsed = time.perf_counter() - start
    LOGGER.info(
        "Conversao concluida: records=%d output_rows=%d extended_debug=%s "
        "elapsed=%.3fs outputs=%s",
        counts["records"],
        counts["output_rows"],
        extended_debug,
        elapsed,
        [str(path) for path in (csv_path, xlsx_path) if path],
    )
    return ConversionResult(
        counts=counts,
        csv_path=csv_path,
        xlsx_path=xlsx_path,
        elapsed_seconds=elapsed,
    )
