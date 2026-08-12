"""Phase 8.5: startup sequence."""

import io
import time
import unittest

from callshield.ui.app import AppContext
from callshield.ui.screens import startup as startup_mod
from tests._common import IsolatedEnv
from tests._ui import ScriptedContext, caps, emoji_characters, plain


class TestUIStartup(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    # ------------------------------------------------------------- sequence
    def test_nine_named_stages(self):
        self.assertEqual(len(startup_mod.STAGE_KEYS), 9)
        self.assertEqual(startup_mod.STAGE_KEYS[0], "startup.init")
        self.assertEqual(startup_mod.STAGE_KEYS[-1], "startup.interface")

    def test_startup_probes_real_backend(self):
        ctx = ScriptedContext(self.cfg)
        report = startup_mod.run_startup(ctx, animate=False)
        self.assertIn(report.daemon_state, ("RUNNING", "STOPPED", "STALE", "UNKNOWN"))
        self.assertTrue(report.database_ok)
        self.assertTrue(report.engine_ok)
        self.assertTrue(report.intelligence_ok)
        self.assertEqual(report.policy, self.cfg.screening_policy)

    def test_startup_is_short(self):
        ctx = ScriptedContext(self.cfg)
        started = time.monotonic()
        startup_mod.run_startup(ctx, animate=False)
        self.assertLess(time.monotonic() - started, startup_mod.MAX_DURATION + 3.0)

    def test_startup_never_raises_when_backend_fails(self):
        class BrokenBackend:
            def daemon_state(self):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                def call(*args, **kwargs):
                    raise RuntimeError("boom")

                return call

        ctx = ScriptedContext(self.cfg)
        ctx.backend = BrokenBackend()
        report = startup_mod.run_startup(ctx, animate=False)
        self.assertTrue(report.warnings)
        self.assertFalse(report.database_ok)

    # --------------------------------------------------------------- frames
    def test_frame_lists_every_stage(self):
        ctx = ScriptedContext(self.cfg)
        text = plain(startup_mod.render_frame(ctx.surface, ctx.t, 3, None, "0.8.0"))
        for key in startup_mod.STAGE_KEYS:
            self.assertIn(ctx.t(key), text)

    def test_frame_has_no_emoji(self):
        ctx = ScriptedContext(self.cfg)
        text = plain(startup_mod.render_frame(ctx.surface, ctx.t, 9, None, "0.8.0"))
        self.assertEqual(emoji_characters(text), [])

    def test_summary_shows_offline_hint_and_no_android_claim(self):
        ctx = ScriptedContext(self.cfg)
        report = startup_mod.run_startup(ctx, animate=False)
        report.daemon_state = "STOPPED"
        text = plain(startup_mod.summary_lines(ctx.surface, ctx.t, report))
        self.assertIn("OFFLINE", text)
        self.assertIn("NOT VERIFIED", text)

    def test_animation_disabled_produces_no_output(self):
        out = io.StringIO()
        ctx = AppContext(self.cfg, caps=caps(interactive=False), stdout=out)
        startup_mod.run_startup(ctx, animate=False)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
