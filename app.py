"""Interface grafica do Datalogger Decoder."""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from converter import ConversionResult, convert_file, paths_for_directory
from logging_config import configure_logging


LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_MS = 100

def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent

    return str(base_path / relative_path)


class DataloggerDecoderApp:
    """Janela principal da aplicacao."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Datalogger Decoder")
        self.root.minsize(760, 420)

        self.root.iconbitmap(resource_path("assets/datalogger_decoder.ico"))

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_output_directory: Path | None = None

        self.input_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.format_var = tk.StringVar(value="xlsx")
        self.delimiter_var = tk.StringVar(value=";")
        self.extended_debug_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Pronto")
        self.progress_text_var = tk.StringVar(value="Progresso: 0%")
        self.records_text_var = tk.StringVar(value="Registros: 0 / 0")

        self._build_ui()
        self._update_csv_state()
        self.root.after(POLL_INTERVAL_MS, self._poll_worker_events)
        LOGGER.info("Aplicativo iniciado")

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        frame = ttk.Frame(self.root, padding=20)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        title = ttk.Label(frame, text="Datalogger Decoder", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 18))

        ttk.Label(frame, text="Arquivo .bin:").grid(row=1, column=0, sticky="w", pady=6)
        self.input_entry = ttk.Entry(frame, textvariable=self.input_var, state="readonly")
        self.input_entry.grid(row=1, column=1, sticky="ew", padx=(10, 10), pady=6)
        self.select_file_button = ttk.Button(
            frame, text="Selecionar arquivo", command=self._select_input_file
        )
        self.select_file_button.grid(row=1, column=2, sticky="ew", pady=6)

        ttk.Label(frame, text="Pasta de destino:").grid(row=2, column=0, sticky="w", pady=6)
        self.output_entry = ttk.Entry(frame, textvariable=self.output_dir_var, state="readonly")
        self.output_entry.grid(row=2, column=1, sticky="ew", padx=(10, 10), pady=6)
        self.select_output_button = ttk.Button(
            frame, text="Selecionar pasta", command=self._select_output_directory
        )
        self.select_output_button.grid(row=2, column=2, sticky="ew", pady=6)

        ttk.Label(frame, text="Formato de saida:").grid(row=3, column=0, sticky="w", pady=6)
        format_frame = ttk.Frame(frame)
        format_frame.grid(row=3, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=6)
        self.format_buttons: list[ttk.Radiobutton] = []
        for text, value in (("XLSX", "xlsx"), ("CSV", "csv"), ("CSV + XLSX", "both")):
            button = ttk.Radiobutton(
                format_frame,
                text=text,
                value=value,
                variable=self.format_var,
                command=self._update_csv_state,
            )
            button.pack(side="left", padx=(0, 18))
            self.format_buttons.append(button)

        ttk.Label(frame, text="Delimitador CSV:").grid(row=4, column=0, sticky="w", pady=6)
        self.delimiter_combo = ttk.Combobox(
            frame,
            textvariable=self.delimiter_var,
            values=(";", ","),
            width=10,
            state="readonly",
        )
        self.delimiter_combo.grid(row=4, column=1, sticky="w", padx=(10, 0), pady=6)

        self.extended_debug_checkbox = ttk.Checkbutton(
            frame,
            text="Opção avançada: versão estendida para debug dos pacotes",
            variable=self.extended_debug_var,
        )
        self.extended_debug_checkbox.grid(
            row=5, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=6
        )

        ttk.Separator(frame).grid(row=6, column=0, columnspan=3, sticky="ew", pady=16)

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        progress_info = ttk.Frame(frame)
        progress_info.grid(row=8, column=0, columnspan=3, sticky="ew")
        progress_info.columnconfigure(1, weight=1)
        ttk.Label(progress_info, textvariable=self.progress_text_var).grid(row=0, column=0, sticky="w")
        ttk.Label(progress_info, textvariable=self.records_text_var).grid(row=0, column=1, sticky="e")

        ttk.Label(frame, textvariable=self.status_var).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(12, 16)
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=10, column=0, columnspan=3, sticky="e")
        self.open_folder_button = ttk.Button(
            buttons,
            text="Abrir pasta de destino",
            command=self._open_output_directory,
            state="disabled",
        )
        self.open_folder_button.pack(side="left", padx=(0, 10))
        self.convert_button = ttk.Button(buttons, text="Converter", command=self._start_conversion)
        self.convert_button.pack(side="left")

    def _select_input_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecionar arquivo binario",
            filetypes=(("Arquivos binarios", "*.bin"), ("Todos os arquivos", "*.*")),
        )
        if not selected:
            return

        input_path = Path(selected)
        self.input_var.set(str(input_path))
        if not self.output_dir_var.get():
            self.output_dir_var.set(str(input_path.parent))
        LOGGER.info("Arquivo selecionado: %s", input_path)

    def _select_output_directory(self) -> None:
        initial_dir = self.output_dir_var.get() or self.input_var.get()
        if initial_dir and Path(initial_dir).is_file():
            initial_dir = str(Path(initial_dir).parent)
        selected = filedialog.askdirectory(
            title="Selecionar pasta de destino",
            initialdir=initial_dir or None,
        )
        if selected:
            self.output_dir_var.set(selected)
            LOGGER.info("Pasta de destino selecionada: %s", selected)

    def _update_csv_state(self) -> None:
        uses_csv = self.format_var.get() in {"csv", "both"}
        self.delimiter_combo.configure(state="readonly" if uses_csv else "disabled")

    def _start_conversion(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            input_path = Path(self.input_var.get())
            if not self.input_var.get():
                raise ValueError("Selecione um arquivo .bin.")
            output_directory = Path(self.output_dir_var.get()) if self.output_dir_var.get() else input_path.parent
            output_format = self.format_var.get()
            delimiter = self.delimiter_var.get()
            extended_debug = self.extended_debug_var.get()
            csv_path, xlsx_path = paths_for_directory(
                input_path,
                output_directory,
                output_format,
                extended_debug=extended_debug,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Dados invalidos", str(exc))
            return

        self.last_output_directory = None
        self.progress["value"] = 0
        self.progress_text_var.set("Progresso: 0%")
        self.records_text_var.set("Registros: 0 / 0")
        self.status_var.set("Processando...")
        self._set_controls_enabled(False)

        self.worker = threading.Thread(
            target=self._conversion_worker,
            args=(input_path, csv_path, xlsx_path, delimiter, extended_debug),
            daemon=True,
            name="datalogger-converter",
        )
        self.worker.start()

    def _conversion_worker(
        self,
        input_path: Path,
        csv_path: Path | None,
        xlsx_path: Path | None,
        delimiter: str,
        extended_debug: bool,
    ) -> None:
        try:
            result = convert_file(
                input_path,
                csv_path=csv_path,
                xlsx_path=xlsx_path,
                delimiter=delimiter,
                extended_debug=extended_debug,
                progress_callback=lambda current, total: self.events.put(
                    ("progress", (current, total))
                ),
            )
            self.events.put(("success", result))
        except (FileNotFoundError, PermissionError, ValueError, RuntimeError, OSError) as exc:
            LOGGER.exception("Falha ao converter %s", input_path)
            self.events.put(("error", self._friendly_error_message(exc)))
        except Exception as exc:  # noqa: BLE001 - fronteira da worker thread.
            LOGGER.exception("Erro inesperado ao converter %s", input_path)
            self.events.put(
                ("error", "Nao foi possivel converter o arquivo.\n\nOcorreu um erro inesperado. Consulte o log para detalhes.")
            )

    @staticmethod
    def _friendly_error_message(exc: Exception) -> str:
        text = str(exc)
        if isinstance(exc, PermissionError):
            detail = "Sem permissao para ler o arquivo ou gravar na pasta de destino."
        elif isinstance(exc, FileNotFoundError):
            detail = "O arquivo de entrada nao foi encontrado."
        elif isinstance(exc, RuntimeError):
            detail = text
        elif isinstance(exc, ValueError):
            detail = text
        elif isinstance(exc, OSError):
            detail = f"Erro de acesso a arquivo ou pasta: {text}"
        else:
            detail = "Ocorreu um erro inesperado. Consulte o log para detalhes."
        return f"Nao foi possivel converter o arquivo.\n\n{detail}"

    def _poll_worker_events(self) -> None:
        try:
            while True:
                event_type, payload = self.events.get_nowait()
                if event_type == "progress":
                    current, total = payload
                    self._show_progress(current, total)
                elif event_type == "success":
                    self._finish_success(payload)
                elif event_type == "error":
                    self._finish_error(str(payload))
        except queue.Empty:
            pass
        finally:
            self.root.after(POLL_INTERVAL_MS, self._poll_worker_events)

    def _show_progress(self, current: int, total: int) -> None:
        percent = (current / total * 100.0) if total else 0.0
        self.progress["value"] = percent
        self.progress_text_var.set(f"Progresso: {percent:.0f}%")
        self.records_text_var.set(f"Registros: {current:,} / {total:,}".replace(",", "."))

    def _finish_success(self, result: ConversionResult) -> None:
        self._set_controls_enabled(True)
        self.status_var.set(f"Concluido em {result.elapsed_seconds:.2f} s")
        self._show_progress(result.records, result.records)

        output_files = result.output_files
        if output_files:
            self.last_output_directory = output_files[0].parent
            self.open_folder_button.configure(state="normal")

        output_text = "\n".join(str(path.resolve()) for path in output_files)
        LOGGER.info(
            "Conversao finalizada na GUI: records=%d outputs=%s",
            result.records,
            output_text,
        )
        formatted_records = f"{result.records:,}".replace(",", ".")
        messagebox.showinfo(
            "Conversao concluida",
            "Conversao concluida com sucesso.\n\n"
            f"Registros processados: {formatted_records}\n"
            f"Arquivo(s) gerado(s):\n{output_text}",
        )

    def _finish_error(self, message: str) -> None:
        self._set_controls_enabled(True)
        self.status_var.set("Falha na conversao")
        messagebox.showerror("Erro na conversao", message)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.convert_button.configure(state=state)
        self.select_file_button.configure(state=state)
        self.select_output_button.configure(state=state)
        for button in self.format_buttons:
            button.configure(state=state)
        self.extended_debug_checkbox.configure(state=state)
        if enabled:
            self._update_csv_state()
            self.open_folder_button.configure(
                state="normal" if self.last_output_directory else "disabled"
            )
        else:
            self.delimiter_combo.configure(state="disabled")
            self.open_folder_button.configure(state="disabled")

    def _open_output_directory(self) -> None:
        if self.last_output_directory is None:
            return
        try:
            if sys.platform != "win32":
                raise OSError("A abertura automatica da pasta esta disponivel somente no Windows.")
            os.startfile(self.last_output_directory)  # type: ignore[attr-defined]
        except OSError as exc:
            LOGGER.exception("Nao foi possivel abrir a pasta: %s", self.last_output_directory)
            messagebox.showerror("Nao foi possivel abrir a pasta", str(exc))


def main() -> None:
    log_path = configure_logging()
    logger = logging.getLogger(__name__)
    if log_path:
        logger.info("Log em %s", log_path)
    root = tk.Tk()
    DataloggerDecoderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
