from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anyio
import pytz
from googleapiclient.discovery import build
from google.oauth2 import service_account

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class GoogleEventWindow:
    time_min: datetime
    time_max: datetime


def _utc_rfc3339(dt: datetime) -> str:
    dt_utc = dt.astimezone(pytz.UTC)
    # RFC3339; Google acepta el sufijo 'Z' para UTC.
    return dt_utc.isoformat().replace("+00:00", "Z")


class GoogleCalendarClient:
    def __init__(self, calendar_scopes: list[str] | None = None):
        if not settings.GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE:
            raise RuntimeError(
                "Falta GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE en variables de entorno (.env)."
            )

        scopes = calendar_scopes or ["https://www.googleapis.com/auth/calendar"]
        credentials = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE,
            scopes=scopes,
        )
        # API de Google: el cliente es síncrono.
        self._service = build(
            "calendar",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )

    async def list_events_between(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        # Ejecutamos la llamada bloqueante en un hilo para no romper el async.
        return await anyio.to_thread.run_sync(
            self._list_events_between_sync,
            calendar_id,
            time_min,
            time_max,
        )

    async def create_event(
        self,
        calendar_id: str,
        *,
        start_utc: datetime,
        end_utc: datetime,
        summary: str,
        description: str | None = None,
    ) -> str:
        return await anyio.to_thread.run_sync(
            self._create_event_sync,
            calendar_id,
            start_utc,
            end_utc,
            summary,
            description,
        )

    def _create_event_sync(
        self,
        calendar_id: str,
        start_utc: datetime,
        end_utc: datetime,
        summary: str,
        description: str | None,
    ) -> str:
        event_body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": _utc_rfc3339(start_utc), "timeZone": "UTC"},
            "end": {"dateTime": _utc_rfc3339(end_utc), "timeZone": "UTC"},
        }
        if description:
            event_body["description"] = description

        created = (
            self._service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute()
        )
        event_id = created.get("id")
        if not event_id:
            raise RuntimeError("Google Calendar: no se pudo obtener event id")
        return event_id

    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        await anyio.to_thread.run_sync(self._delete_event_sync, calendar_id, event_id)

    def _delete_event_sync(self, calendar_id: str, event_id: str) -> None:
        self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def _list_events_between_sync(
        self, calendar_id: str, time_min: datetime, time_max: datetime
    ) -> list[dict[str, Any]]:
        time_min_str = _utc_rfc3339(time_min)
        time_max_str = _utc_rfc3339(time_max)

        events_result = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min_str,
                timeMax=time_max_str,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = events_result.get("items") or []
        return items


def get_google_calendar_client() -> GoogleCalendarClient:
    # Instancia perezosa (cache por proceso).
    if not hasattr(get_google_calendar_client, "_client"):
        setattr(get_google_calendar_client, "_client", GoogleCalendarClient())
    return getattr(get_google_calendar_client, "_client")

