"""Phase 8.5: navigation, shortcuts, screen stack and key handling."""

import unittest

from callshield.ui.navigation import Pager, ScreenStack, keys as K
from callshield.ui.screens import REGISTRY, make_screen
from callshield.ui.screens.dashboard import QUICK_ACTIONS
from tests._common import IsolatedEnv
from tests._ui import caps, make_app, render


class TestKeyDecoding(unittest.TestCase):
    def test_arrow_keys(self):
        self.assertEqual(K.decode("\x1b[A"), K.UP)
        self.assertEqual(K.decode("\x1b[B"), K.DOWN)
        self.assertEqual(K.decode("\x1b[C"), K.RIGHT)
        self.assertEqual(K.decode("\x1b[D"), K.LEFT)

    def test_paging_keys(self):
        self.assertEqual(K.decode("\x1b[5~"), K.PAGE_UP)
        self.assertEqual(K.decode("\x1b[6~"), K.PAGE_DOWN)

    def test_enter_escape_and_interrupt(self):
        self.assertEqual(K.decode("\r"), K.ENTER)
        self.assertEqual(K.decode("\n"), K.ENTER)
        self.assertEqual(K.decode("\x1b"), K.ESC)
        self.assertEqual(K.decode("\x03"), K.INTERRUPT)

    def test_unknown_escape_sequence_becomes_escape_not_silence(self):
        self.assertEqual(K.decode("\x1b[Z"), K.ESC)
        self.assertEqual(K.decode("\x1b[999~"), K.ESC)

    def test_quit_and_back_predicates(self):
        self.assertTrue(K.is_quit("q"))
        self.assertTrue(K.is_quit(K.INTERRUPT))
        self.assertTrue(K.is_back(K.ESC))
        self.assertFalse(K.is_quit("x"))

    def test_empty_input_is_no_key(self):
        self.assertEqual(K.decode(""), K.NONE)


class TestScreenStack(unittest.TestCase):
    def test_push_and_pop(self):
        stack = ScreenStack("root", "ROOT")
        stack.push("child", "CHILD")
        self.assertEqual(stack.depth, 2)
        self.assertEqual(stack.trail(), ["ROOT", "CHILD"])
        stack.pop()
        self.assertEqual(stack.current, "root")

    def test_depth_is_bounded(self):
        stack = ScreenStack("root", "ROOT")
        for index in range(50):
            stack.push("s%d" % index, "S")
        self.assertLessEqual(stack.depth, 12)

    def test_pop_on_empty_is_safe(self):
        stack = ScreenStack()
        self.assertIsNone(stack.pop())


class TestPager(unittest.TestCase):
    def test_pagination(self):
        pager = Pager(10, 25)
        self.assertEqual(pager.pages, 3)
        self.assertTrue(pager.next_page())
        self.assertEqual(pager.page, 2)
        pager.last_page()
        self.assertEqual(pager.page, 3)
        self.assertFalse(pager.next_page())
        pager.first_page()
        self.assertFalse(pager.previous_page())

    def test_empty_dataset_has_one_page(self):
        self.assertEqual(Pager(10, 0).pages, 1)


class TestApplicationNavigation(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_every_registered_screen_builds_and_renders(self):
        ctx, app = make_app(self.cfg)
        for key in REGISTRY:
            screen = make_screen(key, ctx)
            self.assertIsNotNone(screen, key)
            screen.on_enter()
            self.assertTrue(screen.body(ctx.surface) is not None)

    def test_dashboard_lists_every_quick_action(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70))
        text = render(app)
        for key, label in QUICK_ACTIONS:
            self.assertIn(ctx.t(label), text)

    def test_arrow_then_enter_pushes_a_screen(self):
        ctx, app = make_app(self.cfg)
        app.handle_key(K.DOWN)
        app.handle_key(K.ENTER)
        self.assertEqual(app.stack.depth, 2)

    def test_escape_returns_to_the_previous_screen(self):
        ctx, app = make_app(self.cfg)
        app.handle_key(K.DOWN)
        app.handle_key(K.ENTER)
        self.assertEqual(app.stack.depth, 2)
        self.assertTrue(app.handle_key(K.ESC))
        self.assertEqual(app.stack.depth, 1)

    def test_escape_at_root_exits_rather_than_trapping(self):
        ctx, app = make_app(self.cfg)
        self.assertFalse(app.handle_key(K.ESC))

    def test_q_quits_from_any_depth(self):
        ctx, app = make_app(self.cfg)
        app.handle_key("2")
        self.assertFalse(app.handle_key("q"))

    def test_ctrl_c_exits_cleanly(self):
        ctx, app = make_app(self.cfg)
        self.assertFalse(app.handle_key(K.INTERRUPT))
        self.assertEqual(app.exit_code, 0)

    def test_number_shortcut_jumps_directly(self):
        ctx, app = make_app(self.cfg)
        app.handle_key("2")
        self.assertEqual(app.stack.depth, 2)

    def test_out_of_range_number_is_reported_not_crashing(self):
        ctx, app = make_app(self.cfg, screen_key="settings")
        app.handle_key("9")
        self.assertEqual(app.stack.depth, 1)
        self.assertIn(ctx.t("prompt.invalid_choice"), render(app))

    def test_unknown_key_is_ignored(self):
        ctx, app = make_app(self.cfg)
        self.assertTrue(app.handle_key("~"))
        self.assertEqual(app.stack.depth, 1)

    def test_home_action_returns_to_dashboard(self):
        ctx, app = make_app(self.cfg)
        app.handle_key("2")
        app.handle_key("h")
        self.assertEqual(app.stack.depth, 1)

    def test_menu_selection_stays_visible_when_body_is_clipped(self):
        ctx, app = make_app(self.cfg, caps=caps(width=90, height=18))
        for _ in range(10):
            app.handle_key(K.DOWN)
        text = render(app)
        selected = app.current.menu.selected
        self.assertIn(selected.label, text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
