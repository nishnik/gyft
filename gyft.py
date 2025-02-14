import argparse
import iitkgp_erp_login.erp as erp
import requests
from timetable import delete_calendar, create_calendar, build_courses, generate_ics
from utils.dates import SEM_BEGIN

headers = {
    "timeout": "20",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-D",
        "--development",
        action="store_true",
        help="Automate erpcreds parsing while development (except OTP)",
    )
    parser.add_argument(
        "-O",
        "--otp",
        action="store_true",
        help="Automate erpcreds parsing while development (including OTP)",
    )
    parser.add_argument(
        "-o", "--output", help="Output file containing timetable in .ics format"
    )
    parser.add_argument(
        "-d",
        "--del-events",
        action="store_true",
        help="Delete events automatically added by the script before adding new events",
    )

    parser.add_argument('-c', "--cal", dest='cal', default="primary",
        help="Name of the calendar in which the events will be added to, you will have to manually create a calendar on the google calendar app/website",)

    args = parser.parse_args()
    return args


def main():
    args = parse_args()
    if args.del_events:
        delete_calendar()
        if (
            input("\nWould you like to generate a new timetable? (y/n): ").lower()
            == "n"
        ):
            return

    output_filename = args.output if args.output else "timetable.ics"

    session = requests.Session()

    if args.otp and not args.development:
        print('ERROR: -O [--otp] must be used with -D [--development]')
        return

    if args.development:
        if args.otp:
            import erpcreds

            _, sso_token = erp.login(
                headers,
                session,
                ERPCREDS=erpcreds,
                OTP_CHECK_INTERVAL=2,
                LOGGING=True,
            )
        else:
            import erpcreds

            _, sso_token = erp.login(
                headers,
                session,
                ERPCREDS=erpcreds,
                LOGGING=True,
            )
    else:
        _, sso_token = erp.login(headers, session)

    roll_number = erp.ROLL_NUMBER

    courses = get_courses(session, sso_token, roll_number)

    print("Timetable fetched.\n")

    print("What would you like to do now?")
    print("1. Add timetable directly to Google Calendar (requires client_secret.json)")
    print("2. Generate an ICS file")
    print("3. Exit")
    choice = int(input("Enter your choice: "))

    print(args.cal)

    if choice == 1:
        create_calendar(courses,args.cal)
    elif choice == 2:
        generate_ics(courses, output_filename)
    else:
        exit()


def get_courses(session: requests.Session, sso_token: str, roll_number: str):
    erp_timetable_url = "https://erp.iitkgp.ac.in/Acad/student/student_timetable.jsp"
    courses_url: str = "https://erp.iitkgp.ac.in/Academic/student_performance_details_ug.htm?semno={}&rollno={}"

    timetable_page = session.post(
        headers=headers,
        url=erp_timetable_url,
        data={
            "ssoToken": sso_token,
            "module_id": "16",
            "menu_id": "40",
        },
    )
    sem_num = 1

    if SEM_BEGIN.month > 6:
        # autumn semester
        sem_num = (int(SEM_BEGIN.strftime("%y")) - int(roll_number[:2])) * 2 + 1
    else:
        # spring semester - sem begin year is 1 more than autumn sem
        sem_num = (int(SEM_BEGIN.strftime("%y")) - int(roll_number[:2])) * 2

    r = session.post(
        headers=headers,
        url=courses_url.format(sem_num, roll_number),
        data={
            "ssoToken": sso_token,
            "semno": sem_num,
            "rollno": roll_number,
            "order": "asc",
        },
    )
    sub_dict = {item["subno"]: item["subname"] for item in r.json()}
    course_names = {k: v.replace("&amp;", "&") for k, v in sub_dict.items()}

    courses = build_courses(timetable_page.text, course_names)
    return courses


if __name__ == "__main__":
    main()
