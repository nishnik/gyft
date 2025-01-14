"""
This file contains the Flask application that serves as the backend for GYFT.
"""
import io
import logging
from typing import Dict, List
import requests
from flask import Flask, request, send_file, jsonify
from iitkgp_erp_login import erp
import iitkgp_erp_login.utils as erp_utils
from flask_cors import CORS
from timetable import generate_ics
from gyft import get_courses
import base64
from PIL import Image
from timetable.image_parser.table_parser import parse_table
from timetable.image_parser.build_courses_from_image import build_courses_from_image


app = Flask(__name__)
CORS(app)

headers = {
    "timeout": "20",
    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
}


def check_missing_fields(all_fields: Dict[str, str]) -> List[str]:
    return [field for field, value in all_fields.items() if not value]


class ErpResponse:
    def __init__(
        self,
        success: bool = True,
        message: str = None,
        data: dict = None,
        status_code: int = 200,
    ):
        self.success = success
        self.message = message
        self.data = data or {}
        self.status_code = status_code

        if not success:
            logging.error(" %s", message)

    def to_dict(self):
        response = {"status": "success" if self.success else "error"}
        if self.message:
            response["message"] = self.message
        if self.data:
            response |= self.data
        return response

    def to_response(self):
        return jsonify(self.to_dict()), self.status_code


@app.route("/secret-question", methods=["POST"])
def get_secret_question():
    try:
        data = request.form
        all_fields = {
            "roll_number": data.get("roll_number"),
        }
        missing = check_missing_fields(all_fields)
        if len(missing) > 0:
            return ErpResponse(
                False, f"Missing Fields: {', '.join(missing)}", status_code=400
            ).to_response()

        session = requests.Session()
        secret_question = erp.get_secret_question(
            headers=headers,
            session=session,
            roll_number=all_fields["roll_number"],
            log=True,
        )
        sessionToken = erp_utils.get_cookie(session, "JSESSIONID")

        return ErpResponse(
            True,
            data={"SECRET_QUESTION": secret_question,
                  "SESSION_TOKEN": sessionToken},
        ).to_response()
    except erp.ErpLoginError as e:
        return ErpResponse(False, str(e), status_code=401).to_response()
    except Exception as e:
        return ErpResponse(False, str(e), status_code=500).to_response()


@app.route("/request-otp", methods=["POST"])
def request_otp():
    try:
        data = request.form
        all_fields = {
            "roll_number": data.get("roll_number"),
            "password": data.get("password"),
            "secret_answer": data.get("secret_answer"),
            "sessionToken": request.headers["Session-Token"],
        }
        missing = check_missing_fields(all_fields)
        if len(missing) > 0:
            return ErpResponse(
                False, f"Missing Fields: {', '.join(missing)}", status_code=400
            ).to_response()

        login_details = erp.get_login_details(
            ROLL_NUMBER=all_fields["roll_number"],
            PASSWORD=all_fields["password"],
            secret_answer=all_fields["secret_answer"],
            sessionToken=all_fields["sessionToken"],
        )

        session = requests.Session()
        erp_utils.set_cookie(session, "JSESSIONID", all_fields["sessionToken"])
        erp.request_otp(
            headers=headers, session=session, login_details=login_details, log=True
        )

        return ErpResponse(
            True, message="OTP has been sent to your connected email accounts"
        ).to_response()
    except erp.ErpLoginError as e:
        return ErpResponse(False, str(e), status_code=401).to_response()
    except Exception as e:
        return ErpResponse(False, str(e), status_code=500).to_response()


@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.form
        all_fields = {
            "roll_number": data.get("roll_number"),
            "password": data.get("password"),
            "secret_answer": data.get("secret_answer"),
            "otp": data.get("otp"),
            "sessionToken": request.headers["Session-Token"],
        }
        missing = check_missing_fields(all_fields)
        if len(missing) > 0:
            return ErpResponse(
                False, f"Missing Fields: {', '.join(missing)}", status_code=400
            ).to_response()

        login_details = erp.get_login_details(
            ROLL_NUMBER=all_fields["roll_number"],
            PASSWORD=all_fields["password"],
            secret_answer=all_fields["secret_answer"],
            sessionToken=all_fields["sessionToken"],
        )
        login_details["email_otp"] = all_fields["otp"]

        session = requests.Session()
        erp_utils.set_cookie(session, "JSESSIONID", all_fields["sessionToken"])
        sso_token = erp.signin(
            headers=headers, session=session, login_details=login_details, log=True
        )

        return ErpResponse(True, data={"ssoToken": sso_token}).to_response()
    except erp.ErpLoginError as e:
        return ErpResponse(False, str(e), status_code=401).to_response()
    except Exception as e:
        return ErpResponse(False, str(e), status_code=500).to_response()


