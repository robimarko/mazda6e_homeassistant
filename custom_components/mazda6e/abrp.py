"""Optional upload of Mazda cloud snapshots to ABRP."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import aiohttp

from .models import VehicleStatus

_LOGGER = logging.getLogger(__name__)
ABRP_URL = "https://api.iternio.com/2/app/tlm"


def telemetry(status: VehicleStatus) -> dict[str, object] | None:
    """Build a generic ABRP telemetry point from fields Mazda actually reports."""
    if status.soc is None or not 0 <= status.soc <= 100:
        return None
    timestamp = status.last_update or datetime.now(UTC)
    time = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    point: dict[str, object] = {
        "provider": "ABRP_OTA",
        "soc": {"time": time, "frac": status.soc / 100},
    }
    if status.range_km is not None and status.range_km >= 0:
        point["estimatedBatteryRange"] = {"time": time, "m": status.range_km * 1000}
    if status.odometer_km is not None and status.odometer_km >= 0:
        point["odometer"] = {"time": time, "m": status.odometer_km * 1000}
    if status.is_charging is not None:
        if status.is_charging:
            charging = (
                "CHARGING_DC"
                if status.dc_plugged_in
                else "CHARGING_AC" if status.plugged_in else "CHARGING_UNKNOWN"
            )
        else:
            charging = "PLUGGED_IN" if status.plugged_in else "NOT_CHARGING"
        point["chargingState"] = {"time": time, "state": charging}
    if status.vehicle_state is not None:
        point["drivingState"] = {
            "time": time,
            "state": "PARK" if status.vehicle_state == "parked" else "DRIVE",
        }
    if status.speed_kmh is not None:
        point["speed"] = {"time": time, "ms": status.speed_kmh / 3.6}
    return point


class AbrpUploader:
    """Keep ABRP credentials and avoid resending the same cloud snapshot."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self.api_key = ""
        self.tokens: dict[str, str] = {}
        self._sent: dict[str, tuple[str, str]] = {}

    def configure(self, api_key: str, tokens: dict[str, str]) -> None:
        if self.api_key == api_key and self.tokens == tokens:
            return
        self.api_key = api_key
        self.tokens = dict(tokens)
        self._sent.clear()

    async def send(self, vin: str, status: VehicleStatus) -> None:
        token = self.tokens.get(vin)
        point = telemetry(status)
        if not self.api_key or not token or point is None:
            return
        # The cloud can repeat an old timestamp over several polls.
        identity = (token, status.last_update.isoformat() if status.last_update else "")
        if status.last_update and self._sent.get(vin) == identity:
            return
        try:
            async with self.session.post(
                ABRP_URL,
                headers={"X-API-KEY": self.api_key, "X-TLM-TOKEN": token},
                json=[point],
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status >= 400:
                    _LOGGER.warning(
                        "ABRP telemetry upload failed for %s (HTTP %s)", vin[-6:], response.status
                    )
                    return
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning(
                "ABRP telemetry upload failed for %s: %s", vin[-6:], type(err).__name__
            )
            return
        self._sent[vin] = identity
