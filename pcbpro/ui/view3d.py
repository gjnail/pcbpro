"""Real-time OpenGL 3D board viewer."""
from __future__ import annotations

import ctypes
import math

import numpy as np
from OpenGL import GL
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .boardtex import EDGE_RGB, FINISH_RGB, board_textures
from .document import Document
from .mesh import scene_parts

VERT = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNrm;
layout(location=2) in vec2 aUV;
uniform mat4 uMVP;
out vec3 vPos; out vec3 vNrm; out vec2 vUV;
void main() { vPos = aPos; vNrm = aNrm; vUV = aUV; gl_Position = uMVP * vec4(aPos, 1.0); }
"""

FRAG = """
#version 330 core
in vec3 vPos; in vec3 vNrm; in vec2 vUV;
uniform vec3 uColor; uniform float uSpec; uniform float uShine; uniform float uMetal;
uniform int uUseTex; uniform sampler2D uTex; uniform vec3 uEye;
uniform vec3 uEmit; uniform int uGlow; uniform float uAlpha;
out vec4 frag;
vec3 envColor(vec3 r) {
    float t = clamp(r.z * 0.5 + 0.5, 0.0, 1.0);
    vec3 c = mix(vec3(0.20, 0.19, 0.18), vec3(0.90, 0.92, 0.98), smoothstep(0.30, 0.80, t));
    c += vec3(1.3) * pow(max(dot(r, normalize(vec3(-0.35, 0.45, 0.82))), 0.0), 40.0);
    c += vec3(0.5) * pow(max(dot(r, normalize(vec3(0.6, -0.3, 0.55))), 0.0), 30.0);
    return c;
}
void main() {
    vec3 N = normalize(vNrm);
    vec3 V = normalize(uEye - vPos);
    if (dot(N, V) < 0.0) N = -N;
    if (uGlow == 1) {  // additive halo around a lit LED (simulation)
        float f = pow(max(dot(N, V), 0.0), 2.5);
        frag = vec4(uColor * f, 1.0);
        return;
    }
    vec3 base = uColor; float spec = uSpec; float metal = uMetal; float shine = uShine;
    if (uUseTex == 1) {
        vec4 t = texture(uTex, vUV);
        base = t.rgb; spec = t.a; metal = smoothstep(0.75, 0.95, t.a);
        shine = mix(38.0, 90.0, metal);
    }
    vec3 L1 = normalize(vec3(-0.35, 0.45, 0.82));
    vec3 L2 = normalize(vec3(0.60, -0.30, 0.45));
    vec3 L3 = normalize(vec3(0.10, 0.25, -1.0));
    // key + fill lights from above, a weak light from below and a camera head-light so
    // every side of the board (including the bottom) is readable
    float d = max(dot(N, L1), 0.0) * 0.55 + max(dot(N, L2), 0.0) * 0.22 + max(dot(N, L3), 0.0) * 0.20
            + max(dot(N, V), 0.0) * 0.30;
    vec3 amb = mix(vec3(0.17, 0.17, 0.19), vec3(0.32, 0.34, 0.38), abs(N.z) * 0.5 + 0.5);
    vec3 diffuse = base * (amb + d);
    vec3 H1 = normalize(L1 + V);
    vec3 H2 = normalize(L2 + V);
    float s = pow(max(dot(N, H1), 0.0), shine) + 0.45 * pow(max(dot(N, H2), 0.0), shine);
    vec3 R = reflect(-V, N);
    vec3 env = envColor(R);
    float fres = pow(1.0 - max(dot(N, V), 0.0), 5.0);
    vec3 metalCol = base * (0.12 + 0.85 * env);
    vec3 col = mix(diffuse, metalCol, metal);
    col += mix(vec3(1.0), base, metal) * s * spec * 0.9;
    col += env * fres * 0.10 * spec;
    col += uEmit;
    col = col / (col + vec3(0.85)) * 1.85;
    // see-through parts (tube glass): more opaque at grazing angles and where the highlights are
    float a = uAlpha < 0.999 ? clamp(uAlpha + fres * 0.6 + s * spec * 0.5, 0.0, 1.0) : 1.0;
    frag = vec4(clamp(col, 0.0, 1.0), a);
}
"""

BG_VERT = """
#version 330 core
out vec2 vUV;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    vUV = p; gl_Position = vec4(p * 2.0 - 1.0, 0.999, 1.0);
}
"""

BG_FRAG = """
#version 330 core
in vec2 vUV; out vec4 frag;
void main() {
    vec3 top = vec3(0.17, 0.19, 0.23);
    vec3 bot = vec3(0.05, 0.055, 0.07);
    float v = clamp(vUV.y, 0.0, 1.0);
    vec3 c = mix(bot, top, v);
    float d = distance(vUV, vec2(0.5, 0.55));
    c *= 1.0 - 0.35 * smoothstep(0.3, 0.9, d);
    frag = vec4(c, 1.0);
}
"""


def _compile(vs: str, fs: str) -> int:
    def shader(src, kind):
        s = GL.glCreateShader(kind)
        GL.glShaderSource(s, src)
        GL.glCompileShader(s)
        if not GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS):
            raise RuntimeError(GL.glGetShaderInfoLog(s).decode())
        return s

    prog = GL.glCreateProgram()
    GL.glAttachShader(prog, shader(vs, GL.GL_VERTEX_SHADER))
    GL.glAttachShader(prog, shader(fs, GL.GL_FRAGMENT_SHADER))
    GL.glLinkProgram(prog)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        raise RuntimeError(GL.glGetProgramInfoLog(prog).decode())
    return prog


def perspective(fovy, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy) / 2)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


def look_at(eye, target, up):
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.identity(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[0, 3], m[1, 3], m[2, 3] = -s @ eye, -u @ eye, f @ eye
    return m


class Mesh:
    def __init__(self, data: np.ndarray, material=None, texture=None):
        self.count = len(data)
        self.material = material
        self.texture = texture
        self.vao = GL.glGenVertexArrays(1)
        self.vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        data = np.ascontiguousarray(data, dtype=np.float32)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_STATIC_DRAW)
        for loc, size, off in ((0, 3, 0), (1, 3, 12), (2, 2, 24)):
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, GL.GL_FALSE, 32, ctypes.c_void_p(off))
        GL.glBindVertexArray(0)

    def delete(self):
        GL.glDeleteBuffers(1, [self.vbo])
        GL.glDeleteVertexArrays(1, [self.vao])


class View3D(QOpenGLWidget):
    info = Signal(str)

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(8)
        self.setFormat(fmt)
        self.doc = doc
        self.yaw, self.pitch = -25.0, 42.0
        self.dist = 120.0
        self.target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.show_components = True
        self.show_enclosure = False  # pedal view: enclosure, knobs and hardware
        self.show_lid = False
        self._flip = False  # scene rotated so knobs point up (pots under the board)
        self.meshes: list[Mesh] = []
        self.glow_meshes: dict[str, list[Mesh]] = {}  # LED lenses per component (lit by the simulation)
        self.halos: dict[str, Mesh] = {}
        self.sim = None
        self.textures: list[int] = []
        self.dirty = True
        self._fitted = False
        self._last = None
        self._gl_ok = False
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(120)
        self._rebuild_timer.timeout.connect(self.update)
        doc.changed.connect(self.mark_dirty)
        doc.replaced.connect(self._on_replaced)
        self.setMinimumSize(300, 200)
        self.setFocusPolicy(Qt.StrongFocus)

    def _on_replaced(self):
        self._fitted = False
        self.mark_dirty()

    def mark_dirty(self):
        self.dirty = True
        if self.isVisible():
            self._rebuild_timer.start()

    # ------------------------------------------------------------------ GL lifecycle
    def initializeGL(self):
        self.prog = _compile(VERT, FRAG)
        self.bg_prog = _compile(BG_VERT, BG_FRAG)
        self.bg_vao = GL.glGenVertexArrays(1)
        self.u = {n: GL.glGetUniformLocation(self.prog, n) for n in
                  ("uMVP", "uColor", "uSpec", "uShine", "uMetal", "uUseTex", "uTex", "uEye", "uEmit", "uGlow",
                   "uAlpha")}
        self.max_aniso = 1.0
        try:
            self.max_aniso = float(GL.glGetFloatv(0x84FF))
        except Exception:
            pass
        self._gl_ok = True
        self.dirty = True

    def _upload_texture(self, rgba: np.ndarray) -> int:
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        h, w = rgba.shape[:2]
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, rgba)
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        if self.max_aniso > 1:
            GL.glTexParameterf(GL.GL_TEXTURE_2D, 0x84FE, min(16.0, self.max_aniso))
        return tex

    def _clear(self):
        for m in self.meshes:
            m.delete()
        self.meshes = []
        for ms in self.glow_meshes.values():
            for m in ms:
                m.delete()
        for m in self.halos.values():
            m.delete()
        self.glow_meshes = {}
        self.halos = {}
        if self.textures:
            GL.glDeleteTextures(len(self.textures), self.textures)
        self.textures = []

    def rebuild(self):
        from .mesh import board_meshes, mat
        proj = self.doc.project
        self._clear()
        if len(proj.board.outline) < 3:
            self.dirty = False
            return
        top_rgba, bot_rgba = board_textures(proj)
        tex_top = self._upload_texture(top_rgba)
        tex_bot = self._upload_texture(bot_rgba)
        self.textures = [tex_top, tex_bot]
        bm = board_meshes(proj)
        fin = FINISH_RGB.get(proj.board.finish, FINISH_RGB["HASL (lead-free)"])
        pedal = self._pedal_parts(proj)
        F = self._world
        if len(bm["top"]):
            self.meshes.append(Mesh(F(bm["top"]), texture=tex_top))
        if len(bm["bottom"]):
            self.meshes.append(Mesh(F(bm["bottom"]), texture=tex_bot))
        if len(bm["edge"]):
            self.meshes.append(Mesh(F(bm["edge"]), mat(tuple(c / 255 for c in EDGE_RGB), 0.15, 16)))
        if len(bm["plated"]):
            self.meshes.append(Mesh(F(bm["plated"]), mat(tuple(c / 255 for c in fin), 0.9, 60, 1.0)))
        if len(bm["bare"]):
            self.meshes.append(Mesh(F(bm["bare"]), mat(tuple(c / 255 for c in EDGE_RGB), 0.1, 10)))
        glow: dict = {}
        self._ztop = 0.0  # height of the tallest part (tubes, caps) so the camera can frame it
        for material, arr in scene_parts(proj, self.show_components, glow).items():
            self._ztop = max(self._ztop, float(arr[:, 2].max()))
            self.meshes.append(Mesh(F(arr), material))
        self._build_glow(glow, F)
        for material, arr in pedal.items():
            self.meshes.append(Mesh(F(arr), material))
        if not self._fitted:
            self.fit()
        self.dirty = False

    # ------------------------------------------------------------------ simulation glow
    def set_simulation(self, controller) -> None:
        """Light LED lenses from a running SimController."""
        self.sim = controller
        controller.updated.connect(lambda: self.isVisible() and self.update())
        controller.stopped.connect(lambda *_: self.update())

    def _build_glow(self, glow: dict, F) -> None:
        from .mesh import dome
        for uid, items in glow.items():
            meshes = []
            pts = []
            for material, arr in items:
                w = F(arr)
                meshes.append(Mesh(w, material))
                pts.append(w[:, :3])
            self.glow_meshes[uid] = meshes
            allp = np.concatenate(pts)
            lo, hi = allp.min(axis=0), allp.max(axis=0)
            centre = (lo + hi) / 2
            size = float(max(hi[0] - lo[0], hi[1] - lo[1], 0.6))
            r = size * 1.6
            halo = dome(0.0, 0.0, -r * 0.35, r, 28, 10)
            halo[:, 0] += centre[0]
            halo[:, 1] += centre[1]
            top = hi[2] if not self._flip else lo[2]
            if self._flip:
                halo[:, 2] *= -1
                halo[:, 5] *= -1
            halo[:, 2] += top
            self.halos[uid] = Mesh(halo.astype(np.float32), (1.0, 1.0, 1.0, 0.0, 1.0, 0.0))

    def _paint_glow(self) -> None:
        levels: dict[str, tuple] = {}
        sim = self.sim
        if sim is not None and sim.running:
            for uid, level, col, _label in sim.led_states():
                if level > levels.get(uid, (0.0, None))[0]:
                    levels[uid] = (level, col)
        GL.glUniform1i(self.u["uUseTex"], 0)
        GL.glUniform1f(self.u["uAlpha"], 1.0)
        for uid, meshes in self.glow_meshes.items():
            level, col = levels.get(uid, (0.0, None))
            for m in meshes:
                r, g, b, spec, shine, metal = m.material[:6]
                if level > 0:
                    er, eg, eb = (int(col[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
                    k = 1.8 * level
                    GL.glUniform3f(self.u["uEmit"], er * k, eg * k, eb * k)
                    GL.glUniform3f(self.u["uColor"], r * (1 - 0.4 * level), g * (1 - 0.4 * level),
                                   b * (1 - 0.4 * level))
                else:
                    GL.glUniform3f(self.u["uEmit"], 0.0, 0.0, 0.0)
                    GL.glUniform3f(self.u["uColor"], r * 0.75, g * 0.75, b * 0.75)
                GL.glUniform1f(self.u["uSpec"], spec)
                GL.glUniform1f(self.u["uShine"], shine)
                GL.glUniform1f(self.u["uMetal"], metal)
                GL.glBindVertexArray(m.vao)
                GL.glDrawArrays(GL.GL_TRIANGLES, 0, m.count)
        GL.glUniform3f(self.u["uEmit"], 0.0, 0.0, 0.0)
        lit = [(uid, lv, col) for uid, (lv, col) in levels.items() if lv > 0.02 and uid in self.halos]
        if not lit:
            return
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glUniform1i(self.u["uGlow"], 1)
        for uid, level, col in lit:
            er, eg, eb = (int(col[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
            k = 0.55 * level
            GL.glUniform3f(self.u["uColor"], er * k, eg * k, eb * k)
            m = self.halos[uid]
            GL.glBindVertexArray(m.vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, m.count)
        GL.glUniform1i(self.u["uGlow"], 0)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)

    # ------------------------------------------------------------------ pedal view
    def _pedal_parts(self, proj) -> dict:
        self._flip = False
        if not self.show_enclosure:
            return {}
        from ..pedal.enclosure import get_enclosure
        from ..pedal.mesh3d import pedal_parts
        enc = get_enclosure(proj)
        if enc is None:
            return {}
        self._flip = enc.face_side == "bottom"
        return pedal_parts(proj, show_lid=self.show_lid)

    def _world(self, arr):
        if not self._flip:
            return arr
        from ..pedal.mesh3d import flip_for_pedal_view
        return flip_for_pedal_view(arr)

    def set_show_enclosure(self, on: bool):
        self.show_enclosure = on
        self._fitted = False
        self.mark_dirty()

    def set_show_lid(self, on: bool):
        self.show_lid = on
        self.mark_dirty()

    # ------------------------------------------------------------------ camera
    def fit(self):
        b = self.doc.project.board
        x0, y0, x1, y1 = b.bounds()
        self.target = np.array([(x0 + x1) / 2, -(y0 + y1) / 2, b.thickness / 2], dtype=np.float32)
        diag = math.hypot(x1 - x0, y1 - y0)
        if self.show_enclosure:
            from ..pedal.mesh3d import pedal_bounds
            pb = pedal_bounds(self.doc.project)
            if pb is not None:
                self.target = np.array([(pb[0] + pb[3]) / 2, (pb[1] + pb[4]) / 2, (pb[2] + pb[5]) / 2],
                                       dtype=np.float32)
                diag = math.hypot(pb[3] - pb[0], pb[4] - pb[1]) * 1.35  # leave room for knobs and jacks
        else:
            tall = getattr(self, "_ztop", 0.0) - b.thickness
            if tall > diag * 0.2:  # tubes, transformers, big caps: aim at their middle and back off
                self.target[2] = b.thickness + tall * 0.4
                diag = max(diag, math.hypot(diag, tall) * 1.05)
        if self._flip:
            self.target = self.target * np.array([-1.0, 1.0, -1.0], dtype=np.float32)
        self.dist = max(10.0, diag * 2.0)
        self._fitted = True
        self.update()

    def set_view(self, name: str):
        views = {"top": (0.0, 89.9), "bottom": (0.0, -89.9), "front": (0.0, 12.0), "iso": (-25.0, 42.0),
                 "back": (180.0, 12.0), "left": (-90.0, 12.0), "right": (90.0, 12.0), "pedal": (-18.0, 48.0)}
        self.yaw, self.pitch = views.get(name, views["iso"])
        self.fit()

    def eye(self) -> np.ndarray:
        cy, sy = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
        cp, sp = math.cos(math.radians(self.pitch)), math.sin(math.radians(self.pitch))
        return self.target + self.dist * np.array([cp * sy, -cp * cy, sp], dtype=np.float32)

    def matrices(self):
        w, h = max(1, self.width()), max(1, self.height())
        eye = self.eye()
        up = np.array([0, 0, 1], dtype=np.float32)
        if abs(self.pitch) > 89:
            cy, sy = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
            up = np.array([-sy, cy, 0], dtype=np.float32)
        view = look_at(eye.astype(np.float64), self.target.astype(np.float64), up.astype(np.float64))
        proj = perspective(24.0, w / h, max(0.05, self.dist * 0.01), self.dist * 20)
        return proj @ view, eye

    # ------------------------------------------------------------------ painting
    def paintGL(self):
        if not self._gl_ok:
            return
        if self.dirty:
            try:
                self.rebuild()
            except Exception as e:  # keep the UI alive; report the problem
                self.dirty = False
                self.info.emit(f"3D rebuild failed: {e}")
        GL.glDisable(GL.GL_BLEND)  # the LED halo pass blends; never let that leak into the next frame
        GL.glDepthMask(GL.GL_TRUE)
        GL.glClearColor(0.08, 0.09, 0.11, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glUseProgram(self.bg_prog)
        GL.glBindVertexArray(self.bg_vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_MULTISAMPLE)
        mvp, eye = self.matrices()
        GL.glUseProgram(self.prog)
        GL.glUniformMatrix4fv(self.u["uMVP"], 1, GL.GL_TRUE, mvp.astype(np.float32))
        GL.glUniform3f(self.u["uEye"], *[float(v) for v in eye])
        GL.glUniform1i(self.u["uTex"], 0)
        GL.glUniform3f(self.u["uEmit"], 0.0, 0.0, 0.0)
        GL.glUniform1i(self.u["uGlow"], 0)
        GL.glUniform1f(self.u["uAlpha"], 1.0)
        see_through = []
        for m in self.meshes:
            if m.texture is not None:
                GL.glUniform1i(self.u["uUseTex"], 1)
                GL.glUniform3f(self.u["uEmit"], 0.0, 0.0, 0.0)
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, m.texture)
            else:
                if len(m.material) > 6 and m.material[6] < 0.999:
                    see_through.append(m)  # drawn last, over everything opaque
                    continue
                self._set_material(m.material)
            GL.glBindVertexArray(m.vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, m.count)
        GL.glUniform3f(self.u["uEmit"], 0.0, 0.0, 0.0)
        self._paint_glow()
        if see_through:  # tube glass: alpha-blended, no depth writes so what is inside stays visible
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glDepthMask(GL.GL_FALSE)
            GL.glUniform1i(self.u["uUseTex"], 0)
            for m in see_through:
                self._set_material(m.material)
                GL.glUniform1f(self.u["uAlpha"], m.material[6])
                GL.glBindVertexArray(m.vao)
                GL.glDrawArrays(GL.GL_TRIANGLES, 0, m.count)
            GL.glUniform1f(self.u["uAlpha"], 1.0)
            GL.glUniform3f(self.u["uEmit"], 0.0, 0.0, 0.0)
            GL.glDepthMask(GL.GL_TRUE)
            GL.glDisable(GL.GL_BLEND)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)

    def _set_material(self, material) -> None:
        """Upload a mesh material (r, g, b, spec, shine, metal[, alpha, emit]); emit makes it glow (tube heaters)."""
        GL.glUniform1i(self.u["uUseTex"], 0)
        r, g, b, spec, shine, metal = material[:6]
        GL.glUniform3f(self.u["uColor"], r, g, b)
        GL.glUniform1f(self.u["uSpec"], spec)
        GL.glUniform1f(self.u["uShine"], shine)
        GL.glUniform1f(self.u["uMetal"], metal)
        e = material[7] if len(material) > 7 else 0.0
        GL.glUniform3f(self.u["uEmit"], r * e * 1.6, g * e * 1.6, b * e * 1.6)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.dirty:
            self._rebuild_timer.start()

    # ------------------------------------------------------------------ interaction
    def mousePressEvent(self, ev):
        self._last = ev.position()
        self.setFocus()

    def mouseMoveEvent(self, ev):
        if self._last is None:
            return
        d = ev.position() - self._last
        self._last = ev.position()
        if ev.buttons() & Qt.LeftButton and not (ev.modifiers() & Qt.ShiftModifier):
            self.yaw -= d.x() * 0.4
            self.pitch = max(-89.9, min(89.9, self.pitch + d.y() * 0.4))
        elif ev.buttons() & (Qt.RightButton | Qt.MiddleButton | Qt.LeftButton):
            mvp, eye = self.matrices()
            fwd = self.target - eye
            fwd /= np.linalg.norm(fwd)
            up = np.array([0, 0, 1.0])
            if abs(self.pitch) > 89:
                cy, sy = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
                up = np.array([-sy, cy, 0.0])
            right = np.cross(fwd, up)
            right /= np.linalg.norm(right)
            upv = np.cross(right, fwd)
            k = self.dist * 0.0012
            self.target = (self.target - right * d.x() * k + upv * d.y() * k).astype(np.float32)
        self.update()

    def mouseReleaseEvent(self, ev):
        self._last = None

    def mouseDoubleClickEvent(self, ev):
        self.fit()

    def wheelEvent(self, ev):
        self.dist = max(2.0, min(3000.0, self.dist * (0.999 ** ev.angleDelta().y())))
        self.update()

    def keyPressEvent(self, ev):
        keys = {Qt.Key_1: "top", Qt.Key_2: "bottom", Qt.Key_3: "front", Qt.Key_0: "iso", Qt.Key_4: "left",
                Qt.Key_6: "right", Qt.Key_8: "back"}
        if ev.key() in keys:
            self.set_view(keys[ev.key()])
        elif ev.key() == Qt.Key_Home:
            self.fit()
        else:
            super().keyPressEvent(ev)

    def set_show_components(self, on: bool):
        self.show_components = on
        self.mark_dirty()
