import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ax_product.web import create_local_review_web_app_from_env


class LocalReviewerWebTests(unittest.TestCase):
    def test_built_console_is_mounted_without_shadowing_api_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            console_dist = Path(temporary)
            (console_dist / "index.html").write_text(
                "<!doctype html><title>AX Preflight</title>", encoding="utf-8"
            )
            api = FastAPI()

            @api.get("/api/capabilities")
            def capabilities() -> dict[str, bool]:
                return {"local_file_upload": True}

            with (
                patch.dict(
                    "os.environ", {"AX_PRODUCT_CONSOLE_DIST": str(console_dist)}
                ),
                patch(
                    "ax_product.web.create_local_review_app_from_env",
                    return_value=api,
                ),
            ):
                client = TestClient(create_local_review_web_app_from_env())

            self.assertEqual(
                client.get("/api/capabilities").json(),
                {"local_file_upload": True},
            )
            root = client.get("/")
            self.assertEqual(root.status_code, 200)
            self.assertIn("AX Preflight", root.text)


if __name__ == "__main__":
    unittest.main()
