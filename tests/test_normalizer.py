import unittest

from callshield.normalizer import normalize
from callshield.utils import InvalidNumberError


class TestNormalizer(unittest.TestCase):
    def test_formatted_number_with_spaces(self):
        r = normalize("+91 98765 43210")
        self.assertEqual(r.normalized, "+919876543210")
        self.assertEqual(r.digits, "919876543210")

    def test_compact_plus(self):
        r = normalize("+919876543210")
        self.assertEqual(r.normalized, "+919876543210")

    def test_no_plus_with_default_country_trunk_zero(self):
        r = normalize("09876543210", default_country="IN")
        self.assertEqual(r.normalized, "+919876543210")

    def test_00_prefix(self):
        r = normalize("00919876543210")
        self.assertEqual(r.normalized, "+919876543210")

    def test_strips_common_punctuation(self):
        r = normalize("+91-(98765) 43210")
        self.assertEqual(r.normalized, "+919876543210")

    def test_rejects_empty(self):
        with self.assertRaises(InvalidNumberError):
            normalize("   ")

    def test_rejects_non_digit_characters(self):
        with self.assertRaises(InvalidNumberError):
            normalize("+91-9876a-43210")

    def test_rejects_too_short(self):
        with self.assertRaises(InvalidNumberError):
            normalize("+1234")

    def test_rejects_too_long(self):
        with self.assertRaises(InvalidNumberError):
            normalize("+1234567890123456789")

    def test_us_number(self):
        r = normalize("+1 415-555-2671")
        self.assertEqual(r.normalized, "+14155552671")


if __name__ == "__main__":
    unittest.main()
