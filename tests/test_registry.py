#!/usr/bin/env python3
"""Registry unit tests: kind resolution, size normalisation, duration checks."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import registry  # noqa: E402


class ResolveTest(unittest.TestCase):
    def kind(self, model: str) -> str:
        capability = registry.resolve(model)
        return capability.kind if capability else "unknown"

    def test_video_families(self):
        for model in (
            "doubao-seedance-2-5",
            "doubao-seedance-2-0-260128",
            "wan2.5-t2v-preview",
            "wan2.2-i2v-plus",
            "MiniMax-Hailuo-02",
            "T2V-01-Director",
            "sora-2",
            "veo-3",
        ):
            self.assertEqual(self.kind(model), "video", model)

    def test_image_families(self):
        for model in (
            "doubao-seedream-4-0",
            "wan2.5-t2i-preview",
            "image-01",
            "gpt-image-1",
            "dall-e-3",
            "flux-pro",
            "stable-diffusion-3",
        ):
            self.assertEqual(self.kind(model), "image", model)

    def test_unknown_is_not_guessed_randomly(self):
        self.assertEqual(self.kind("deepseek-v4-pro"), "unknown")
        self.assertEqual(self.kind("claude-opus-5"), "unknown")

    def test_guess_kind_when_outside_registry(self):
        self.assertEqual(registry.guess_kind("some-vendor-t2v-v9"), "video")
        self.assertEqual(registry.guess_kind("acme-image-pro"), "image")
        self.assertEqual(registry.guess_kind("plain-chat"), "unknown")

    def test_user_override_wins(self):
        import json
        import tempfile

        payload = {"rules": [{"match": ["doubao-seedance-*"], "kind": "image", "size": {"form": "aspect"}}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            capability = registry.resolve("doubao-seedance-2-5", registry.load_rules(path))
            self.assertEqual(capability.kind, "image")
            self.assertEqual(capability.size_form(), "aspect")
        finally:
            os.unlink(path)


class SizeTest(unittest.TestCase):
    def test_wh_form(self):
        capability = registry.resolve("gpt-image-1")
        self.assertEqual(registry.validate_size("gpt-image-1", "1024x1024", capability), "1024x1024")
        self.assertEqual(registry.validate_size("gpt-image-1", "1024*1024", capability), "1024x1024")

    def test_star_form(self):
        capability = registry.resolve("wan2.5-t2i-preview")
        self.assertEqual(registry.validate_size("wan2.5-t2i-preview", "1280x720", capability), "1280*720")

    def test_resolution_form_passes_through(self):
        capability = registry.resolve("MiniMax-Hailuo-02")
        self.assertEqual(registry.validate_size("MiniMax-Hailuo-02", "1080P", capability), "1080P")

    def test_garbage_rejected(self):
        capability = registry.resolve("gpt-image-1")
        with self.assertRaises(registry.RegistryError):
            registry.validate_size("gpt-image-1", "big", capability)


class DurationTest(unittest.TestCase):
    def test_enum(self):
        capability = registry.resolve("MiniMax-Hailuo-02")
        self.assertEqual(registry.check_duration("MiniMax-Hailuo-02", 6, capability), 6)
        with self.assertRaises(registry.RegistryError):
            registry.check_duration("MiniMax-Hailuo-02", 7, capability)

    def test_range_and_auto(self):
        capability = registry.resolve("doubao-seedance-2-5")
        self.assertEqual(registry.check_duration("doubao-seedance-2-5", 10, capability), 10)
        self.assertEqual(registry.check_duration("doubao-seedance-2-5", -1, capability), -1)
        with self.assertRaises(registry.RegistryError):
            registry.check_duration("doubao-seedance-2-5", 2, capability)

    def test_describe_is_human_readable(self):
        text = registry.resolve("MiniMax-Hailuo-02").describe()
        self.assertIn("duration∈{6,10}s", text)
        self.assertIn("1080P", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