@app.route("/timetable", methods=["POST"])
def download_ics():
    try:
        data = request.form
        all_fields = {
            "roll_number": data.get("roll_number"),
            "ssoToken": request.headers["SSO-Token"],
        }
        missing = check_missing_fields(all_fields)
        if len(missing) > 0:
            return ErpResponse(
                False, f"Missing Fields: {', '.join(missing)}", status_code=400
            ).to_response()

        roll_number = all_fields["roll_number"]
        sso_token = all_fields["ssoToken"]

        session = requests.Session()
        erp_utils.populate_session_with_login_tokens(session, sso_token)

        courses = get_courses(session, sso_token, roll_number)

        ics_content = generate_ics(courses, "")

        # Create an in-memory file-like object for the ics content
        ics_file = io.BytesIO()
        ics_file.write(ics_content.encode("utf-8"))
        ics_file.seek(0)

        return send_file(
            ics_file,
            as_attachment=True,
            mimetype="text/calendar",
            download_name=f"${roll_number}-timetable.ics",
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    

@app.route("/parse_image", methods=["POST"])
def image_parser():
    try:
        # print("Hello", request)
        data = request.form

        all_fields = {
            "image": data.get("image"),
        }

        with open("dump.txt", "w") as f:
            f.write(all_fields["image"])
        missing = check_missing_fields(all_fields)
        if len(missing) > 0:
            return ErpResponse(
                False, f"Missing Fields: {', '.join(missing)}", status_code=400
            ).to_response()
        image = all_fields["image"]

        if image.startswith("data:image"):
            image = image.split(",")[1]
        
        image_data = io.BytesIO(base64.b64decode(image))
        # data = parse_table(Image.open(image_data))
        data = [['Day Name', '8:0:AM-8:55:AM', '9:0:AM-9:55:AM', '10:0:AM-10:55:AM.', '11:0:AM-11:55:AM', '12:0:PM-12:55:PM', '2:0:PM-2:55:PM', '3:0:PM-3:55:PM', '4:0:PM-4:55:PM', '5:0:PM-5:55:PM'], ['Mon', 'cS11002\nNR422', 'cS11002\nNR422', 'EC29201\nIn the Department', 'EC29201\nIn the Department', 'EC29201\nIn the Department', '', '£C21201\nNR311', '£C21201\nNR311', ''], ['Tue', '', '', '', '', 'cS11002\nNR422', '£C21201\nNR311', '£C21201\nNR311', '', ''], ['Wed', '', '', 'cy11003\nNR111', 'cS11002\nNR422', 'MA11004\nNR111', '', '', '', ''], ['Thur', '', 'cy11003\nNR111', '', 'MA11004\nNR111', '', '', '', '', ''], ['Fri', '', 'MA11004\nNR111', 'MA11004\nNR111', 'cy11003\nNR111', 'cy11003\nNR111', 'cy19003\nIn the Department', 'cy19003\nIn the Department', 'cy19003\nIn the Department', '']]

        courses = build_courses_from_image(data)

        ics_content = generate_ics(courses, "")

        # Create an in-memory file-like object for the ics content
        ics_file = io.BytesIO()
        ics_file.write(ics_content.encode("utf-8"))
        ics_file.seek(0)

        return send_file(
            ics_file,
            as_attachment=True,
            mimetype="text/calendar",
            download_name="timetable.ics",
        )
    except Exception as e:
        return ErpResponse(False, str(e), status_code=500).to_response()


if __name__ == "__main__":
    # Run the application on the local development server
    app.run()

# flask --app app.py run
