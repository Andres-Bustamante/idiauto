from playwright.sync_api import sync_playwright

URL = "https://idi.avance.org.co/acceso/Index.html"
USER = ""
PASSWORD = ""

tarjetasCache = {}

TIPOS_ACTIVIDAD = {
    "1": ("Desarrollo Software", "2"),
    "2": ("Pruebas unitarias", "28"),
}

SECCIONES = {
    "Vencidas": "vencidas",
    "Para Hoy": "paraHoy",
    "Esta Semana": "estaSemana",
    "Este mes": "esteMes",
    "Próximo": "proximo",
    "Sin Fecha definida": "sinFecha",
}

TIPOS_INTERRUPCION = {
    "1": ("Ir al baño", "9"),
    "2": ("Llamada telefónica", "2"),
    "3": ("Onces", "5"),
    "4": ("Pausa Activa", "3"),
    "5": ("Tomar Agua", "10"),
}


def login(page, usuario=None, password=None):
    print("Página cargada. Iniciando login...")
    page.locator("#usuario").fill(usuario or USER)
    page.locator("#password").fill(password or PASSWORD)
    try:
        page.locator("#btnIngresar").click(timeout=2000)
    except Exception:
        page.locator("#password").press("Enter")


def mostrarTarjetas(page):
    global tarjetasCache
    page.locator("#menu_804").click()
    page.locator("#vencidas").wait_for(state="attached", timeout=2000)
    page.wait_for_timeout(2000)

    resultado = {}
    total = 0
    for titulo, contenedor_id in SECCIONES.items():
        contenedor = page.locator(f"#{contenedor_id}")
        if contenedor.count() == 0:
            resultado[titulo] = []
            continue
        tarjetas = contenedor.locator(".subtarea")
        items = []
        for i in range(tarjetas.count()):
            t = tarjetas.nth(i)
            try:
                items.append({
                    "id": t.get_attribute("id") or "",
                    "titulo": (t.locator(".titlesubtarea").text_content() or "").strip(),
                    "fecha": (t.locator(".fechavencimiento").text_content() or "").strip(),
                    "subtareas": (t.locator(".subtareascheck").text_content() or "").strip(),
                })
            except Exception:
                continue
        resultado[titulo] = items
        total += len(items)
    print(f"[mostrarTarjetas] {total} tarjetas cargadas en caché.")
    tarjetasCache = resultado

    try:
        page.locator("#salir").click(timeout=3000)
    except Exception:
        pass
    return resultado


def _seleccionarTarjeta():
    todas = [(sec, it) for sec, items in tarjetasCache.items() for it in items]
    if not todas:
        print("No hay tarjetas en caché.")
        return None
    print("\nTarjetas disponibles:")
    for i, (sec, it) in enumerate(todas, 1):
        print(f"  {i}) [{sec}] {it['id']} — {it['titulo']}")
    while True:
        try:
            idx = int(input("Seleccione el número de la tarjeta: ").strip())
            if 1 <= idx <= len(todas):
                return todas[idx - 1][1]
        except ValueError:
            pass
        print("Opción inválida.")


def _seleccionarTipoActividad():
    print("\nTipo de actividad:")
    for key, (nombre, _) in TIPOS_ACTIVIDAD.items():
        print(f"  {key}) {nombre}")
    while True:
        op = input("Opción: ").strip()
        if op in TIPOS_ACTIVIDAD:
            return TIPOS_ACTIVIDAD[op]
        print("Opción inválida.")


def _abrirModalNueva(page, nombreActividad, tipoValor):
    page.locator("#botonNueva").click()
    page.locator("#nombreActividad").wait_for(state="visible", timeout=10000)
    page.locator("#nombreActividad").fill(nombreActividad)
    page.locator("#tipoActividad").select_option(tipoValor)
    page.locator("#agregarActividad").click()
    print(f"Actividad agregada: {nombreActividad}")


def _listarActividadesPanel(page):
    panel = page.locator("#panelTareas")
    if panel.count() == 0:
        return []
    items = panel.locator(".flexintactivity")
    actividades = []
    for i in range(items.count()):
        item = items.nth(i)
        try:
            titulo = (item.locator(".mi-div p")
                      .text_content() or "").strip()
            fecha = ""
            if item.locator(".mi-div span").count() > 0:
                fecha = (item.locator(".mi-div span")
                         .text_content() or "").strip()
            if titulo:
                actividades.append({
                    "titulo": titulo,
                    "fecha": fecha,
                    "play": item.locator(".btnPlay img"),
                })
        except Exception:
            continue
    return actividades


