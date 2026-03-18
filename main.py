#!/usr/bin/env python3
"""
RetiBrowser - A Kivy-based Reticulum NomadNet Micron Browser
Connects to a community hub and renders Micron markup pages.

Requirements:
    pip install kivy rns

Usage:
    python main.py
"""

import os
import sys
import time
import threading
import traceback

# ─── Kivy config BEFORE import ───────────────────────────────────────────────
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")
os.environ["KIVY_TEXT"] = "sdl2"

# Enable Android logging
try:
    import android
    from android.runnable import run_on_ui_thread
    def log(msg):
        print(f"[RetiBrowser] {msg}")
except ImportError:
    def log(msg):
        print(f"[RetiBrowser] {msg}")

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.animation import Animation

import RNS
import RNS.vendor.umsgpack as umsgpack

# ─── Font Configuration ───────────────────────────────────────────────────────
FONT_PATH = None

def _init_font():
    global FONT_PATH
    for base in [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "files"),
    ]:
        fp = os.path.join(base, "JetBrainsMonoNerdFont.ttf")
        if os.path.exists(fp):
            FONT_PATH = fp
            log(f"Using bundled font: {FONT_PATH}")
            return
    FONT_PATH = ""
    log("Using system default font")

_init_font()

# ─── Constants ────────────────────────────────────────────────────────────────
NODERAGE_HOST = "rns01.ohiomesh.net"
NODERAGE_PORT = 4242
DEFAULT_NODE  = "fad4f4c59b38f341d357383593c41bd8"
DEFAULT_PAGE  = "/page/index.mu"
PAGE_TIMEOUT  = 30
LINK_TIMEOUT  = 30

# ─── Colours ──────────────────────────────────────────────────────────────────
MICRON_COLORS = {
    "f00": (1,0,0,1),       "0f0": (0,1,0,1),       "00f": (0,0,1,1),
    "ff0": (1,1,0,1),       "0ff": (0,1,1,1),       "f0f": (1,0,1,1),
    "fff": (1,1,1,1),       "000": (0,0,0,1),       "888": (.53,.53,.53,1),
    "aaa": (.67,.67,.67,1), "0a0": (0,.63,0,1),     "a00": (.63,0,0,1),
    "00a": (0,0,.63,1),     "fa0": (1,.63,0,1),     "0fa": (0,1,.63,1),
    "f80": (1,.5,0,1),      "5f5": (.33,1,.33,1),   "55f": (.33,.33,1,1),
    "f55": (1,.33,.33,1),   "5ff": (.33,1,1,1),
}
BG_COLOR  = (0.05, 0.05, 0.08, 1)
FG_COLOR  = (0.85, 0.90, 0.85, 1)
NAV_COLOR = (0.10, 0.12, 0.16, 1)
BTN_COLOR = (0.15, 0.20, 0.28, 1)
BTN_PRESS = (0.25, 0.35, 0.50, 1)
LNK_COLOR = (0.40, 0.80, 1.00, 1)


# ─── Micron Parser ────────────────────────────────────────────────────────────

def hex3_to_rgba(h):
    if h in MICRON_COLORS:
        return MICRON_COLORS[h]
    try:
        return (int(h[0]*2,16)/255, int(h[1]*2,16)/255, int(h[2]*2,16)/255, 1)
    except Exception:
        return FG_COLOR

def hex2_to_rgba(h):
    try:
        v = int(h, 16) / 255
        return (v, v, v, 1)
    except Exception:
        return FG_COLOR


