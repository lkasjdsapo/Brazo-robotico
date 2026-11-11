import os
import math
import struct
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from OpenGL.GL import *
from OpenGL.GLU import *


def ev(nombre):
    """Devuelve '<nombre>' para los eventos de Tkinter."""
    return chr(60) + nombre + chr(62)


def _normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    largo = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
    return (n[0] / largo, n[1] / largo, n[2] / largo) if largo > 1e-9 else (0.0, 1.0, 0.0)


def cargar_stl(ruta):
    """Lee un STL (binario o ASCII) y devuelve una lista de (normal, v0, v1, v2)."""
    with open(ruta, "rb") as f:
        datos = f.read()

    vertices = []
    es_ascii = datos[:5].lower() == b"solid" and b"facet" in datos[:1024].lower()
    if not es_ascii and len(datos) >= 84:
        n = struct.unpack_from("=I", datos, 80)[0]
        for i in range(min(n, (len(datos) - 84) // 50)):
            v = struct.unpack_from("=12f", datos, 84 + i * 50)
            vertices += [v[3:6], v[6:9], v[9:12]]
    else:
        for linea in datos.decode("utf-8", "ignore").splitlines():
            p = linea.split()
            if len(p) >= 4 and p[0] == "vertex":
                vertices.append((float(p[1]), float(p[2]), float(p[3])))

    return [(_normal(a, b, c), a, b, c)
            for a, b, c in zip(vertices[0::3], vertices[1::3], vertices[2::3])]


class PFD(ctypes.Structure):
    _fields_ = (
        [("nSize", wintypes.WORD), ("nVersion", wintypes.WORD), ("dwFlags", wintypes.DWORD)]
        + [(n, ctypes.c_ubyte) for n in (
            "iPixelType", "cColorBits", "cRedBits", "cRedShift", "cGreenBits", "cGreenShift",
            "cBlueBits", "cBlueShift", "cAlphaBits", "cAlphaShift", "cAccumBits", "cAccumRedBits",
            "cAccumGreenBits", "cAccumBlueBits", "cAccumAlphaBits", "cDepthBits", "cStencilBits",
            "cAuxBuffers", "iLayerType", "bReserved")]
        + [("dwLayerMask", wintypes.DWORD), ("dwVisibleMask", wintypes.DWORD),
           ("dwDamageMask", wintypes.DWORD)]
    )


PIEZAS = [
    ("01_base_industrial",    "P1 (Base)",         (0.22, 0.25, 0.30)),
    ("02_torreta_hombro",     "P2 (Torreta)",      (0.88, 0.42, 0.12)),
    ("03_brazo_principal",    "P3 (Brazo)",        (0.92, 0.50, 0.15)),
    ("04_antebrazo_codo",     "P4 (Antebrazo)",    (0.88, 0.42, 0.12)),
    ("05_muneca_rotacion",    "P5 (Muñeca Rot.)",  (0.28, 0.33, 0.40)),
    ("06_muneca_inclinacion", "P6 (Muñeca Inc.)",  (0.75, 0.78, 0.82)),
    ("07_cuerpo_pinza",       "P7 (Cuerpo Pinza)", (0.18, 0.55, 0.78)),
    ("08_dedo_pinza_izq",     "P8 (Dedo Izq.)",    (0.85, 0.20, 0.22)),
    ("09_dedo_pinza_der",     "P9 (Dedo Der.)",    (0.85, 0.20, 0.22)),
]
CLAVES = [p[0] for p in PIEZAS]
COLORES = {p[0]: p[2] + (1.0,) for p in PIEZAS}

EJES_CADENA = [(0, 1, 0), (0, 0, 1), (0, 0, 1), (0, 1, 0), (0, 0, 1), (0, 1, 0)]


class Visor(tk.Frame):
    """Lienzo 3D de OpenGL dentro de un Frame de Tkinter (solo Windows)."""

    def __init__(self, master):
        super().__init__(master, bg="#171A21")
        self.hdc = self.hglrc = None
        self.mallas = {}
        self.listas = {}
        self.ensamblado = False
        self.mostrar_ejes = True

        self.art = [0.0] * 6 + [8.0]                 
        self.offsets = [40.0, 68.8, 129.0, 90.0, 51.0, 34.0, 29.0]
        self.pos = [0.0, 0.0, 0.0]
        self.rot = [0.0, 0.0, 0.0]
        self.vista_inicial()

        self.bind(ev("Map"), self._crear_contexto)
        self.bind(ev("Configure"), self._redimensionar)
        self.bind(ev("Expose"), lambda e: self.dibujar())
        self.bind(ev("ButtonPress-1"), self._clic)
        self.bind(ev("ButtonPress-3"), self._clic)
        self.bind(ev("B1-Motion"), self._girar)
        self.bind(ev("B3-Motion"), self._desplazar)
        self.bind(ev("MouseWheel"), self._zoom)

    def vista_inicial(self, az=45.0, el=28.0):
        self.az, self.el, self.dist = az, el, 560.0
        self.objetivo = [0.0, 165.0, 0.0]

    def _crear_contexto(self, _=None):
        if self.hglrc:
            return
        self.update_idletasks()
        user32, gdi32, opengl32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.opengl32
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        gdi32.ChoosePixelFormat.argtypes = [wintypes.HDC, ctypes.POINTER(PFD)]
        gdi32.ChoosePixelFormat.restype = ctypes.c_int
        gdi32.SetPixelFormat.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.POINTER(PFD)]
        gdi32.SetPixelFormat.restype = wintypes.BOOL
        gdi32.SwapBuffers.argtypes = [wintypes.HDC]
        gdi32.SwapBuffers.restype = wintypes.BOOL
        opengl32.wglCreateContext.argtypes = [wintypes.HDC]
        opengl32.wglCreateContext.restype = wintypes.HANDLE
        opengl32.wglMakeCurrent.argtypes = [wintypes.HDC, wintypes.HANDLE]
        opengl32.wglMakeCurrent.restype = wintypes.BOOL

        self.hdc = user32.GetDC(self.winfo_id())
        pfd = PFD()
        pfd.nSize = ctypes.sizeof(PFD)
        pfd.nVersion = 1
        pfd.dwFlags = 0x04 | 0x20 | 0x01          # ventana + OpenGL + doble buffer
        pfd.cColorBits = 24
        pfd.cDepthBits = 24
        gdi32.SetPixelFormat(self.hdc, gdi32.ChoosePixelFormat(self.hdc, ctypes.byref(pfd)), ctypes.byref(pfd))
        self.hglrc = opengl32.wglCreateContext(self.hdc)
        opengl32.wglMakeCurrent(self.hdc, self.hglrc)

        glClearColor(0.09, 0.11, 0.14, 1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_NORMALIZE)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_LIGHT1)
        glLightfv(GL_LIGHT0, GL_POSITION, [350.0, 600.0, 450.0, 1.0])
        glLightfv(GL_LIGHT0, GL_AMBIENT, [0.25, 0.25, 0.28, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [0.85, 0.85, 0.82, 1.0])
        glLightfv(GL_LIGHT0, GL_SPECULAR, [0.60, 0.60, 0.60, 1.0])
        glLightfv(GL_LIGHT1, GL_POSITION, [-400.0, 300.0, -350.0, 1.0])
        glLightfv(GL_LIGHT1, GL_AMBIENT, [0.05, 0.05, 0.08, 1.0])
        glLightfv(GL_LIGHT1, GL_DIFFUSE, [0.35, 0.40, 0.50, 1.0])
        glLightfv(GL_LIGHT1, GL_SPECULAR, [0.20, 0.20, 0.25, 1.0])

        self._proyeccion(self.winfo_width(), self.winfo_height())
        for clave, tris in self.mallas.items():
            self._compilar(clave, tris)
        self.dibujar()

    def _activar(self):
        if not (self.hdc and self.hglrc):
            return False
        ctypes.windll.opengl32.wglMakeCurrent(self.hdc, self.hglrc)
        return True

    def _proyeccion(self, ancho, alto):
        if not self._activar():
            return
        glViewport(0, 0, max(ancho, 1), max(alto, 1))
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(42.0, max(ancho, 1) / max(alto, 1), 5.0, 3500.0)
        glMatrixMode(GL_MODELVIEW)

    def _redimensionar(self, e):
        if self.hglrc:
            self._proyeccion(e.width, e.height)
            self.dibujar()

    def _compilar(self, clave, triangulos):
        if not self._activar():
            return
        if clave in self.listas:
            glDeleteLists(self.listas[clave], 1)
        lista = glGenLists(1)
        glNewList(lista, GL_COMPILE)
        glBegin(GL_TRIANGLES)
        for n, v0, v1, v2 in triangulos:
            glNormal3fv(n)
            glVertex3fv(v0)
            glVertex3fv(v1)
            glVertex3fv(v2)
        glEnd()
        glEndList()
        self.listas[clave] = lista

    def importar(self, clave, ruta):
        triangulos = cargar_stl(ruta)
        if not triangulos:
            raise ValueError("El archivo no contiene triángulos.")
        self.mallas[clave] = triangulos
        self._compilar(clave, triangulos)
        self.dibujar()
        return len(triangulos)

    def ajustar_offsets_auto(self):
        """Cada distancia entre articulaciones = altura (Y máxima) de la pieza anterior."""
        for i, clave in enumerate(CLAVES[:7]):
            if clave in self.mallas:
                self.offsets[i] = round(max(max(v0[1], v1[1], v2[1])
                                            for _, v0, v1, v2 in self.mallas[clave]), 1)

    def _pieza(self, clave):
        if clave in self.mallas:
            glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE, COLORES[clave])
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.45, 0.45, 0.48, 1.0])
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 48.0)
            glCallList(self.listas[clave])

    def _ejes(self, escala=22.0, grosor=1.5):
        if not self.mostrar_ejes:
            return
        glDisable(GL_LIGHTING)
        glLineWidth(grosor)
        glBegin(GL_LINES)
        for color, punta in (((0.95, 0.25, 0.25), (escala, 0, 0)),
                             ((0.25, 0.95, 0.35), (0, escala, 0)),
                             ((0.30, 0.55, 1.00), (0, 0, escala))):
            glColor3f(*color)
            glVertex3f(0, 0, 0)
            glVertex3f(*punta)
        glEnd()
        glEnable(GL_LIGHTING)

    def _rejilla(self):
        glDisable(GL_LIGHTING)
        glLineWidth(1.0)
        glColor3f(0.22, 0.26, 0.32)
        glBegin(GL_LINES)
        for i in range(-300, 301, 30):
            glVertex3f(i, 0, -300)
            glVertex3f(i, 0, 300)
            glVertex3f(-300, 0, i)
            glVertex3f(300, 0, i)
        glEnd()
        glEnable(GL_LIGHTING)
        self._ejes(65.0, 2.5)

    def dibujar(self):
        if not self._activar():
            return
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        az, el = math.radians(self.az), math.radians(self.el)
        ox, oy, oz = self.objetivo
        gluLookAt(ox + self.dist * math.cos(el) * math.sin(az),
                  oy + self.dist * math.sin(el),
                  oz + self.dist * math.cos(el) * math.cos(az),
                  ox, oy, oz, 0.0, 1.0 if math.cos(el) >= 0 else -1.0, 0.0)
        self._rejilla()

        glPushMatrix()
        glTranslatef(*self.pos)
        glRotatef(self.rot[0], 1, 0, 0)
        glRotatef(self.rot[1], 0, 1, 0)
        glRotatef(self.rot[2], 0, 0, 1)

        if not self.ensamblado:
            for i, clave in enumerate(CLAVES):
                glPushMatrix()
                glTranslatef(-220 + 55 * i, 8.0, 0.0)
                if clave in self.mallas:
                    self._ejes()
                self._pieza(clave)
                glPopMatrix()
        else:
            self._pieza(CLAVES[0])
            for i, eje in enumerate(EJES_CADENA):
                glTranslatef(0.0, self.offsets[i], 0.0)
                glRotatef(self.art[i], *eje)
                self._ejes()
                self._pieza(CLAVES[i + 1])
            glTranslatef(0.0, self.offsets[6], 0.0)
            for clave, signo in (("08_dedo_pinza_izq", -1), ("09_dedo_pinza_der", 1)):
                glPushMatrix()
                glTranslatef(signo * self.art[6], 0.0, 0.0)
                self._pieza(clave)
                glPopMatrix()

        glPopMatrix()
        ctypes.windll.gdi32.SwapBuffers(self.hdc)

    # ---- ratón
    def _clic(self, e):
        self.focus_set()
        self.ultimo = (e.x, e.y)

    def _girar(self, e):
        self.az = (self.az - (e.x - self.ultimo[0]) * 0.5) % 360.0
        self.el = max(-89.0, min(89.0, self.el + (e.y - self.ultimo[1]) * 0.5))
        self.ultimo = (e.x, e.y)
        self.dibujar()

    def _desplazar(self, e):
        self.objetivo[0] -= (e.x - self.ultimo[0]) * 0.4
        self.objetivo[1] += (e.y - self.ultimo[1]) * 0.4
        self.ultimo = (e.x, e.y)
        self.dibujar()

    def _zoom(self, e):
        self.dist = max(140.0, min(1400.0, self.dist + (-25.0 if e.delta > 0 else 25.0)))
        self.dibujar()


