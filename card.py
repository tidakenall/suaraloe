"""
card.py — Always-on-top, translucent, draggable lyrics card.

Compact frosted-glass panel showing the previous / current / next lyric.
Long lines wrap (never truncated) and the card grows to fit. When the lyric
advances, the lines glide up Apple-Music style. Drag anywhere on the card to
move it. Drag the bottom-right grip to resize: sideways sets the width, and
dragging it up past a point snaps the card into a slim one-line strip that
shows only the current lyric (drag down to get the full card back).
Position, width and slim/full are remembered.
"""
from __future__ import annotations
import math
import AppKit
import Quartz
from Foundation import NSMakeRect

DEFAULT_W   = 300.0
MAX_W       = 560.0
MIN_W       = 160.0
SNAP_PX     = 24.0        # vertical drag needed to switch full <-> slim
PAD_X       = 16.0
PAD_Y       = 11.0
PAD_Y_SLIM  = 7.0
SLIM_FONT   = (10.0, 16.0)  # slim line shrinks within this range to fit one row
GAP         = 5.0
GRIP        = 14.0
RADIUS      = 16.0
BG_ALPHA    = 0.55        # glass opacity; text stays fully crisp on top
ANIM_SECS   = 0.45
SLIDE_PX    = 14.0
LIGHT_ON    = 0.58        # backdrop luminance above this -> dark text
LIGHT_OFF   = 0.42        # ...and below this -> white text (hysteresis)

# Per-slot (prev, current, next): font size, weight, text alpha
_SLOTS = [
    (13.0, AppKit.NSFontWeightMedium, 0.45),
    (16.0, AppKit.NSFontWeightBold,   1.00),
    (13.0, AppKit.NSFontWeightMedium, 0.45),
]
N = len(_SLOTS)


class _FlippedView(AppKit.NSView):
    """Top-left origin, so label offsets don't depend on the window height."""
    def isFlipped(self):
        return True


class _ResizeGrip(AppKit.NSView):
    """Bottom-right handle: horizontal drag = width, vertical drag = slim/full."""
    def initWithCard_(self, card):
        self = AppKit.NSView.initWithFrame_(self, NSMakeRect(0, 0, GRIP, GRIP))
        if self is None:
            return None
        self.card = card
        self.start = None
        return self

    def mouseDownCanMoveWindow(self):
        return False

    def resetCursorRects(self):
        cursor = AppKit.NSCursor.crosshairCursor()
        try:   # diagonal window-resize cursor (private but long-standing)
            cursor = AppKit.NSCursor._windowResizeNorthWestSouthEastCursor()
        except Exception:
            pass
        self.addCursorRect_cursor_(self.bounds(), cursor)

    def mouseDown_(self, event):
        m = AppKit.NSEvent.mouseLocation()
        f = self.card._window.frame()
        self.start = (m.x, m.y, f.size.width, f.size.height)

    def mouseDragged_(self, event):
        if self.start is not None:
            x0, y0, w0, h0 = self.start
            m = AppKit.NSEvent.mouseLocation()
            # Screen y grows upward; dragging down makes the card taller.
            self.card.resize_to(w0 + m.x - x0, h0 + y0 - m.y, h0)

    def mouseUp_(self, event):
        self.start = None
        self.card.save_size()

    def drawRect_(self, rect):
        color = _text_color(self.card._light_bg).colorWithAlphaComponent_(0.35)
        color.setStroke()
        for inset in (4.0, 8.0):
            path = AppKit.NSBezierPath.bezierPath()
            path.setLineWidth_(1.2)
            path.moveToPoint_((GRIP - 3, inset))         # flipped: y grows downward
            path.lineToPoint_((inset, GRIP - 3))
            path.stroke()


def _text_color(light_bg: bool) -> AppKit.NSColor:
    return (AppKit.NSColor.colorWithWhite_alpha_(0.08, 1.0) if light_bg
            else AppKit.NSColor.whiteColor())


def _label(size: float, weight: float, alpha: float) -> AppKit.NSTextField:
    lbl = AppKit.NSTextField.wrappingLabelWithString_("")
    lbl.setSelectable_(False)
    lbl.setAlignment_(AppKit.NSTextAlignmentCenter)
    lbl.setFont_(AppKit.NSFont.systemFontOfSize_weight_(size, weight))
    lbl.setTextColor_(AppKit.NSColor.whiteColor())
    lbl.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
    lbl.setMaximumNumberOfLines_(0)
    lbl.setAlphaValue_(alpha)
    return lbl