def parse_micron(text):
    """
    Parse Micron markup → list of render elements.

    Supported:
      - Headings: > >> >>> with optional trailing <
      - Inline: `! bold  `* italic  `_ underline  `` reset
      - Colour: `Fxxx fg  `f reset-fg  `Bxxx bg  `b reset-bg  `gXX grayscale
      - Alignment: `c  `l  `r  `a (flush before changing)
      - Links: `[label`path]`  and  `[`path]`
      - Link field refs stripped: `[Label`path`field1|field2]`
      - Input fields (read-only): `<...>  rendered as dimmed placeholder
      - lxmf@ links: rendered as ✉ label, not navigation
      - Dividers: -  ---  `-`  -X (custom fill char X)
      - Literal mode: `= ... `=
      - Comments: # (not #!)
      - Cache headers: all leading #! lines stripped
      - Escape: \\ before any char
    """
    elements = []
    cur_fg, cur_bg  = FG_COLOR, BG_COLOR
    cur_bold = cur_ital = cur_uline = False
    cur_align = "left"
    in_literal = False
    literal_buffer = []

    def reset_fmt():
        nonlocal cur_fg, cur_bg, cur_bold, cur_ital, cur_uline, cur_align
        cur_fg, cur_bg = FG_COLOR, BG_COLOR
        cur_bold = cur_ital = cur_uline = False
        cur_align = "left"

    def _inline_segments(line):
        """
        Tokenise one line of inline Micron markup.
        Returns (segments_list, links_list, final_align).
        Does NOT handle line-level tokens (>, <, -, #, etc.).
        """
        nonlocal cur_fg, cur_bg, cur_bold, cur_ital, cur_uline, cur_align
        segments, links = [], []
        seg_fg, seg_bg   = cur_fg, cur_bg
        seg_bold, seg_ital, seg_uline = cur_bold, cur_ital, cur_uline
        seg_align = cur_align
        buf = ""
        i = 0

        def flush():
            nonlocal buf
            if buf:
                segments.append({
                    "text": buf, "bold": seg_bold, "italic": seg_ital,
                    "underline": seg_uline, "fg": seg_fg, "bg": seg_bg,
                })
            buf = ""

        while i < len(line):
            ch = line[i]

            # Backslash escape
            if ch == "\\" and i + 1 < len(line):
                buf += line[i + 1]
                i += 2
                continue

            if ch != "`":
                buf += ch
                i += 1
                continue

            nxt = line[i+1] if i+1 < len(line) else ""

            # `` reset all formatting
            if nxt == "`":
                flush(); reset_fmt()
                seg_fg, seg_bg = cur_fg, cur_bg
                seg_bold = seg_ital = seg_uline = False
                i += 2; continue

            # `! bold
            if nxt == "!":
                flush(); seg_bold = not seg_bold; i += 2; continue

            # `* italic
            if nxt == "*":
                flush(); seg_ital = not seg_ital; i += 2; continue

            # `_ underline
            if nxt == "_":
                flush(); seg_uline = not seg_uline; i += 2; continue

            # `a alignment reset — flush first
            if nxt == "a":
                flush(); seg_align = "left"; i += 2; continue

            # `c `l `r alignment (only when followed by non-backtick)
            if nxt in ("c","l","r") and i+2 < len(line) and line[i+2] != "`":
                flush()
                seg_align = {"c":"center","l":"left","r":"right"}[nxt]
                i += 2; continue

            # `Fxxx foreground colour
            if nxt == "F" and i+4 < len(line):
                flush(); seg_fg = hex3_to_rgba(line[i+2:i+5]); i += 5; continue

            # `f reset foreground
            if nxt == "f":
                flush(); seg_fg = FG_COLOR; i += 2; continue

            # `Bxxx background colour
            if nxt == "B" and i+4 < len(line):
                flush(); seg_bg = hex3_to_rgba(line[i+2:i+5]); i += 5; continue

            # `b reset background
            if nxt == "b":
                flush(); seg_bg = BG_COLOR; i += 2; continue

            # `gXX grayscale foreground
            if nxt == "g" and i+3 < len(line):
                flush(); seg_fg = hex2_to_rgba(line[i+2:i+4]); i += 4; continue

            # `[label`path]`  link
            if nxt == "[":
                flush()
                j = line.find("`", i+2)
                if j == -1:
                    buf += ch; i += 1; continue
                label_text = line[i+2:j]
                k = line.find("]", j+1)
                if k == -1:
                    buf += ch; i += 1; continue
                raw_path = line[j+1:k]
                # Strip field references: `[Label`path`field1|field2]`
                if "`" in raw_path:
                    raw_path = raw_path[:raw_path.index("`")]
                node_addr, page_path = "", raw_path
                if ":" in raw_path and not raw_path.startswith("/"):
                    node_addr, page_path = raw_path.split(":", 1)
                if not label_text:
                    label_text = page_path
                # lxmf@ addresses are messaging, not page navigation
                if page_path.startswith("lxmf") or node_addr.startswith("lxmf"):
                    segments.append({
                        "text": f"✉ {label_text}", "bold": False, "italic": True,
                        "underline": True, "fg": (0.6,0.8,0.6,1), "bg": seg_bg,
                    })
                else:
                    links.append({
                        "type":"link", "label":label_text,
                        "path":page_path, "node":node_addr, "fg":LNK_COLOR,
                    })
                i = k+1
                if i < len(line) and line[i] == "`":
                    i += 1
                continue

            # `<fieldname`default>  input field (read-only: render placeholder)
            if nxt == "<":
                flush()
                end = line.find(">", i+2)
                if end != -1:
                    field_spec = line[i+2:end]
                    tick = field_spec.rfind("`")
                    default = field_spec[tick+1:] if tick != -1 else ""
                    if default:
                        segments.append({
                            "text": f"[{default}]", "bold": False, "italic": True,
                            "underline": False, "fg": (0.5,0.6,0.7,1), "bg": seg_bg,
                        })
                    i = end + 1
                else:
                    buf += ch; i += 1
                continue

            # Unrecognised escape — emit literally
            buf += ch; i += 1

        flush()
        return segments, links, seg_align

    def _make_heading(level, raw_text, base_fg):
        """Process a heading line, allowing inline markup inside it."""
        content = raw_text.rstrip().rstrip("<").strip()
        segs, lnks, align = _inline_segments(content)
        # Promote all segments to heading style
        result = []
        if segs:
            for s in segs:
                s["bold"] = True
                if s["fg"] == FG_COLOR:
                    s["fg"] = base_fg
            result.append({"type":"text","heading":level,"align":"left","segments":segs})
        if lnks:
            result.extend(lnks)
        if not result:
            result = [{"type":"text","heading":level,"align":"left",
                       "segments":[{"text":content,"bold":True,"italic":False,
                                    "underline":False,"fg":base_fg,"bg":BG_COLOR}]}]
        return result

    def process_line(line):
        """Handle one source line, returns list of elements."""
        stripped = line.strip()

        # Headings — process inline markup inside them
        if line.startswith(">>>"):
            return _make_heading(3, line[3:], (0.7,0.9,1,1))
        if line.startswith(">>"):
            return _make_heading(2, line[2:], (0.6,1,0.7,1))
        if line.startswith(">"):
            return _make_heading(1, line[1:], (1,0.85,0.3,1))

        # Section depth reset
        if stripped == "<":
            return []

        # Dividers: single "-", "---", "`-`", "-X" (custom char)
        if stripped == "-" or stripped.startswith("---") or stripped == "`-`":
            return [{"type":"divider"}]
        if len(stripped) == 2 and stripped[0] == "-" and stripped[1] not in " \t":
            return [{"type":"divider","char":stripped[1]}]

        # Empty line
        if stripped == "":
            return [{"type":"blank"}]

        # Comment (not cache header)
        if line.startswith("#") and not line.startswith("#!"):
            return []

        # Normal inline markup
        segs, lnks, align = _inline_segments(line)
        result = []
        if segs:
            result.append({"type":"text","heading":0,"align":align,"segments":segs})
        result.extend(lnks)
        return result if result else [{"type":"blank"}]

    # Strip all leading #! control/cache header lines
    lines = text.split("\n")
    while lines and lines[0].strip().startswith("#!"):
        lines = lines[1:]

    for raw_line in lines:
        line = raw_line.rstrip("\r")

        if in_literal:
            if "`=" in line:
                idx = line.index("`=")
                literal_buffer.append(line[:idx])
                elements.append({"type":"literal","content":"\n".join(literal_buffer)})
                literal_buffer = []
                in_literal = False
                remainder = line[idx+2:]
                if remainder:
                    elements.extend(process_line(remainder))
            else:
                literal_buffer.append(line)
        elif "`=" in line:
            idx = line.index("`=")
            before, after = line[:idx], line[idx+2:]
            if "`=" in after:
                end_idx = after.index("`=")
                if before:
                    elements.extend(process_line(before))
                elements.append({"type":"literal","content":after[:end_idx]})
                remainder = after[end_idx+2:]
                if remainder:
                    elements.extend(process_line(remainder))
            else:
                if before:
                    elements.extend(process_line(before))
                in_literal = True
                literal_buffer = [after]
        else:
            elements.extend(process_line(line))

    if in_literal and literal_buffer:
        elements.append({"type":"literal","content":"\n".join(literal_buffer)})

    return elements