FONDO, PANEL = "#181B20", "#1E222A"


def crear_control(padre, fila, texto, vmin, vmax, inicial, unidad, paso, al_cambiar):
    """Fila con etiqueta, botón -, deslizador, botón + y valor. Devuelve (variable, poner)."""
    var = tk.DoubleVar(value=inicial)
    valor = tk.Label(padre, width=8, anchor="e", bg=PANEL, fg="#98C379",
                     font=("Consolas", 10, "bold"), text=f"{int(inicial):4d} {unidad}")

    def actualizar(v):
        v = float(v)
        valor.configure(text=f"{int(round(v)):4d} {unidad}")
        al_cambiar(v)

    def poner(v):
        v = max(vmin, min(vmax, v))
        var.set(v)
        actualizar(v)

    tk.Label(padre, text=texto, bg=PANEL, fg="#E6E9EF", anchor="w").grid(row=fila, column=0, sticky="w", padx=3, pady=3)
    tk.Button(padre, text="-", width=3, bg="#282C34", fg="white", relief=tk.FLAT,
              command=lambda: poner(var.get() - paso)).grid(row=fila, column=1, padx=2)
    tk.Scale(padre, variable=var, from_=vmin, to=vmax, orient=tk.HORIZONTAL, resolution=1,
             showvalue=False, bg=PANEL, troughcolor="#2C313C", highlightthickness=0, bd=0,
             command=actualizar).grid(row=fila, column=2, sticky="ew", padx=4)
    tk.Button(padre, text="+", width=3, bg="#282C34", fg="white", relief=tk.FLAT,
              command=lambda: poner(var.get() + paso)).grid(row=fila, column=3, padx=2)
    valor.grid(row=fila, column=4, sticky="e", padx=3)
    return var, poner