def _crearNuevaActividad(page):
    print("\n¿Qué tipo de actividad quieres crear?")
    print("  1) Actividad reciente (desde panel lateral)")
    print("  2) Nueva actividad desde tarjetas")
    print("  3) Nueva actividad con nombre personalizado")
    sub = input("Opción: ").strip()

    if sub == "1":
        actividades = _listarActividadesPanel(page)
        if not actividades:
            print("No hay actividades recientes en el panel.")
            return
        print("\nActividades recientes:")
        for i, a in enumerate(actividades, 1):
            print(f"  {i}) {a['titulo']}  —  {a['fecha']}")
        while True:
            try:
                idx = int(input("Seleccione el número: ").strip())
                if 1 <= idx <= len(actividades):
                    break
            except ValueError:
                pass
            print("Opción inválida.")
        actividades[idx - 1]["play"].click(force=True)
        print(f"Ejecutando: {actividades[idx - 1]['titulo']}")
    elif sub == "2":
        tarjeta = _seleccionarTarjeta()
        if tarjeta is None:
            return
        _, tipoValor = _seleccionarTipoActividad()
        _abrirModalNueva(page, tarjeta["titulo"], tipoValor)
    elif sub == "3":
        nombre = input("Nombre de la actividad: ").strip()
        if not nombre:
            print("Nombre vacío, cancelando.")
            return
        _, tipoValor = _seleccionarTipoActividad()
        _abrirModalNueva(page, nombre, tipoValor)
    else:
        print("Opción inválida.")


def _asegurarActividades(page):
    """Si no estamos en la vista de actividades, navega hasta ella."""
    try:
        if page.locator("#panelTareas").count() == 0:
            irAActividades(page)
            page.wait_for_timeout(500)
    except Exception:
        pass


def suspenderActividad(page, unidades="0", comentarios=""):
    _asegurarActividades(page)
    page.locator("#btnSuspender").wait_for(
        state="visible", timeout=15000)
    page.locator("#btnSuspender").click(force=True)
    page.locator("#unidadesSuspender").wait_for(
        state="visible", timeout=15000)
    page.wait_for_timeout(300)
    page.locator("#unidadesSuspender").fill(unidades or "0")
    page.locator("#comentariosSuspender").fill(comentarios)
    page.locator("#suspenderActividad").click(force=True)
    page.wait_for_timeout(500)


def finalizarActividad(page, unidades="0", comentarios=""):
    _asegurarActividades(page)
    page.locator("#btnFin").wait_for(state="visible", timeout=15000)
    page.locator("#btnFin").click(force=True)
    page.locator("#unidadesFinalizar").wait_for(
        state="visible", timeout=15000)
    page.wait_for_timeout(300)
    page.locator("#unidadesFinalizar").fill(unidades or "0")
    page.locator("#comentariosFinalizar").fill(comentarios)
    page.locator("#finalizarActividad").click(force=True)
    page.wait_for_timeout(500)


def interrumpirActividad(page, tipoValor, descripcion=""):
    _asegurarActividades(page)
    page.locator("#btnInterrupcion").wait_for(
        state="visible", timeout=15000)
    page.locator("#btnInterrupcion").click(force=True)
    page.locator("#tipoInterrupcion").wait_for(
        state="visible", timeout=15000)
    page.wait_for_timeout(300)
    page.locator("#tipoInterrupcion").select_option(tipoValor)
    page.locator("#descripcionInterrupcion").fill(descripcion)
    page.locator("#agregarInterrupcion").click(force=True)
    page.wait_for_timeout(500)


def crearActividad(page, nombre, tipoValor):
    _abrirModalNueva(page, nombre, tipoValor)


def hayActividadActiva(page):
    try:
        btn = page.locator("#btnSuspender").first
        return btn.count() > 0 and btn.is_visible()
    except Exception:
        return False


def obtenerActividadActiva(page):
    """Devuelve el nombre de la actividad activa o None.
    Busca en la tabla la fila cuya columna de estado dice 'En ejecución'.
    """
    try:
        nombre = page.evaluate(
            """() => {
                const tds = document.querySelectorAll('td');
                for (const td of tds) {
                    const t = (td.innerText || '').trim();
                    if (!t.includes('En ejecución')) continue;
                    const row = td.closest('tr');
                    if (!row) continue;
                    const cells = Array.from(row.querySelectorAll('td'))
                        .map(c => (c.innerText || '').trim())
                        .filter(x => x && !x.includes('En ejecución'));
                    if (!cells.length) return null;
                    // El título suele ser la celda con más texto
                    // sin ser solo un número/hora.
                    let best = '';
                    for (const c of cells) {
                        if (/^\\d/.test(c)) continue;
                        if (c.length > best.length) best = c;
                    }
                    return best || cells[0];
                }
                return null;
            }"""
        )
        return nombre
    except Exception:
        return None