# ─── Reticulum Network Layer ──────────────────────────────────────────────────

class AnnounceHandler:
    """Receives RNS announce packets and extracts node info."""

    aspect_filter = None  # Accept all aspects (must be None, not "nomadnetwork")

    def __init__(self, on_announce_callback=None):
        self.on_announce_callback = on_announce_callback
        self._announced_nodes = {}

    def received_announce(self, destination_hash, announced_identity, app_data,
                          announce_packet_hash=None, is_path_response=False):
        if not announced_identity:
            return
        try:
            node_hash = RNS.hexrep(destination_hash, delimit=False)

            # Parse app_data — NomadNet nodes use several formats:
            #   dict   : {"name": "...", "type": "...", ...}
            #   list   : [b"NodeName", None|dict]  — most common NomadNet format
            #   bytes  : msgpack-encoded dict or list
            #   scalar : int/None — no useful name info
            info = {}
            if isinstance(app_data, bytes):
                try:
                    info = umsgpack.unpackb(app_data)
                except Exception:
                    info = {}
            elif isinstance(app_data, dict):
                info = app_data
            elif isinstance(app_data, list):
                # [b'NodeName', optional_dict_or_None]
                name_raw = app_data[0] if app_data else None
                extra    = app_data[1] if len(app_data) > 1 else None
                if isinstance(name_raw, bytes):
                    info["name"] = name_raw.decode("utf-8", errors="replace")
                if isinstance(extra, dict):
                    info.update(extra)
            # scalar (int, None, etc.) → info stays {}

            # If info itself is a list (nested unpack), handle similarly
            if isinstance(info, list):
                name_raw = info[0] if info else None
                extra    = info[1] if len(info) > 1 else None
                info = {}
                if isinstance(name_raw, bytes):
                    info["name"] = name_raw.decode("utf-8", errors="replace")
                if isinstance(extra, dict):
                    info.update(extra)
            elif not isinstance(info, dict):
                info = {}

            name = (info.get("name") or info.get("nodename") or
                    info.get("node_name") or info.get("title") or
                    info.get("display_name") or info.get("hostname") or
                    f"Node {node_hash[:8]}")

            node_record = {
                "hash":         node_hash,
                "name":         name,
                "timestamp":    info.get("timestamp", time.time()),
                "capabilities": info.get("capabilities", []),
                "type":         info.get("type", "unknown"),
            }
            self._announced_nodes[node_hash] = node_record
            log(f"Announce: {name} ({node_hash[:8]}…)")

            if self.on_announce_callback:
                Clock.schedule_once(
                    lambda dt, nr=node_record: self.on_announce_callback(nr), 0)
        except Exception as e:
            RNS.log(f"RetiBrowser: announce handler error: {e}", RNS.LOG_ERROR)

    def get_announced_nodes(self):
        return list(self._announced_nodes.values())