class LyricsCard:
    def __init__(self) -> None:
        self._window: AppKit.NSPanel | None = None
        self._rows: list[AppKit.NSTextField] = []
        self._ghost: AppKit.NSTextField | None = None
        self._grip: _ResizeGrip | None = None
        self._lines: list[str] = [""] * N        # as requested by the app
        self._shown_lines: list[str] = [""] * N  # after slim filtering
        self._width = DEFAULT_W
        self._slim = bool(AppKit.NSUserDefaults.standardUserDefaults().boolForKey_("cardSlim"))
        self._frames: list[tuple[float, float]] = [(PAD_Y, 0.0)] * N   # (y, h)
        self._shown = False
        self._light_bg = False
        self._mode = "auto"        # "auto" | "dark" (dark text) | "light" (white text)
        self._setup()
        # Sampling the backdrop needs Screen Recording access; ask once.
        self._can_sample = bool(Quartz.CGPreflightScreenCaptureAccess())
        if not self._can_sample:
            Quartz.CGRequestScreenCaptureAccess()

    def _setup(self) -> None:
        vis = AppKit.NSScreen.mainScreen().visibleFrame()
        h0 = PAD_Y * 2 + 20
        x = vis.origin.x + vis.size.width - DEFAULT_W - 20
        y = vis.origin.y + 20

        win = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, DEFAULT_W, h0),
            128,   # NSWindowStyleMaskNonactivatingPanel | Borderless
            2,     # NSBackingStoreBuffered
            False,
        )
        win.setLevel_(AppKit.NSStatusWindowLevel)       # above normal windows
        win.setFloatingPanel_(True)
        win.setHidesOnDeactivate_(False)
        win.setCollectionBehavior_(
            1      # CanJoinAllSpaces
            | 16   # Stationary
            | 256  # FullScreenAuxiliary
        )
        win.setOpaque_(False)
        win.setBackgroundColor_(AppKit.NSColor.clearColor())
        win.setHasShadow_(False)                        # subtle: no drop shadow
        win.setMovableByWindowBackground_(True)
        win.setAppearance_(
            AppKit.NSAppearance.appearanceNamed_("NSAppearanceNameVibrantDark")
        )

        root = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, DEFAULT_W, h0))
        root.setWantsLayer_(True)
        win.setContentView_(root)

        vev = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, DEFAULT_W, h0)
        )
        vev.setMaterial_(6)         # Popover — follows the window's appearance
        vev.setBlendingMode_(0)     # BehindWindow — blurs what's under the card
        vev.setState_(1)            # Active even when app isn't frontmost
        vev.setAutoresizingMask_(18)  # width + height sizable
        vev.setAlphaValue_(BG_ALPHA)
        vev.setWantsLayer_(True)
        vev.layer().setCornerRadius_(RADIUS)
        vev.layer().setMasksToBounds_(True)
        root.addSubview_(vev)

        for size, weight, alpha in _SLOTS:
            lbl = _label(size, weight, alpha)
            lbl.setFrame_(NSMakeRect(PAD_X, PAD_Y, DEFAULT_W - PAD_X * 2, 0))
            root.addSubview_(lbl)
            self._rows.append(lbl)

        ghost = _label(*_SLOTS[0])
        ghost.setAlphaValue_(0.0)
        root.addSubview_(ghost)

        grip = _ResizeGrip.alloc().initWithCard_(self)
        grip.setFrame_(NSMakeRect(DEFAULT_W - GRIP - 3, h0 - GRIP - 3, GRIP, GRIP))
        grip.setAutoresizingMask_(1 | 8)   # stick to the bottom-right corner
        root.addSubview_(grip)

        self._window = win
        self._ghost  = ghost
        self._grip   = grip

        # Restore last position and width (no-op the first time).
        win.setFrameAutosaveName_("LyricsCardCompact")
        self._width = min(max(win.frame().size.width, MIN_W), MAX_W)

    @property
    def _inner_w(self) -> float:
        return self._width - PAD_X * 2

    def resize_to(self, width: float, height: float, start_height: float) -> None:
        """Called while dragging the grip. Height only chooses slim vs. full;
        the actual height always follows the text so nothing gets cut off."""
        width = min(max(width, MIN_W), MAX_W)
        slim = self._slim
        if not slim and height < start_height - SNAP_PX:
            slim = True
        elif slim and height > start_height + SNAP_PX:
            slim = False
        if abs(width - self._width) < 0.5 and slim == self._slim:
            return
        animate = slim != self._slim
        self._width, self._slim = width, slim
        self._layout(self._lines, "fade" if animate else "none", force=True)

    def save_size(self) -> None:
        AppKit.NSUserDefaults.standardUserDefaults().setBool_forKey_(self._slim, "cardSlim")

    def _fit_slim_font(self, text: str) -> AppKit.NSFont:
        """Largest bold font (within SLIM_FONT) that fits the text on one row."""
        lo, hi = SLIM_FONT
        font = AppKit.NSFont.systemFontOfSize_weight_(hi, AppKit.NSFontWeightBold)
        width = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            text, {AppKit.NSFontAttributeName: font}).size().width
        size = hi if width <= self._inner_w else max(lo, math.floor(hi * self._inner_w / width * 2) / 2)
        return AppKit.NSFont.systemFontOfSize_weight_(size, AppKit.NSFontWeightBold)

    def _measure(self, lbl: AppKit.NSTextField, text: str) -> float:
        if not text:
            return 0.0
        lbl.setStringValue_(text)
        size = lbl.cell().cellSizeForBounds_(NSMakeRect(0, 0, self._inner_w, 10000))
        return float(math.ceil(size.height))

    def set_lines(self, lines: list[str], mode: str = "none") -> None:
        """
        lines: [previous, current, next]; "" hides a slot.
        mode:  "advance" glide up (lyric moved to the next line),
               "fade"    cross-fade in (new song / seek / status text),
               "none"    update in place.
        """
        if lines == self._lines:
            return
        self._lines = list(lines)
        self._layout(lines, mode)

    def _layout(self, lines: list[str], mode: str, force: bool = False) -> None:
        if self._window is None:
            return
        if self._slim:
            lines = ["", lines[1], ""]
        if lines == self._shown_lines and not force:
            return

        inner_w    = self._inner_w
        old_lines  = self._shown_lines
        old_frames = self._frames
        old_font   = self._rows[1].font()
        self._shown_lines = list(lines)
        pad = PAD_Y_SLIM if self._slim else PAD_Y

        # Slim: shrink the current line to fit one row; full: normal size.
        cur = self._rows[1]
        cur.setFont_(self._fit_slim_font(lines[1]) if self._slim and lines[1]
                     else AppKit.NSFont.systemFontOfSize_weight_(*_SLOTS[1][:2]))

        # Measure with the final text and lay out top-down.
        frames: list[tuple[float, float]] = []
        y = pad
        for lbl, text in zip(self._rows, lines):
            h = self._measure(lbl, text)
            frames.append((y, h))
            y += h + (GAP if h else 0.0)
        content = max(y - GAP, pad) if any(f[1] for f in frames) else pad
        height = content + pad
        self._frames = frames

        # Window grows/shrinks from its top edge.
        cur = self._window.frame()
        top = cur.origin.y + cur.size.height
        new_win = NSMakeRect(cur.origin.x, top - height, self._width, height)

        finals = [_SLOTS[k][2] for k in range(N)]
        advance = mode == "advance"

        # Starting state for each label (final text/frame is already known).
        for k, lbl in enumerate(self._rows):
            fy, fh = frames[k]
            if advance:
                # This text used to sit one slot lower: start there, then rise.
                if k + 1 < N and old_frames[k + 1][1] > 0 and old_lines[k + 1] == lines[k]:
                    sy, sa = old_frames[k + 1][0], finals[k + 1]
                else:
                    sy, sa = fy + SLIDE_PX, 0.0
            elif mode == "fade":
                sy, sa = fy, 0.0
            else:
                sy, sa = fy, finals[k]
            lbl.setStringValue_(lines[k])
            lbl.setFrame_(NSMakeRect(PAD_X, sy, inner_w, fh))
            lbl.setAlphaValue_(sa if lines[k] else 0.0)

        # The line that scrolled off the top drifts up and fades out
        # (in slim mode that's the previous current line).
        ghost = self._ghost
        g = 1 if self._slim else 0
        if advance and old_lines[g] and old_frames[g][1] > 0:
            ghost.setFont_(old_font if g == 1 else self._rows[0].font())
            ghost.setStringValue_(old_lines[g])
            ghost.setFrame_(NSMakeRect(PAD_X, old_frames[g][0], inner_w, old_frames[g][1]))
            ghost.setAlphaValue_(finals[g])
        else:
            ghost.setAlphaValue_(0.0)

        if mode == "none":
            self._window.setFrame_display_(new_win, True)
            return

        def run(ctx):
            ctx.setDuration_(ANIM_SECS)
            ctx.setAllowsImplicitAnimation_(True)
            self._window.animator().setFrame_display_(new_win, True)
            for k, lbl in enumerate(self._rows):
                fy, fh = frames[k]
                lbl.animator().setFrame_(NSMakeRect(PAD_X, fy, inner_w, fh))
                lbl.animator().setAlphaValue_(finals[k] if lines[k] else 0.0)
            if advance:
                gy, gh = old_frames[g]
                ghost.animator().setFrame_(
                    NSMakeRect(PAD_X, gy - SLIDE_PX, inner_w, gh))
                ghost.animator().setAlphaValue_(0.0)

        AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(run, None)

    # ------------------------------------------------------------------ #
    #  Adaptive colour: white text on dark backdrops, dark text on light  #
    # ------------------------------------------------------------------ #

    def _backdrop_luminance(self) -> float | None:
        """Average luminance (0-1) of whatever is on screen behind the card."""
        win = self._window
        if win is None or not win.isVisible():
            return None
        f = win.frame()
        screen_h = AppKit.NSScreen.screens()[0].frame().size.height
        rect = Quartz.CGRectMake(f.origin.x, screen_h - (f.origin.y + f.size.height),
                                 f.size.width, f.size.height)
        img = Quartz.CGWindowListCreateImage(
            rect,
            Quartz.kCGWindowListOptionOnScreenBelowWindow,   # excludes the card itself
            win.windowNumber(),
            Quartz.kCGWindowImageNominalResolution,
        )
        if img is None:
            return None
        rep = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(img)
        w, h = int(rep.pixelsWide()), int(rep.pixelsHigh())
        if w < 2 or h < 2:
            return None
        srgb = AppKit.NSColorSpace.sRGBColorSpace()
        total, n = 0.0, 0
        for gy in range(4):
            for gx in range(8):
                c = rep.colorAtX_y_(int((gx + 0.5) * w / 8), int((gy + 0.5) * h / 4))
                c = c.colorUsingColorSpace_(srgb) if c is not None else None
                if c is None:
                    continue
                total += (0.2126 * c.redComponent() + 0.7152 * c.greenComponent()
                          + 0.0722 * c.blueComponent())
                n += 1
        return total / n if n else None

    @staticmethod
    def _system_is_light() -> bool:
        app = AppKit.NSApplication.sharedApplication()
        name = app.effectiveAppearance().bestMatchFromAppearancesWithNames_(
            ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"])
        return name == "NSAppearanceNameAqua"

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.adapt()

    def adapt(self) -> None:
        """Pick text/glass tint from the backdrop; call a few times a second."""
        if self._window is None:
            return
        if self._mode != "auto":
            self._apply_theme(self._mode == "dark")
            return
        if not self._can_sample:
            # Permission may be granted while we're running.
            self._can_sample = bool(Quartz.CGPreflightScreenCaptureAccess())
        light = self._light_bg
        lum = self._backdrop_luminance() if self._can_sample else None
        if lum is None:
            light = self._system_is_light()
        elif lum > LIGHT_ON:
            light = True
        elif lum < LIGHT_OFF:
            light = False
        self._apply_theme(light)

    def _apply_theme(self, light: bool) -> None:
        if light == self._light_bg and self._window.appearance() is not None:
            return
        self._light_bg = light
        self._window.setAppearance_(AppKit.NSAppearance.appearanceNamed_(
            "NSAppearanceNameAqua" if light else "NSAppearanceNameVibrantDark"))
        color = _text_color(light)
        for lbl in (*self._rows, self._ghost):
            lbl.setTextColor_(color)
        self._grip.setNeedsDisplay_(True)

    def show(self) -> None:
        if not self._shown and self._window is not None:
            self._window.orderFrontRegardless()
            self._shown = True
            self.adapt()

    def hide(self) -> None:
        if self._shown and self._window is not None:
            self._window.orderOut_(None)
            self._shown = False
            self._lines = [""] * N   # next show re-fades in
            self._shown_lines = [""] * N

    @property
    def is_shown(self) -> bool:
        return self._shown