def dailyActividad(page, tipoDailyValor="29"):
    """Si hay actividad activa, la suspende. Si no, crea una 'Daily'."""
    if hayActividadActiva(page):
        suspenderActividad(page, "0", "Daily")
        return "suspendida"
    crearActividad(page, "Daily", tipoDailyValor)
    return "creada"


def ejecutarActividadReciente(page, index):
    actividades = _listarActividadesPanel(page)
    if 0 <= index < len(actividades):
        actividades[index]["play"].click(force=True)
        return actividades[index]["titulo"]
    return None


def irAActividades(page):
    page.locator("#menu_8").click()
    page.locator("#menu_801").click()


def obtenerDetalleTarjeta(page, card_id, output_dir=None):
    """Abre el modal de una tarjeta, extrae su detalle y lo cierra."""
    import base64
    import os
    page.locator(f"[id='{card_id}']").dblclick()
    page.locator(f"[id='modal_{card_id}']").wait_for(
        state="visible", timeout=5000,
    )
    page.wait_for_timeout(400)

    data = page.evaluate(f"""() => {{
        const id = '{card_id}';
        const qid = (prefix) => document.getElementById(prefix + id);
        const modal = document.getElementById('modal_' + id);
        const descEl = modal ? modal.querySelector(
            "[class*='descripcion_content']"
        ) : null;
        let descripcionHtml = '';
        let descripcionTexto = '';
        let imagenes = [];
        if (descEl) {{
            descripcionHtml = descEl.innerHTML || '';
            descripcionTexto = descEl.innerText || '';
            imagenes = Array.from(
                descEl.querySelectorAll('img')
            ).map(img => img.src).filter(src =>
                src.startsWith('data:image')
            );
        }}
        const titulo = (qid('titulotarea_')?.value || '').trim();
        const estadoEl = qid('estadotarea_');
        const estado = estadoEl
            ? estadoEl.options[estadoEl.selectedIndex]?.text
            : '';
        const propietario = (qid('propietariotarea_')?.value || '').trim();
        const creacion = (qid('creaciontarea_')?.value || '').trim();
        const vencimiento = (qid('datetimepicker_')?.value || '').trim();
        const proyectoEl = qid('proyectotarea_');
        const proyecto = proyectoEl
            ? proyectoEl.options[proyectoEl.selectedIndex]?.text
            : '';
        const prioridadEl = qid('prioridadtarea_');
        const prioridad = prioridadEl
            ? prioridadEl.options[prioridadEl.selectedIndex]?.text
            : '';
        const subtareaRows = document.querySelectorAll('.trSubtareas_' + id);
        const subtareas = Array.from(subtareaRows).map(row => {{
            const nombreEl = row.querySelector(
                "textarea[id^='nombresubtarea_']"
            );
            const nombre = (nombreEl?.value || '').trim();
            const sid = nombreEl ? nombreEl.id.replace(
                'nombresubtarea_', ''
            ) : '';
            const vencEl = row.querySelector(
                "input[id^='tablesubtareas_datetimepicker_']"
            );
            const vencSub = vencEl ? vencEl.value : '';
            const finEl = row.querySelector(
                "textarea[id^='fechafinalizacion_']"
            );
            const finalizada = !!(finEl && finEl.value.trim());
            const asigEl = row.querySelector(
                "textarea[id^='fechaasignacion_']"
            );
            const asignada = asigEl ? asigEl.value : '';
            return {{nombre, id: sid, vencimiento: vencSub, finalizada,
                     asignada}};
        }});
        const timelineEl = qid('listlineatiempo_');
        const comentarios = [];
        if (timelineEl) {{
            timelineEl.querySelectorAll('.d-flex.pt-4').forEach(div => {{
                const nombre = (
                    div.querySelector('.nombre strong')?.innerText || ''
                ).trim();
                const texto = (
                    div.querySelector('.comentario p')?.innerText || ''
                ).trim();
                const fecha = (
                    div.querySelector('.lineatiempo_fecha')?.innerText || ''
                ).trim();
                const adjunto = (
                    div.querySelector('.adjunto p')?.innerText || ''
                ).trim();
                comentarios.push({{nombre, texto, fecha, adjunto}});
            }});
        }}
        return {{
            titulo, estado, propietario, creacion, vencimiento,
            proyecto, prioridad, descripcionHtml, descripcionTexto,
            imagenes, subtareas, comentarios,
        }};
    }}""")

    rutas_imagenes = []
    if output_dir and data.get("imagenes"):
        os.makedirs(output_dir, exist_ok=True)
        for i, src in enumerate(data["imagenes"]):
            try:
                header, b64 = src.split(",", 1)
                ext = "png"
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                path = os.path.join(output_dir, f"img_{i+1}.{ext}")
                with open(path, "wb") as f:
                    f.write(base64.b64decode(b64))
                rutas_imagenes.append(path)
            except Exception:
                continue
    data["rutas_imagenes"] = rutas_imagenes
    data.pop("imagenes", None)

    _cerrarModalTarjeta(page, card_id)
    return data