class ReticulumClient:
    """Manages the RNS instance and page fetching."""

    def __init__(self, on_announce_callback=None):
        self.rns              = None
        self.identity         = None
        self._active_link     = None
        self._lock            = threading.Lock()
        self.announce_handler = AnnounceHandler(on_announce_callback)

    def start(self, hub_host=NODERAGE_HOST, hub_port=NODERAGE_PORT):
        # Resolve a writable config directory
        try:
            from kivy.app import App as KivyApp
            app = KivyApp.get_running_app()
            config_root = app.user_data_dir if (app and app.user_data_dir) else os.path.expanduser("~")
        except Exception:
            config_root = os.path.expanduser("~")

        config_path = os.path.join(config_root, ".reticulum_retibrowser")
        os.makedirs(config_path, exist_ok=True)

        # Write RNS config.
        # enable_transport = No — we are a CLIENT, not a relay.
        # With Yes, RNS tries to rebroadcast every incoming announce to other
        # interfaces; having only one interface causes:
        #   [Error] No interfaces could process the outbound packet
        with open(os.path.join(config_path, "config"), "w") as f:
            f.write(f"""[reticulum]
  enable_transport = No
  share_instance   = No
  rpc_listener     = No

[interfaces]

  [[Community Hub]]
    type        = TCPClientInterface
    enabled     = yes
    target_host = {hub_host}
    target_port = {hub_port}
""")

        self.rns = RNS.Reticulum(configdir=config_path, loglevel=RNS.LOG_DEBUG)

        # Persistent identity — a new random identity every launch causes ECDH
        # handshake failures when the server has a cached (now-stale) public key.
        identity_file = os.path.join(config_path, "identity")
        if os.path.exists(identity_file):
            self.identity = RNS.Identity.from_file(identity_file)
            log(f"Loaded identity: {RNS.hexrep(self.identity.hash, delimit=False)[:8]}…")
        else:
            self.identity = RNS.Identity()
            self.identity.to_file(identity_file)
            log(f"Created identity: {RNS.hexrep(self.identity.hash, delimit=False)[:8]}…")

        # Register handler BEFORE any announces could arrive
        RNS.Transport.register_announce_handler(self.announce_handler)
        RNS.log("RetiBrowser: Reticulum started", RNS.LOG_NOTICE)

    def get_announced_nodes(self):
        return self.announce_handler.get_announced_nodes()

    def fetch_page(self, node_hex, page_path, on_done, on_error, on_progress=None):
        threading.Thread(
            target=self._fetch_thread,
            args=(node_hex, page_path, on_done, on_error, on_progress),
            daemon=True,
        ).start()

    def _fetch_thread(self, node_hex, page_path, on_done, on_error, on_progress):
        """
        Pure callback chain — no sleep(), no Event.wait(), no polling.

        _fetch_thread
          → (path in table?) yes → _step_identity
                              no  → register _PathWatcher + timeout
                                      → on announce → _step_identity
          → _step_identity  → recall identity → _step_open_link
          → _step_open_link → RNS.Link() + timeout clock
                                → _on_link_established → _step_send_request
          → _step_send_request → link.request()
                                    → response_received → on_done
                                    → request_failed   → on_error
        """
        def status(msg):
            log(f"[fetch] {msg}")
            if on_progress:
                on_progress(msg)

        def teardown():
            try:
                with self._lock:
                    if self._active_link:
                        self._active_link.teardown()
                        self._active_link = None
            except Exception:
                pass

        def fail(msg):
            teardown()
            on_error(msg)

        try:
            dest_hash = bytes.fromhex(node_hex)
            status(f"dest={node_hex[:8]}… path={page_path}")

            # Log interface state
            interfaces = getattr(RNS.Transport, "interfaces", [])
            status(f"{len(interfaces)} interface(s): " +
                   ", ".join(f"{getattr(i,'name','?')} online={getattr(i,'online','?')}"
                             for i in interfaces))

            def _step_identity(dh):
                identity = RNS.Identity.recall(dh)
                if not identity:
                    fail(f"[FAIL] Identity not recalled for {RNS.hexrep(dh,delimit=False)[:8]}…\n"
                         f"  Server may not be announcing. Check server log.")
                    return
                status(f"Identity recalled: {RNS.hexrep(identity.hash,delimit=False)[:8]}…")
                # Note: identity.hash ≠ dest_hash by design (dest includes app+aspects)
                _step_open_link(identity, dh)

            def _step_open_link(identity, dh):
                destination = RNS.Destination(
                    identity, RNS.Destination.OUT, RNS.Destination.SINGLE,
                    "nomadnetwork", "page",
                )
                status(f"Opening link to {RNS.hexrep(dh,delimit=False)[:8]}…")

                timeout_ev = [None]

                def _on_link_established(link):
                    if timeout_ev[0]:
                        timeout_ev[0].cancel()
                        timeout_ev[0] = None
                    status("Link established!")
                    _step_send_request(link)

                def _on_link_closed(link):
                    # If the timeout clock is still pending when the link closes,
                    # it means the link never established. Let the timeout fire
                    # naturally with its descriptive error rather than failing
                    # immediately — RNS may internally retry the link after a
                    # path rediscovery, and we don't want to abort prematurely.
                    # The timeout clock will call fail() if the link stays down.
                    if timeout_ev[0]:
                        status("Link closed before established — waiting for timeout or retry")

                def _on_link_timeout(dt):
                    timeout_ev[0] = None
                    fail(f"[FAIL] Link timed out after {LINK_TIMEOUT}s\n"
                         f"  Is the page node destination still running?")

                with self._lock:
                    self._active_link = RNS.Link(destination)
                self._active_link.set_link_established_callback(_on_link_established)
                self._active_link.set_link_closed_callback(_on_link_closed)
                timeout_ev[0] = Clock.schedule_once(_on_link_timeout, LINK_TIMEOUT)
                status("Waiting for link…")

            def _step_send_request(link):
                status(f"Sending request: {page_path}")

                def response_received(receipt):
                    status(f"Response: status={receipt.status}")
                    if receipt.status == RNS.RequestReceipt.FAILED:
                        fail(f"[FAIL] Request failed for {page_path}")
                        return
                    if receipt.response is not None:
                        raw = receipt.response
                        page_content = (raw.decode("utf-8", errors="replace")
                                        if isinstance(raw, bytes) else str(raw))
                        status(f"Response {len(page_content)} chars — rendering…")
                        teardown()
                        on_done(page_content)

                def progress_updated(receipt):
                    status(f"Downloading… {int(receipt.progress*100)}%")

                def request_failed(receipt):
                    fail(f"[FAIL] Request failed (status={receipt.status}) for {page_path}")

                # Send the FULL path — server routes on this argument directly.
                # Never truncate to "/page": that breaks every page except index.mu.
                link.request(
                    page_path,
                    data              = None,
                    response_callback = response_received,
                    failed_callback   = request_failed,
                    progress_callback = progress_updated,
                    timeout           = PAGE_TIMEOUT,
                )

            # ── Start the chain ───────────────────────────────────────────────
            # Always expire any cached path before requesting — cached entries
            # from previous sessions may be stale (hub topology changes between
            # runs). A stale path causes "link was never established / trying to
            # rediscover" because RNS trusts the cache and sends the link request
            # to a next-hop that no longer exists on the network.
            if hasattr(RNS.Transport, "expire_announced_path"):
                try:
                    RNS.Transport.expire_announced_path(dest_hash)
                    status("Expired cached path — requesting fresh route")
                except Exception:
                    pass
            elif RNS.Transport.has_path(dest_hash):
                # expire_announced_path not available in this RNS version —
                # use has_path as a read-only check but still re-request to
                # validate the path is still live before opening a link.
                status("Path in cache (will verify via fresh request)")

            status("Requesting path…")
            RNS.Transport.request_path(dest_hash)

            # Wait using BOTH mechanisms:
            # 1. Clock.schedule_interval polls has_path() every 0.25s — catches
            #    path-response packets which update the routing table but do NOT
            #    trigger announce handlers.
            # 2. _PathWatcher handles announce packets (also carry the identity).
            # Whichever fires first cancels the other and continues the chain.

            _path_resolved = [False]
            path_poll      = [None]
            path_timeout   = [None]
            watcher        = [None]

            def _resolve_path():
                if _path_resolved[0]:
                    return
                _path_resolved[0] = True
                if path_poll[0]:
                    Clock.unschedule(path_poll[0])
                    path_poll[0] = None
                if path_timeout[0]:
                    path_timeout[0].cancel()
                    path_timeout[0] = None
                if watcher[0]:
                    try:
                        RNS.Transport.deregister_announce_handler(watcher[0])
                    except Exception:
                        pass
                    watcher[0] = None
                _step_identity(dest_hash)

            def _poll_path(dt):
                if RNS.Transport.has_path(dest_hash):
                    status("Path resolved via path-response")
                    _resolve_path()
                    return False  # stop interval

            def _on_path_timeout(dt):
                path_timeout[0] = None
                if _path_resolved[0]:
                    return
                _path_resolved[0] = True
                if path_poll[0]:
                    Clock.unschedule(path_poll[0])
                if watcher[0]:
                    try:
                        RNS.Transport.deregister_announce_handler(watcher[0])
                    except Exception:
                        pass
                fail(f"[FAIL] Path not found after {LINK_TIMEOUT}s\n"
                     f"  Node: {node_hex}\n"
                     f"  Hub: {NODERAGE_HOST}:{NODERAGE_PORT}\n"
                     f"  Is the server connected to the hub?")

            class _PathWatcher:
                aspect_filter = None
                def received_announce(self_w, destination_hash, announced_identity,
                                      app_data, **kw):
                    if destination_hash == dest_hash:
                        status("Path resolved via announce")
                        _resolve_path()

            watcher[0] = _PathWatcher()
            RNS.Transport.register_announce_handler(watcher[0])
            path_poll[0]    = Clock.schedule_interval(_poll_path, 0.25)
            path_timeout[0] = Clock.schedule_once(_on_path_timeout, LINK_TIMEOUT)

        except Exception as e:
            on_error(f"[EXCEPTION] {e}\n{traceback.format_exc()}")


