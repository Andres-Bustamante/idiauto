from __future__ import annotations

import contextlib
import io
import os
import platform
import subprocess
import sys
import tempfile
from queue import Queue
from threading import Thread
from typing import Any, Callable


def abrir_archivo(path: str) -> None:
    """Abre un archivo con el visor por defecto del sistema."""
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass

from playwright.sync_api import sync_playwright
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Log,
    Markdown,
    Rule,
    Select,
    Static,
)

import html2text

import credentials
import main as core


_HTML2MD = html2text.HTML2Text()
_HTML2MD.body_width = 0
_HTML2MD.ignore_images = True
_HTML2MD.single_line_break = True
_HTML2MD.protect_links = True


def html_a_markdown(html: str) -> str:
    if not html:
        return ""
    try:
        md = _HTML2MD.handle(html).strip()
        return md
    except Exception:
        return html


SECCION_META = {
    "Vencidas": ("overdue", "⚠"),
    "Para Hoy": ("today", "●"),
    "Esta Semana": ("week", "◐"),
    "Este mes": ("month", "○"),
    "Próximo": ("later", "·"),
    "Sin Fecha definida": ("none", "·"),
}


class BrowserWorker:
    """Playwright en un hilo dedicado, con jobs serializados por cola."""

    def __init__(
        self,
        on_event: Callable[[str, Any], None],
        usuario: str,
        password: str,
    ):
        self.on_event = on_event
        self._jobs: Queue = Queue()
        self._thread = Thread(target=self._run, daemon=True)
        self.page = None
        self.usuario = usuario
        self.password = password

    def start(self):
        self._thread.start()

    def submit(self, fn: Callable[["BrowserWorker"], Any]):
        self._jobs.put(fn)

    def stop(self):
        self._jobs.put(None)

    def _instalar_chromium(self):
        import re
        import stat
        if getattr(sys, "frozen", False):
            from playwright._impl._driver import (
                compute_driver_executable, get_driver_env,
            )
            drv = compute_driver_executable()
            env = {**os.environ, **get_driver_env()}
            parts = list(drv) if isinstance(drv, (list, tuple)) else [drv]
            # Dar permisos de ejecución al binario de node bundleado
            for p in parts:
                try:
                    if os.path.isfile(p):
                        st = os.stat(p)
                        os.chmod(p, st.st_mode | stat.S_IEXEC
                                 | stat.S_IXGRP | stat.S_IXOTH)
                except Exception:
                    pass
            # Añadir el dir del node al PATH para re-spawn
            node_dir = os.path.dirname(parts[0])
            env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
            env["PLAYWRIGHT_NODEJS_PATH"] = parts[0]
            cmd = parts + ["install", "chromium"]
        else:
            cmd = [sys.executable, "-m", "playwright",
                   "install", "chromium"]
            env = None
        self.on_event("log", f"[install cmd] {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        pct_re = re.compile(r"(\d+)%|\|\s*(\d+)\s*%")
        last_pct = -1
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip()
            if not line:
                continue
            m = pct_re.search(line)
            if m:
                pct_str = m.group(1) or m.group(2)
                try:
                    pct = int(pct_str)
                except Exception:
                    pct = None
                if pct is not None and pct != last_pct:
                    last_pct = pct
                    self.on_event("install_progress", (pct, line))
            else:
                self.on_event("install_progress", (None, line))
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(
                f"playwright install chromium falló: {proc.returncode}"
            )

    def _run(self):
        # Si estamos en bundle PyInstaller, apuntar al chromium incluido.
        if getattr(sys, "frozen", False):
            bundle_browsers = os.path.join(
                sys._MEIPASS, "ms-playwright",
            )
            if os.path.isdir(bundle_browsers):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundle_browsers

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                self.on_event(
                    "log",
                    f"[fatal] No se pudo iniciar Chromium: {e}",
                )
                return
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            self.page = context.new_page()
            try:
                self.page.goto(core.URL)
                self.page.locator("#usuario").wait_for(
                    state="visible", timeout=10000,
                )
                core.login(self.page, self.usuario, self.password)
                self.page.wait_for_timeout(2000)
                self.page.locator("#menu_8").click()
                core.mostrarTarjetas(self.page)
                core.irAActividades(self.page)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    tipos = core.listarTiposActividad(self.page)
                activa = core.obtenerActividadActiva(self.page)
                self.on_event("ready", {
                    "tarjetas": core.tarjetasCache,
                    "tipos": tipos,
                    "actividad_activa": activa,
                })
            except Exception as e:
                self.on_event("log", f"[init error] {e}")
                browser.close()
                return

            while True:
                job = self._jobs.get()
                if job is None:
                    break
                try:
                    job(self)
                except Exception as e:
                    self.on_event("log", f"[error] {e}")
            browser.close()


# --------------------------------------------------------------------------
# Modals
# --------------------------------------------------------------------------


MODAL_CSS = """
ModalScreen { align: center middle; }
.modal {
    background: $surface;
    border: round $primary;
    padding: 1 2;
    width: 72;
    height: auto;
    max-height: 90%;
}
.modal-title {
    text-style: bold;
    color: $primary;
    margin-bottom: 1;
    width: 100%;
}
.modal-sub {
    color: $text-muted;
    margin-bottom: 1;
    width: 100%;
}
.modal-row { height: auto; margin-bottom: 1; }
.modal-row Label { color: $text-muted; margin-bottom: 0; }
.modal-buttons {
    margin-top: 1;
    height: 3;
    align-horizontal: right;
}
.modal-buttons Button { margin-left: 2; min-width: 12; }
"""


class LoginModal(ModalScreen[dict | None]):
    """Pide usuario y contraseña y los guarda en el keyring del SO."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    CSS = MODAL_CSS

    def __init__(self, usuario_actual: str = ""):
        super().__init__()
        self._usuario_actual = usuario_actual

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("Iniciar sesión en IDI", classes="modal-title")
            yield Static(
                "Las credenciales se guardarán cifradas en el "
                "keyring del sistema (Secret Service / Keychain).",
                classes="modal-sub",
            )
            with Vertical(classes="modal-row"):
                yield Label("Usuario")
                yield Input(
                    value=self._usuario_actual,
                    placeholder="usuario.ejemplo",
                    id="input-usuario",
                )
            with Vertical(classes="modal-row"):
                yield Label("Contraseña")
                yield Input(
                    placeholder="••••••••",
                    password=True,
                    id="input-password",
                )
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancelar", id="cancel")
                yield Button(
                    "Guardar e iniciar", variant="primary", id="ok",
                )

    def on_mount(self) -> None:
        wid = "input-password" if self._usuario_actual else "input-usuario"
        self.query_one(f"#{wid}", Input).focus()

    def _submit(self) -> None:
        usuario = self.query_one("#input-usuario", Input).value.strip()
        password = self.query_one("#input-password", Input).value
        if not usuario or not password:
            self.app.notify(
                "Usuario y contraseña son obligatorios.",
                severity="warning",
            )
            return
        self.dismiss({"usuario": usuario, "password": password})

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "input-usuario":
            self.query_one("#input-password", Input).focus()
        else:
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Confirmación simple Sí/No. Enter = Sí, Esc = No."""

    BINDINGS = [
        Binding("escape", "no", "No"),
        Binding("enter", "si", "Sí"),
    ]

    CSS = MODAL_CSS

    def __init__(self, title: str, detalle: str = ""):
        super().__init__()
        self._title = title
        self._detalle = detalle

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(self._title, classes="modal-title")
            if self._detalle:
                yield Static(self._detalle, classes="modal-sub")
            with Horizontal(classes="modal-buttons"):
                yield Button("No", id="no")
                yield Button("Sí, confirmar", variant="primary", id="si")

    def on_mount(self) -> None:
        self.query_one("#si", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "si")

    def action_si(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class InputModal(ModalScreen[dict | None]):
    """Modal con campos de texto genérico. Enter envía, Esc cancela."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancelar"),
    ]

    CSS = MODAL_CSS

    def __init__(
        self,
        title: str,
        fields: list[tuple[str, str, str]],
        subtitle: str = "",
    ):
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._fields = fields  # list of (key, label, default)

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(self._title, classes="modal-title")
            if self._subtitle:
                yield Static(self._subtitle, classes="modal-sub")
            for key, label, default in self._fields:
                with Vertical(classes="modal-row"):
                    yield Label(label)
                    yield Input(value=default, id=f"input-{key}")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancelar", id="cancel")
                yield Button("Aceptar", variant="primary", id="ok")

    def on_mount(self) -> None:
        if self._fields:
            key = self._fields[0][0]
            self.query_one(f"#input-{key}", Input).focus()

    def _submit(self) -> None:
        data = {
            key: self.query_one(f"#input-{key}", Input).value
            for key, _, _ in self._fields
        }
        self.dismiss(data)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SelectModal(ModalScreen[str | None]):
    """Modal para elegir un valor de una lista."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancelar"),
    ]

    CSS = MODAL_CSS + """
    SelectModal ListView { height: auto; max-height: 20; margin-bottom: 1; }
    """

    def __init__(self, title: str, options: list[tuple[str, str]]):
        super().__init__()
        self._title = title
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(
                "↑↓ para navegar · Enter para seleccionar",
                classes="modal-sub",
            )
            yield ListView(
                *[
                    ListItem(Label(lbl), id=f"opt-{i}")
                    for i, (lbl, _) in enumerate(self._options)
                ]
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancelar", id="cancel")
                yield Button("Aceptar", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one(ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = int(event.item.id.split("-")[1])
        self.dismiss(self._options[idx][1])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            lv = self.query_one(ListView)
            if lv.index is not None:
                self.dismiss(self._options[lv.index][1])
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TarjetaDetalleModal(ModalScreen[dict | None]):
    """Muestra descripción, subtareas, fotos, comentarios y permite
    agregar un comentario o crear actividad desde una subtarea."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    CSS = MODAL_CSS + """
    TarjetaDetalleModal .modal {
        width: 100%; height: 100%;
        max-width: 100%; max-height: 100%;
        border: round $primary;
    }
    TarjetaDetalleModal .modal-buttons { height: 1; margin-top: 1; }
    TarjetaDetalleModal .modal-buttons Button {
        min-width: 10; height: 1;
        padding: 0 2; border: none;
        margin-left: 1;
    }
    .detalle-section { margin-top: 1; }
    .detalle-section-title {
        text-style: bold; color: $accent;
    }
    .subtarea-row {
        height: auto; margin-bottom: 0;
        padding: 0 1;
    }
    .subtarea-row Button {
        min-width: 12; height: 1;
        padding: 0 1; border: none;
    }
    .subtarea-label { width: 1fr; }
    """

    def __init__(self, detalle: dict, titulo_card: str):
        super().__init__()
        self._d = detalle or {}
        self._titulo = titulo_card

    def compose(self) -> ComposeResult:
        d = self._d
        with Vertical(classes="modal"):
            yield Label(
                f"📋 {d.get('titulo') or self._titulo}",
                classes="modal-title",
            )
            yield Static(
                f"[dim]{d.get('proyecto', '')} · "
                f"{d.get('prioridad', '')} · "
                f"{d.get('estado', '')} · "
                f"venc. {d.get('vencimiento', '-') or '-'}[/dim]",
                classes="modal-sub",
            )

            with VerticalScroll():
                desc_html = (d.get("descripcionHtml") or "").strip()
                desc_md = html_a_markdown(desc_html)
                if not desc_md:
                    desc_md = (d.get("descripcionTexto") or "").strip()
                if desc_md:
                    yield Label(
                        "Descripción", classes="detalle-section-title",
                    )
                    yield Markdown(
                        desc_md[:6000]
                        + ("\n\n_...(truncado)_" if len(desc_md) > 6000 else ""),
                        classes="detalle-section",
                    )

                fotos = d.get("rutas_imagenes") or []
                if fotos:
                    yield Label(
                        f"📷 Fotos ({len(fotos)})",
                        classes="detalle-section-title",
                    )
                    self._fotos = fotos
                    for i, p in enumerate(fotos):
                        name = os.path.basename(p)
                        with Horizontal(classes="subtarea-row"):
                            yield Static(
                                f"  {i+1}. {name}  [dim]{p}[/dim]",
                                classes="subtarea-label",
                            )
                            yield Button(
                                "Abrir",
                                id=f"foto-{i}",
                                variant="primary",
                            )

                subs = d.get("subtareas") or []
                if subs:
                    yield Label(
                        f"✓ Subtareas ({len(subs)})",
                        classes="detalle-section-title",
                    )
                    for i, s in enumerate(subs):
                        marca = "✓" if s.get("finalizada") else "○"
                        nombre = (s.get("nombre") or "").strip() or "(sin nombre)"
                        venc = s.get("vencimiento") or ""
                        with Horizontal(classes="subtarea-row"):
                            yield Static(
                                f"{marca} {nombre}"
                                + (f" [dim]· {venc}[/dim]" if venc else ""),
                                classes="subtarea-label",
                            )
                            if not s.get("finalizada"):
                                yield Button(
                                    "Finalizar",
                                    id=f"finsub-{i}",
                                    variant="success",
                                )

                yield Label(
                    "✎ Nuevo comentario", classes="detalle-section-title",
                )
                yield Input(
                    placeholder="Escribe un comentario...",
                    id="input-comentario",
                )

            with Horizontal(classes="modal-buttons"):
                yield Button("Cerrar", id="cancel")
                yield Button(
                    "Guardar comentario", variant="success", id="guardar",
                )

    def on_mount(self) -> None:
        self._subs = self._d.get("subtareas") or []
        if not hasattr(self, "_fotos"):
            self._fotos = []

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "cancel":
            self.dismiss(None)
        elif bid == "guardar":
            texto = self.query_one("#input-comentario", Input).value.strip()
            if not texto:
                self.app.notify(
                    "Escribe un comentario.", severity="warning",
                )
                return
            self.dismiss({"action": "comentario", "texto": texto})
        elif bid and bid.startswith("foto-"):
            idx = int(bid.split("-")[1])
            if 0 <= idx < len(self._fotos):
                abrir_archivo(self._fotos[idx])
                self.app.notify(
                    f"Abriendo {os.path.basename(self._fotos[idx])}...",
                    timeout=3,
                )
        elif bid and bid.startswith("finsub-"):
            idx = int(bid.split("-")[1])
            if 0 <= idx < len(self._subs):
                sub = self._subs[idx]
                self.dismiss({
                    "action": "finalizar_sub",
                    "sub_id": sub.get("id"),
                    "nombre": sub.get("nombre"),
                })

    def action_cancel(self) -> None:
        self.dismiss(None)


class CrearActividadModal(ModalScreen[dict | None]):
    """Elegir origen (tarjeta / reciente / personalizado) + tipo + nombre."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancelar"),
    ]

    CSS = MODAL_CSS + """
    CrearActividadModal .modal { width: 80; }
    """

    def __init__(
        self,
        tarjetas: dict,
        recientes: list[str],
        tipos: list[tuple[str, str]],
    ):
        super().__init__()
        self._tarjetas = tarjetas
        self._recientes = recientes
        self._tipos = tipos or [("(sin tipos)", "")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("Crear nueva actividad", classes="modal-title")
            yield Static(
                "Elige la fuente del nombre de la actividad",
                classes="modal-sub",
            )

            with Vertical(classes="modal-row"):
                yield Label("Origen")
                origenes = [
                    ("Desde tarjeta", "tarjeta"),
                    ("Actividad reciente (panel)", "reciente"),
                    ("Nombre personalizado", "custom"),
                ]
                yield Select(
                    options=origenes, value="tarjeta",
                    id="origen", allow_blank=False,
                )

            tarjeta_opts = []
            for sec, items in self._tarjetas.items():
                for it in items:
                    label = (
                        f"[{sec}] {it.get('id', '')} — "
                        f"{it.get('titulo', '')}"
                    )
                    tarjeta_opts.append((label, it.get("titulo", "")))
            self._tarjeta_opts = tarjeta_opts
            self._reciente_opts = [
                (t, str(i)) for i, t in enumerate(self._recientes)
            ]

            with Vertical(classes="modal-row", id="row-tarjeta"):
                yield Label("Tarjeta")
                yield Select(
                    options=tarjeta_opts or [("(sin tarjetas)", "")],
                    id="tarjeta", allow_blank=True,
                )

            with Vertical(classes="modal-row", id="row-reciente"):
                yield Label("Reciente")
                yield Select(
                    options=self._reciente_opts or [("(sin recientes)", "")],
                    id="reciente", allow_blank=True,
                )

            with Vertical(classes="modal-row", id="row-nombre"):
                yield Label("Nombre")
                yield Input(
                    placeholder="Escribe el nombre de la actividad",
                    id="nombre",
                )

            with Vertical(classes="modal-row", id="row-tipo"):
                yield Label("Tipo de actividad")
                yield Select(
                    options=self._tipos, value=self._tipos[0][1],
                    id="tipo", allow_blank=False,
                )

            with Horizontal(classes="modal-buttons"):
                yield Button("Cancelar", id="cancel")
                yield Button("Crear", variant="primary", id="ok")

    def on_mount(self) -> None:
        self._aplicar_origen("tarjeta")

    def _aplicar_origen(self, origen: str) -> None:
        def show(wid: str, visible: bool) -> None:
            self.query_one(f"#{wid}").display = visible

        show("row-tarjeta", origen == "tarjeta")
        show("row-reciente", origen == "reciente")
        show("row-nombre", origen == "custom")
        show("row-tipo", origen != "reciente")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "origen":
            self._aplicar_origen(str(event.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "ok":
            self.dismiss(None)
            return
        origen = self.query_one("#origen", Select).value
        tipo = self.query_one("#tipo", Select).value
        if origen == "custom":
            nombre = self.query_one("#nombre", Input).value.strip()
            if not nombre:
                self.app.notify(
                    "El nombre no puede estar vacío.",
                    severity="warning",
                )
                return
            self.dismiss({"modo": "custom", "nombre": nombre, "tipo": tipo})
        elif origen == "reciente":
            idx_str = self.query_one("#reciente", Select).value
            if idx_str in (None, Select.BLANK, ""):
                self.app.notify(
                    "Selecciona una actividad reciente.",
                    severity="warning",
                )
                return
            self.dismiss({"modo": "reciente", "index": int(idx_str)})
        else:
            nombre = self.query_one("#tarjeta", Select).value
            if nombre in (None, Select.BLANK, ""):
                self.app.notify(
                    "Selecciona una tarjeta.", severity="warning",
                )
                return
            self.dismiss(
                {"modo": "tarjeta", "nombre": nombre, "tipo": tipo}
            )

    def action_cancel(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------
# Main app
# --------------------------------------------------------------------------


class IdiAutoApp(App):
    CSS = """
    Screen { layout: vertical; background: $background; }

    /* ----- loader ----- */
    #loader-wrap {
        width: 100%;
        height: 1fr;
        align: center middle;
        background: $surface;
    }
    #loader-wrap.hidden { display: none; }
    #loader-box {
        width: auto;
        height: auto;
        align: center middle;
    }
    #loader { width: 40; height: 1; }
    #loader-text {
        width: auto;
        text-align: center;
        margin-top: 1;
        color: $text-muted;
    }

    /* ----- status strip ----- */
    #status {
        height: 3; padding: 0 1;
        background: $boost;
        color: $text;
        border-bottom: solid $primary;
    }
    #status.hidden { display: none; }
    #status-left { width: 1fr; content-align: left middle; }
    #status-right {
        width: auto; content-align: right middle; color: $text-muted;
    }

    /* ----- main grid ----- */
    #main { height: 1fr; }
    #main.hidden { display: none; }

    #sidebar {
        width: 2fr;
        border: round $primary;
        padding: 0 1;
    }
    #sidebar-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    .seccion-title {
        text-style: bold;
        padding: 0 1;
    }
    .sec-overdue { color: $error; }
    .sec-today   { color: $warning; }
    .sec-week    { color: $accent; }
    .sec-month   { color: $primary; }
    .sec-later   { color: $secondary; }
    .sec-none    { color: $text-muted; }
    .tarjeta {
        padding: 0 2;
        margin-bottom: 0;
    }
    .tarjeta-id { color: $text-muted; }
    .tarjeta-fecha { color: $text-muted; }
    .seccion-empty { color: $text-muted; padding: 0 2; }
    .separator { color: $surface; }

    /* ----- actions panel ----- */
    #actions {
        width: 1fr;
        min-width: 30;
        border: round $accent;
        padding: 1;
    }
    #actions-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .group-title {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 0;
    }
    #actions Button {
        width: 100%;
        margin-bottom: 1;
    }
    #actions Rule { margin: 0; }

    /* ----- log ----- */
    #log {
        height: 25%;
        border: round $warning;
        padding: 0 1;
    }
    """ + MODAL_CSS

    BINDINGS = [
        Binding("c", "crear", "Crear"),
        Binding("s", "suspender", "Suspender"),
        Binding("i", "interrumpir", "Interrumpir"),
        Binding("f", "finalizar", "Finalizar"),
        Binding("d", "daily", "Daily"),
        Binding("r", "refrescar", "Refrescar"),
        Binding("t", "ver_tarjeta", "Detalle tarjeta"),
        Binding("l", "login", "Credenciales"),
        Binding("q", "quit", "Salir"),
    ]

    def __init__(self):
        super().__init__()
        self.worker: BrowserWorker | None = None
        self.tarjetas: dict = {}
        self.recientes: list[str] = []
        self.tipos: list[tuple[str, str]] = []
        self.actividad_activa: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="loader-wrap"):
            with Vertical(id="loader-box"):
                yield LoadingIndicator(id="loader")
                yield Static(
                    "Iniciando sesión y cargando datos...",
                    id="loader-text",
                )
        with Horizontal(id="status"):
            yield Static("", id="status-left")
            yield Static("", id="status-right")
        with Horizontal(id="main"):
            with VerticalScroll(id="sidebar"):
                yield Label("Tarjetas", id="sidebar-title")
                yield Static("", id="tarjetas-view")
            with VerticalScroll(id="actions"):
                yield Label("Acciones", id="actions-title")

                yield Label("Trabajo activo", classes="group-title")
                yield Button(
                    "⏸  Suspender  (s)", id="btn-suspender",
                )
                yield Button(
                    "⚡  Interrumpir  (i)", id="btn-interrumpir",
                )
                yield Button(
                    "✓  Finalizar  (f)",
                    id="btn-finalizar", variant="success",
                )
                yield Button(
                    "☕  Daily  (d)",
                    id="btn-daily", variant="warning",
                )

                yield Rule()
                yield Label("Nueva actividad", classes="group-title")
                yield Button(
                    "+  Crear actividad  (c)",
                    id="btn-crear", variant="primary",
                )

                yield Rule()
                yield Button(
                    "↻  Refrescar  (r)", id="btn-refrescar",
                )
        yield Log(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "idiAuto"
        self.sub_title = "Automatización IDI"
        self.query_one("#main").add_class("hidden")
        self.query_one("#status").add_class("hidden")
        self._iniciar_sesion()

    def _iniciar_sesion(self) -> None:
        creds = credentials.load()
        if creds and creds.get("usuario") and creds.get("password"):
            self._arrancar_worker(creds["usuario"], creds["password"])
            self._log(
                f"Credenciales cargadas desde keyring ({creds['usuario']})."
            )
            return

        def on_close(data: dict | None) -> None:
            if not data:
                self._log("Inicio cancelado — sin credenciales. Pulsa 'L'.")
                self._set_loading(False)
                return
            try:
                credentials.save(data["usuario"], data["password"])
                self._log("Credenciales guardadas en keyring.")
            except Exception as e:
                self._log(f"[warn] No se pudo guardar en keyring: {e}")
            self._arrancar_worker(data["usuario"], data["password"])

        self.push_screen(LoginModal(), on_close)

    def _emitir_actividad_activa(self, w) -> None:
        try:
            activa = core.obtenerActividadActiva(w.page)
            self._on_worker_event("activa", activa)
        except Exception:
            pass

    def _submit_job(self, job) -> None:
        if self.worker is None:
            self.notify(
                "Sesión no iniciada. Pulsa 'L' para ingresar credenciales.",
                severity="warning",
            )
            return
        self.worker.submit(job)
        self.worker.submit(self._emitir_actividad_activa)

    def _arrancar_worker(self, usuario: str, password: str) -> None:
        self.worker = BrowserWorker(
            self._on_worker_event, usuario, password,
        )
        self.worker.start()
        self._log("Iniciando navegador y sesión...")

    # ---- state helpers ----------------------------------------------------
    def _set_loading(self, loading: bool, msg: str | None = None) -> None:
        self.query_one("#loader-wrap").set_class(not loading, "hidden")
        self.query_one("#main").set_class(loading, "hidden")
        self.query_one("#status").set_class(loading, "hidden")
        if msg:
            self.query_one("#loader-text", Static).update(msg)

    def _log(self, msg: str) -> None:
        self.query_one("#log", Log).write_line(msg)

    def _refresh_status(self) -> None:
        total = sum(len(v) for v in self.tarjetas.values())
        vencidas = len(self.tarjetas.get("Vencidas", []))
        hoy = len(self.tarjetas.get("Para Hoy", []))
        left = (
            f"[b]{total}[/b] tarjetas  ·  "
            f"[red]{vencidas} vencidas[/red]  ·  "
            f"[yellow]{hoy} hoy[/yellow]"
        )
        if self.actividad_activa:
            right = (
                f"[green]▶ ACTIVA:[/green] "
                f"[b]{self.actividad_activa}[/b]"
            )
        else:
            right = "[dim]⏸ sin actividad activa[/dim]"
        self.query_one("#status-left", Static).update(left)
        self.query_one("#status-right", Static).update(right)

    # ---- worker bridge ----------------------------------------------------
    def _on_worker_event(self, kind: str, payload: Any) -> None:
        self.call_from_thread(self._handle_event, kind, payload)

    def _handle_event(self, kind: str, payload: Any) -> None:
        if kind == "ready":
            data = payload or {}
            self.tarjetas = data.get("tarjetas", {}) or {}
            self.tipos = data.get("tipos", []) or []
            self.actividad_activa = data.get("actividad_activa")
            self._render_tarjetas()
            self._refresh_status()
            self._set_loading(False)
            self.notify(
                f"Listo. {sum(len(v) for v in self.tarjetas.values())} "
                f"tarjetas cargadas.",
                title="Sesión iniciada",
                severity="information",
            )
            self._log("Sesión iniciada correctamente.")
        elif kind == "log":
            self._log(str(payload))
        elif kind == "tarjetas":
            self.tarjetas = payload or {}
            self._render_tarjetas()
            self._refresh_status()
            self._set_loading(False)
            self.notify("Tarjetas refrescadas.", severity="information")
        elif kind == "toast":
            msg, severity = payload
            self.notify(msg, severity=severity)
        elif kind == "activa":
            self.actividad_activa = payload
            self._refresh_status()
        elif kind == "install_start":
            self._set_loading(True, str(payload))
        elif kind == "install_progress":
            pct, line = payload
            text = line if len(line) < 60 else line[:57] + "..."
            if pct is not None:
                filled = int(pct / 5)
                bar = "█" * filled + "░" * (20 - filled)
                self.query_one("#loader-text", Static).update(
                    f"Instalando Chromium  [green]{bar}[/green] {pct}%\n"
                    f"[dim]{text}[/dim]"
                )
            else:
                self.query_one("#loader-text", Static).update(
                    f"Instalando Chromium\n[dim]{text}[/dim]"
                )
        elif kind == "install_end":
            self.query_one("#loader-text", Static).update(
                "Iniciando sesión y cargando datos..."
            )

    # ---- render -----------------------------------------------------------
    def _render_tarjetas(self) -> None:
        lines: list[str] = []
        for sec, items in self.tarjetas.items():
            cls, icon = SECCION_META.get(sec, ("", "·"))
            color = {
                "overdue": "red",
                "today": "yellow",
                "week": "cyan",
                "month": "blue",
                "later": "magenta",
                "none": "white",
            }.get(cls, "white")
            lines.append(
                f"[{color} b]{icon} {sec}[/{color} b] "
                f"[dim]({len(items)})[/dim]"
            )
            if not items:
                lines.append("    [dim]sin tarjetas[/dim]")
            for it in items:
                tid = it.get("id", "")
                titulo = it.get("titulo", "")
                fecha = it.get("fecha", "")
                lines.append(
                    f"    [dim]{tid}[/dim]  {titulo}"
                    + (f"  [dim]· {fecha}[/dim]" if fecha else "")
                )
            lines.append("")
        self.query_one("#tarjetas-view", Static).update(
            "\n".join(lines) or "[dim]Sin tarjetas.[/dim]"
        )

    # ---- actions ----------------------------------------------------------
    def action_refrescar(self) -> None:
        self._refrescar_tarjetas()

    def action_crear(self) -> None:
        self._abrir_crear()

    def action_suspender(self) -> None:
        self._abrir_suspender()

    def action_interrumpir(self) -> None:
        self._abrir_interrumpir()

    def action_finalizar(self) -> None:
        self._abrir_finalizar()

    def action_daily(self) -> None:
        self._accion_daily()

    def action_ver_tarjeta(self) -> None:
        self._abrir_ver_tarjeta()

    def _abrir_ver_tarjeta(self) -> None:
        opciones = []
        for sec, items in self.tarjetas.items():
            for it in items:
                tid = it.get("id", "")
                titulo = it.get("titulo", "")
                if not tid:
                    continue
                opciones.append((f"[{sec}] {tid} — {titulo}", tid))
        if not opciones:
            self.notify("No hay tarjetas cargadas.", severity="warning")
            return

        def on_pick(card_id: str | None) -> None:
            if not card_id:
                return
            self._cargar_detalle(card_id)

        self.push_screen(
            SelectModal("Elige una tarjeta", opciones), on_pick,
        )

    def _cargar_detalle(self, card_id: str) -> None:
        self._set_loading(True, f"Cargando detalle de {card_id}...")
        titulo_card = ""
        for sec, items in self.tarjetas.items():
            for it in items:
                if it.get("id") == card_id:
                    titulo_card = it.get("titulo", "")
                    break

        def job(w: BrowserWorker):
            try:
                w.page.locator("#botonSalir").click(timeout=2000)
                w.page.wait_for_timeout(300)
            except Exception:
                pass
            try:
                w.page.locator("#menu_8").click(timeout=2000)
                w.page.locator("#menu_804").click(timeout=3000)
                w.page.locator("#vencidas").wait_for(
                    state="attached", timeout=3000,
                )
                w.page.wait_for_timeout(600)
            except Exception as e:
                self._on_worker_event("log", f"[detalle] nav: {e}")

            tmpdir = os.path.join(
                tempfile.gettempdir(), "idiauto", card_id,
            )
            try:
                detalle = core.obtenerDetalleTarjeta(
                    w.page, card_id, output_dir=tmpdir,
                )
            except Exception as e:
                self._on_worker_event(
                    "log", f"[detalle error] {e}",
                )
                detalle = {}

            try:
                w.page.locator("#salir").click(timeout=2000)
                w.page.wait_for_timeout(300)
            except Exception:
                pass
            core.irAActividades(w.page)
            self.call_from_thread(
                self._mostrar_detalle, card_id, titulo_card, detalle,
            )

        self._submit_job(job)

    def _mostrar_detalle(
        self, card_id: str, titulo_card: str, detalle: dict,
    ) -> None:
        self._set_loading(False)
        if not detalle:
            self.notify(
                "No se pudo cargar el detalle.", severity="error",
            )
            return

        def on_close(data: dict | None) -> None:
            if not data:
                return
            if data.get("action") == "comentario":
                self._agregar_comentario(card_id, data["texto"])
            elif data.get("action") == "finalizar_sub":
                self.notify(
                    f"Finalizar subtarea aún no implementado "
                    f"(id={data.get('sub_id')}). "
                    f"Pégame el HTML del botón 'Finalizar' de la web "
                    f"para cablearlo.",
                    severity="warning",
                    timeout=8,
                )

        self.push_screen(
            TarjetaDetalleModal(detalle, titulo_card), on_close,
        )

    def _agregar_comentario(self, card_id: str, texto: str) -> None:
        self._set_loading(True, "Guardando comentario...")

        def job(w: BrowserWorker):
            try:
                w.page.locator("#botonSalir").click(timeout=2000)
                w.page.wait_for_timeout(300)
            except Exception:
                pass
            try:
                w.page.locator("#menu_8").click(timeout=2000)
                w.page.locator("#menu_804").click(timeout=3000)
                w.page.locator("#vencidas").wait_for(
                    state="attached", timeout=3000,
                )
                w.page.wait_for_timeout(600)
                core.agregarComentarioTarjeta(w.page, card_id, texto)
                self._on_worker_event(
                    "toast", ("Comentario guardado.", "information"),
                )
            except Exception as e:
                self._on_worker_event(
                    "toast", (f"Error al comentar: {e}", "error"),
                )
            try:
                w.page.locator("#salir").click(timeout=2000)
                w.page.wait_for_timeout(300)
            except Exception:
                pass
            core.irAActividades(w.page)
            self.call_from_thread(self._set_loading, False)

        self._submit_job(job)

    def _crear_desde_subtarea(self, nombre: str) -> None:
        tipos = self.tipos or []
        if not tipos:
            self.notify("No hay tipos cargados.", severity="warning")
            return
        tipo_default = tipos[0][1]

        def on_pick_tipo(tipo_valor: str | None) -> None:
            if not tipo_valor:
                return

            def on_confirm(ok: bool) -> None:
                if not ok:
                    return

                def job(w: BrowserWorker):
                    core.crearActividad(w.page, nombre, tipo_valor)
                    self._on_worker_event(
                        "toast",
                        (
                            f"Actividad '{nombre}' creada.",
                            "information",
                        ),
                    )
                self._submit_job(job)

            tipo_lbl = self._tipo_label(tipo_valor)
            self.push_screen(
                ConfirmModal(
                    "¿Crear actividad desde subtarea?",
                    f"Nombre: [b]{nombre}[/b]\n"
                    f"Tipo: [b]{tipo_lbl}[/b]",
                ),
                on_confirm,
            )

        self.push_screen(
            SelectModal("Tipo de actividad", tipos), on_pick_tipo,
        )

    def action_login(self) -> None:
        creds = credentials.load() or {}
        usuario_actual = creds.get("usuario", "")

        def on_close(data: dict | None) -> None:
            if not data:
                return
            credentials.save(data["usuario"], data["password"])
            self.notify(
                "Credenciales actualizadas. Reinicia la app para "
                "aplicar en la sesión del navegador.",
                severity="information",
                timeout=6,
            )
            self._log("Credenciales guardadas en keyring.")

        self.push_screen(LoginModal(usuario_actual=usuario_actual), on_close)

    def _refrescar_tarjetas(self) -> None:
        def on_confirm(ok: bool) -> None:
            if not ok:
                return
            self._set_loading(True, "Refrescando tarjetas...")

            def job(w: BrowserWorker):
                try:
                    w.page.locator("#botonSalir").click(timeout=3000)
                    w.page.wait_for_timeout(500)
                except Exception:
                    pass
                w.page.locator("#menu_8").click()
                core.mostrarTarjetas(w.page)
                core.irAActividades(w.page)
                self._on_worker_event("tarjetas", core.tarjetasCache)
            self._submit_job(job)

        self.push_screen(
            ConfirmModal(
                "¿Refrescar tarjetas?",
                "Se recargarán las tarjetas desde el servidor.",
            ),
            on_confirm,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        {
            "btn-refrescar": self._refrescar_tarjetas,
            "btn-crear": self._abrir_crear,
            "btn-suspender": self._abrir_suspender,
            "btn-interrumpir": self._abrir_interrumpir,
            "btn-finalizar": self._abrir_finalizar,
            "btn-daily": self._accion_daily,
        }.get(bid, lambda: None)()

    def _abrir_crear(self) -> None:
        def after_list(recientes_titulos):
            self.recientes = recientes_titulos

            def on_close(data: dict | None) -> None:
                if not data:
                    return
                self._ejecutar_crear(data)

            self.push_screen(
                CrearActividadModal(
                    self.tarjetas, self.recientes, self.tipos,
                ),
                on_close,
            )

        def job(w: BrowserWorker):
            lista = core._listarActividadesPanel(w.page)
            titulos = [a["titulo"] for a in lista]
            self.call_from_thread(after_list, titulos)
        self._submit_job(job)

    def _tipo_label(self, valor: str) -> str:
        return next(
            (lbl for lbl, v in self.tipos if v == valor),
            valor,
        )

    def _ejecutar_crear(self, data: dict) -> None:
        modo = data["modo"]
        if modo == "reciente":
            try:
                titulo = self.recientes[data["index"]]
            except (IndexError, KeyError):
                titulo = f"#{data['index']}"
            detalle = f"Ejecutar actividad reciente: [b]{titulo}[/b]"
        else:
            tipo_lbl = self._tipo_label(data["tipo"])
            detalle = (
                f"Nombre: [b]{data['nombre']}[/b]\n"
                f"Tipo: [b]{tipo_lbl}[/b]"
            )

        def on_confirm(ok: bool) -> None:
            if not ok:
                return

            def job(w: BrowserWorker):
                if modo == "custom":
                    core.crearActividad(
                        w.page, data["nombre"], data["tipo"],
                    )
                    self._on_worker_event(
                        "toast",
                        (
                            f"Actividad creada: {data['nombre']}",
                            "information",
                        ),
                    )
                elif modo == "tarjeta":
                    core.crearActividad(
                        w.page, data["nombre"], data["tipo"],
                    )
                    self._on_worker_event(
                        "toast",
                        (
                            f"Actividad creada desde tarjeta: "
                            f"{data['nombre']}",
                            "information",
                        ),
                    )
                elif modo == "reciente":
                    titulo = core.ejecutarActividadReciente(
                        w.page, data["index"]
                    )
                    self._on_worker_event(
                        "toast",
                        (
                            f"Reciente ejecutada: {titulo}",
                            "information",
                        ),
                    )
            self._submit_job(job)

        self.push_screen(
            ConfirmModal("¿Crear actividad?", detalle), on_confirm,
        )

    def _abrir_suspender(self) -> None:
        def on_close(data: dict | None) -> None:
            if not data:
                return
            detalle = (
                f"Unidades: [b]{data['unidades'] or '0'}[/b]\n"
                f"Comentarios: [b]{data['comentarios'] or '(ninguno)'}[/b]"
            )

            def on_confirm(ok: bool) -> None:
                if not ok:
                    return

                def job(w: BrowserWorker):
                    core.suspenderActividad(
                        w.page, data["unidades"], data["comentarios"],
                    )
                    self._on_worker_event(
                        "toast", ("Actividad suspendida.", "warning"),
                    )
                self._submit_job(job)

            self.push_screen(
                ConfirmModal("¿Suspender actividad?", detalle), on_confirm,
            )

        self.push_screen(
            InputModal(
                "Suspender actividad",
                [
                    ("unidades", "Unidades (default 0)", "0"),
                    ("comentarios", "Comentarios", ""),
                ],
                subtitle="Pausa la actividad en ejecución",
            ),
            on_close,
        )

    def _abrir_finalizar(self) -> None:
        def on_close(data: dict | None) -> None:
            if not data:
                return
            detalle = (
                f"Unidades: [b]{data['unidades'] or '0'}[/b]\n"
                f"Comentarios: [b]{data['comentarios'] or '(ninguno)'}[/b]"
            )

            def on_confirm(ok: bool) -> None:
                if not ok:
                    return

                def job(w: BrowserWorker):
                    core.finalizarActividad(
                        w.page, data["unidades"], data["comentarios"],
                    )
                    self._on_worker_event(
                        "toast", ("Actividad finalizada.", "information"),
                    )
                self._submit_job(job)

            self.push_screen(
                ConfirmModal("¿Finalizar actividad?", detalle), on_confirm,
            )

        self.push_screen(
            InputModal(
                "Finalizar actividad",
                [
                    ("unidades", "Unidades (default 0)", "0"),
                    ("comentarios", "Comentarios", ""),
                ],
                subtitle="Cierra la actividad en ejecución",
            ),
            on_close,
        )

    def _abrir_interrumpir(self) -> None:
        tipos = [
            (nombre, valor)
            for _, (nombre, valor) in core.TIPOS_INTERRUPCION.items()
        ]

        def pick_tipo(valor: str | None) -> None:
            if not valor:
                return

            tipo_lbl = next(
                (n for n, v in tipos if v == valor), valor,
            )

            def on_desc(data: dict | None) -> None:
                if data is None:
                    return
                detalle = (
                    f"Tipo: [b]{tipo_lbl}[/b]\n"
                    f"Descripción: [b]"
                    f"{data['descripcion'] or '(ninguna)'}[/b]"
                )

                def on_confirm(ok: bool) -> None:
                    if not ok:
                        return

                    def job(w: BrowserWorker):
                        core.interrumpirActividad(
                            w.page, valor, data["descripcion"],
                        )
                        self._on_worker_event(
                            "toast",
                            ("Interrupción registrada.", "warning"),
                        )
                    self._submit_job(job)

                self.push_screen(
                    ConfirmModal(
                        "¿Registrar interrupción?", detalle,
                    ),
                    on_confirm,
                )

            self.push_screen(
                InputModal(
                    "Descripción de la interrupción",
                    [("descripcion", "Descripción", "")],
                ),
                on_desc,
            )

        self.push_screen(SelectModal("Tipo de interrupción", tipos), pick_tipo)

    def _accion_daily(self) -> None:
        tipo_daily = next(
            (v for lbl, v in self.tipos if lbl.lower() == "daily"),
            "29",
        )

        def on_confirm(ok: bool) -> None:
            if not ok:
                return

            def job(w: BrowserWorker):
                resultado = core.dailyActividad(w.page, tipo_daily)
                if resultado == "suspendida":
                    self._on_worker_event(
                        "toast",
                        (
                            "Daily: actividad activa suspendida.",
                            "warning",
                        ),
                    )
                else:
                    self._on_worker_event(
                        "toast",
                        (
                            "Daily: actividad 'Daily' creada.",
                            "information",
                        ),
                    )
            self._submit_job(job)

        self.push_screen(
            ConfirmModal(
                "¿Iniciar Daily?",
                "Si hay una actividad activa será suspendida; "
                "si no, se creará una nueva actividad 'Daily'.",
            ),
            on_confirm,
        )

    def on_unmount(self) -> None:
        if self.worker is not None:
            self.worker.stop()


if __name__ == "__main__":
    IdiAutoApp().run()
