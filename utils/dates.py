from __future__ import print_function
import requests
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup as bs
from utils import build_event
import sys
from collections import defaultdict


SEM_BEGIN = build_event.generate_india_time(2025, 1, 2, 0, 0)
MID_TERM_BEGIN = build_event.generate_india_time(2025, 2, 18, 0, 0)
MID_TERM_END = build_event.generate_india_time(2025, 2, 26, 0, 0)
END_TERM_BEGIN = build_event.generate_india_time(2025, 4, 21, 0, 0)
AUT_BREAK_BEGIN = build_event.generate_india_time(2024, 10, 5, 0, 0)
AUT_BREAK_END = build_event.generate_india_time(2024, 10, 13, 0, 0)



# Recurrence strings from above dates
GYFT_RECUR_STRS = [
    ["RRULE:FREQ=WEEKLY;UNTIL={}".format(END_TERM_BEGIN.strftime("%Y%m%dT000000Z"))],
    ["RRULE:FREQ=WEEKLY;UNTIL={}".format(MID_TERM_BEGIN.strftime("%Y%m%dT000000Z"))],
    ["RRULE:FREQ=WEEKLY;UNTIL={}".format(END_TERM_BEGIN.strftime("%Y%m%dT070000Z"))],
    ["RRULE:FREQ=WEEKLY;UNTIL={}".format(MID_TERM_BEGIN.strftime("%Y%m%dT080000Z"))],
]


### getting holidays
def get_holidates() -> (list[datetime], list[str, datetime]):
    """
    scrapes holiday list from IITKGP website
    returns: list of holidays as occasions and datetime objects
    """
    headers = {
        "timeout": "20",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu Chromium/51.0.2704.79 Chrome/51.0.2704.79 Safari/537.36",
    }
    url = "https://www.iitkgp.ac.in/holidays"
    result = requests.get(url=url, headers=headers).text
    doc = bs(result, "html.parser")
    tbody = doc.tbody
    trs = tbody.contents
    holidays = []
    hol_dates = []
    hdays = defaultdict(list)
    for i in range(3, len(trs) - 7, 2):
        cnt = 0
        for tr in trs[i]:
            cnt = cnt + 1
            if cnt == 2:
                occasion = tr.string
            if cnt == 4:
                datetime_str = tr.string
                d = (int)(datetime_str[:2])
                m = (int)(datetime_str[3:5])
                y = (int)(datetime_str[6:])
                datetime_object = datetime.strptime(datetime_str, "%d.%m.20%y")
                hol_date = build_event.generate_india_time(y, m, d, 0, 0)
                holidays.append([occasion, datetime_object])
                hol_dates.append(hol_date)
            if cnt == 6:
                hday = tr.string
                if hol_date.date() >= date.today() and hol_date < END_TERM_BEGIN:
                    hdays[hday].append(hol_date)


    ### appending mid/end sem in holidates list
    hol_dates.extend(
        [
            SEM_BEGIN,
            MID_TERM_BEGIN,
            MID_TERM_END,
            END_TERM_BEGIN,
            AUT_BREAK_BEGIN,
            AUT_BREAK_END,
        ]
    )
    hol_dates.sort()
    return hol_dates, holidays, hdays




# Sanity check

sanity = [
    SEM_BEGIN < MID_TERM_BEGIN,
    MID_TERM_BEGIN < MID_TERM_END,
    MID_TERM_END < END_TERM_BEGIN,
]

# check if anything is False
sanity_check = [item for item in sanity if not item]

if len(sanity_check) > 0:
    print("Check the dates you have entered")
    print("Note: SEM_BEGIN < MID_TERM_BEGIN < MID_TERM_END < END_TERM_BEGIN")
    sys.exit(1)

hol_dates, holidays, hdays = get_holidates()


def get_dates() -> list[datetime, datetime]:
    """
    returns intervals of working dates
    """
    intervals = []
    for i in range(0, len(hol_dates)):
        if hol_dates[i] == MID_TERM_BEGIN:
            continue
        if hol_dates[i] >= AUT_BREAK_BEGIN and hol_dates[i] < AUT_BREAK_END:
            continue
        if hol_dates[i] >= SEM_BEGIN and hol_dates[i] < END_TERM_BEGIN:
            intervals.append(
                [
                    hol_dates[i],
                    hol_dates[i + 1] - timedelta(days=1),
                ]
            )
    return intervals


def next_weekday(current_day: datetime, weekday: str) -> datetime:
    days = {
        "Monday": 0,
        "Tuesday": 1,
        "Wednesday": 2,
        "Thursday": 3,
        "Friday": 4,
        "Saturday": 5,
    }
    weekday = days[weekday]
    days_ahead = weekday - current_day.weekday()
    if days_ahead <= 0:  # Target day already happened this week
        days_ahead += 7
    return current_day + timedelta(days_ahead)


def get_rfc_time(time: int, day: str, minute: int = 0, second: int = 0) -> str:
    r"""
    Returns RFC3339 formatted time string
    Args:
        time: hour in 24-hour format
        minute:
        second:
        day: A day string from the set {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"}

    Returns: str
    """
    now = datetime.now()
    date = next_weekday(now, day)
    return (
        date.replace(hour=time, minute=minute, second=second)
        .__str__()
        .replace(" ", "T")
    )


### creating strings to use in EXDATE call in google calendar

days_by_id = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}

## hdates maps all days of the week to datetime objects(each datetime obj is a holiday on the day key)
mid_term_count = (MID_TERM_END - MID_TERM_BEGIN).days + 1
for single_date in (MID_TERM_BEGIN + timedelta(n) for n in range(mid_term_count)):
    if single_date.date() >= date.today():
        hdays[days_by_id[single_date.weekday()]].append(single_date)

if (
    SEM_BEGIN.month > 6
):  ## not to be added in EXDATE strings as would not exist in the recurrence of spring sem
    autumn_day_count = (AUT_BREAK_END - AUT_BREAK_BEGIN).days + 1
    for single_date in (
        AUT_BREAK_BEGIN + timedelta(n) for n in range(autumn_day_count)
    ):
        if single_date.date() >= date.today():
            hdays[days_by_id[single_date.weekday()]].append(single_date)

for hday in hdays.keys():
    hdays[hday].sort()
    hdays[hday] = list(set(hdays[hday]))  ### datetime dict(list)