# ─── UI Widgets ───────────────────────────────────────────────────────────────

class IconButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", BTN_COLOR)
        kwargs.setdefault("color", FG_COLOR)
        kwargs.setdefault("font_size", sp(28))
        kwargs.setdefault("size_hint_x", None)
        kwargs.setdefault("width", dp(52))
        kwargs.setdefault("bold", False)
        kwargs.setdefault("font_name", FONT_PATH)
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)


class AddressBar(BoxLayout):
    def __init__(self, on_navigate, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(48), spacing=dp(4), padding=[dp(4),dp(4)], **kwargs)
        self.on_navigate = on_navigate
        with self.canvas.before:
            Color(*NAV_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)
        self.back_btn    = IconButton(text="←", width=dp(44))
        self.fwd_btn     = IconButton(text="→", width=dp(44))
        self.refresh_btn = IconButton(text="⟳", width=dp(44))
        self.go_btn      = IconButton(text="➜", width=dp(44))
        self.address = TextInput(
            text="", multiline=False, font_size=sp(14),
            background_color=(0.12,0.15,0.20,1),
            foreground_color=FG_COLOR, cursor_color=LNK_COLOR,
            padding=[dp(8), dp(10)],
        )
        for w in (self.back_btn, self.fwd_btn, self.refresh_btn, self.address, self.go_btn):
            self.add_widget(w)
        self.address.bind(on_text_validate=self._go)
        self.go_btn.bind(on_press=self._go)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _go(self, *_):
        self.on_navigate(self.address.text.strip())

    def set_url(self, url):
        self.address.text = url


class StatusBar(Label):
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, height=dp(24), font_size=sp(11),
                         halign="left", color=(0.6,0.6,0.6,1),
                         text_size=(Window.width, None), **kwargs)
        with self.canvas.before:
            Color(0.08, 0.08, 0.10, 1)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self.text_size = (self.width, None)


class LinkButton(Button):
    def __init__(self, label, path, node, on_tap, **kwargs):
        super().__init__(
            text=f"  ▸ {label}",
            background_normal="", background_down="",
            background_color=(0,0,0,0), color=LNK_COLOR,
            halign="left", valign="middle",
            size_hint_y=None, height=dp(34), font_size=sp(14), **kwargs)
        self.path, self.node, self.on_tap = path, node, on_tap
        self.text_size = (None, None)
        self.bind(size=lambda *_: setattr(self, "text_size", (self.width, None)))
        self.bind(on_press=self._pressed)

    def _pressed(self, *_):
        self.background_color = BTN_PRESS
        Clock.schedule_once(lambda *_: setattr(self, "background_color", (0,0,0,0)), 0.15)
        self.on_tap(self.node, self.path)