def _cerrarModalTarjeta(page, card_id):
    """Cierra la modal de la tarjeta quitándole la clase 'active'."""
    try:
        page.evaluate(
            f"""() => {{
                const m = document.getElementById('modal_{card_id}');
                if (m) m.classList.remove('active');
            }}"""
        )
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
    page.wait_for_timeout(400)


def agregarComentarioTarjeta(page, card_id, texto):
    """Abre la tarjeta, agrega un comentario y cierra la modal."""
    page.locator(f"[id='{card_id}']").dblclick()
    page.locator(f"[id='modal_{card_id}']").wait_for(
        state="visible", timeout=5000,
    )
    page.wait_for_timeout(300)
    page.locator(f"[id='comentariotarea_{card_id}']").fill(texto)
    page.locator(f"[id='guardarComentario_{card_id}']").click(force=True)
    page.wait_for_timeout(600)
    _cerrarModalTarjeta(page, card_id)


def listarTiposActividad(page):
    """Abre el modal 'Nueva', extrae los tipos de #tipoActividad y lo cierra."""
    tipos = []
    try:
        page.locator("#botonNueva").click()
        page.locator("#tipoActividad").wait_for(
            state="attached", timeout=5000,
        )
        try:
            page.wait_for_function(
                "document.querySelectorAll('#tipoActividad option').length > 1",
                timeout=8000,
            )
        except Exception as e:
            print(f"[listarTiposActividad] timeout esperando options: {e}")
        raw = page.locator("#tipoActividad").evaluate(
            "el => Array.from(el.options).map(o => ({v: o.value, t: o.text}))"
        )
        print(f"[listarTiposActividad] crudo: {len(raw)} opciones -> {raw[:3]}")
        for opt in raw:
            value = (opt.get("v") or "").strip()
            label = (opt.get("t") or "").strip()
            if not value or not label:
                continue
            if value in ("-1", "0"):
                continue
            tipos.append((label, value))
    except Exception as e:
        print(f"[listarTiposActividad] error leyendo: {e}")

    try:
        page.locator(
            "button[data-dismiss='modal']:has-text('Cerrar')"
        ).first.click(timeout=2000)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
    page.wait_for_timeout(300)
    print(f"[listarTiposActividad] final: {len(tipos)} tipos")
    return tipos


def _suspenderActividad(page):
    unidades = input("Unidades terminadas (default 0): ").strip() or "0"
    comentarios = input("Comentarios: ").strip()
    suspenderActividad(page, unidades, comentarios)
    print("Actividad suspendida.")


def _finalizarActividad(page):
    unidades = input("Unidades terminadas (default 0): ").strip() or "0"
    comentarios = input("Comentarios: ").strip()
    finalizarActividad(page, unidades, comentarios)
    print("Actividad finalizada.")


def _interrumpirActividad(page):
    print("\nTipo de interrupción:")
    for k, (nombre, _) in TIPOS_INTERRUPCION.items():
        print(f"  {k}) {nombre}")
    while True:
        op = input("Opción: ").strip()
        if op in TIPOS_INTERRUPCION:
            break
        print("Opción inválida.")
    descripcion = input("Descripción: ").strip()
    interrumpirActividad(page, TIPOS_INTERRUPCION[op][1], descripcion)
    print("Interrupción registrada.")


def comenzarActividad(page):
    page.locator("#menu_8").click()
    page.locator("#menu_801").click()

    print("\n¿Qué desea hacer?")
    print("  1) Crear nueva actividad")
    print("  2) Suspender actividad en ejecución")
    print("  3) Interrumpir actividad en ejecución")
    print("  4) Finalizar actividad en ejecución")
    opcion = input("Opción: ").strip()

    acciones = {
        "1": _crearNuevaActividad,
        "2": _suspenderActividad,
        "3": _interrumpirActividad,
        "4": _finalizarActividad,
    }
    accion = acciones.get(opcion)
    if accion is None:
        print("Opción inválida.")
        return
    accion(page)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        try:
            page.goto(URL)
            page.locator("#usuario").wait_for(state="visible", timeout=10000)
            login(page)
            page.wait_for_timeout(2000)
            page.locator("#menu_8").click()
            mostrarTarjetas(page)

            while True:
                try:
                    comenzarActividad(page)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"[error] {e}")
                print("\n(Ctrl+C para salir)")
        except KeyboardInterrupt:
            print("\nSaliendo por interrupción del usuario...")
        finally:
            browser.close()
            print("Proceso terminado.")


if __name__ == "__main__":
    main()
