"""Phase 8.5: screen content, real backend values and about page."""

import unittest

from callshield.ui.navigation import keys as K
from callshield.ui.screens import REGISTRY, about as about_mod
from tests._common import IsolatedEnv, run_cli
from tests._ui import caps, emoji_characters, make_app, plain, render


class UIScreenCase(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def screen(self, key, **kwargs):
        ctx, app = make_app(self.cfg, screen_key=key, **kwargs)
        return ctx, app, render(app)


class TestDashboard(UIScreenCase):
    def test_four_sections(self):
        ctx, app, text = self.screen("dashboard", caps=caps(width=100, height=70))
        for key in ("main.section.system", "main.section.threat",
                    "main.section.intelligence", "main.section.actions"):
            self.assertIn(ctx.t(key), text)

    def test_values_come_from_the_backend(self):
        run_cli(self.cfg, "scan", "+919876500001")
        run_cli(self.cfg, "scan", "+919876500002")
        ctx, app, text = self.screen("dashboard", caps=caps(width=100, height=70))
        metrics = ctx.backend.event_metrics()
        self.assertTrue(metrics.ok)
        self.assertGreaterEqual(metrics.get("total"), 2)
        self.assertIn(str(metrics.get("total")), text)

    def test_offline_daemon_shows_start_action(self):
        ctx, app, text = self.screen("dashboard", caps=caps(width=100, height=70))
        self.assertIn(ctx.t("main.action.start_daemon"), text)
        self.assertIn("OFFLINE", text)

    def test_never_claims_android_screening(self):
        ctx, app, text = self.screen("dashboard", caps=caps(width=100, height=70))
        self.assertIn("NOT VERIFIED", text)


class TestScanCenter(UIScreenCase):
    def test_menu_entries(self):
        ctx, app, text = self.screen("scan")
        for key in ("scan.basic", "scan.advanced", "scan.history", "scan.compare"):
            self.assertIn(ctx.t(key), text)

    def test_basic_scan_uses_the_real_engine(self):
        ctx, app = make_app(self.cfg, screen_key="scan",
                            answers=["+919876500123"],
                            caps=caps(width=100, height=70))
        app.handle_key("1")
        text = render(app)
        self.assertEqual(app.stack.depth, 2)
        # The masked number and a real verdict from the engine are shown.
        self.assertIn("0123", text)
        self.assertNotIn("+919876500123", text)
        self.assertIn(ctx.t("common.risk"), text)

    def test_invalid_number_is_reported(self):
        ctx, app = make_app(self.cfg, screen_key="scan", answers=["not-a-number"])
        app.handle_key("1")
        text = render(app)
        self.assertIn("ERROR", text)
        self.assertIn("Invalid phone number", text)

    def test_cancelled_prompt_returns_to_the_menu(self):
        ctx, app = make_app(self.cfg, screen_key="scan", answers=[None])
        app.handle_key("1")
        self.assertEqual(app.stack.depth, 1)
        self.assertIn(ctx.t("prompt.empty_input"), render(app))

    def test_advanced_scan_has_every_required_section(self):
        ctx, app = make_app(self.cfg, screen_key="scan",
                            answers=["+919876500124"],
                            caps=caps(width=110, height=200))
        app.handle_key("2")
        text = render(app)
        for key in (
            "scan.section.identity",
            "scan.section.reputation",
            "scan.section.signals",
            "scan.section.confidence",
            "scan.section.behavior",
            "scan.section.trend",
            "scan.section.trust",
            "scan.section.policy",
            "scan.section.screening",
            "scan.section.history",
        ):
            self.assertIn(ctx.t(key), text)


class TestMonitor(UIScreenCase):
    def test_waiting_state_when_no_events(self):
        ctx, app, text = self.screen("monitor")
        self.assertIn(ctx.t("monitor.waiting"), text)

    def test_shows_real_events(self):
        run_cli(self.cfg, "scan", "+919876500055")
        ctx, app, text = self.screen("monitor", caps=caps(width=100, height=60))
        events = ctx.backend.recent_events(limit=5)
        self.assertTrue(events.ok)
        self.assertTrue(events.data)
        self.assertIn("0055", text)
        self.assertNotIn("+919876500055", text)

    def test_offline_daemon_is_labelled_not_hidden(self):
        ctx, app, text = self.screen("monitor")
        self.assertIn(ctx.t("monitor.daemon_offline"), text)

    def test_refresh_key_does_not_block(self):
        ctx, app, _text = self.screen("monitor")
        self.assertTrue(app.handle_key("r"))


class TestDaemonScreen(UIScreenCase):
    def test_lists_every_control(self):
        ctx, app, text = self.screen("daemon", caps=caps(width=100, height=60))
        for key in ("daemon.status", "daemon.start", "daemon.stop",
                    "daemon.restart", "daemon.health", "daemon.metrics"):
            self.assertIn(ctx.t(key), text)

    def test_stop_requires_confirmation(self):
        ctx, app = make_app(self.cfg, screen_key="daemon", answers=[""])
        item = app.current.menu.by_key("stop")
        app.current.activate(item)
        self.assertIn("[y/N]", ctx.asked[-1])
        self.assertIn(ctx.t("common.cancelled"), render(app))


class TestScreeningScreen(UIScreenCase):
    def test_entries_and_android_disclaimer(self):
        ctx, app, text = self.screen("screening", caps=caps(width=100, height=60))
        for key in ("screening.status", "screening.health", "screening.metrics",
                    "screening.mode", "screening.enable", "screening.disable"):
            self.assertIn(ctx.t(key), text)
        self.assertIn("NOT VERIFIED", text)

    def test_active_mode_is_routed_through_the_cli_confirmation(self):
        ctx, app = make_app(self.cfg, screen_key="screening")
        item = app.current.menu.by_key("active")
        self.assertIsNotNone(item)
        # The CLI handler owns the ACTIVE confirmation prompt; the UI must not
        # reimplement it.
        import inspect

        from callshield.ui.screens import screening as screening_mod

        source = inspect.getsource(screening_mod)
        self.assertIn("run_with_terminal", source)
        self.assertIn("screening_mode_active", source)


class TestPolicyScreen(UIScreenCase):
    def test_lists_policies_and_emergency_state(self):
        ctx, app, text = self.screen("policy", caps=caps(width=100, height=70))
        for key in ("policy.current", "policy.test", "policy.emergency"):
            self.assertIn(ctx.t(key), text)
        for name in ("RELAXED", "BALANCED", "STRICT"):
            self.assertIn(name, text)

    def test_simulation_does_not_change_configuration(self):
        from callshield.config import load_config

        before = load_config()
        ctx, app = make_app(self.cfg, screen_key="policy", answers=["90", "88"])
        app.current.activate(app.current.menu.by_key("test"))
        after = load_config()
        self.assertEqual(before.screening_policy, after.screening_policy)
        self.assertEqual(before.screening_mode, after.screening_mode)
        self.assertEqual(before.screening_enabled, after.screening_enabled)

    def test_emergency_engagement_requires_confirmation(self):
        ctx, app = make_app(self.cfg, screen_key="policy", answers=[""])
        app.current.activate(app.current.menu.by_key("emergency"))
        self.assertIn("[y/N]", ctx.asked[-1])


class TestBlockAndReportCenters(UIScreenCase):
    def test_block_center_shows_lists(self):
        run_cli(self.cfg, "block", "+919876500077", "--reason", "spam")
        ctx, app, text = self.screen("blocks", caps=caps(width=100, height=70))
        self.assertIn(ctx.t("blocks.blacklist"), text)
        self.assertIn(ctx.t("blocks.whitelist"), text)

    def test_report_center_stores_locally(self):
        from callshield.database import Database

        ctx, app = make_app(self.cfg, screen_key="reports",
                            answers=["+919876500088", "scam call", "y"])
        app._apply(app.current.activate(app.current.menu.by_key("submit")))
        db = Database(self.cfg.database_path)
        try:
            self.assertEqual(db.count_reports("+919876500088"), 1)
        finally:
            db.close()
        self.assertIn(ctx.t("reports.saved"), render(app))

    def test_report_cancelled_stores_nothing(self):
        from callshield.database import Database

        ctx, app = make_app(self.cfg, screen_key="reports",
                            answers=["+919876500099", "reason", ""])
        app.current.activate(app.current.menu.by_key("submit"))
        db = Database(self.cfg.database_path)
        try:
            self.assertEqual(db.count_reports("+919876500099"), 0)
        finally:
            db.close()


class TestHistoryScreen(UIScreenCase):
    def test_paging_keys(self):
        for index in range(25):
            run_cli(self.cfg, "scan", "+91987650%04d" % index)
        ctx, app = make_app(self.cfg, screen_key="history")
        action = app.current.activate(app.current.menu.by_key("events"))
        app._apply(action)
        listing = app.current
        self.assertGreater(listing.pager.pages, 1)
        listing.handle(K.PAGE_DOWN)
        self.assertEqual(listing.pager.page, 2)
        listing.handle(K.PAGE_UP)
        self.assertEqual(listing.pager.page, 1)

    def test_queries_are_bounded(self):
        from callshield.ui.screens import history as history_mod

        self.assertLessEqual(history_mod.QUERY_LIMIT, 1000)

    def test_numbers_are_masked(self):
        run_cli(self.cfg, "scan", "+919876500058")
        ctx, app = make_app(self.cfg, screen_key="history",
                            caps=caps(width=110, height=60))
        app._apply(app.current.activate(app.current.menu.by_key("events")))
        text = render(app)
        self.assertNotIn("+919876500058", text)
        self.assertIn("*", text)


class TestDiagnosticsScreen(UIScreenCase):
    def test_runs_doctor_read_only(self):
        ctx, app, text = self.screen("diagnostics", caps=caps(width=100, height=60))
        self.assertIn(ctx.t("diagnostics.title"), text)
        for word in ("HEALTHY", "WARNING", "ERROR", "NOT VERIFIED"):
            if word in text:
                break
        else:  # pragma: no cover - the report always carries a status
            self.fail("no diagnostic status word rendered")

    def test_offers_no_repair_action(self):
        import inspect

        from callshield.ui.screens import diagnostics as diag_mod

        self.assertNotIn("repair=True", inspect.getsource(diag_mod))


class TestAboutScreen(UIScreenCase):
    def test_exact_content(self):
        ctx, app, text = self.screen("about", caps=caps(width=100, height=60))
        self.assertIn("CALLSHIELD", text)
        self.assertIn(ctx.version, text)
        self.assertIn("Sarthak Bharambe", text)
        self.assertIn("CyberVault", text)
        self.assertIn("@cyber_vault123", text)
        self.assertIn("Termux / Linux", text)
        self.assertIn("MIT", text)

    def test_version_is_0_8_0(self):
        ctx, _app, _text = self.screen("about")
        self.assertEqual(ctx.version, "0.8.0")

    def test_local_first_architecture_statement(self):
        ctx, app, text = self.screen("about", caps=caps(width=100, height=60))
        self.assertIn("Local-first", text)
        self.assertIn("network communication", text.replace("\n", " "))

    def test_no_android_app_claim_and_no_fake_links(self):
        ctx, app, text = self.screen("about", caps=caps(width=100, height=60))
        lowered = text.lower()
        self.assertNotIn("http://", lowered)
        self.assertNotIn("https://", lowered)
        self.assertNotIn("android app", lowered)

    def test_constants(self):
        self.assertEqual(about_mod.AUTHOR, "Sarthak Bharambe")
        self.assertEqual(about_mod.YOUTUBE, "CyberVault")
        self.assertEqual(about_mod.INSTAGRAM, "@cyber_vault123")
        self.assertEqual(about_mod.PLATFORM, "Termux / Linux")
        self.assertEqual(about_mod.LICENSE, "MIT")


class TestPresentation(UIScreenCase):
    def test_no_emoji_on_any_screen(self):
        ctx, _app = make_app(self.cfg)
        for key in REGISTRY:
            screen = ctx.make_screen(key)
            screen.on_enter()
            text = plain(screen.body(ctx.surface))
            self.assertEqual(emoji_characters(text), [], key)

    def test_status_words_are_used_not_colour_alone(self):
        ctx, app, text = self.screen("dashboard", caps=caps(width=100, height=70))
        self.assertTrue(
            any(word in text for word in
                ("READY", "OFFLINE", "STOPPED", "DISABLED", "NOT VERIFIED"))
        )

    def test_rendering_without_colour_contains_no_escape_codes(self):
        ctx, app = make_app(self.cfg, caps=caps(color=False))
        for line in app.render():
            self.assertNotIn("\x1b[", line)

    def test_ascii_fallback_avoids_box_drawing(self):
        ctx, app = make_app(self.cfg, caps=caps(unicode=False, width=90, height=40))
        text = render(app)
        for char in ("\u2500", "\u2502", "\u25b8"):
            self.assertNotIn(char, text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
