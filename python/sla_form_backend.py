"""RAMA SLA and NOC API backed by MySQL."""

import base64
import datetime
import getpass
import hashlib
import hmac
import json
import logging
import os
import random
import re
import sys
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pymysql

PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_ROOT = os.path.dirname(PYTHON_DIR)
DB_HOST = os.environ.get("RAMA_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("RAMA_DB_PORT", "3306"))
DB_USER = os.environ.get("RAMA_DB_USER", "root")
DB_PASSWORD = os.environ.get("RAMA_DB_PASSWORD", "")
DB_NAME = os.environ.get("RAMA_DB_NAME", "rama_sla")
INQUIRY_STATUSES = ("Active", "Pending", "Postponed", "Done")
SESSION_COOKIE = "rama_noc_session"
SESSION_LIFETIME_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 120000
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


def connect_database():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
    )


def ensure_database():
    try:
        connection = connect_database()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM sla_inquiries LIMIT 0")
            cursor.execute("SELECT 1 FROM noc_users LIMIT 0")
        connection.close()
    except pymysql.MySQLError as error:
        raise RuntimeError(
            "Cannot connect to MySQL database '{}' or its NOC account table. "
            "Run database/rama_sla_schema.sql and check RAMA_DB_HOST, RAMA_DB_PORT, "
            "RAMA_DB_USER, and RAMA_DB_PASSWORD. Details: {}".format(DB_NAME, error)
        )

    bootstrap_accounts()


