"""
gui.py
------
Interfaz gráfica de escritorio (Tkinter) para chord_extractor.

Abre un archivo de audio, lo analiza en segundo plano y muestra:
  - tonalidad, tempo y método usado
  - una línea de tiempo con los acordes coloreados a escala
  - la tabla de segmentos (inicio, fin, duración, acorde)
  - un reproductor con el cursor sincronizado sobre la línea de tiempo
  - exportación a JSON y a .lab

Arrancar:
    python gui.py
    python gui.py cancion.mp3      # abre ya con el archivo cargado

Dependencias: Tkinter (viene con Python) y, para el reproductor, pygame:
    pip install pygame
Sin pygame la aplicación funciona igual, solo se desactiva la reproducción.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from chord_extractor import ExtractionResult, extract
from history import History, HistoryUnavailable, options_key
import ytaudio
from chordviz import (
    color_for,
    format_time,
    pretty_label,
    ruler_step,
    text_color_for,
    tint_for,
)

try:
    import pygame
except ImportError:  # el reproductor es opcional
    pygame = None

AUDIO_TYPES = [
    ("Audio", "*.mp3 *.wav *.flac *.ogg *.opus *.m4a *.aac *.wma"),
    ("Todos los archivos", "*.*"),
]

APP_NAME = "Chord Extractor"
APP_VERSION = "1.1"
AUTHOR = "pepon"
AUTHOR_SITE = "pepon.cl"

# Paletas. Tkinter no trae tema oscuro, así que hay que definir cada color y
# reaplicarlo a mano al cambiar. Los tonos siguen los de la interfaz web para que
# las dos se vean como la misma aplicación.
THEMES = {
    "claro": {
        "bg": "#f6f7f9",
        "panel": "#ffffff",
        "text": "#14161c",
        "muted": "#6b7280",
        "border": "#e3e4ea",
        "accent": "#3b5bdb",
        "accent_text": "#ffffff",
        "accent_hover": "#2f4bc0",
        "field": "#ffffff",
        "select_bg": "#dbe4ff",
        "ruler": "#b9bcc6",
        "playhead": "#111827",
        "seg_outline": "#ffffff",
        "trough": "#e6e7ec",
        "dark_titlebar": False,
    },
    "oscuro": {
        "bg": "#14161c",
        "panel": "#1b1e26",
        "text": "#e8e9ef",
        "muted": "#969aa8",
        "border": "#2f333f",
        "accent": "#6b83f0",
        "accent_text": "#0e1016",
        "accent_hover": "#8598f5",
        "field": "#22262f",
        "select_bg": "#33406b",
        "ruler": "#565b6b",
        "playhead": "#f2f3f7",
        "seg_outline": "#1b1e26",
        "trough": "#2a2e39",
        "dark_titlebar": True,
    },
}
DEFAULT_THEME = "oscuro"


FROZEN = getattr(sys, "frozen", False)   # True dentro del .exe de PyInstaller


def app_dir() -> str:
    """Carpeta de datos de la aplicación (log y preferencias)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    directory = os.path.join(base, "ChordExtractor")
    os.makedirs(directory, exist_ok=True)
    return directory


def log_path() -> str:
    """Archivo donde se vuelca la traza cuando no hay consola (build windowed)."""
    return os.path.join(app_dir(), "error.log")


def load_theme() -> str:
    """Tema guardado de la sesión anterior, o el de por defecto."""
    try:
        with open(os.path.join(app_dir(), "config.json"), encoding="utf-8") as fh:
            name = json.load(fh).get("theme")
        return name if name in THEMES else DEFAULT_THEME
    except (OSError, ValueError):
        return DEFAULT_THEME