ARTICULACIONES = [
    ("Art. 1: Giro de Base (Y)",        -180, 180, 0, "°", 5),
    ("Art. 2: Inclinación Hombro (Z)",   -90,  90, 0, "°", 5),
    ("Art. 3: Inclinación Codo (Z)",    -120, 120, 0, "°", 5),
    ("Art. 4: Rotación Antebrazo (Y)",  -180, 180, 0, "°", 5),
    ("Art. 5: Inclinación Muñeca (Z)",  -110, 110, 0, "°", 5),
    ("Art. 6: Giro de Pinza (Y)",       -180, 180, 0, "°", 5),
    ("Art. 7: Apertura de Pinza (X)",      0,  16, 8, "mm", 1),
]
ESCENA = [
    ("Mover X", -250, 250, "mm", 10, "pos", 0), ("Mover Y", -150, 200, "mm", 10, "pos", 1),
    ("Mover Z", -250, 250, "mm", 10, "pos", 2), ("Rotar X", -180, 180, "°", 5, "rot", 0),
    ("Rotar Y", -180, 180, "°", 5, "rot", 1), ("Rotar Z", -180, 180, "°", 5, "rot", 2),
]
TECLAS = [("1", "q"), ("2", "w"), ("3", "e"), ("4", "r"), ("5", "t"), ("6", "y"), ("7", "u")]