class NodeDrawer(BoxLayout):
    def __init__(self, on_node_select, **kwargs):
        super().__init__(orientation="vertical", size_hint=(None,None),
                         width=dp(280), height=Window.height, **kwargs)
        self.on_node_select = on_node_select
        self._displayed_hashes = set()

        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)
        Window.bind(size=lambda w, s: setattr(self, "height", s[1]))

        # Header
        hdr = BoxLayout(size_hint_y=None, height=dp(56))
        with hdr.canvas.before:
            Color(*NAV_COLOR)
            hdr._bg = Rectangle(pos=hdr.pos, size=hdr.size)
        hdr.bind(pos=lambda i,v: setattr(i._bg,"pos",v),
                 size=lambda i,v: setattr(i._bg,"size",v))
        ttl = Label(text="Discovered Nodes", halign="left", valign="middle",
                    font_size=sp(18), bold=True)
        ttl.bind(size=lambda i,v: setattr(i,"text_size",i.size))
        hdr.add_widget(ttl)
        close = IconButton(text="×", width=dp(44))
        close.bind(on_press=self._close)
        hdr.add_widget(close)
        self.add_widget(hdr)

        # Node list
        self._scroll = ScrollView(do_scroll_x=False)
        self._node_list = BoxLayout(orientation="vertical", size_hint_y=None,
                                    spacing=dp(2), padding=dp(4))
        self._node_list.bind(minimum_height=self._node_list.setter("height"))
        self._scroll.add_widget(self._node_list)
        self.add_widget(self._scroll)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _close(self, *_):
        if hasattr(self, "parent") and hasattr(self.parent, "toggle_drawer"):
            self.parent.toggle_drawer()

    def add_node(self, node_info):
        nh = node_info.get("hash", "")
        if nh in self._displayed_hashes:
            return
        self._displayed_hashes.add(nh)

        card = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(64), padding=dp(8), spacing=dp(8))
        with card.canvas.before:
            Color(0.12, 0.15, 0.20, 1)
            card._bg = Rectangle(pos=card.pos, size=card.size)
        card.bind(pos=lambda i,v: setattr(i._bg,"pos",v),
                  size=lambda i,v: setattr(i._bg,"size",v))

        info = BoxLayout(orientation="vertical")
        name_lbl = Label(text=node_info.get("name","?"), halign="left", valign="middle",
                         font_size=sp(14), bold=True, color=FG_COLOR, font_name=FONT_PATH)
        name_lbl.bind(size=lambda i,v: setattr(i,"text_size",i.size))
        hash_lbl = Label(text=f"{nh[:16]}…", halign="left", valign="top",
                         font_size=sp(10), color=(0.6,0.6,0.6,1), font_name=FONT_PATH)
        hash_lbl.bind(size=lambda i,v: setattr(i,"text_size",i.size))
        info.add_widget(name_lbl)
        info.add_widget(hash_lbl)

        nav = Button(text="Go →", size_hint_x=None, width=dp(60),
                     background_normal="", background_down="",
                     background_color=BTN_COLOR, color=LNK_COLOR, font_size=sp(12))
        nav.bind(on_press=lambda i, h=nh: self._navigate(h))
        card.add_widget(info)
        card.add_widget(nav)
        self._node_list.add_widget(card)

    def _navigate(self, node_hash):
        if self.on_node_select:
            self.on_node_select(node_hash)
            self._close()

    def clear_nodes(self):
        self._node_list.clear_widgets()
        self._displayed_hashes.clear()


class NavigationDrawer(FloatLayout):
    def __init__(self, content, drawer, **kwargs):
        super().__init__(**kwargs)
        self.drawer = drawer
        self.drawer_open = False
        self._touch_start_x = None
        self.add_widget(content)
        self.add_widget(drawer)
        Clock.schedule_once(lambda dt: setattr(drawer, "pos", (-drawer.width, 0)), 0.1)

    def toggle_drawer(self):
        if self.drawer_open:
            self.drawer_open = False
            Animation(pos=(-self.drawer.width, 0), duration=0.25).start(self.drawer)
        else:
            self.drawer_open = True
            self.drawer.height = self.height
            Animation(pos=(0, 0), duration=0.25).start(self.drawer)

    def on_touch_down(self, touch):
        self._touch_start_x = touch.x
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if self._touch_start_x is not None:
            dx = touch.x - self._touch_start_x
            if dx > dp(50) and self._touch_start_x < dp(30) and not self.drawer_open:
                self.toggle_drawer()
            elif dx < -dp(50) and self.drawer_open:
                self.toggle_drawer()
            elif self.drawer_open and touch.x > self.drawer.width:
                self.toggle_drawer()
        self._touch_start_x = None
        return super().on_touch_up(touch)

    def on_size(self, *_):
        if hasattr(self, "drawer"):
            self.drawer.height = self.height


