from __future__ import annotations

import logging
import random
from pathlib import Path

import simplematrixbotlib as botlib
from nio.events.room_events import RoomMemberEvent

from ascal.calendar import AngloSaxonCalendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ascal.eclipses import get_upcoming_eclipses
from bot.formatting import (
    format_as_date,
    format_calendar,
    format_eclipses,
    format_help,
    format_holidays,
    format_moon,
    format_next_month,
    format_sun,
    format_tides,
    format_today,
    format_tomorrow,
)
from bot.user_settings import geocode_location, get_user_location, set_user_location
from bot.moderation import register_moderation

log = logging.getLogger(__name__)


def run_bot(config: dict) -> None:
    mc = config["matrix"]
    cc = config["calendar"]
    bc = config.get("bot", {})
    prefix = bc.get("prefix", "!")

    if mc.get("access_token"):
        creds = botlib.Creds(mc["homeserver"], mc["username"], access_token=mc["access_token"])
    else:
        creds = botlib.Creds(mc["homeserver"], mc["username"], mc["password"])
    bot_config = botlib.Config()
    bot_config.join_on_invite = True
    bot_config.encryption_enabled = True
    bot_config.ignore_unverified_devices = True
    bot_config.store_path = "./crypto_store/"
    bot = botlib.Bot(creds, bot_config)

    # Load timefacts
    facts_file = Path(__file__).resolve().parent.parent / "data" / "timefacts.txt"
    if facts_file.exists():
        timefacts = [f.strip() for f in facts_file.read_text().split("---") if f.strip()]
    else:
        timefacts = []
        log.warning("timefacts.txt not found at %s", facts_file)

    default_cal = AngloSaxonCalendar(
        latitude=cc["latitude"],
        longitude=cc["longitude"],
        timezone=cc["timezone"],
    )
    log.info("Warming calendar cache...")
    default_cal.warm_cache()
    log.info("Cache ready.")

    def _get_local_observer(user_id: str) -> tuple[AngloSaxonCalendar | None, str]:
        """Return (local_observer, timezone) for a user.

        Returns (None, default_tz) if the user has no custom location.
        The local observer is only used for sunrise/sunset/tides — month
        boundaries always come from default_cal.
        """
        loc = get_user_location(user_id)
        if loc is None:
            return None, cc["timezone"]
        return AngloSaxonCalendar(
            latitude=loc["latitude"],
            longitude=loc["longitude"],
            timezone=loc["timezone"],
        ), loc["timezone"]

    @bot.listener.on_message_event
    async def on_message(room, message):
        match = botlib.MessageMatch(room, message, bot, prefix=prefix)
        if not (match.is_not_from_this_bot() and match.prefix()):
            return

        sender = message.sender
        cmd = match.command()
        try:
            if cmd == "location":
                place = " ".join(match.args())
                if not place:
                    loc = get_user_location(sender)
                    if loc:
                        await bot.api.send_markdown_message(
                            room.room_id,
                            f"Your location: {loc.get('display_name', 'unknown')} ({loc['timezone']})",
                        )
                    else:
                        await bot.api.send_markdown_message(
                            room.room_id,
                            f"No location set. Use `{prefix}location City, State/Country` to set one.",
                        )
                    return
                result = geocode_location(place)
                if result is None:
                    await bot.api.send_markdown_message(
                        room.room_id, f"Could not find a location matching \"{place}\".",
                    )
                    return
                display_name, lat, lon, tz = result
                set_user_location(sender, lat, lon, tz, display_name)
                await bot.api.send_markdown_message(
                    room.room_id,
                    f"Location set to **{display_name}** ({tz})",
                )

            elif cmd == "today":
                obs, tz = _get_local_observer(sender)
                asd = default_cal.get_today(local_observer=obs)
                await bot.api.send_markdown_message(room.room_id, format_today(asd, tz))

            elif cmd == "tomorrow" or cmd == "morgen":
                obs, tz = _get_local_observer(sender)
                local_cal = obs or default_cal
                tomorrow = datetime.now(ZoneInfo(tz)).date() + timedelta(days=1)
                asd = default_cal.get_date(tomorrow)
                # Recompute with local observer's twilight
                if obs:
                    asd.sunrise_time = obs.get_sunrise_time(tomorrow)
                    asd.sunset_time = obs.get_sunset_time(tomorrow)
                    asd.first_light, asd.last_light = obs.get_twilight_times(tomorrow)
                await bot.api.send_markdown_message(room.room_id, format_tomorrow(asd))

            elif cmd == "nextmonth":
                name, begins = default_cal.get_next_month()
                await bot.api.send_markdown_message(
                    room.room_id, format_next_month(name, begins)
                )

            elif cmd == "calendar":
                asd = default_cal.get_today()
                await bot.api.send_markdown_message(
                    room.room_id, format_calendar(asd.year_calendar)
                )

            elif cmd == "tides":
                obs, tz = _get_local_observer(sender)
                cal = obs or default_cal
                now = datetime.now(ZoneInfo(tz))
                sunset = cal.get_sunset_time(now.date())
                if now.time() >= sunset:
                    sunset_date = now.date()
                else:
                    sunset_date = now.date() - timedelta(days=1)
                tides = cal.get_as_day_tides(sunset_date)
                current = cal.get_current_tide(now)
                await bot.api.send_markdown_message(
                    room.room_id,
                    format_tides(tides, current, f"Tides for the current AS day ({tz})"),
                )

            elif cmd == "nexttides":
                obs, tz = _get_local_observer(sender)
                cal = obs or default_cal
                now = datetime.now(ZoneInfo(tz))
                sunset = cal.get_sunset_time(now.date())
                if now.time() >= sunset:
                    sunset_date = now.date() + timedelta(days=1)
                else:
                    sunset_date = now.date()
                tides = cal.get_as_day_tides(sunset_date)
                current = cal.get_current_tide(now)
                await bot.api.send_markdown_message(
                    room.room_id,
                    format_tides(tides, current, f"Tides starting next sunset ({tz})"),
                )

            elif cmd == "sun":
                obs, tz = _get_local_observer(sender)
                cal = obs or default_cal
                sun = cal.get_sun_info()
                await bot.api.send_markdown_message(room.room_id, format_sun(sun))

            elif cmd == "timefact":
                if timefacts:
                    fact = random.choice(timefacts)
                    await bot.api.send_markdown_message(room.room_id, fact)
                else:
                    await bot.api.send_markdown_message(room.room_id, "No timefacts available.")

            elif cmd == "moon":
                obs, tz = _get_local_observer(sender)
                cal = obs or default_cal
                moon = cal.get_moon_info()
                await bot.api.send_markdown_message(room.room_id, format_moon(moon))

            elif cmd == "eclipses":
                obs, tz = _get_local_observer(sender)
                cal = obs or default_cal
                eclipses = get_upcoming_eclipses(
                    ZoneInfo(tz),
                    float(cal.latitude),
                    float(cal.longitude),
                )
                await bot.api.send_markdown_message(room.room_id, format_eclipses(eclipses))

            elif cmd == "date":
                args = match.args()
                if not args:
                    await bot.api.send_markdown_message(
                        room.room_id, f"Usage: `{prefix}date YYYY-MM-DD`",
                    )
                    return
                try:
                    from datetime import date as date_cls
                    d = date_cls.fromisoformat(args[0])
                except ValueError:
                    await bot.api.send_markdown_message(
                        room.room_id, f"Invalid date format. Use `{prefix}date YYYY-MM-DD`.",
                    )
                    return
                obs, tz = _get_local_observer(sender)
                asd = default_cal.get_date(d)
                await bot.api.send_markdown_message(room.room_id, format_as_date(asd))

            elif cmd == "holidays":
                asd = default_cal.get_today()
                await bot.api.send_markdown_message(
                    room.room_id, format_holidays(asd.year_calendar)
                )

            elif cmd == "help":
                await bot.api.send_markdown_message(
                    room.room_id, format_help(prefix)
                )

        except Exception:
            log.exception("Error handling command %s", cmd)
            await bot.api.send_markdown_message(
                room.room_id, "Something went wrong processing that command."
            )

    welcome_room_name = bc.get("welcome_room")

    WELCOME_MSG = (
        "Welcome to the Ingwine Heathenship space. "
        "This server is for people who are interested in practicing Ingwine "
        "Heathenship. It is not a place for people from other religious "
        "traditions to \"observe\" us or satisfy their curiosity. "
        "Introduce yourself here so we can get to know you a little better "
        "before granting you access to the rest of the rooms.\n\n"
        "Learn more about our tradition at https://ingwine.org/"
    )

    if welcome_room_name:
        @bot.listener.on_custom_event(RoomMemberEvent)
        async def on_member(room, event):
            if (
                event.membership == "join"
                and event.prev_membership != "join"
                and room.display_name == welcome_room_name
            ):
                user = event.state_key
                log.info("New join in %s: %s", welcome_room_name, user)
                msg = f"{user}: {WELCOME_MSG}"
                await bot.api.send_markdown_message(room.room_id, msg)

    register_moderation(bot, config)

    bot.run()