def save_theme(name: str) -> None:
    try:
        with open(os.path.join(app_dir(), "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"theme": name}, fh)
    except OSError:
        pass       # que no se pueda recordar la preferencia no es motivo de error


def set_dark_titlebar(window, dark: bool) -> None:
    """
    Barra de título oscura en Windows 10 2004+ / 11 (DWMWA_USE_IMMERSIVE_DARK_MODE).
    Sin esto, un tema oscuro con barra blanca parece un error de la aplicación.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        # 20 en builds modernas, 19 en las primeras que lo soportaron.
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass       # en Windows antiguo o si DWM falla, se queda la barra clara


def report_error(trace: str) -> str | None:
    """
    Deja la traza donde se pueda leer y devuelve la ruta del log si se usó.
    En el .exe windowed sys.stderr es None, así que la consola no sirve.
    """
    if not FROZEN and sys.stderr is not None:
        print(trace, file=sys.stderr)
        return None
    try:
        path = log_path()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{trace}")
        return path
    except OSError:
        return None


def diagnose(exc: BaseException, trace: str) -> str | None:
    """
    Traduce los fallos de entorno más habituales a una explicación accionable.
    Devuelve None si no reconocemos el error (entonces se muestra tal cual).
    """
    text = f"{type(exc).__name__}: {exc}\n{trace}"
    version = ".".join(str(n) for n in sys.version_info[:2])

    # numpy 1.x no tiene wheels para Python 3.13+: pip lo compila mal y la
    # detección de longdouble queda rota, así que revienta al importarlo.
    if "longdouble" in text or ("numpy" in text and "getlimits" in text):
        return (f"Este Python es {version} y numpy 1.x (que madmom necesita, por eso "
                f"requirements.txt fija numpy<2) sólo llega hasta Python 3.12.\n"
                f"El error ocurre al importar numpy, antes de tocar el audio.\n\n"
                f"Crea el entorno con Python 3.12 y arranca la GUI desde ahí:\n"
                f"    py -3.12 -m venv venv312\n"
                f"    venv312\\Scripts\\pip install \"numpy<2\" cython scipy \\\n"
                f"        \"git+https://github.com/CPJKU/madmom.git\" pygame\n"
                f"    venv312\\Scripts\\python gui.py")

    if "ffmpeg" in text.lower() or "avconv" in text.lower():
        return ("Falta ffmpeg, que madmom usa para decodificar MP3/M4A.\n"
                "Instálalo y abre una terminal nueva:\n"
                "    winget install Gyan.FFmpeg      (Windows)\n"
                "    sudo dnf install ffmpeg-free    (Fedora)\n\n"
                "Los archivos WAV funcionan sin ffmpeg.")

    if isinstance(exc, ModuleNotFoundError):
        missing = getattr(exc, "name", "") or ""
        if missing.split(".")[0] == "demucs":
            return ("La opción «Separar con Demucs» necesita el paquete demucs:\n"
                    "    pip install demucs\n"
                    "(arrastra PyTorch, son varios GB)")
        return f"Falta el paquete «{missing}». Instálalo con:\n    pip install {missing}"

    return None


class ChordApp(ttk.Frame):
    def __init__(self, master: tk.Tk, initial_file: str | None = None):
        super().__init__(master, padding=10)
        self.master.title(APP_NAME)
        self.master.geometry("1020x720")
        self.master.minsize(760, 560)
        self.pack(fill="both", expand=True)

        self.audio_path: str | None = None
        self.result: ExtractionResult | None = None
        self.duration: float = 0.0
        self.position: float = 0.0

        self._queue: queue.Queue = queue.Queue()
        self._playing = False
        self._play_offset = 0.0     # segundos de audio ya consumidos antes del play actual
        self._pause_pos = 0.0
        self._row_ids: list[str] = []
        # Fila que hemos seleccionado nosotros al seguir la reproducción. Tk
        # ENCOLA <<TreeviewSelect>>, así que una bandera booleana ya está en
        # False cuando llega el evento; hay que comparar por identidad.
        self._auto_selected_row: str | None = None

        self._audio_ready = self._init_mixer()
        self.theme_name = load_theme()
        # Si el historial no se puede abrir, la aplicación sigue funcionando:
        # simplemente reanaliza siempre.
        try:
            self.history: History | None = History(app_dir())
        except HistoryUnavailable:
            self.history = None

        self._build_style()
        self._build_toolbar()
        self._build_options()
        self._build_summary()
        self._build_timeline()
        self._build_table()
        self._build_player()
        # Segunda pasada: canvas, menú y tabla no existían en la primera.
        self._apply_theme()

        self.after(60, self._tick)
        if initial_file:
            self._set_audio(initial_file)

    # ------------------------------------------------------------------ setup
    def _init_mixer(self) -> bool:
        if pygame is None:
            return False
        try:
            # El búfer por defecto de pygame (512 muestras, ~12 ms) deja poco
            # margen: cualquier pausa del hilo de Tk redibujando la tabla o la
            # línea de tiempo puede provocar un corte audible. 2048 (~46 ms) da
            # holgura sin que se note al pausar o saltar.
            pygame.mixer.init(buffer=2048)
            return True
        except Exception:
            return False

    def _build_style(self):
        self.style = ttk.Style()
        # clam es el único tema de ttk que deja redefinir colores a fondo; los
        # nativos de Windows ignoran la mayoría de las opciones de background.
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self._apply_theme()

    def _apply_theme(self):
        c = self.colors = THEMES[self.theme_name]
        s = self.style

        self.master.configure(bg=c["bg"])
        s.configure(".", background=c["bg"], foreground=c["text"],
                    fieldbackground=c["field"], troughcolor=c["trough"],
                    bordercolor=c["border"], focuscolor=c["accent"])
        for widget in ("TFrame", "TLabel", "TLabelframe", "TLabelframe.Label",
                       "TCheckbutton", "TRadiobutton", "TSeparator", "TScale"):
            s.configure(widget, background=c["bg"], foreground=c["text"])
        s.configure("TSeparator", background=c["border"])
        s.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"])
        s.configure("Title.TLabel", background=c["bg"], foreground=c["text"],
                    font=("Segoe UI", 11, "bold"))
        s.configure("Big.TLabel", background=c["bg"], foreground=c["text"],
                    font=("Segoe UI", 22, "bold"))

        # Botones: planos, con uno de acento para la acción principal.
        s.configure("TButton", background=c["panel"], foreground=c["text"],
                    bordercolor=c["border"], relief="flat", padding=(12, 6))
        s.map("TButton",
              background=[("disabled", c["bg"]), ("pressed", c["border"]),
                          ("active", c["field"])],
              foreground=[("disabled", c["muted"])])
        s.configure("Accent.TButton", background=c["accent"],
                    foreground=c["accent_text"], relief="flat", padding=(16, 6),
                    font=("Segoe UI", 9, "bold"))
        s.map("Accent.TButton",
              background=[("disabled", c["trough"]), ("active", c["accent_hover"])],
              foreground=[("disabled", c["muted"])])

        s.configure("TCheckbutton", indicatorcolor=c["field"])
        s.map("TCheckbutton",
              indicatorcolor=[("selected", c["accent"])],
              foreground=[("disabled", c["muted"])])

        s.configure("TCombobox", fieldbackground=c["field"], background=c["panel"],
                    foreground=c["text"], arrowcolor=c["text"],
                    bordercolor=c["border"], selectbackground=c["select_bg"],
                    selectforeground=c["text"])
        s.map("TCombobox",
              fieldbackground=[("readonly", c["field"]), ("disabled", c["bg"])],
              foreground=[("disabled", c["muted"])])
        # El desplegable del Combobox es un Listbox tk interno: sólo se puede
        # colorear por la base de datos de opciones.
        self.master.option_add("*TCombobox*Listbox.background", c["field"])
        self.master.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.master.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.master.option_add("*TCombobox*Listbox.selectForeground", c["accent_text"])

        s.configure("TProgressbar", background=c["accent"], troughcolor=c["trough"],
                    bordercolor=c["border"], lightcolor=c["accent"],
                    darkcolor=c["accent"])
        s.configure("TScrollbar", background=c["panel"], troughcolor=c["trough"],
                    bordercolor=c["border"], arrowcolor=c["muted"])
        s.map("TScrollbar", background=[("active", c["border"])])
        s.configure("TScale", troughcolor=c["trough"], background=c["bg"])

        s.configure("Treeview", rowheight=24, background=c["panel"],
                    fieldbackground=c["panel"], foreground=c["text"],
                    bordercolor=c["border"], relief="flat")
        s.map("Treeview", background=[("selected", c["select_bg"])],
              foreground=[("selected", c["text"])])
        s.configure("Treeview.Heading", background=c["field"], foreground=c["muted"],
                    relief="flat", font=("Segoe UI", 9, "bold"))
        s.map("Treeview.Heading", background=[("active", c["border"])])

        # El canvas es un widget clásico: no lo alcanza ttk.
        if hasattr(self, "canvas"):
            self.canvas.configure(bg=c["panel"], highlightbackground=c["border"])
        if hasattr(self, "theme_btn"):
            # El botón anuncia a qué tema cambia, no en cuál estás.
            self.theme_btn.configure(
                text="☀  Tema claro" if self.theme_name == "oscuro"
                else "☾  Tema oscuro")

        set_dark_titlebar(self.master, c["dark_titlebar"])
        if hasattr(self, "tree"):
            self._retag_rows()
        if hasattr(self, "canvas"):
            self._draw_timeline()

    def _set_theme(self, name: str):
        if name not in THEMES or name == self.theme_name:
            return
        self.theme_name = name
        self._apply_theme()
        save_theme(name)

    def _toggle_theme(self):
        self._set_theme("claro" if self.theme_name == "oscuro" else "oscuro")

    def _retag_rows(self):
        """Recolorea las filas: el tinte por acorde depende del tema."""
        if not self.result:
            return
        dark = self.theme_name == "oscuro"
        for seg in self.result.chords:
            self.tree.tag_configure(f"chord{seg.chord}",
                                    background=tint_for(seg.chord, dark=dark),
                                    foreground=self.colors["text"])

    def _show_about(self):
        win = tk.Toplevel(self.master)
        win.title(f"Acerca de {APP_NAME}")
        win.configure(bg=self.colors["bg"])
        set_dark_titlebar(win, self.colors["dark_titlebar"])
        win.resizable(False, False)
        win.transient(self.master)

        body = ttk.Frame(win, padding=24)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="Extractor de acordes, tonalidad y tempo desde audio",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(body, text=f"Versión {APP_VERSION}",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 14))

        ttk.Separator(body, orient="horizontal").pack(fill="x")

        credit = ttk.Frame(body)
        credit.pack(fill="x", pady=14)
        ttk.Label(credit, text="Creado por", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(credit, text=AUTHOR, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(credit, text=AUTHOR_SITE, font=("Segoe UI", 11)).pack(anchor="w",
                                                                       pady=(2, 0))

        ttk.Separator(body, orient="horizontal").pack(fill="x")

        ttk.Label(body, style="Muted.TLabel", justify="left",
                  text="Detección de acordes con los modelos preentrenados de madmom.\n"
                       "Interfaz en Python y Tkinter; audio con pygame y ffmpeg.\n"
                       "El historial se guarda en una base SQLite en tu carpeta de "
                       "datos.").pack(anchor="w", pady=(14, 16))

        ttk.Button(body, text="Cerrar", command=win.destroy).pack(anchor="e")

        # Centrar sobre la ventana principal
        win.update_idletasks()
        x = self.master.winfo_rootx() + (self.master.winfo_width() - win.winfo_width()) // 2
        y = self.master.winfo_rooty() + (self.master.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        win.grab_set()
        win.focus_set()
        win.bind("<Escape>", lambda _e: win.destroy())

    def _show_url_dialog(self):
        win = tk.Toplevel(self.master)
        win.title("Abrir audio desde una URL")
        win.configure(bg=self.colors["bg"])
        set_dark_titlebar(win, self.colors["dark_titlebar"])
        win.resizable(False, False)
        win.transient(self.master)

        body = ttk.Frame(win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Pega el enlace del vídeo",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(body, style="Muted.TLabel", justify="left",
                  text="Se descarga sólo la pista de audio. Si viene en Opus se "
                       "cambia de contenedor a .opus sin recodificar;\nsi viene "
                       "en AAC hay que convertirla a MP3, porque el reproductor "
                       "no admite AAC.").pack(anchor="w", pady=(4, 12))

        url_var = tk.StringVar()
        url_entry = ttk.Entry(body, textvariable=url_var, width=64)
        url_entry.pack(fill="x")

        info_label = ttk.Label(body, style="Muted.TLabel", justify="left")
        info_label.pack(anchor="w", pady=(12, 0))
        progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        progress.pack(fill="x", pady=(12, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(16, 0))
        cancel_btn = ttk.Button(buttons, text="Cancelar", command=win.destroy)
        cancel_btn.pack(side="right")
        action_btn = ttk.Button(buttons, text="Consultar", style="Accent.TButton")
        action_btn.pack(side="right", padx=(0, 8))

        state: dict = {"info": None, "busy": False}
        queue_ = queue.Queue()

        def set_busy(busy: bool, text: str = ""):
            state["busy"] = busy
            action_btn.configure(state="disabled" if busy else "normal")
            url_entry.configure(state="disabled" if busy else "normal")
            if text:
                info_label.configure(text=text)

        def poll():
            try:
                kind, payload = queue_.get_nowait()
            except queue.Empty:
                if state["busy"]:
                    win.after(80, poll)
                return

            if kind == "progress":
                progress.configure(value=payload)
                info_label.configure(
                    text=f"Descargando… {payload:.0f} %")
                win.after(80, poll)
                return

            set_busy(False)
            if kind == "error":
                exc, trace = payload
                report_error(trace)
                info_label.configure(text=f"Error: {exc}")
                messagebox.showerror("No se pudo obtener el audio", str(exc),
                                     parent=win)
                return

            if kind == "info":
                info = state["info"] = payload
                minutes = format_time(info.duration)
                ram = info.estimated_ram_mb / 1024
                secs = info.estimated_analysis_seconds
                detail = (f"{info.title}\n"
                          f"{info.uploader} · {minutes}\n"
                          f"Pista: {'Opus → .opus sin recodificar' if info.has_opus else 'AAC → hay que convertir a MP3'}\n"
                          f"Análisis estimado: ~{ram:.1f} GB de RAM y ~{format_time(secs)}")
                if info.is_long:
                    detail += ("\n\n⚠  Es un audio largo. El análisis carga la señal "
                               "entera en memoria,\n    así que puede agotar la RAM "
                               "del equipo.")
                info_label.configure(text=detail)
                action_btn.configure(text="Descargar y cargar")
                return

            if kind == "downloaded":
                path, info = payload
                win.destroy()
                self._on_stop()
                self._load_audio(path)
                self.analyze_btn.configure(state="normal")
                self.result = None
                self.duration = 0.0
                self.position = 0.0
                self._clear_results()
                self.status.configure(
                    text=f"Descargado: {info.title} — pulsa «Analizar».")

        def work_probe(url):
            try:
                queue_.put(("info", ytaudio.probe(url)))
            except BaseException as exc:
                queue_.put(("error", (exc, traceback.format_exc())))

        def work_download(url, info):
            try:
                path = ytaudio.download(
                    url, self._downloads_dir(), info,
                    on_progress=lambda pct: queue_.put(("progress", pct)))
                queue_.put(("downloaded", (path, info)))
            except BaseException as exc:
                queue_.put(("error", (exc, traceback.format_exc())))

        def on_action():
            url = url_var.get().strip()
            if not url:
                return
            info = state["info"]
            if info is None:
                set_busy(True, "Consultando el enlace…")
                target, args = work_probe, (url,)
            else:
                if info.is_long and not messagebox.askyesno(
                        "Audio largo",
                        f"«{info.title}» dura {format_time(info.duration)}.\n\n"
                        f"El análisis necesitará unos "
                        f"{info.estimated_ram_mb / 1024:.1f} GB de RAM y "
                        f"{format_time(info.estimated_analysis_seconds)}.\n"
                        f"¿Continuar de todas formas?",
                        parent=win, default="no", icon="warning"):
                    return
                set_busy(True, "Descargando…")
                target, args = work_download, (url, info)
            threading.Thread(target=target, args=args, daemon=True).start()
            win.after(80, poll)

        def on_url_change(*_a):
            # Si cambia la URL, la consulta anterior ya no vale.
            state["info"] = None
            action_btn.configure(text="Consultar")
            progress.configure(value=0)

        url_var.trace_add("write", on_url_change)
        action_btn.configure(command=on_action)
        url_entry.bind("<Return>", lambda _e: on_action())

        win.update_idletasks()
        x = self.master.winfo_rootx() + (self.master.winfo_width() - win.winfo_width()) // 2
        y = self.master.winfo_rooty() + (self.master.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()
        url_entry.focus_set()
        win.bind("<Escape>", lambda _e: win.destroy())

    @staticmethod
    def _downloads_dir() -> str:
        directory = os.path.join(app_dir(), "downloads")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _show_history(self):
        if self.history is None:
            return
        win = tk.Toplevel(self.master)
        win.title("Historial de análisis")
        win.configure(bg=self.colors["bg"])
        set_dark_titlebar(win, self.colors["dark_titlebar"])
        win.geometry("900x460")
        win.transient(self.master)

        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)

        search_row = ttk.Frame(body)
        search_row.pack(fill="x", pady=(0, 10))
        ttk.Label(search_row, text="Buscar:").pack(side="left")
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=search_var, width=34)
        search_entry.pack(side="left", padx=(8, 8))
        ttk.Label(search_row, style="Muted.TLabel",
                  text="por nombre de archivo, método o tonalidad · "
                       "pulsa una cabecera para ordenar").pack(side="left")

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)

        # (columna, título, ancho, alineación, cómo se ordena)
        columns = (
            ("archivo", "Archivo", 250, "w", lambda e: e.filename.lower()),
            ("fecha", "Analizado", 130, "w", lambda e: e.created_at),
            ("metodo", "Método", 90, "w", lambda e: e.method),
            ("tonalidad", "Tonalidad", 100, "w", lambda e: (e.key or "").lower()),
            ("tempo", "Tempo", 80, "e", lambda e: e.tempo_bpm or 0.0),
            ("acordes", "Acordes", 70, "e", lambda e: e.chord_count),
            ("duracion", "Duración", 80, "e", lambda e: e.audio_duration),
            ("audio", "Audio", 110, "w", lambda e: e.file_exists),
        )
        sort_keys = {col: key for col, _t, _w, _a, key in columns}
        titles = {col: title for col, title, _w, _a, _k in columns}

        tree = ttk.Treeview(table, columns=[c[0] for c in columns],
                            show="headings", selectmode="browse")
        for col, title, width, anchor, _key in columns:
            tree.heading(col, text=title,
                         command=lambda c=col: sort_by(c))
            tree.column(col, width=width, anchor=anchor,
                        stretch=(col == "archivo"))
        scroll = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        tree.tag_configure("missing", foreground=self.colors["muted"])

        ids: dict[str, int] = {}
        count_label = ttk.Label(body, style="Muted.TLabel")
        # Por defecto, lo más reciente primero.
        state = {"entries": [], "column": "fecha", "reverse": True}

        def sort_by(column: str):
            if state["column"] == column:
                state["reverse"] = not state["reverse"]
            else:
                state["column"] = column
                # Fechas y números empiezan de mayor a menor; el texto, de A a Z.
                state["reverse"] = column in ("fecha", "tempo", "acordes",
                                              "duracion", "audio")
            render()

        def refresh():
            """Relee de la base y repinta."""
            state["entries"] = self.history.recent()
            render()

        def render():
            """Aplica filtro y orden sobre lo ya leído."""
            needle = search_var.get().strip().lower()
            entries = [
                e for e in state["entries"]
                if not needle
                or needle in e.filename.lower()
                or needle in e.method.lower()
                or needle in (e.key or "").lower()
            ]
            entries.sort(key=sort_keys[state["column"]], reverse=state["reverse"])

            for col in sort_keys:
                arrow = ""
                if col == state["column"]:
                    arrow = "  ▼" if state["reverse"] else "  ▲"
                tree.heading(col, text=titles[col] + arrow)

            tree.delete(*tree.get_children())
            ids.clear()
            for e in entries:
                row = tree.insert(
                    "", "end", tags=() if e.file_exists else ("missing",),
                    values=(e.filename, f"{e.created_at:%d/%m/%Y %H:%M}", e.method,
                            e.key or "—",
                            f"{e.tempo_bpm:.1f}" if e.tempo_bpm else "—",
                            e.chord_count, format_time(e.audio_duration),
                            "disponible" if e.file_exists else "no encontrado"))
                ids[row] = e.id

            total = len(state["entries"])
            if needle:
                count_label.configure(
                    text=f"{len(entries)} de {total} análisis coinciden con "
                         f"«{search_var.get().strip()}».")
            else:
                count_label.configure(
                    text=f"{total} análisis guardados. Los marcados como «no "
                         f"encontrado» se pueden ver, pero no reproducir.")

        search_var.trace_add("write", lambda *_a: render())

        def load_selected():
            sel = tree.selection()
            if not sel:
                return
            got = self.history.get(ids[sel[0]])
            if got is None:
                return
            result, source_path = got
            self._on_stop()
            self._load_audio(source_path if os.path.isfile(source_path) else None)
            self.analyze_btn.configure(
                state="normal" if self.audio_path else "disabled")
            self._clear_results()
            self._show_result(result)
            self.status.configure(
                text=f"Cargado del historial: {os.path.basename(source_path)}"
                     + ("" if self.audio_path else
                        " — el audio ya no está en su ruta original, "
                        "no se puede reproducir."))
            win.destroy()

        def delete_selected():
            sel = tree.selection()
            if not sel:
                return
            values = tree.item(sel[0], "values")
            if messagebox.askyesno(
                    "Eliminar del historial",
                    f"¿Eliminar este análisis?\n\n"
                    f"{values[0]}\n{values[2]} · analizado el {values[1]}\n\n"
                    f"El archivo de audio no se toca, pero habrá que volver a "
                    f"procesarlo.",
                    parent=win, default="no", icon="warning"):
                self.history.delete(ids[sel[0]])
                refresh()

        def clear_all():
            total = len(state["entries"])
            if not total:
                return
            if messagebox.askyesno(
                    "Vaciar historial",
                    f"¿Borrar los {total} análisis guardados?\n\n"
                    f"Esto no se puede deshacer. Los archivos de audio no se "
                    f"tocan, pero habrá que volver a procesarlos.",
                    parent=win, default="no", icon="warning"):
                self.history.clear()
                refresh()

        tree.bind("<Double-Button-1>", lambda _e: load_selected())

        count_label.pack(anchor="w", pady=(10, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Cerrar", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="Vaciar historial", command=clear_all
                   ).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Eliminar", command=delete_selected
                   ).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Cargar", command=load_selected,
                   style="Accent.TButton").pack(side="right", padx=(0, 8))

        refresh()
        win.grab_set()
        win.focus_set()
        win.bind("<Escape>", lambda _e: win.destroy())

    def _build_toolbar(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x")

        ttk.Button(bar, text="Abrir audio…", command=self._on_open).pack(side="left")
        # yt-dlp es opcional y externo: si no está, la función no existe.
        if ytaudio.find_ytdlp():
            ttk.Button(bar, text="Desde URL…", command=self._show_url_dialog
                       ).pack(side="left", padx=(8, 0))
        self.file_label = ttk.Label(bar, text="Ningún archivo seleccionado",
                                    style="Muted.TLabel")
        self.file_label.pack(side="left", padx=10)

        # Con side="right" el primero que se empaqueta queda más a la derecha.
        self.analyze_btn = ttk.Button(bar, text="Analizar", command=self._on_analyze,
                                      state="disabled", style="Accent.TButton")
        self.analyze_btn.pack(side="right")
        ttk.Button(bar, text="Acerca de", command=self._show_about
                   ).pack(side="right", padx=(0, 8))
        # La franja del menú la dibuja Windows y no acepta color, así que el
        # cambio de tema vive aquí, donde sí se puede estilar.
        self.theme_btn = ttk.Button(bar, command=self._toggle_theme, width=14)
        self.theme_btn.pack(side="right", padx=(0, 8))
        self.history_btn = ttk.Button(bar, text="Historial",
                                      command=self._show_history)
        self.history_btn.pack(side="right", padx=(0, 8))
        if self.history is None:
            self.history_btn.configure(state="disabled")

    def _build_options(self):
        box = ttk.Labelframe(self, text="Opciones de análisis", padding=8)
        box.pack(fill="x", pady=(10, 0))

        ttk.Label(box, text="Método:").grid(row=0, column=0, sticky="w")
        self.method_var = tk.StringVar(value="deepchroma")
        ttk.Combobox(box, textvariable=self.method_var, width=12, state="readonly",
                     values=["deepchroma", "cnn"]).grid(row=0, column=1, padx=(4, 16))

        self.key_var = tk.BooleanVar(value=True)
        self.tempo_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="Tonalidad", variable=self.key_var
                        ).grid(row=0, column=2, padx=(0, 8))
        ttk.Checkbutton(box, text="Tempo", variable=self.tempo_var
                        ).grid(row=0, column=3, padx=(0, 16))

        # Sin esto no habría forma de recalcular un archivo ya cacheado.
        self.force_var = tk.BooleanVar(value=False)
        self.force_check = ttk.Checkbutton(
            box, text="Reanalizar (ignorar historial)", variable=self.force_var)
        self.force_check.grid(row=0, column=7, padx=(16, 0), sticky="e")
        if self.history is None:
            self.force_check.grid_remove()

        # La separación con Demucs no puede funcionar empaquetada:
        # separate_harmonic() lanza "sys.executable -m demucs", y dentro del .exe
        # sys.executable es el propio ejecutable. En vez de dejar un control
        # muerto con una etiqueta disculpándose, no se construye.
        self.separate_var = tk.BooleanVar(value=False)
        self.device_var = tk.StringVar(value="auto")
        if not FROZEN:
            self.separate_check = ttk.Checkbutton(
                box, text="Separar con Demucs (bass + other)",
                variable=self.separate_var, command=self._sync_device_state)
            self.separate_check.grid(row=0, column=4, padx=(0, 8))

            ttk.Label(box, text="Dispositivo:").grid(row=0, column=5, sticky="w")
            self.device_combo = ttk.Combobox(box, textvariable=self.device_var,
                                             width=7, state="disabled",
                                             values=["auto", "cuda", "cpu"])
            self.device_combo.grid(row=0, column=6, padx=(4, 0))

        self.progress = ttk.Progressbar(box, mode="indeterminate")
        self.progress.grid(row=1, column=0, columnspan=8, sticky="ew", pady=(10, 0))
        self.status = ttk.Label(box, text="Listo.", style="Muted.TLabel")
        self.status.grid(row=2, column=0, columnspan=8, sticky="w", pady=(6, 0))
        box.columnconfigure(6, weight=1)

    def _build_summary(self):
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(10, 0))
        self.summary = ttk.Label(row, text="Tonalidad: —     Tempo: —     Acordes: —",
                                 style="Title.TLabel")
        self.summary.pack(side="left")

        self.export_json_btn = ttk.Button(row, text="Exportar .lab",
                                          command=self._on_export_lab, state="disabled")
        self.export_json_btn.pack(side="right")
        self.export_lab_btn = ttk.Button(row, text="Exportar JSON",
                                         command=self._on_export_json, state="disabled")
        self.export_lab_btn.pack(side="right", padx=(0, 6))

    def _build_timeline(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="x", pady=(8, 0))

        self.canvas = tk.Canvas(wrap, height=110, bg=self.colors["panel"],
                                highlightthickness=1,
                                highlightbackground=self.colors["border"],
                                cursor="hand2")
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda _e: self._draw_timeline())
        self.canvas.bind("<Button-1>", self._on_timeline_click)
        self.canvas.bind("<B1-Motion>", self._on_timeline_click)

        self.hscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.hscroll.set)
        self.hscroll.pack(fill="x")

        # A 1x cabe la canción entera; con zoom la pista se ensancha y aparece el
        # scroll, que es lo que permite leer los acordes cortos.
        zoom_row = ttk.Frame(wrap)
        zoom_row.pack(fill="x", pady=(6, 0))
        ttk.Label(zoom_row, text="Zoom", style="Muted.TLabel").pack(side="left")
        self.zoom_var = tk.DoubleVar(value=1.0)
        ttk.Scale(zoom_row, from_=1.0, to=20.0, variable=self.zoom_var,
                  command=lambda _v: self._on_zoom(), length=180).pack(side="left", padx=8)
        self.zoom_label = ttk.Label(zoom_row, text="1.0×", style="Muted.TLabel", width=6)
        self.zoom_label.pack(side="left")
        ttk.Label(zoom_row, style="Muted.TLabel",
                  text="Haz clic en la línea de tiempo o en una fila para saltar a ese punto."
                  ).pack(side="left", padx=16)

    def _on_zoom(self):
        self.zoom_label.configure(text=f"{self.zoom_var.get():.1f}×")
        self._draw_timeline()
        self._scroll_playhead_into_view()

    def _build_table(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, pady=(10, 0))

        cols = ("n", "start", "end", "dur", "chord")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for col, text, width, anchor in (
            ("n", "#", 50, "e"),
            ("start", "Inicio", 90, "e"),
            ("end", "Fin", 90, "e"),
            ("dur", "Duración", 90, "e"),
            ("chord", "Acorde", 120, "w"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor,
                             stretch=(col == "chord"))
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)

    def _build_player(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(10, 0))

        self.play_btn = ttk.Button(bar, text="▶  Reproducir", width=14,
                                   command=self._on_play_pause, state="disabled")
        self.play_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="■  Parar", width=10,
                                   command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)

        self.time_label = ttk.Label(bar, text="0:00.0 / 0:00.0", style="Muted.TLabel")
        self.time_label.pack(side="left", padx=12)

        self.now_label = ttk.Label(bar, text="—", style="Big.TLabel")
        self.now_label.pack(side="right")
        ttk.Label(bar, text="Acorde actual:", style="Muted.TLabel"
                  ).pack(side="right", padx=(0, 8))

        if not self._audio_ready:
            hint = ("Reproductor no disponible: instala pygame (pip install pygame)"
                    if pygame is None else
                    "Reproductor no disponible: no se pudo abrir el dispositivo de audio")
            ttk.Label(bar, text=hint, style="Muted.TLabel").pack(side="left", padx=12)

    # ------------------------------------------------------------------ archivo
    def _on_open(self):
        path = filedialog.askopenfilename(title="Elige un archivo de audio",
                                          filetypes=AUDIO_TYPES)
        if path:
            self._set_audio(path)

    def _set_audio(self, path: str):
        if not os.path.isfile(path):
            messagebox.showerror("Archivo no encontrado", path)
            return
        self._on_stop()
        self._load_audio(path)
        self.analyze_btn.configure(state="normal")
        self.status.configure(text="Archivo cargado. Pulsa «Analizar».")
        self.result = None
        self.duration = 0.0
        self.position = 0.0
        self._clear_results()

    def _load_audio(self, path: str | None):
        """
        Deja el audio listo para reproducir sin tocar los resultados. Con None
        (entrada del historial cuyo archivo ya no está) desactiva el reproductor.
        """
        self.audio_path = path
        if path is None:
            self.file_label.configure(text="Audio no encontrado",
                                      style="Muted.TLabel")
            self.play_btn.configure(state="disabled")
            self.stop_btn.configure(state="disabled")
            return
        self.file_label.configure(text=os.path.basename(path), style="TLabel")
        if self._audio_ready:
            try:
                pygame.mixer.music.load(path)
                self.play_btn.configure(state="normal")
                self.stop_btn.configure(state="normal")
            except Exception:
                self.play_btn.configure(state="disabled")
                self.stop_btn.configure(state="disabled")

    def _clear_results(self):
        self.tree.delete(*self.tree.get_children())
        self._row_ids = []
        self._auto_selected_row = None
        self.zoom_var.set(1.0)
        self.zoom_label.configure(text="1.0×")
        self.summary.configure(text="Tonalidad: —     Tempo: —     Acordes: —")
        self.now_label.configure(text="—")
        self.export_json_btn.configure(state="disabled")
        self.export_lab_btn.configure(state="disabled")
        self._draw_timeline()

    def _sync_device_state(self):
        if not hasattr(self, "device_combo"):
            return          # empaquetado: los controles de Demucs no existen
        self.device_combo.configure(
            state="readonly" if self.separate_var.get() else "disabled")

    # ------------------------------------------------------------------ análisis
    def _on_analyze(self):
        if not self.audio_path:
            return
        self._set_busy(True)
        note = ("Separando con Demucs y analizando… (la primera vez descarga el "
                "modelo; en CPU puede tardar minutos)"
                if self.separate_var.get() else
                "Analizando… (los modelos de madmom tardan unos segundos)")
        self.status.configure(text=note)

        opts = dict(
            method=self.method_var.get(),
            with_key=self.key_var.get(),
            with_tempo=self.tempo_var.get(),
            separate=self.separate_var.get(),
            device=self.device_var.get(),
        )
        threading.Thread(target=self._worker,
                         args=(self.audio_path, opts, self.force_var.get()),
                         daemon=True).start()
        self.after(100, self._poll_worker)

    def _worker(self, path: str, opts: dict, force: bool):
        """
        Hilo de trabajo: busca en el historial y, si no hay nada, analiza y
        guarda. El hash y la consulta también van aquí para no bloquear la
        interfaz.
        """
        try:
            result = cached_at = fingerprint = None
            okey = options_key(opts["method"], opts["with_key"],
                               opts["with_tempo"], opts["separate"])
            if self.history is not None:
                # Un problema del historial nunca debe impedir analizar.
                try:
                    fingerprint = History.fingerprint(path)
                    if not force:
                        hit = self.history.find(fingerprint, okey)
                        if hit is not None:
                            result, cached_at = hit
                except Exception:
                    fingerprint = None

            if result is None:
                result = extract(path, **opts)
                if self.history is not None and fingerprint:
                    try:
                        self.history.save(result, path, fingerprint, okey)
                    except Exception:
                        pass
            self._queue.put(("ok", (result, cached_at)))
        except BaseException as exc:  # el hilo no puede tocar Tk directamente
            self._queue.put(("error", (exc, traceback.format_exc())))

    def _poll_worker(self):
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_worker)
            return

        self._set_busy(False)
        if kind == "error":
            exc, trace = payload
            # La traza completa no cabe en el diálogo, pero hace falta para
            # depurar: va a la consola o, en el .exe, a un archivo de log.
            logged = report_error(trace)
            self.status.configure(text=f"Error: {exc}")
            hint = diagnose(exc, trace)
            detail = f"{type(exc).__name__}: {exc}"
            if hint:
                detail += f"\n\n{hint}"
            detail += (f"\n\nTraza completa en:\n{logged}" if logged
                       else "\n\n(La traza completa está en la consola.)")
            messagebox.showerror("Error al analizar", detail)
            return
        result, cached_at = payload
        self._show_result(result, cached_at=cached_at)

    def _set_busy(self, busy: bool):
        self.analyze_btn.configure(state="disabled" if busy else "normal")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _show_result(self, result: ExtractionResult, cached_at=None):
        self.result = result
        self.duration = max((c.end for c in result.chords), default=0.0)
        self.position = 0.0

        key = result.key or "—"
        tempo = f"{result.tempo_bpm} BPM" if result.tempo_bpm else "—"
        sep = " · separado (Demucs)" if result.separated else ""
        self.summary.configure(
            text=f"Tonalidad: {key}     Tempo: {tempo}     "
                 f"Acordes: {len(result.chords)}     Método: {result.method}{sep}")
        if cached_at is not None:
            self.status.configure(
                text=f"Recuperado del historial (analizado el "
                     f"{cached_at:%d/%m/%Y %H:%M}). Marca «Reanalizar» para "
                     f"recalcularlo.")
        else:
            self.status.configure(
                text=f"Análisis completado en {format_time(self.duration)} de audio.")

        self.tree.delete(*self.tree.get_children())
        self._row_ids = []
        self._auto_selected_row = None
        for i, seg in enumerate(result.chords, start=1):
            row = self.tree.insert(
                "", "end", tags=(f"chord{seg.chord}",),
                values=(i, f"{seg.start:.2f}", f"{seg.end:.2f}",
                        f"{seg.end - seg.start:.2f}", pretty_label(seg.chord)))
            self._row_ids.append(row)
        self._retag_rows()      # el tinte depende del tema activo

        self.export_json_btn.configure(state="normal")
        self.export_lab_btn.configure(state="normal")
        self._draw_timeline()
        self._set_position(0.0)

    # ------------------------------------------------------------------ timeline
    def _geometry(self):
        """
        (pad, ancho útil) en coordenadas del canvas, o None si aún no hay tamaño.
        Con zoom > 1 el ancho supera el visible y el canvas hace scroll.
        """
        pad = 10
        visible = self.canvas.winfo_width() - 2 * pad
        if visible <= 20:
            return None
        return pad, visible * self.zoom_var.get()

    def _draw_timeline(self):
        c = self.canvas
        c.delete("all")
        geom = self._geometry()
        if geom is None:
            return
        pad, span = geom
        height = c.winfo_height()
        c.configure(scrollregion=(0, 0, span + 2 * pad, height))

        colors = self.colors
        if not self.result or self.duration <= 0:
            c.create_text(c.winfo_width() / 2, height / 2,
                          text="Analiza un archivo para ver aquí la línea de acordes",
                          fill=colors["muted"], font=("Segoe UI", 10))
            return

        top, bottom = 12, height - 26
        for seg in self.result.chords:
            x0 = pad + seg.start / self.duration * span
            x1 = pad + seg.end / self.duration * span
            if x1 - x0 < 1:
                x1 = x0 + 1
            c.create_rectangle(x0, top, x1, bottom, fill=color_for(seg.chord),
                               outline=colors["seg_outline"], width=1)
            if x1 - x0 > 26:
                c.create_text((x0 + x1) / 2, (top + bottom) / 2,
                              text=pretty_label(seg.chord),
                              fill=text_color_for(seg.chord),
                              font=("Segoe UI", 9, "bold"))

        step = ruler_step(self.duration)
        t = 0.0
        while t <= self.duration:
            x = pad + t / self.duration * span
            c.create_line(x, bottom, x, bottom + 5, fill=colors["ruler"])
            c.create_text(x, bottom + 14, text=format_time(t), fill=colors["muted"],
                          font=("Segoe UI", 8))
            t += step

        c.create_line(pad, top, pad, bottom, fill=colors["playhead"], width=2,
                      tags="playhead")
        self._move_playhead()

    def _move_playhead(self):
        geom = self._geometry()
        if geom is None or not self.result or self.duration <= 0:
            return
        pad, span = geom
        x = pad + min(self.position, self.duration) / self.duration * span
        self.canvas.coords("playhead", x, 12, x, self.canvas.winfo_height() - 26)
        self._follow_playhead()

    def _on_timeline_click(self, event):
        geom = self._geometry()
        if geom is None or not self.result or self.duration <= 0:
            return
        pad, span = geom
        # canvasx() traduce el píxel de pantalla a coordenada de la pista scrolleada
        t = (self.canvas.canvasx(event.x) - pad) / span * self.duration
        self._seek(max(0.0, min(t, self.duration)))

    def _playhead_x(self) -> float | None:
        geom = self._geometry()
        if geom is None or not self.result or self.duration <= 0:
            return None
        pad, span = geom
        return pad + min(self.position, self.duration) / self.duration * span

    def _scroll_playhead_into_view(self):
        x = self._playhead_x()
        if x is None:
            return
        total = self.canvas.bbox("all")
        if not total:
            return
        width = max(total[2], 1)
        visible = self.canvas.winfo_width()
        if width <= visible:
            return
        self.canvas.xview_moveto(max(0.0, (x - visible / 2) / width))

    def _follow_playhead(self):
        """Con zoom el cursor se sale de la vista: lo seguimos sólo cuando ya salió,
        para no pelearnos con el scroll manual."""
        x = self._playhead_x()
        if x is None:
            return
        visible = self.canvas.winfo_width()
        left = self.canvas.canvasx(0)
        if x < left + 40 or x > left + visible - 40:
            self._scroll_playhead_into_view()

    # ------------------------------------------------------------------ tabla
    def _chord_at(self, t: float):
        if not self.result:
            return None, -1
        for i, seg in enumerate(self.result.chords):
            if seg.start <= t < seg.end:
                return seg, i
        return None, -1

    def _on_row_selected(self, _event):
        if not self.result:
            return
        sel = self.tree.selection()
        # Si la fila es la que marcamos al seguir la reproducción, el evento lo
        # hemos provocado nosotros: saltar aquí reiniciaría el audio en cada
        # cambio de acorde y se oiría un chasquido.
        if not sel or sel[0] == self._auto_selected_row:
            return
        index = self._row_ids.index(sel[0])
        self._seek(self.result.chords[index].start)

    # ------------------------------------------------------------------ player
    def _on_play_pause(self):
        if not self._audio_ready or not self.audio_path:
            return
        if self._playing:
            pygame.mixer.music.pause()
            self._pause_pos = self.position
            self._playing = False
            self.play_btn.configure(text="▶  Reproducir")
        else:
            if pygame.mixer.music.get_busy():          # estaba en pausa
                pygame.mixer.music.unpause()
                # get_pos() puede o no contar el tiempo en pausa: recalibramos.
                self._play_offset = self._pause_pos - pygame.mixer.music.get_pos() / 1000
            else:
                self._start_at(self.position)
            self._playing = True
            self.play_btn.configure(text="⏸  Pausa")

    def _start_at(self, seconds: float):
        try:
            pygame.mixer.music.play(start=seconds)
            self._play_offset = seconds
        except Exception:
            # algunos formatos no admiten 'start': reproducimos desde el principio
            pygame.mixer.music.play()
            self._play_offset = 0.0
            self._set_position(0.0)

    def _on_stop(self):
        if self._audio_ready:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self._playing = False
        self._play_offset = 0.0
        self._pause_pos = 0.0
        self.play_btn.configure(text="▶  Reproducir")
        self._set_position(0.0)

    def _seek(self, seconds: float):
        self._set_position(seconds)
        if not self._audio_ready:
            return
        if self._playing:
            self._start_at(seconds)
        else:
            self._pause_pos = seconds
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    def _tick(self):
        if self._playing and self._audio_ready:
            if pygame.mixer.music.get_busy():
                self._set_position(self._play_offset + pygame.mixer.music.get_pos() / 1000)
            else:
                self._on_stop()
        self.after(60, self._tick)

    def _set_position(self, seconds: float):
        self.position = max(0.0, seconds)
        self.time_label.configure(
            text=f"{format_time(self.position)} / {format_time(self.duration)}")
        self._move_playhead()

        seg, index = self._chord_at(self.position)
        self.now_label.configure(text=pretty_label(seg.chord) if seg else "—")
        if index >= 0 and index < len(self._row_ids):
            row = self._row_ids[index]
            if self.tree.selection() != (row,):
                self._auto_selected_row = row
                self.tree.selection_set(row)
                self.tree.see(row)

    # ------------------------------------------------------------------ export
    def _export(self, kind: str, extension: str, content: str):
        base = os.path.splitext(os.path.basename(self.audio_path or "acordes"))[0]
        path = filedialog.asksaveasfilename(
            title=f"Guardar {kind}", defaultextension=extension,
            initialfile=f"{base}{extension}",
            filetypes=[(kind, f"*{extension}"), ("Todos los archivos", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.status.configure(text=f"Guardado en {path}")
        except OSError as exc:
            messagebox.showerror("No se pudo guardar", str(exc))

    def _on_export_json(self):
        if self.result:
            self._export("JSON", ".json", self.result.to_json(indent=2))

    def _on_export_lab(self):
        if self.result:
            self._export("Anotación .lab", ".lab", self.result.to_lab())


def main():
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    ChordApp(root, initial_file=initial)
    root.mainloop()


if __name__ == "__main__":
    main()