class PageView(ScrollView):
    def __init__(self, on_link_tap, **kwargs):
        super().__init__(do_scroll_x=False, bar_width=dp(4),
                         bar_color=LNK_COLOR, bar_inactive_color=(0.3,0.3,0.3,0.5),
                         **kwargs)
        self.on_link_tap = on_link_tap
        self.container = BoxLayout(orientation="vertical", size_hint_y=None,
                                   spacing=dp(2), padding=[dp(12), dp(8)])
        self.container.bind(minimum_height=self.container.setter("height"))
        self.add_widget(self.container)
        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    @mainthread
    def show_elements(self, elements):
        self.container.clear_widgets()
        self.scroll_y = 1

        for el in elements:
            t = el.get("type")

            if t == "blank":
                self.container.add_widget(Widget(size_hint_y=None, height=dp(6)))

            elif t == "divider":
                div_char = el.get("char")
                if div_char:
                    lbl = Label(text=div_char * 40, font_size=sp(12), halign="left",
                                valign="top", size_hint_y=None, height=dp(18),
                                color=(0.4, 0.5, 0.6, 1))
                    lbl.bind(width=lambda i,w: setattr(i,"text_size",(w,None)))
                    self.container.add_widget(lbl)
                else:
                    w = Widget(size_hint_y=None, height=dp(1))
                    with w.canvas.before:
                        Color(0.3, 0.4, 0.5, 1)
                        r = Rectangle(pos=w.pos, size=w.size)
                    w.bind(pos=lambda i,v,_r=r: setattr(_r,"pos",v),
                           size=lambda i,v,_r=r: setattr(_r,"size",v))
                    self.container.add_widget(w)

            elif t == "link":
                btn = LinkButton(label=el["label"], path=el["path"],
                                 node=el.get("node",""), on_tap=self.on_link_tap)
                self.container.add_widget(btn)

            elif t == "text":
                heading  = el.get("heading", 0)
                align    = el.get("align", "left")
                segments = el.get("segments", [])

                markup_parts = []
                non_default_bgs = []
                for seg in segments:
                    txt = (seg["text"].replace("&","&amp;")
                                     .replace("[","[[").replace("]","]]"))
                    r,g,b,a = seg["fg"]
                    col = "#{:02x}{:02x}{:02x}".format(int(r*255),int(g*255),int(b*255))
                    p = f"[color={col}]"
                    if seg.get("bold"):      p += "[b]"
                    if seg.get("italic"):    p += "[i]"
                    if seg.get("underline"): p += "[u]"
                    p += txt
                    if seg.get("underline"): p += "[/u]"
                    if seg.get("italic"):    p += "[/i]"
                    if seg.get("bold"):      p += "[/b]"
                    p += "[/color]"
                    markup_parts.append(p)
                    if seg.get("bg") and seg["bg"] != BG_COLOR:
                        non_default_bgs.append(seg["bg"])

                fs = {0:sp(14), 1:sp(20), 2:sp(17), 3:sp(15)}[heading]
                lbl = Label(text="".join(markup_parts), markup=True,
                            font_size=fs, halign=align, valign="top",
                            size_hint_y=None, color=FG_COLOR)
                lbl.bind(
                    width=lambda i,w: setattr(i,"text_size",(w,None)),
                    texture_size=lambda i,ts: setattr(i,"height",ts[1]+dp(2)))
                lbl.text_size = (self.width - dp(24), None)

                if non_default_bgs:
                    bg = non_default_bgs[0]
                    with lbl.canvas.before:
                        Color(*bg)
                        bgr = Rectangle(pos=lbl.pos, size=lbl.size)
                    lbl.bind(pos=lambda i,v,r=bgr: setattr(r,"pos",v),
                             size=lambda i,v,r=bgr: setattr(r,"size",v))

                self.container.add_widget(lbl)

            elif t == "literal":
                safe = el.get("content","").replace("[","[[").replace("]","]]")
                lbl = Label(text=safe, markup=True, font_size=sp(12),
                            halign="left", valign="top", size_hint_y=None,
                            color=(0.7,0.7,0.7,1), font_name=FONT_PATH)
                lbl.bind(
                    width=lambda i,w: setattr(i,"text_size",(w,None)),
                    texture_size=lambda i,ts: setattr(i,"height",ts[1]+dp(2)))
                lbl.text_size = (self.width - dp(24), None)
                self.container.add_widget(lbl)

    @mainthread
    def show_status(self, msg, color=FG_COLOR):
        self.container.clear_widgets()
        lbl = Label(text=msg, markup=True, color=color,
                    halign="center", valign="middle", size_hint=(1,1))
        lbl.bind(size=lambda i,_: setattr(i,"text_size",i.size))
        self.container.add_widget(lbl)


# ─── Main App ─────────────────────────────────────────────────────────────────

