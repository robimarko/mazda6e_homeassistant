"""ABRP upload uses only Mazda fields and never breaks Mazda polling."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from custom_components.mazda6e.abrp import ABRP_URL, AbrpUploader, telemetry
from custom_components.mazda6e.config_flow import _parse_abrp_tokens
from custom_components.mazda6e.models import VehicleStatus


def test_telemetry_maps_known_fields_without_inventing_gps() -> None:
    status = VehicleStatus(
        soc=81,
        range_km=400,
        odometer_km=12345.6,
        charge_status_code=6,
        charge_status="charging",
        vehicle_state="parked",
        speed_kmh=0,
        last_update=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert telemetry(status) == {
        "provider": "ABRP_OTA",
        "soc": {"time": "2026-01-02T00:00:00Z", "frac": 0.81},
        "estimatedBatteryRange": {"time": "2026-01-02T00:00:00Z", "m": 400000},
        "odometer": {"time": "2026-01-02T00:00:00Z", "m": 12345600.0},
        "chargingState": {"time": "2026-01-02T00:00:00Z", "state": "CHARGING_AC"},
        "drivingState": {"time": "2026-01-02T00:00:00Z", "state": "PARK"},
        "speed": {"time": "2026-01-02T00:00:00Z", "ms": 0.0},
    }
    assert telemetry(VehicleStatus()) is None


async def test_upload_uses_vehicle_token_and_deduplicates_timestamp() -> None:
    response = MagicMock(status=200)
    request = MagicMock()
    request.__aenter__ = AsyncMock(return_value=response)
    request.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.post.return_value = request
    uploader = AbrpUploader(session)
    uploader.configure("api-key", {"VIN1": "car-token"})
    status = VehicleStatus(soc=50, last_update=datetime(2026, 1, 2, tzinfo=UTC))

    await uploader.send("VIN1", status)
    await uploader.send("VIN1", status)
    await uploader.send("VIN2", status)

    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args == (ABRP_URL,)
    assert kwargs["headers"] == {"X-API-KEY": "api-key", "X-TLM-TOKEN": "car-token"}
    assert kwargs["json"] == [{
        "provider": "ABRP_OTA",
        "soc": {"time": "2026-01-02T00:00:00Z", "frac": 0.5},
    }]


def test_token_mapping_rejects_malformed_lines() -> None:
    assert _parse_abrp_tokens("VIN1=token1\nVIN2=token2") == {"VIN1": "token1", "VIN2": "token2"}
    try:
        _parse_abrp_tokens("VIN1=token1\nVIN1=token2")
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate VIN should be rejected")