def make_password_hash(password):
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def check_password(password, encoded_hash):
    try:
        algorithm, iterations, salt_text, expected_text = encoded_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(expected_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def verify_account_password(password, stored_value):
    if stored_value.startswith("pbkdf2_sha256$"):
        return check_password(password, stored_value), False

    # Older manually-created accounts may contain a plain-text password.
    # Accept it once, then replace it with a salted PBKDF2 hash at login.
    try:
        matches = hmac.compare_digest(
            password.encode("utf-8"), stored_value.encode("utf-8")
        )
    except (AttributeError, UnicodeEncodeError):
        return False, False
    return matches, matches


def create_account(username, password, role):
    username = username.strip()
    if not username or len(username) > 80:
        raise ValueError("Usernames must contain between 1 and 80 characters.")
    if len(password) < 12:
        raise ValueError("Passwords must be at least 12 characters.")

    connection = connect_database()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO noc_users (username, password_hash, user_role)
                VALUES (%s, %s, %s)
                """,
                (username, make_password_hash(password), role),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def bootstrap_accounts():
    connection = connect_database()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM noc_users")
            account_count = cursor.fetchone()[0]
    finally:
        connection.close()

    if account_count:
        return

    manager_username = os.environ.get("RAMA_MANAGER_USERNAME")
    manager_password = os.environ.get("RAMA_MANAGER_PASSWORD")
    worker_username = os.environ.get("RAMA_WORKER_USERNAME")
    worker_password = os.environ.get("RAMA_WORKER_PASSWORD")

    if all((manager_username, manager_password, worker_username, worker_password)):
        if manager_username.strip().lower() == worker_username.strip().lower():
            raise ValueError("Manager and worker usernames must be different.")
        create_account(manager_username, manager_password, "manager")
        create_account(worker_username, worker_password, "worker")
        print("Created initial NOC manager and worker accounts from environment settings.")
        return

    if not sys.stdin.isatty():
        raise RuntimeError(
            "No NOC accounts exist. Set RAMA_MANAGER_USERNAME, "
            "RAMA_MANAGER_PASSWORD, RAMA_WORKER_USERNAME, and "
            "RAMA_WORKER_PASSWORD before starting the API, or start it in an "
            "interactive terminal to create the accounts."
        )

    print("Create the first NOC accounts (passwords must be at least 12 characters).")
    manager_username = input("Manager username: ").strip()
    manager_password = getpass.getpass("Manager password: ")
    worker_username = input("Worker username: ").strip()
    worker_password = getpass.getpass("Worker password: ")
    if manager_username.lower() == worker_username.lower():
        raise ValueError("Manager and worker usernames must be different.")
    create_account(manager_username, manager_password, "manager")
    create_account(worker_username, worker_password, "worker")
    print("Initial NOC manager and worker accounts created.")


def get_text(form_data, key, fallback=""):
    value = form_data.get(key)
    if value is None:
        return fallback
    return str(value).strip()


def map_tier_code(tier_value):
    tier_text = (tier_value or "").upper()
    if "GOLD" in tier_text:
        return "GOLD"
    if "BRONZE" in tier_text:
        return "BRONZE"
    if "CUSTOM" in tier_text or "MULTI" in tier_text:
        return "CUSTOM"
    return "SILVER"


def map_sector_code(company_name):
    name = (company_name or "").upper()
    if "BANK" in name or "FINANCE" in name:
        return "BANK"
    if "HOSPITAL" in name or "CLINIC" in name or "HEALTH" in name:
        return "HOSPITAL"
    if "HOTEL" in name or "RESORT" in name:
        return "HOTEL"
    if "REAL ESTATE" in name or "PROPERTY" in name or "BUILDING" in name:
        return "REAL_ESTATE"
    if "SCHOOL" in name or "UNIVERSITY" in name:
        return "EDUCATION"
    if "GOV" in name or "OFFICE" in name or "MINISTRY" in name:
        return "GOVT"
    return "SME"


def create_inquiry(form_data):
    company_name = get_text(form_data, "company_name")
    contact_person = get_text(form_data, "contact_person")
    phone_number = get_text(form_data, "phone_number")
    sub_city = get_text(form_data, "sub_city")
    if not all((company_name, contact_person, phone_number, sub_city)):
        raise ValueError("Company, contact person, phone number, and sub-city are required.")

    tier_code = map_tier_code(get_text(form_data, "preferred_tier", "SILVER"))
    inquiry_ref = "RAMA-SLA-{}-{:06d}".format(
        datetime.datetime.now().year,
        random.SystemRandom().randint(0, 999999),
    )
    connection = connect_database()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sla_inquiries (
                    inquiry_ref, company_name, contact_person, contact_title,
                    phone_number, email_address, sub_city, specific_address,
                    sector_code, preferred_tier_code, additional_requirements,
                    inquiry_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    inquiry_ref,
                    company_name,
                    contact_person,
                    get_text(form_data, "contact_title"),
                    phone_number,
                    get_text(form_data, "email"),
                    sub_city,
                    get_text(form_data, "specific_address"),
                    map_sector_code(company_name),
                    tier_code,
                    get_text(form_data, "additional_requirements"),
                    "PENDING_AUDIT",
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return inquiry_ref


def list_inquiries():
    connection = connect_database()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT i.inquiry_id, i.inquiry_ref, i.company_name,
                       i.contact_person, i.contact_title, i.phone_number,
                       i.email_address, i.sub_city, i.woreda,
                       i.specific_address, i.sector_code, s.sector_name,
                       i.preferred_tier_code, t.tier_name, t.response_time_p1,
                       i.estimated_switches, i.estimated_routers,
                       i.estimated_firewalls, i.estimated_access_points,
                       i.total_estimated_devices, i.inquiry_status,
                       i.additional_requirements, i.created_at, i.updated_at
                FROM sla_inquiries AS i
                INNER JOIN sla_tiers AS t
                    ON t.tier_code = i.preferred_tier_code
                INNER JOIN client_sectors AS s
                    ON s.sector_code = i.sector_code
                ORDER BY i.created_at DESC, i.inquiry_id DESC
                """
            )
            rows = cursor.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat(sep=" ")
            row["updated_at"] = row["updated_at"].isoformat(sep=" ")
        return rows
    finally:
        connection.close()


