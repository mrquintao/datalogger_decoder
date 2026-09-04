"""Interface de linha de comando para o mesmo motor usado pela GUI."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from converter import convert_file, output_paths
from logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Decodifica os registros de 8 bytes do microSD para CSV e/ou XLSX, "
            "preservando registro, cabecalho e payload originais."
        )
    )
    parser.add_argument("input", type=Path, help="arquivo dataNNN.bin")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="caminho base da saida (padrao: <entrada>_decoded)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("csv", "xlsx", "both"),
        default="csv",
        help="formato de saida (padrao: csv)",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        help="delimitador do CSV; use ';' para Excel em pt-BR (padrao: ',')",
    )
    parser.add_argument(
        "--extended-debug",
        action="store_true",
        help="gera a versao completa com campos internos dos pacotes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    logger = logging.getLogger(__name__)
    args = build_parser().parse_args(argv)
    csv_path, xlsx_path = output_paths(
        args.input,
        args.output,
        args.format,
        extended_debug=args.extended_debug,
    )

    try:
        result = convert_file(
            args.input,
            csv_path=csv_path,
            xlsx_path=xlsx_path,
            delimiter=args.delimiter,
            extended_debug=args.extended_debug,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception("Falha na conversao via CLI")
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"Registros decodificados: {result.records}")
    if result.counts["padding_candidates"]:
        print(f"Padding sinalizado (e preservado): {result.counts['padding_candidates']}")
    if result.csv_path:
        print(f"CSV:  {result.csv_path.resolve()}")
    if result.xlsx_path:
        print(f"XLSX: {result.xlsx_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