class Aplicacion:
    def __init__(self, ventana):
        self.ventana = ventana
        ventana.title("Simulador de Brazo Robótico 3D")
        ventana.geometry("1360x820")
        ventana.configure(bg=FONDO)
        self.ultima_carpeta = os.path.expanduser("~")

        estilo = ttk.Style(ventana)
        estilo.theme_use("clam")
        estilo.configure(".", background=FONDO, foreground="#E6E9EF", font=("Segoe UI", 9))
        estilo.configure("TLabelframe", background=PANEL, bordercolor="#323844")
        estilo.configure("TLabelframe.Label", background=PANEL, foreground="#61AFEF", font=("Segoe UI", 10, "bold"))

        self._interfaz()
        for i, (mas, menos) in enumerate(TECLAS):
            for t in (mas, menos, menos.upper()):
                signo = 1 if t == mas else -1
                ventana.bind(ev(f"KeyPress-{t}"), lambda e, i=i, s=signo: self._mover_art(i, s))
        ventana.bind(ev("KeyPress-h"), lambda e: self.home())
        ventana.bind(ev("KeyPress-H"), lambda e: self.home())

    def _boton(self, padre, texto, color, comando, **kw):
        return tk.Button(padre, text=texto, bg=color, fg="white", relief=tk.FLAT,
                         padx=8, pady=5, command=comando, **kw)

    def _interfaz(self):
        raiz = ttk.Frame(self.ventana)
        raiz.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        izq = ttk.Frame(raiz)
        izq.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self.visor = Visor(izq)
        self.visor.pack(fill=tk.BOTH, expand=True)

        vistas = ttk.LabelFrame(izq, text="Vistas de cámara")
        vistas.pack(fill=tk.X, pady=(8, 0))
        for texto, az, el in (("Isométrica", 45, 28), ("Superior", 0, 89), ("Lateral", 90, 0), ("Frontal", 0, 0)):
            self._boton(vistas, texto, "#2E4057", lambda a=az, e=el: self.vista(a, e)).pack(side=tk.LEFT, padx=6, pady=6)
        self.var_ejes = tk.BooleanVar(value=True)
        tk.Checkbutton(vistas, text="Mostrar ejes locales", variable=self.var_ejes, bg=PANEL, fg="#E6E9EF",
                       selectcolor="#282C34", activebackground=PANEL, command=self._ejes).pack(side=tk.RIGHT, padx=10)

        der = ttk.Frame(raiz, width=510)
        der.pack(side=tk.RIGHT, fill=tk.Y)
        der.pack_propagate(False)

        g = ttk.LabelFrame(der, text="Importar piezas STL (una por una)")
        g.pack(fill=tk.X, padx=6, pady=(6, 3))
        rejilla = tk.Frame(g, bg=PANEL)
        rejilla.pack(fill=tk.X, padx=6, pady=4)
        self.botones = {}
        for i, (clave, texto, _) in enumerate(PIEZAS):
            b = tk.Button(rejilla, text=texto, bg="#282C34", fg="#ECEFF4", relief=tk.RAISED, bd=1,
                          padx=4, pady=4, command=lambda c=clave: self.importar(c))
            b.grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3)
            rejilla.columnconfigure(i % 3, weight=1)
            self.botones[clave] = b
        self.btn_ensamblar = self._boton(g, "Ensamblar Sistema", "#2B5B3F", self.ensamblar,
                                         font=("Segoe UI", 9, "bold"))
        self.btn_ensamblar.pack(fill=tk.X, padx=8, pady=3)
        self.estado = tk.Label(g, text="0/9 piezas | Modo: Despiece", bg=PANEL, fg="#E5C07B",
                               font=("Segoe UI", 9, "bold"))
        self.estado.pack(fill=tk.X, pady=(2, 6))

        g = ttk.LabelFrame(der, text="Articulaciones")
        g.pack(fill=tk.X, padx=6, pady=3)
        tabla = tk.Frame(g, bg=PANEL)
        tabla.pack(fill=tk.X, padx=6, pady=4)
        tabla.columnconfigure(2, weight=1)
        self.ctrl_art = [
            crear_control(tabla, i, t, a, b, ini, u, paso,
                          lambda v, i=i: self._asignar(self.visor.art, i, v))
            for i, (t, a, b, ini, u, paso) in enumerate(ARTICULACIONES)
        ]
        tk.Label(g, text="Teclado: 1/Q 2/W 3/E 4/R 5/T 6/Y 7/U = articulaciones | H = Home",
                 bg=PANEL, fg="#ABB2BF", font=("Segoe UI", 8)).pack(pady=(0, 4))

        g = ttk.LabelFrame(der, text="Mover y rotar todo el modelo")
        g.pack(fill=tk.X, padx=6, pady=3)
        tabla = tk.Frame(g, bg=PANEL)
        tabla.pack(fill=tk.X, padx=6, pady=4)
        tabla.columnconfigure(2, weight=1)
        self.ctrl_escena = [
            crear_control(tabla, i, t, a, b, 0, u, paso,
                          lambda v, k=k, j=j: self._asignar(getattr(self.visor, k), j, v))
            for i, (t, a, b, u, paso, k, j) in enumerate(ESCENA)
        ]

        self._boton(der, "HOME (articulaciones, modelo y cámara)", "#8B2635", self.home,
                    font=("Segoe UI", 10, "bold")).pack(fill=tk.X, padx=8, pady=8)

    def _asignar(self, lista, i, v):
        lista[i] = v
        self.visor.dibujar()

    def _mover_art(self, i, signo):
        var, poner = self.ctrl_art[i]
        poner(var.get() + signo * ARTICULACIONES[i][5])

    def _ejes(self):
        self.visor.mostrar_ejes = self.var_ejes.get()
        self.visor.dibujar()

    def vista(self, az, el):
        self.visor.vista_inicial(az, el)
        self.visor.dibujar()

    def home(self):
        for (_, poner), spec in zip(self.ctrl_art, ARTICULACIONES):
            poner(spec[3])
        for _, poner in self.ctrl_escena:
            poner(0)
        self.vista(45.0, 28.0)

    def _estado(self, detalle=""):
        modo = "ENSAMBLADO" if self.visor.ensamblado else "Despiece"
        self.estado.configure(text=f"{len(self.visor.mallas)}/9 piezas | Modo: {modo}" + (f" | {detalle}" if detalle else ""))

    def importar(self, clave):
        ruta = filedialog.askopenfilename(
            title=f"Archivo STL para {clave}", initialdir=self.ultima_carpeta,
            filetypes=[("Archivos STL", "*.stl"), ("Todos los archivos", "*.*")])
        if not ruta:
            return
        try:
            n = self.visor.importar(clave, ruta)
        except Exception as exc:
            messagebox.showerror("Error al importar", f"No se pudo leer:\n{ruta}\n\n{exc}")
            return
        self.ultima_carpeta = os.path.dirname(ruta)
        self.botones[clave].configure(bg="#2B5B3F", fg="white")
        self._estado(f"{os.path.basename(ruta)} ({n} triángulos)")

    def ensamblar(self):
        if not self.visor.mallas:
            messagebox.showinfo("Sin piezas", "Primero importa al menos una pieza.")
            return
        self.visor.ensamblado = not self.visor.ensamblado
        if self.visor.ensamblado:
            self.visor.ajustar_offsets_auto()
        self.btn_ensamblar.configure(text="Ver Piezas Separadas" if self.visor.ensamblado else "Ensamblar Sistema")
        self._estado()
        self.visor.dibujar()


if __name__ == "__main__":
    ventana = tk.Tk()
    Aplicacion(ventana)
    ventana.mainloop()