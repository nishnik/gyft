from __future__ import print_function
from datetime import datetime
import os
from bs4 import BeautifulSoup
from googleapiclient.discovery import re
import httplib2
from apiclient import discovery
import icalendar
from oauth2client import client, file, tools
from icalendar import Calendar

from timetable.generate_ics import generate_ics
from utils import (
    END_TERM_BEGIN,
    SEM_BEGIN,
    GYFT_RECUR_STRS,
)
from timetable import Course
from utils.dates import MID_TERM_END

DEBUG = False

SCOPES = "https://www.googleapis.com/auth/calendar"
CLIENT_SECRET_FILE = "client_secret.json"
APPLICATION_NAME = "gyft"

def is_in_correct_sem(dt: datetime) -> bool:
    if(datetime.now().replace(tzinfo=None) <= MID_TERM_END.replace(tzinfo=None)):
        return dt.replace(tzinfo=None) < MID_TERM_END.replace(tzinfo=None)
    elif( datetime.now().replace(tzinfo=None) >= MID_TERM_END.replace(tzinfo=None)):
        return dt.replace(tzinfo=None) < END_TERM_BEGIN.replace(tzinfo=None) and dt.replace(tzinfo=None) > MID_TERM_END.replace(tzinfo=None)
    else:
        return True

def parse_ics(ics,length):
    events = []
    with open(ics, 'r') as rf:
        ical = Calendar().from_ical(rf.read())
        for i, comp in enumerate(ical.walk()):
            if ((comp.name == "VEVENT") and ( length == "c" and is_in_correct_sem(comp.get('dtstart').dt))  ) :
                event = {}
                for name, prop in comp.property_items():

                    if name in ["SUMMARY", "LOCATION"]:
                        event[name.lower()] = prop.to_ical().decode('utf-8')

                    elif name == "DTSTART":
                        event["start"] = {
                            "dateTime": prop.dt.isoformat(),
                            "timeZone": ( str(prop.dt.tzinfo) if prop.dt.tzinfo else "Asia/Kolkata" )
                        }

                    elif name == "DTEND":
                        event["end"] = {
                            "dateTime": prop.dt.isoformat(),
                            "timeZone": ( str(prop.dt.tzinfo) if prop.dt.tzinfo else "Asia/Kolkata" )
                        }
                    elif name == "RRULE":
                        freq = str(prop.get("FREQ")[0]).strip()
                        duration = comp.get('duration').dt
                        end_time = (comp.get('dtstart').dt + duration)
                        until = prop.get('UNTIL')[0]
                        event["recurrence"] = [
                                ("RRULE:FREQ="+freq+";UNTIL={}").format(
                                    until.strftime("%Y%m%dT000000Z")
                                    )
                                ]
                        event["end"]= {
                                'dateTime': end_time.isoformat(),
                                "timeZone":  "Asia/Kolkata"
                                }
                    elif name == "SEQUENCE":
                        event[name.lower()] = prop

                    elif name == "TRANSP":
                        event["transparency"] = prop.lower()

                    elif name == "CLASS":
                        event["visibility"] = prop.lower()

                    elif name == "ORGANIZER":
                        event["organizer"] = {
                            "displayName": prop.params.get("CN") or '',
                            "email": re.match('mailto:(.*)', prop).group(1) or ''
                        }

                    elif name == "DESCRIPTION":
                        desc = prop.to_ical().decode('utf-8')
                        desc = desc.replace(u'\xa0', u' ')
                        if name.lower() in event:
                            event[name.lower()] = desc + '\r\n' + event[name.lower()]
                        else:
                            event[name.lower()] = desc

                    elif name == 'X-ALT-DESC' and "description" not in event:
                        soup = BeautifulSoup(prop, 'lxml')
                        desc = soup.body.text.replace(u'\xa0', u' ')
                        if 'description' in event:
                            event['description'] += '\r\n' + desc
                        else:
                            event['description'] = desc

                    elif name == 'ATTENDEE':
                        if 'attendees' not in event:
                            event["attendees"] = []
                        RSVP = prop.params.get('RSVP') or ''
                        RSVP = 'RSVP={}'.format('TRUE:{}'.format(prop) if RSVP == 'TRUE' else RSVP)
                        ROLE = prop.params.get('ROLE') or ''
                        event['attendees'].append({
                            'displayName': prop.params.get('CN') or '',
                            'email': re.match('mailto:(.*)', prop).group(1) or '',
                            'comment': ROLE
                            # 'comment': '{};{}'.format(RSVP, ROLE)
                        })

                    # VALARM: only remind by UI popup
                    elif name == 'ACTION':
                        event['reminders'] = {'useDefault': True}

                    else:
                        # print(name)
                        pass

                events.append(event)

    return events

