"""FancyTanky robot REST API connector with offline simulation fallback."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from src.providers.localai import log_api_error


class FancyTankyConnector:
    """Communicates with a local FancyTanky tracked tank robot REST server."""

    _DIRECTION_MAP = {
        "vorwärts": "forward",
        "vor": "forward",
        "forward": "forward",
        "rückwärts": "backward",
        "zurück": "backward",
        "backward": "backward",
        "links": "left",
        "left": "left",
        "rechts": "right",
        "right": "right",
        "stopp": "stop",
        "stop": "stop",
    }

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout_seconds: float = 2.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    def _request(self, method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        client = self._http_client or httpx.Client(timeout=self.timeout_seconds)
        should_close = self._http_client is None
        url = f"{self.base_url}{path}"
        try:
            resp = client.request(method, url, json=json_body)
            resp.raise_for_status()
            return {"ok": True, "source": "fancytanky-live", "data": resp.json()}
        except Exception as exc:
            log_api_error("FancyTanky", method, url, detail=str(exc))
            return {
                "ok": False,
                "source": "fancytanky-sim",
                "error": str(exc),
                "simulated_action": {"method": method, "path": path, "payload": json_body or {}},
            }
        finally:
            if should_close:
                client.close()

    def get_status(self) -> Dict[str, Any]:
        """Fetch live battery, ultrasonic distance, and cliff status from FancyTanky."""
        res = self._request("GET", "/api/status")
        if res["ok"]:
            return res
        return {
            "ok": True,
            "source": "fancytanky-sim",
            "data": {"battery_pct": 85, "distance_cm": 42.0, "state": "standby"},
        }

    def move(self, direction: str, speed: float = 0.6) -> Dict[str, Any]:
        """Command FancyTanky chassis movement."""
        return self._request("POST", "/api/move", {"direction": direction, "speed": speed})

    def trigger_expression(self, action: str) -> Dict[str, Any]:
        """Trigger a FancyTanky gesture ('yes', 'no', or 'sleep')."""
        return self._request("POST", f"/api/action/{action}")

    def execute_natural_command(self, text: str, language: str = "de") -> str:
        """Map a natural-language command into a FancyTanky REST call and summarize the outcome."""
        lowered = text.lower()
        if any(word in lowered for word in ("ja", "yes", "nicken", "nod")):
            res = self.trigger_expression("yes")
            return self._format_reply("yes", res, language)

        if any(word in lowered for word in ("nein", "no", "schütteln", "shake")):
            res = self.trigger_expression("no")
            return self._format_reply("no", res, language)

        if any(word in lowered for word in ("schlaf", "sleep", "ruhemodus")):
            res = self.trigger_expression("sleep")
            return self._format_reply("sleep", res, language)

        for keyword, direction in self._DIRECTION_MAP.items():
            if keyword in lowered:
                res = self.move(direction)
                return self._format_reply(f"move:{direction}", res, language)

        status = self.get_status()
        data = status.get("data", {})
        if language == "de":
            return (
                f"FancyTanky Status ({status['source']}): Batterie {data.get('battery_pct', '?')}%, "
                f"Abstand {data.get('distance_cm', '?')} cm."
            )
        return (
            f"FancyTanky status ({status['source']}): battery {data.get('battery_pct', '?')}%, "
            f"distance {data.get('distance_cm', '?')} cm."
        )

    @staticmethod
    def _format_reply(action: str, result: Dict[str, Any], language: str) -> str:
        mode = result.get("source", "fancytanky")
        if language == "de":
            return f"Befehl '{action}' an FancyTanky gesendet ({mode})."
        return f"Sent '{action}' command to FancyTanky ({mode})."

