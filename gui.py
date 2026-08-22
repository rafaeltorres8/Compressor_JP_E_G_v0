
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from tkinter import filedialog, messagebox

from image_processor import CancelledError, CompressionConfig, ImageCompressor

LOG_FILE = "compresor_app.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        # maxBytes/backupCount evitan que el log crezca sin límite en
        # sesiones largas o carpetas con muchísimas imágenes.
        RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
    ],
)

@dataclass
class _Event:
    kind: str  # "log" | "progress" | "done" | "error" | "cancelled"
    payload: object = None


class ImageCompressorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Compresor de Imágenes JPEG/JPG")
        self.root.geometry("560x600")
        self.source_folder = ""

        self._event_queue: queue.Queue[_Event] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._cancel_event = threading.Event()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

   # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.frame = tk.Frame(self.root, padx=10, pady=10)
        self.frame.pack(fill=tk.BOTH, expand=True)

        config_frame = tk.LabelFrame(self.frame, text="Configuración de Compresión", padx=10, pady=10)
        config_frame.pack(fill=tk.X, pady=10)

        vcmd_int = (self.root.register(self._validate_int), "%P")

        tk.Label(config_frame, text="Calidad (1-100, 90 es alta):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.quality_entry = tk.Entry(config_frame, width=10, validate="key", validatecommand=vcmd_int)
        self.quality_entry.insert(0, "90")
        self.quality_entry.grid(row=0, column=1, sticky="w", padx=5, pady=5)

        tk.Label(config_frame, text="Ancho/Alto Máximo (px):").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.max_size_entry = tk.Entry(config_frame, width=10, validate="key", validatecommand=vcmd_int)
        self.max_size_entry.insert(0, "1200")
        self.max_size_entry.grid(row=1, column=1, sticky="w", padx=5, pady=5)

        tk.Label(self.frame, text="1. Selecciona la carpeta de origen:").pack(pady=5, anchor="w")
        self.select_button = tk.Button(self.frame, text="Seleccionar Carpeta", command=self.select_folder)
        self.select_button.pack(pady=5)

        self.path_label = tk.Label(self.frame, text="Carpeta seleccionada: Ninguna", wraplength=520)
        self.path_label.pack(pady=5)

        tk.Label(self.frame, text="2. Iniciar el proceso de compresión:").pack(pady=5, anchor="w")

        button_row = tk.Frame(self.frame)
        button_row.pack(pady=5)

        self.compress_button = tk.Button(
            button_row, text="Comprimir Imágenes", command=self.start_compression, state=tk.DISABLED
        )
        self.compress_button.pack(side=tk.LEFT, padx=5)

        self.cancel_button = tk.Button(
            button_row, text="Cancelar", command=self.cancel_compression, state=tk.DISABLED
        )
        self.cancel_button.pack(side=tk.LEFT, padx=5)

        self.progress = ttk_progressbar(self.frame)

        tk.Label(self.frame, text="Estado del proceso:").pack(pady=5, anchor="w")
        self.status_text = tk.Text(self.frame, height=14, width=64, state=tk.DISABLED, wrap=tk.WORD)
        self.status_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

    @staticmethod
    def _validate_int(value: str) -> bool:
        return value == "" or value.isdigit()

    # ------------------------------------------------------------ Logging

    def log(self, message: str) -> None:
        self.status_text.config(state=tk.NORMAL)
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)

    # --------------------------------------------------------- Selección

    def select_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.source_folder = folder
            self.path_label.config(text=f"Carpeta seleccionada: {self.source_folder}")
            self.compress_button.config(state=tk.NORMAL)
            self.log(f"Carpeta de origen seleccionada: {self.source_folder}")
        else:
            self.source_folder = ""
            self.path_label.config(text="Carpeta seleccionada: Ninguna")
            self.compress_button.config(state=tk.DISABLED)
            self.log("Selección de carpeta cancelada.")

    # ----------------------------------------------------- Arranque/paro

    def start_compression(self) -> None:
        if not self.source_folder:
            messagebox.showerror("Error", "Por favor, selecciona una carpeta de origen.")
            return

        try:
            quality = int(self.quality_entry.get())
            max_size = int(self.max_size_entry.get())
            config = CompressionConfig(quality=quality, max_size=max_size)
            config.validate()
        except ValueError:
            messagebox.showerror(
                "Error de entrada",
                "Asegúrate de que la calidad sea un número entre 1 y 100, "
                "y el tamaño máximo sea un número positivo.",
            )
            return

        self.log("\n--- INICIANDO COMPRESIÓN ---")
        self.log(f"Configuración: Calidad={quality}, Ancho/Alto Máx.={max_size}px")

        self.compress_button.config(state=tk.DISABLED)
        self.select_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        self.progress.start(10)

        self._cancel_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run_worker,
            args=(self.source_folder, config),
            daemon=True,  # no bloquea el cierre de la app si algo va mal
        )
        self._worker_thread.start()
        self.root.after(100, self._poll_queue)

    def cancel_compression(self) -> None:
        self.log("Solicitando cancelación... (terminará tras la imagen actual)")
        self._cancel_event.set()
        self.cancel_button.config(state=tk.DISABLED)

    def _on_close(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            if not messagebox.askyesno(
                "Proceso en curso",
                "Hay una compresión en curso. ¿Seguro que quieres salir? "
                "El proceso se detendrá.",
            ):
                return
            self._cancel_event.set()
        self.root.destroy()

    # ------------------------------------------------------ Hilo worker

    def _run_worker(self, source_folder: str, config: CompressionConfig) -> None:
        """
        Corre en un hilo aparte. NUNCA toca widgets de Tkinter directamente
        desde aquí: solo empuja eventos a la cola thread-safe.
        """

        def on_log(message: str) -> None:
            self._event_queue.put(_Event("log", message))

        def on_progress(done: int, total: int) -> None:
            self._event_queue.put(_Event("progress", (done, total)))

        try:
            compressor = ImageCompressor(
                source_folder=source_folder,
                config=config,
                on_log=on_log,
                on_progress=on_progress,
                cancel_event=self._cancel_event,
            )
            result = compressor.run()
            self._event_queue.put(_Event("done", result))
        except CancelledError:
            self._event_queue.put(_Event("cancelled"))
        except Exception as exc:  # red de seguridad: nunca debe matar el hilo en silencio
            logging.exception("Error inesperado en el hilo de compresión")
            self._event_queue.put(_Event("error", str(exc)))

    def _poll_queue(self) -> None:
        """
        Corre en el hilo principal vía root.after(). Vacía la cola de
        eventos que el worker fue dejando y actualiza la UI de forma segura.
        """
        try:
            while True:
                event = self._event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass

        if self._worker_thread and self._worker_thread.is_alive():
            self.root.after(100, self._poll_queue)

    def _handle_event(self, event: _Event) -> None:
        if event.kind == "log":
            self.log(str(event.payload))
        elif event.kind == "progress":
            done, total = event.payload
            if total:
                self.progress.stop()
                self.progress["mode"] = "determinate"
                self.progress["maximum"] = total
                self.progress["value"] = done
        elif event.kind == "done":
            result = event.payload
            self.log("\n--- COMPRESIÓN FINALIZADA ---")
            self.log(f"Procesadas: {result.processed} | Errores: {result.errors}")
            messagebox.showinfo(
                "Completado",
                f"Se procesaron {result.processed} imágenes exitosamente.\n"
                f"Errores/omitidas: {result.errors}",
            )
            self._reset_controls()
        elif event.kind == "cancelled":
            self.log("--- COMPRESIÓN CANCELADA ---")
            messagebox.showwarning("Cancelado", "El proceso fue cancelado por el usuario.")
            self._reset_controls()
        elif event.kind == "error":
            self.log(f"\nERROR FATAL: {event.payload}")
            messagebox.showerror("Error", f"Ocurrió un error inesperado: {event.payload}")
            self._reset_controls()

    def _reset_controls(self) -> None:
        self.progress.stop()
        self.progress["mode"] = "determinate"
        self.progress["value"] = 0
        self.compress_button.config(state=tk.NORMAL)
        self.select_button.config(state=tk.NORMAL)
        self.cancel_button.config(state=tk.DISABLED)


def ttk_progressbar(parent: tk.Widget):
    # Import local para dejar clara la dependencia puntual de ttk aquí.
    from tkinter import ttk

    bar = ttk.Progressbar(parent, mode="indeterminate")
    bar.pack(fill=tk.X, pady=(0, 10))
    return bar