def get_credentials() -> client.Credentials:
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials
    """
    home_dir = os.path.expanduser("~")
    credential_dir = os.path.join(home_dir, ".credentials")
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir, "calendar-python-quickstart.json")

    store = file.Storage(credential_path)
    credentials: client.Credentials = store.get()
    if (
        not credentials or credentials.invalid
    ):  # FIXME: credentials.invalid is unresolved but works for some reason
        flow: client.Flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
        flow.user_agent = APPLICATION_NAME
        credentials: client.Credentials = tools.run_flow(flow, store)
        print("Storing credentials to " + credential_path)
    return credentials


def get_calendarId(service, summary):
    page_token = None
    while True:
        calendar_list = service.calendarList().list(pageToken=page_token).execute()
        for calendar_list_entry in calendar_list['items']:
            if calendar_list_entry['summary'] == summary:
                return calendar_list_entry['id']
        page_token = calendar_list.get('nextPageToken')
        if not page_token:
            return "primary" 



def cb_insert_event(request_id, response, e):
    summary = response['summary'] if response and 'summary' in response else '?'
    if not e:
        print('({}) - Insert event {}'.format(request_id, summary))
    else:
        print('({}) - Exception {}'.format(request_id, e))


def create_calendar(courses: list[Course], cal_name:str) -> None:
    r"""
    Adds courses to Google Calendar
    Args:
        courses: list of Course objects
    """
    credentials = get_credentials()
    http = credentials.authorize(httplib2.Http())
    service = discovery.build("calendar", "v3", http=http)
    batch = service.new_batch_http_request(callback=cb_insert_event)  # To add events in a batch
    filename = "timetable.ics" if os.path.exists("timetable.ics") else "temp.ics"
    if(filename == "timetable.ics"):
        print("Using existing timetable.ics file, press 'n' to generate and use a temporary one or 'y' to continue : (Y/n)")
        if(input().lower() == "n" and True):
            generate_ics(courses, "temp.ics")
        else:
            print("Invalid input")
            exit(1)

    calendar_id = get_calendarId(service,cal_name)
    length = input("Do you want Events from (C)urrent or (B)oth Semesters (C/b) _default is current_ : ") or 'c'
    if(length.lower() == 'b'):
        print("WARNING: Events from both semesters will be added.\n This may result in duplicate events if tool is used in both semesters")
    events = parse_ics(filename, length.lower())

    for i, event in enumerate(events):
        try:
            print("[ADDING EVENT]: ",event,"\n")
            batch.add(service.events().insert(calendarId=calendar_id, body=event))
        except Exception as e:
            print(e)
    batch.execute(http=http)
    if(os.path.exists("temp.ics")):
        os.remove("temp.ics")

    print("\nAll events added successfully!\n")


def delete_calendar():
    r"""
    Deletes all events in the calendar that recur according to schedule
    """
    credentials = get_credentials()
    http = credentials.authorize(httplib2.Http())
    service = discovery.build("calendar", "v3", http=http)
    batch = service.new_batch_http_request()  # To add events in a batch
    print("Getting the events")
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=SEM_BEGIN.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            singleEvents=False,
            timeMax=END_TERM_BEGIN.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            maxResults=2500,
        )
        .execute()
    )
    events = events_result.get("items", [])
    if not events or len(events) == 0:
        print("No upcoming events found.")
        return
    for event in events:
        if event.get("recurrence", "NoRecur") in GYFT_RECUR_STRS:
            batch.add(
                service.events().delete(calendarId="primary", eventId=event["id"])
            )
            print("Deleted: ", event["summary"], event["start"])
    batch.execute()
    print("Deletion done!")