class RetiBrowserApp(App):
    title = "RetiBrowser – Reticulum Micron Browser"

    def build(self):
        log("build() starting…")
        try:
            Window.clearcolor = BG_COLOR
            self._history, self._hist_pos = [], -1
            self._current_node = DEFAULT_NODE

            self._rns = ReticulumClient(on_announce_callback=self._on_announce_received)
            self._node_drawer = NodeDrawer(on_node_select=self._navigate_to_node)

            main = BoxLayout(orientation="vertical")
            self._addrbar = AddressBar(on_navigate=self._navigate_url)
            self._addrbar.back_btn.bind(on_press=self._go_back)
            self._addrbar.fwd_btn.bind(on_press=self._go_forward)
            self._addrbar.refresh_btn.bind(on_press=self._refresh)

            menu = IconButton(text="≡", width=dp(44))
            menu.bind(on_press=lambda *_: self._nav_drawer.toggle_drawer())
            self._addrbar.add_widget(menu, index=0)

            self._pageview  = PageView(on_link_tap=self._on_link_tap)
            self._statusbar = StatusBar(text="  Initialising Reticulum…")

            main.add_widget(self._addrbar)
            main.add_widget(self._pageview)
            main.add_widget(self._statusbar)

            self._nav_drawer = NavigationDrawer(content=main, drawer=self._node_drawer)
            Clock.schedule_once(self._init_rns_main, 0.5)
            log("build() complete")
            return self._nav_drawer
        except Exception as e:
            log(f"build error: {e}\n{traceback.format_exc()}")
            raise

    # ── Reticulum init ────────────────────────────────────────────────────────

    def _init_rns_main(self, dt=None):
        try:
            log("Starting Reticulum…")
            self._set_status(f"Connecting to {NODERAGE_HOST}:{NODERAGE_PORT}…")
            self._rns.start(NODERAGE_HOST, NODERAGE_PORT)
            log("Reticulum started")
            # Poll for interface online — start in daemon thread so it can
            # call Clock.schedule_interval on the Kivy main loop safely
            threading.Thread(target=self._begin_iface_poll, daemon=True).start()
        except Exception as e:
            log(f"Init error: {e}\n{traceback.format_exc()}")
            self._set_status(f"Init error: {e}")
            self._pageview.show_status(
                f"[color=#ff5555]Failed to start Reticulum:\n{e}[/color]",
                color=(1,0.33,0.33,1))

    def _begin_iface_poll(self):
        """Schedule the interface poll from a thread (Clock is thread-safe)."""
        self._iface_wait_start = time.time()
        Clock.schedule_interval(self._wait_for_interface, 0.25)

    def _wait_for_interface(self, dt):
        """Called every 0.25s on the Kivy main thread until interface is online."""
        elapsed = time.time() - self._iface_wait_start
        interfaces = getattr(RNS.Transport, "interfaces", [])
        online = [i for i in interfaces if getattr(i, "online", False)]

        if online:
            names = ", ".join(getattr(i,"name","?") for i in online)
            log(f"Interface online after {elapsed:.1f}s: {names}")
            self._set_status("Connected — loading page…")
            Clock.unschedule(self._wait_for_interface)
            self._do_initial_load()
            return False

        if elapsed > 30:
            log("Interface never came online after 30s")
            Clock.unschedule(self._wait_for_interface)
            self._set_status("Connection failed — check network")
            self._pageview.show_status(
                f"[color=#ff5555]Could not connect to {NODERAGE_HOST}:{NODERAGE_PORT} "
                f"after 30s[/color]\n[color=#aaaaaa]Check your internet connection.[/color]",
                color=(1,0.33,0.33,1))
            return False

        if int(elapsed) % 2 == 0 and elapsed > 0:
            self._set_status(f"Connecting to {NODERAGE_HOST}… ({int(elapsed)}s)")

    def _do_initial_load(self, dt=None):
        try:
            self._load_page(DEFAULT_NODE, DEFAULT_PAGE, push_history=True)
        except Exception as e:
            log(f"Initial load error: {e}")
            self._set_status(f"Load error: {e}")

    # ── Announce ──────────────────────────────────────────────────────────────

    def _on_announce_received(self, node_info):
        log(f"Announce: {node_info.get('name','?')} ({node_info.get('hash','')[:8]}…)")
        self._node_drawer.add_node(node_info)

    def _navigate_to_node(self, node_hash):
        self._load_page(node_hash, DEFAULT_PAGE, push_history=True)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate_url(self, url):
        url = url.strip()
        if ":" in url and not url.startswith("/"):
            node, path = url.split(":", 1)
        elif url.startswith("/"):
            node, path = self._current_node, url
        else:
            node, path = url, DEFAULT_PAGE
        self._load_page(node.strip(), path.strip(), push_history=True)

    def _on_link_tap(self, node_hex, page_path):
        self._load_page(node_hex or self._current_node, page_path, push_history=True)

    def _go_back(self, *_):
        if self._hist_pos > 0:
            self._hist_pos -= 1
            n, p = self._history[self._hist_pos]
            self._load_page(n, p, push_history=False)

    def _go_forward(self, *_):
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            n, p = self._history[self._hist_pos]
            self._load_page(n, p, push_history=False)

    def _refresh(self, *_):
        if self._history:
            n, p = self._history[self._hist_pos]
            self._load_page(n, p, push_history=False)

    # ── Page loading ──────────────────────────────────────────────────────────

    def _load_page(self, node_hex, page_path, push_history=True):
        node_hex  = node_hex.strip().lower()
        page_path = page_path.strip()
        if not page_path.startswith("/"):
            page_path = "/page/" + page_path
        self._current_node = node_hex

        Clock.schedule_once(lambda *_: self._addrbar.set_url(f"{node_hex}:{page_path}"), 0)

        if push_history:
            self._history = self._history[:self._hist_pos+1]
            self._history.append((node_hex, page_path))
            self._hist_pos = len(self._history) - 1

        self._update_nav_buttons()
        self._set_status(f"Fetching {page_path} from {node_hex[:8]}…")
        self._pageview.show_status("[color=#aaaaaa]Loading…[/color]")
        self._rns.fetch_page(node_hex, page_path,
                             on_done=self._on_page_done,
                             on_error=self._on_page_error,
                             on_progress=self._on_progress)

    @mainthread
    def _update_nav_buttons(self):
        self._addrbar.back_btn.background_color = \
            BTN_COLOR if self._hist_pos > 0 else (0.08,0.10,0.14,1)
        self._addrbar.fwd_btn.background_color = \
            BTN_COLOR if self._hist_pos < len(self._history)-1 else (0.08,0.10,0.14,1)

    def _on_progress(self, msg):
        self._set_status(f"Downloading… {msg}%" if isinstance(msg, int) else str(msg))

    def _on_page_done(self, content):
        self._set_status("Page loaded")
        self._pageview.show_elements(parse_micron(content))

    def _on_page_error(self, msg):
        self._set_status(f"Error: {msg[:80]}")
        self._pageview.show_status(
            f"[color=#ff5555]{msg}[/color]\n\n"
            "[color=#888888]Check connection and node address.[/color]",
            color=(1,0.33,0.33,1))

    @mainthread
    def _set_status(self, msg):
        self._statusbar.text = f"  {msg}"

    def on_stop(self):
        try:
            with self._rns._lock:
                if self._rns._active_link:
                    self._rns._active_link.teardown()
                    self._rns._active_link = None
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    RetiBrowserApp().run()
