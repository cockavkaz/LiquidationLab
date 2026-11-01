"""Run a real Kivy window on a Windows runner and record reviewable UI evidence."""
import hashlib
import json
import sys
import traceback
from pathlib import Path

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from lab.gui import LiquidationLabApp


OUTPUT = Path("qa-output")
OUTPUT.mkdir(exist_ok=True)


def walk(widget):
    yield widget
    for child in widget.children:
        yield from walk(child)


class ProbeApp(LiquidationLabApp):
    def on_start(self):
        self.evidence = []
        self.finished = False
        Clock.schedule_once(lambda dt: self.stage(self.check_replay), .8)
        Clock.schedule_once(lambda dt: self.stage(self.timeout), 90)

    def stage(self, function):
        if self.finished:
            return
        try:
            function()
        except Exception:
            self.fail(traceback.format_exc())

    def capture(self, name):
        filename = OUTPUT / (name + ".png")
        saved = Window.screenshot(name=str(filename))
        path = Path(saved or filename)
        if not path.is_file() or path.stat().st_size < 1000:
            raise AssertionError(f"Screenshot missing or empty: {path}")
        self.evidence.append({"stage": name, "path": str(path), "bytes": path.stat().st_size})

    def current_popup(self):
        popups = [child for child in Window.children if isinstance(child, Popup)]
        if len(popups) != 1:
            raise AssertionError(f"Expected one visible Popup; got {[type(x).__name__ for x in Window.children]}")
        return popups[0]

    def check_replay(self):
        view = self.root
        assert view.session and len(view.candles) >= 300
        view.seek(view.session.warmup + 5)
        cursor = view.session.cursor
        assert view.filter_note.text and view.price_label.text
        view.step(1)
        assert view.session.cursor == cursor + 1
        view.step(-1)
        assert view.session.cursor == cursor
        self.original_cursor = cursor
        view.toggle_play()
        Clock.schedule_once(lambda dt: self.stage(self.check_playback), .9)

    def check_playback(self):
        view = self.root
        assert view.session.cursor > self.original_cursor
        view.pause()
        self.original_cursor = view.session.cursor
        self.capture("01_replay")
        view.open_diagnostics()
        Clock.schedule_once(lambda dt: self.stage(self.wait_diagnostics), .3)

    def wait_diagnostics(self):
        view = self.root
        if view.busy:
            Clock.schedule_once(lambda dt: self.stage(self.wait_diagnostics), .3)
            return
        assert view.diagnostic_report is not None, view.note.text
        assert view.session.cursor == self.original_cursor
        popup = self.current_popup()
        assert "Диагностика" in popup.title
        text = "\n".join(x.text for x in walk(popup) if isinstance(x, Label))
        assert "ПРИЧИНЫ ОТКЛОНЕНИЙ" in text
        assert "стоп/ATR" in text
        assert "\\n" not in text, "Literal backslash-n visible in diagnostics"
        Clock.schedule_once(lambda dt: self.stage(self.check_diagnostic_popup), .3)

    def check_diagnostic_popup(self):
        popup = self.current_popup()
        self.capture("02_diagnostics_top")
        scrolls = [x for x in walk(popup) if isinstance(x, ScrollView)]
        assert scrolls
        scrolls[0].scroll_y = 0
        Clock.schedule_once(lambda dt: self.stage(self.finish_diagnostics), .3)

    def finish_diagnostics(self):
        self.capture("03_diagnostics_bottom")
        self.current_popup().dismiss()
        assert self.root.session.cursor == self.original_cursor
        self.root.validate_oos()
        Clock.schedule_once(lambda dt: self.stage(self.wait_validation), .3)

    def wait_validation(self):
        view = self.root
        if view.busy:
            Clock.schedule_once(lambda dt: self.stage(self.wait_validation), .3)
            return
        assert view.validation_report is not None, view.note.text
        popup = self.current_popup()
        text = "\n".join(x.text for x in walk(popup) if isinstance(x, Label))
        assert "ФИЛЬТРЫ HOLDOUT" in text
        assert "\\n" not in text, "Literal backslash-n visible in validation"
        Clock.schedule_once(lambda dt: self.stage(self.check_validation_popup), .3)

    def check_validation_popup(self):
        self.capture("04_validation")
        view = self.root
        view.export_oos()
        folder = max(Path("reports").glob("validation-*"), key=lambda p: p.stat().st_mtime)
        for group in ("training", "holdout", "baseline_holdout"):
            for suffix in ("diagnostic_gates.csv", "trade_risk.csv"):
                assert (folder / (group + "_" + suffix)).is_file()
        assert (folder / "validation.json").is_file()
        self.current_popup().dismiss()
        view.csv_path.text = str(OUTPUT / "sample.csv")
        original_len = len(view.candles)
        view.save_csv()
        assert (OUTPUT / "sample.csv").is_file(), view.note.text
        view.load_csv()
        assert len(view.candles) == original_len and view.source == "Импорт CSV"
        self.capture("05_csv_reloaded")
        self.finish(True, None)

    def timeout(self):
        raise TimeoutError("UI probe did not finish within 90 seconds")

    def fail(self, reason):
        self.finish(False, reason)

    def finish(self, success, reason):
        if success:
            fingerprints = {
                hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
                for item in self.evidence
            }
            if len(self.evidence) != 5 or len(fingerprints) < 2:
                success = False
                reason = "Window screenshots are identical; visible rendering is unverified"
        self.finished = True
        status = {"success": success, "error": reason, "evidence": self.evidence,
                  "window_size": list(Window.size)}
        (OUTPUT / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print("KIVY_PROBE_RESULT", json.dumps(status, ensure_ascii=True), flush=True)
        self.stop()


if __name__ == "__main__":
    try:
        app = ProbeApp()
        app.run()
        sys.exit(0 if getattr(app, "finished", False) and
                 json.loads((OUTPUT / "status.json").read_text(encoding="utf-8"))["success"] else 1)
    except Exception:
        reason = traceback.format_exc()
        (OUTPUT / "status.json").write_text(json.dumps({"success": False, "error": reason},
                                                       ensure_ascii=False, indent=2), encoding="utf-8")
        print("KIVY_PROBE_FATAL", reason, flush=True)
        sys.exit(1)