def get_dashboard_summary():
    connection = connect_database()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_inquiries,
                    COALESCE(SUM(inquiry_status IN ('Pending', 'PENDING_AUDIT', 'AUDIT_SCHEDULED', 'PROPOSAL_SENT')), 0) AS pending_audits,
                    COALESCE(SUM(inquiry_status IN ('Active', 'CONTRACT_ACTIVE')), 0) AS active_contracts,
                    COALESCE(SUM(preferred_tier_code = 'GOLD'), 0) AS gold_clients
                FROM sla_inquiries
                """
            )
            summary = cursor.fetchone()
            summary = {
                key: int(value or 0)
                for key, value in summary.items()
            }
            cursor.execute(
                """
                SELECT a.audit_id, i.inquiry_ref, i.company_name,
                       a.assigned_engineer_name, a.audit_date, a.audit_time,
                       a.audit_status, a.findings_summary,
                       a.fluke_test_passed, a.ups_health_check_passed
                FROM audit_schedules AS a
                INNER JOIN sla_inquiries AS i ON i.inquiry_id = a.inquiry_id
                WHERE a.audit_date >= CURDATE()
                  AND a.audit_status IN ('SCHEDULED', 'RESCHEDULED')
                ORDER BY a.audit_date, a.audit_time
                LIMIT 20
                """
            )
            audits = cursor.fetchall()
        for audit in audits:
            if audit["audit_date"] is not None:
                audit["audit_date"] = audit["audit_date"].isoformat()
            if audit["audit_time"] is not None:
                audit["audit_time"] = str(audit["audit_time"])
        return summary, audits
    finally:
        connection.close()


def delete_inquiry(inquiry_id):
    connection = connect_database()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM sla_inquiries WHERE inquiry_id = %s", (inquiry_id,)
            )
            deleted = cursor.rowcount
        connection.commit()
        return deleted > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_inquiry_status(inquiry_id, status):
    if status not in INQUIRY_STATUSES:
        raise ValueError("Status must be Active, Pending, Postponed, or Done.")

    connection = connect_database()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE sla_inquiries SET inquiry_status = %s WHERE inquiry_id = %s",
                (status, inquiry_id),
            )
            updated = cursor.rowcount
        connection.commit()
        return updated > 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class SlaRequestHandler(BaseHTTPRequestHandler):
    def send_json(self, status_code, payload, public_cors=False, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = self.headers.get("Origin")
        allowed_origin = origin == "null"
        if origin and origin != "null":
            parsed_origin = urlparse(origin)
            allowed_origin = parsed_origin.hostname in ("localhost", "127.0.0.1")
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token"
            )
            self.send_header("Vary", "Origin")
        if extra_headers:
            for name, value in extra_headers:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        content_type = self.headers.get("Content-Type", "").lower()
        try:
            if "application/json" in content_type:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON request body must be an object.")
                return payload
            values = parse_qs(raw_body.decode("utf-8") or "")
            return {
                key: value[0] if len(value) == 1 else value
                for key, value in values.items()
            }
        except (UnicodeDecodeError, ValueError):
            raise ValueError("Invalid request body.")
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON request body.")

    def get_session(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return None, None
        token = morsel.value
        now = datetime.datetime.utcnow().timestamp()
        with SESSIONS_LOCK:
            session = SESSIONS.get(token)
            if session and session["expires"] > now:
                return token, session
            SESSIONS.pop(token, None)
        return token, None

    def require_session(self, manager=False, csrf=False):
        token, session = self.get_session()
        if session is None:
            self.send_json(401, {"status": "error", "message": "Please sign in."})
            return None
        if manager and session["role"] != "manager":
            self.send_json(403, {"status": "error", "message": "Manager access required."})
            return None
        if csrf and not hmac.compare_digest(
            session["csrf"], self.headers.get("X-CSRF-Token", "")
        ):
            self.send_json(403, {"status": "error", "message": "Invalid security token. Refresh and try again."})
            return None
        return session

    def do_OPTIONS(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.send_json(204, {}, public_cors=True)
            return
        self.send_json(404, {"status": "error", "message": "Endpoint not found."})

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/noc_dashboard.html", "/noc-dashboard.html"):
            try:
                with open(os.path.join(WEB_ROOT, "noc-dashboard.html"), "rb") as page:
                    body = page.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except IOError:
                self.send_json(500, {"status": "error", "message": "NOC dashboard file is missing."})
            return

        if path.lower().endswith(".html"):
            page_name = os.path.basename(path)
            if page_name != path.lstrip("/"):
                self.send_json(404, {"status": "error", "message": "Page not found."})
                return
            page_path = os.path.join(WEB_ROOT, page_name)
            if not os.path.isfile(page_path):
                self.send_json(404, {"status": "error", "message": "Page not found."})
                return
            try:
                with open(page_path, "rb") as page:
                    body = page.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except IOError:
                self.send_json(500, {"status": "error", "message": "Could not read page."})
            return

        if path == "/api/noc/session":
            _, session = self.get_session()
            if session is None:
                self.send_json(200, {"authenticated": False})
            else:
                self.send_json(
                    200,
                    {
                        "authenticated": True,
                        "username": session["username"],
                        "role": session["role"],
                        "csrf_token": session["csrf"],
                    },
                )
            return

        if path == "/api/noc/inquiries":
            if self.require_session() is None:
                return
            try:
                self.send_json(200, {"inquiries": list_inquiries()})
            except pymysql.MySQLError:
                logging.exception("Could not load inquiries.")
                self.send_json(500, {"status": "error", "message": "Could not load inquiries."})
            return

        if path == "/api/noc/dashboard":
            if self.require_session() is None:
                return
            try:
                summary, audits = get_dashboard_summary()
                self.send_json(
                    200,
                    {
                        "summary": summary,
                        "inquiries": list_inquiries(),
                        "audits": audits,
                    },
                )
            except pymysql.MySQLError:
                logging.exception("Could not load NOC dashboard data.")
                self.send_json(
                    500,
                    {
                        "status": "error",
                        "message": "Could not load NOC dashboard data.",
                    },
                )
            return

        self.send_json(404, {"status": "error", "message": "Endpoint not found."})

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/submit-sla":
            try:
                payload = self.read_payload()
                result = self.save_public_inquiry(payload)
                self.send_json(201, result, public_cors=True)
            except ValueError as error:
                self.send_json(400, {"status": "error", "message": str(error)}, public_cors=True)
            except pymysql.MySQLError:
                logging.exception("Could not save SLA inquiry.")
                self.send_json(500, {"status": "error", "message": "Could not save SLA inquiry."}, public_cors=True)
            return

        if path == "/api/noc/login":
            try:
                payload = self.read_payload()
            except ValueError as error:
                self.send_json(400, {"status": "error", "message": str(error)})
                return
            username = get_text(payload, "username")
            password = payload.get("password", "")
            if not isinstance(password, str):
                password = ""
            try:
                connection = connect_database()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT username, password_hash, user_role
                            FROM noc_users
                            WHERE username = %s AND is_active = 1
                            """,
                            (username,),
                        )
                        account = cursor.fetchone()
                finally:
                    connection.close()
            except pymysql.MySQLError:
                logging.exception("Could not verify account.")
                self.send_json(500, {"status": "error", "message": "Could not verify account."})
                return

            password_is_valid = False
            needs_password_upgrade = False
            if account:
                password_is_valid, needs_password_upgrade = verify_account_password(
                    password, account[1]
                )
            if not password_is_valid:
                self.send_json(401, {"status": "error", "message": "Username or password is incorrect."})
                return

            if needs_password_upgrade:
                connection = connect_database()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE noc_users SET password_hash = %s WHERE username = %s",
                            (make_password_hash(password), username),
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

            token = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
            csrf = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
            with SESSIONS_LOCK:
                SESSIONS[token] = {
                    "username": account[0],
                    "role": account[2],
                    "csrf": csrf,
                    "expires": datetime.datetime.utcnow().timestamp() + SESSION_LIFETIME_SECONDS,
                }
            secure_cookie = "; Secure" if self.headers.get("Origin", "").startswith("https://") else ""
            cookie_value = "{}={}; Path=/; HttpOnly; SameSite=Lax{}; Max-Age={}".format(
                SESSION_COOKIE, token, secure_cookie, SESSION_LIFETIME_SECONDS
            )
            self.send_json(
                200,
                {
                    "status": "success",
                    "username": account[0],
                    "role": account[2],
                    "csrf_token": csrf,
                },
                extra_headers=[("Set-Cookie", cookie_value)],
            )
            return

        if path == "/api/noc/logout":
            session = self.require_session(csrf=True)
            if session is None:
                return
            token, _ = self.get_session()
            with SESSIONS_LOCK:
                SESSIONS.pop(token, None)
            self.send_json(
                200,
                {"status": "success"},
                extra_headers=[
                    (
                        "Set-Cookie",
                        "{}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0".format(SESSION_COOKIE),
                    )
                ],
            )
            return

        if path == "/api/noc/inquiries":
            session = self.require_session(manager=True, csrf=True)
            if session is None:
                return
            try:
                inquiry_ref = create_inquiry(self.read_payload())
                self.send_json(201, {"status": "success", "inquiry_ref": inquiry_ref})
            except ValueError as error:
                self.send_json(400, {"status": "error", "message": str(error)})
            except pymysql.MySQLError:
                logging.exception("Could not add inquiry.")
                self.send_json(500, {"status": "error", "message": "Could not add inquiry."})
            return

        status_match = re.match(r"^/api/noc/inquiries/([0-9]+)/status$", path)
        if status_match:
            if self.require_session(manager=True, csrf=True) is None:
                return
            try:
                payload = self.read_payload()
                status = payload.get("status")
                if not isinstance(status, str):
                    raise ValueError("A valid inquiry status is required.")
                updated = update_inquiry_status(int(status_match.group(1)), status)
            except ValueError as error:
                self.send_json(400, {"status": "error", "message": str(error)})
                return
            except pymysql.MySQLError:
                logging.exception("Could not update inquiry status.")
                self.send_json(
                    500,
                    {
                        "status": "error",
                        "message": "Could not update inquiry status.",
                    },
                )
                return
            if not updated:
                self.send_json(404, {"status": "error", "message": "Inquiry not found."})
                return
            self.send_json(200, {"status": "success", "inquiry_status": status})
            return

        self.send_json(404, {"status": "error", "message": "Endpoint not found."})

    def do_DELETE(self):
        match = re.match(r"^/api/noc/inquiries/([0-9]+)$", urlparse(self.path).path)
        if not match:
            self.send_json(404, {"status": "error", "message": "Endpoint not found."})
            return
        if self.require_session(manager=True, csrf=True) is None:
            return
        try:
            deleted = delete_inquiry(int(match.group(1)))
        except pymysql.MySQLError:
            logging.exception("Could not delete inquiry.")
            self.send_json(500, {"status": "error", "message": "Could not delete inquiry."})
            return
        if not deleted:
            self.send_json(404, {"status": "error", "message": "Inquiry not found."})
            return
        self.send_json(200, {"status": "success"})

    def save_public_inquiry(self, form_data):
        company_name = get_text(form_data, "company_name", "Unknown Enterprise")
        contact_person = get_text(form_data, "contact_person", "IT Manager")
        phone_number = get_text(form_data, "phone_number", "+251 900000000")
        sub_city = get_text(form_data, "sub_city", "Bole")
        preferred_tier = get_text(
            form_data,
            "preferred_tier",
            get_text(form_data, "primary_need", "Silver SLA"),
        )
        inquiry_ref = "RAMA-SLA-{}-{:06d}".format(
            datetime.datetime.now().year,
            random.SystemRandom().randint(0, 999999),
        )
        connection = connect_database()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sla_inquiries (
                        inquiry_ref, company_name, contact_person, contact_title,
                        phone_number, email_address, sub_city, specific_address,
                        sector_code, preferred_tier_code, additional_requirements,
                        inquiry_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending')
                    """,
                    (
                        inquiry_ref,
                        company_name,
                        contact_person,
                        get_text(form_data, "contact_title", "Procurement / IT Lead"),
                        phone_number,
                        get_text(form_data, "email", get_text(form_data, "email_address", "info@client.et")),
                        sub_city,
                        get_text(form_data, "specific_address", get_text(form_data, "address", "Addis Ababa")),
                        map_sector_code(company_name),
                        map_tier_code(preferred_tier),
                        get_text(form_data, "requirements", get_text(form_data, "estimated_devices", "Requested via web portal form.")),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {
            "status": "success",
            "inquiry_ref": inquiry_ref,
            "tier_selected": map_tier_code(preferred_tier),
            "message": (
                "SLA inquiry received successfully. Reference ID: {}. "
                "RAMA SLA Team will contact you within 2 hours.".format(inquiry_ref)
            ),
        }

    def log_message(self, format_string, *args):
        return


if __name__ == "__main__":
    ensure_database()
    host = os.environ.get("RAMA_API_HOST", "127.0.0.1")
    port = int(os.environ.get("RAMA_API_PORT", "8001"))
    print(
        "Starting RAMA SLA and NOC API at http://{}:{}/noc-dashboard.html "
        "using MySQL database '{}'.".format(host, port, DB_NAME)
    )
    HTTPServer((host, port), SlaRequestHandler).serve_forever()
