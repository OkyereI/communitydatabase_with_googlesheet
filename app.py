import os
import random
import string
import secrets
import requests
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import urllib.parse
import re
import gspread
# We'll use service_account.Credentials directly, but import necessary for clarity
from google.oauth2.service_account import Credentials
import json # Import json to parse credentials from env var

from flask import Flask, redirect, url_for, flash, request, render_template, Response, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.actions import action
from flask_admin.contrib.sqla import ModelView
from flask_admin.contrib.sqla.filters import FilterLike, DateBetweenFilter
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, IntegerField, BooleanField, SubmitField, PasswordField, DateField
from wtforms.validators import DataRequired, Length, Optional, Regexp, Email, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from sqlalchemy import func
from markupsafe import Markup
from sqlalchemy.exc import IntegrityError

# For Excel export
import pandas as pd
from io import BytesIO
import xlsxwriter

# For loading environment variables (like DATABASE_URL) from .env file
from dotenv import load_dotenv
load_dotenv()

# --- GLOBAL VARIABLES & SETUP ---
basedir = os.path.abspath(os.path.dirname(__file__))

# Ensure necessary folders exist
instance_path = os.path.join(basedir, 'instance')
os.makedirs(instance_path, exist_ok=True)
os.makedirs(os.path.join(basedir, 'templates', 'admin'), exist_ok=True)

# Initialize Flask app
app = Flask(__name__, instance_relative_config=True)
app.config.from_object('config.Config')

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"

# Global variables for gspread client (initialized once)
_gspread_client = None
_google_sheet = None

# --- Google Sheets Integration ---
# Define the scopes required for Google Sheets API access
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheet_client():
    """
    Initializes and returns a gspread client and the target Google Worksheet.
    Handles authentication using a service account credentials from an environment variable.
    """
    global _gspread_client, _google_sheet

    if _gspread_client and _google_sheet:
        return _gspread_client, _google_sheet

    google_sheet_url = app.config.get('GOOGLE_SHEET_URL')
    # NEW: Get service account JSON string directly from environment variable
    service_account_json_str = os.getenv('GOOGLE_CREDENTIALS_JSON')

    if not google_sheet_url:
        app.logger.error("Google Sheet URL not configured.")
        return None, None

    if not service_account_json_str:
        app.logger.error("GOOGLE_CREDENTIALS_JSON environment variable not set. Cannot connect to Google Sheets.")
        return None, None

    try:
        # Parse the JSON string from the environment variable
        creds_info = json.loads(service_account_json_str)
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        _gspread_client = gspread.authorize(creds)
        _google_sheet = _gspread_client.open_by_url(google_sheet_url).sheet1
        app.logger.info("Successfully connected to Google Sheet using environment credentials.")
        return _gspread_client, _google_sheet
    except json.JSONDecodeError as e:
        app.logger.error(f"Failed to parse GOOGLE_CREDENTIALS_JSON: {e}. Ensure it's valid JSON.", exc_info=True)
        return None, None
    except Exception as e:
        app.logger.error(f"Failed to initialize Google Sheets client (check credentials or network): {e}", exc_info=True)
        return None, None

# --- User Model for Admin Authentication ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

# --- Flask-Login user loader ---
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- CommunityMember Model ---
class CommunityMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=True)
    gender = db.Column(db.String(10), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    employment_status = db.Column(db.String(50), nullable=True)
    profession = db.Column(db.String(100), nullable=True)
    employer = db.Column(db.String(100), nullable=True)
    parent_guardian_name = db.Column(db.String(200), nullable=True)
    parent_guardian_contact = db.Column(db.String(20), nullable=True)
    parent_guardian_address = db.Column(db.Text, nullable=True)
    date_of_birth = db.Column(db.Date, nullable=False)
    residence = db.Column(db.Text, nullable=True) # Changed to Text for consistency
    area_code = db.Column(db.String(10), nullable=False)
    is_verified = db.Column(db.Boolean, default=False) # RE-ADDED: is_verified column
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    verification_code = db.Column(db.String(20), unique=True, nullable=True)
    id_card_number = db.Column(db.String(50), unique=True, nullable=False)
    educational_level = db.Column(db.String(50), nullable=True) # Existing educational_level column


    def __repr__(self):
        return f'<CommunityMember {self.first_name} {self.last_name}>'

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def to_dict(self):
        # Helper to convert ORM object to a dictionary for JSON/Google Sheets
        return {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'phone_number': self.phone_number,
            'gender': self.gender,
            'email': self.email,
            'employment_status': self.employment_status,
            'profession': self.profession,
            'employer': self.employer,
            'parent_guardian_name': self.parent_guardian_name,
            'parent_guardian_contact': self.parent_guardian_contact,
            'parent_guardian_address': self.parent_guardian_address,
            'date_of_birth': self.date_of_birth.strftime('%Y-%m-%d') if self.date_of_birth else '',
            'residence': self.residence,
            'area_code': self.area_code,
            'is_verified': self.is_verified, # Keep as boolean for internal use
            'registration_date': self.registration_date.strftime('%Y-%m-%d %H:%M:%S') if self.registration_date else '',
            'verification_code': self.verification_code,
            'id_card_number': self.id_card_number,
            'educational_level': self.educational_level
        }


# --- Verification Code Generation ---
def generate_verification_code(area_code: str) -> str:
    # Ensure area_code is uppercase and truncate/pad to 3 characters
    normalized_area_code = area_code.strip().upper()
    if len(normalized_area_code) > 3:
        normalized_area_code = normalized_area_code[:3]
    elif len(normalized_area_code) < 3:
        normalized_area_code = normalized_area_code.ljust(3, 'X') # Pad with 'X' or '0'

    # Generate 2 random hexadecimal characters
    random_suffix = secrets.token_hex(1).upper() # secrets.token_hex(1) gives 2 hex chars (e.g., 'A3')

    # Base prefix as requested
    base_string = "KN1YA"

    # Combine to form the 10-character verification code
    # KN1YA (5) + AreaCode (3) + Random (2) = 10 chars
    return f"{base_string}{normalized_area_code}{random_suffix}"

# --- SMS Sending Function ---
def send_sms(recipient: str, message: str, verification_code: str = "", full_name: str = "") -> bool:
    app.logger.info("DEBUG: Entering send_sms function. Using GET request logic.")

    api_key = app.config.get('ARKESEL_API_KEY')
    sender_id = app.config.get('ARKESEL_SENDER_ID')
    url = "https://sms.arkesel.com/sms/api"

    if not api_key or not sender_id:
        app.logger.error("ARKESEL_API_KEY or ARKESEL_SENDER_ID not configured. SMS sending disabled.")
        return False

    if recipient:
        recipient = recipient.strip()
        # Normalize phone number to start with '233' and then add '+'
        if recipient.startswith('+'):
            recipient = recipient.lstrip('+') # Remove leading '+' for normalization
        if recipient.startswith('0'):
            recipient = '233' + recipient[1:]
        elif not recipient.startswith('233'):
            recipient = '233' + recipient
        recipient = '+' + recipient # Add '+' back for Arkesel API
    else:
        app.logger.warning("Attempted to send SMS to an empty recipient number.")
        return False

    final_message_parts = []

    if verification_code:
        final_message_parts.append(f"Verification code: {verification_code}")

    if full_name:
        final_message_parts.append(f"Name: {full_name}")

    if (verification_code or full_name) and message.strip():
        final_message_parts.append(".....................................")

    if message.strip():
        final_message_parts.append(message.strip())

    final_message_parts.append("From: Kenyasi N1 Youth association")

    final_message = "\n".join(final_message_parts)

    payload = {
        "action": "send-sms",
        "api_key": api_key,
        "to": recipient,
        "from": sender_id,
        "sms": final_message
    }

    try:
        app.logger.info(f"Attempting to send SMS to {recipient} with message: \n'{final_message}'\n using GET request.")
        response = requests.get(url, params=payload)

        if not response.ok:
            app.logger.error(f"Arkesel API returned non-success HTTP status {response.status_code}.")
            app.logger.error(f"Arkesel Raw Response Text: {response.text}")
            try:
                error_data = response.json()
                app.logger.error(f"Arkesel Parsed Error JSON: {error_data}")
            except requests.exceptions.JSONDecodeError:
                app.logger.error("Arkesel response could not be parsed as JSON.")
            return False

        response_data = response.json()
        if response_data.get('code') == 'ok':
            app.logger.info(f"SMS sent successfully to {recipient}. Arkesel response: {response_data}")
            return True
        else:
            error_code = response_data.get('code', 'N/A')
            error_message = response_data.get('message', 'No specific message from Arkesel.')
            app.logger.error(f"Failed to send SMS to {recipient}. Arkesel API responded with code: '{error_code}', message: '{error_message}'. Full response: {response_data}")
            return False
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error sending SMS to {recipient}: {e}")
        return False


# --- Custom Age Validator ---
def validate_age_range(form, field):
    today = date.today()
    if field.data:
        age = relativedelta(today, field.data).years
        if not (18 <= age <= 45):
            raise ValidationError('Member must be between 18 and 45 years old.')

# --- Flask Forms (Global Scope) ---
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Login')

class CommunityMemberForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired(), Length(max=100)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(max=100)])
    date_of_birth = DateField('Date of Birth (YYYY-MM-DD)', format='%Y-%m-%d', validators=[DataRequired(), validate_age_range])
    gender = SelectField('Gender', choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')], validators=[DataRequired()])
    phone_number = StringField('Phone Number', validators=[Optional(), Length(max=20)])
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])
    residence = TextAreaField('Residence', validators=[Optional()])
    employment_status = SelectField('Employment Status', choices=[
        ('Employed', 'Employed'), ('Unemployed', 'Unemployed'),
        ('Student', 'Student'), ('Retired', 'Retired'), ('Other', 'Other')
    ], validators=[Optional()])
    profession = StringField('Profession', validators=[Optional(), Length(max=100)])
    employer = StringField('Employer', validators=[Optional(), Length(max=100)])
    parent_guardian_name = StringField('Parent/Guardian Name', validators=[Optional(), Length(max=200)])
    parent_guardian_contact = StringField('Parent/Guardian Contact', validators=[Optional(), Length(max=20)])
    parent_guardian_address = TextAreaField('Parent/Guardian Address', validators=[Optional()])
    area_code = StringField('Area Code', validators=[DataRequired(), Length(min=1, max=10, message="Area Code is required and should be max 10 characters")])
    id_card_number = StringField('ID Card Number', validators=[DataRequired(), Length(max=50)])
    educational_level = SelectField('Educational Level', choices=[
        ('None', 'None'),
        ('Primary School', 'Primary School'),
        ('Junior High School', 'Junior High School'),
        ('Senior High School', 'Senior High School'),
        ('Vocational/Technical', 'Vocational/Technical'),
        ('Diploma', 'Diploma'),
        ('Bachelor\'s Degree', 'Bachelor\'s Degree'),
        ('Master\'s Degree', 'Master\'s Degree'),
        ('PhD', 'PhD'),
        ('Other', 'Other')
    ], validators=[Optional()])
    submit = SubmitField('Submit')

class SendAllMessagesForm(FlaskForm):
    message = TextAreaField('Message to All Members', validators=[DataRequired(), Length(min=10, max=1600)],
                            render_kw={"placeholder": "Enter your message here. The system will automatically add the member's Verification Code and Name as a header, and 'From: Kenyasi N1 Youth association' as a footer."})
    submit = SubmitField('Send Message to All')

class CustomPagination:
    def __init__(self, items, page, per_page, total, sort_field=None, sort_desc=None, search_query=None, filter_args=None):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.sort_field = sort_field
        self.sort_desc = sort_desc
        self.search_query = search_query
        self.filter_args = filter_args if filter_args is not None else []

        self.num_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
        self.has_prev = self.page > 0
        self.has_next = (self.page + 1) * self.per_page < self.total
        self.offset = self.page * self.per_page
        self.count = len(items)

    def iter_pages(self, left_edge=2, right_edge=2, left_current=2, right_current=3):
        last_page = self.num_pages - 1
        for num in range(0, self.num_pages):
            if num < left_edge or \
               (num > self.page - left_current - 1 and \
                num < self.page + right_current) or \
               num > last_page - right_edge:
                yield num
            else:
                yield None

# --- Flask-Admin Custom View Definitions (MUST be defined before Admin initialization) ---
class MyAdminIndexView(AdminIndexView):
    @expose('/')
    @login_required
    def index(self):
        total_members = db.session.query(CommunityMember).count()
        employment_status_stats = db.session.query(
            CommunityMember.employment_status, func.count(CommunityMember.id)
        ).group_by(CommunityMember.employment_status).all()
        employment_status_dict = {
            status if status else 'Not Specified': count
            for status, count in employment_status_stats
        }
        gender_stats = db.session.query(
            CommunityMember.gender, func.count(CommunityMember.id)
        ).group_by(CommunityMember.gender).all()
        gender_dict = {
            gender if gender else 'Not Specified': count
            for gender, count in gender_stats
        }
        area_code_stats = db.session.query(
            CommunityMember.area_code, func.count(CommunityMember.id)
        ).group_by(CommunityMember.area_code).order_by(func.count(CommunityMember.id).desc()).limit(5).all()
        area_code_dict = {
            code if code else 'Not Specified': count
            for code, count in area_code_stats
        }
        profession_stats = db.session.query(
            CommunityMember.profession, func.count(CommunityMember.id)
        ).group_by(CommunityMember.profession).order_by(func.count(CommunityMember.id).desc()).all()
        profession_dict = {
            prof if prof and prof.strip() else 'Not Specified': count
            for prof, count in profession_stats
        }
        educational_level_raw = db.session.query(CommunityMember.educational_level, func.count(CommunityMember.id)).group_by(CommunityMember.educational_level).all()
        educational_level_dict = {el: c for el, c in educational_level_raw if el is not None}


        stats = {
            'total_members': total_members,
            'employment_status': employment_status_dict,
            'gender': gender_dict,
            'area_code': area_code_dict,
            'professions': profession_dict,
            'educational_level': educational_level_dict
        }
        return self.render('admin/index.html', stats=stats)


class CommunityMemberView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        flash('You need to log in to access the admin panel.', 'warning')
        return redirect(url_for('login', next=request.url))

    can_create = True
    can_edit = True
    can_delete = True
    can_export = True

    column_list = [
        'first_name', 'last_name', 'phone_number', 'gender', 'email', 'employment_status', 'profession',
        'employer', 'parent_guardian_name', 'parent_guardian_contact', 'parent_guardian_address',
        'date_of_birth', 'residence', 'area_code', 'is_verified', 'registration_date',
        'verification_code', 'id_card_number', 'educational_level', '_actions'
    ]
    column_searchable_list = [
        'first_name', 'last_name', 'phone_number', 'email', 'residence',
        'profession', 'employer', 'area_code', 'verification_code', 'id_card_number', 'educational_level'
    ]

    column_filters = [
        FilterLike(CommunityMember.first_name, 'First Name'),
        FilterLike(CommunityMember.last_name, 'Last Name'),
        FilterLike(CommunityMember.gender, 'Gender'),
        FilterLike(CommunityMember.employment_status, 'Employment Status'),
        FilterLike(CommunityMember.area_code, 'Area Code'),
        FilterLike(CommunityMember.verification_code, 'Verification Code'),
        FilterLike(CommunityMember.id_card_number, 'ID Card Number'),
        FilterLike(CommunityMember.educational_level, 'Educational Level'),
        DateBetweenFilter(CommunityMember.registration_date, 'Registration Date'),
        FilterLike(CommunityMember.is_verified, 'Is Verified') # Added filter for is_verified
    ]
    column_sortable_list = ['first_name', 'last_name', 'registration_date', 'date_of_birth', 'educational_level']

    form = CommunityMemberForm

    list_template = 'admin/community_member_list.html'

    actions = ['send_sms_action', 'print_info_action']

    def _actions_formatter(self, context, model, name):
        edit_url = self.get_url('.edit_view', id=model.id, url=self.get_save_return_url(model, False))
        delete_url = self.get_url('.delete_view', id=model.id, url=self.get_save_return_url(model, False))
        send_sms_url = self.get_url('.send_sms_view', member_id=model.id)
        # Corrected URL for print_member_info route, uses app.route directly
        print_url = url_for('print_member_info', member_id=model.id)

        return Markup(f'''
            <a href="{edit_url}" class="btn btn-xs btn-primary" title="Edit record">
                <span class="glyphicon glyphicon-pencil"></span>
            </a>
            <form class="icon" method="POST" action="{delete_url}">
                <button onclick="return confirm('Are you sure you want to delete this record?');" class="btn btn-xs btn-danger" title="Delete record">
                    <span class="glyphicon glyphicon-trash"></span>
                </button>
            </form>
            <a href="{send_sms_url}" class="btn btn-xs btn-warning" title="Send SMS">
                <span class="glyphicon glyphicon-comment"></span> SMS
            </a>
            <a href="{print_url}" class="btn btn-xs btn-info" title="Print Info" target="_blank">
                <span class="glyphicon glyphicon-print"></span> Print
            </a>
        ''')

    column_formatters = {
        '_actions': _actions_formatter
    }

    def get_save_return_url(self, model, is_created):
        return_url_param = request.args.get('url')

        if return_url_param:
            decoded_url = urllib.parse.unquote(return_url_param)
            cleaned_url = re.sub(r'\s+', '', decoded_url).strip()
            if cleaned_url and not cleaned_url.startswith('/'):
                cleaned_url = '/' + cleaned_url
            final_redirect_url = cleaned_url if cleaned_url else url_for('.index_view')
        else:
            final_redirect_url = url_for('.index_view')

        app.logger.warning(f"Final redirect URL after sanitization: '{final_redirect_url}'")
        return final_redirect_url

    @expose('/')
    @login_required
    def index_view(self, **kwargs):
        page = request.args.get('page', type=int, default=0)
        per_page = self.page_size
        sort_field = request.args.get('sort', type=str)
        sort_desc = request.args.get('sort_desc', type=bool, default=False)

        search_query = request.args.get('search', type=str)

        query = self.get_query()

        if search_query and self.column_searchable_list:
            search_filter_clauses = []
            for col_name in self.column_searchable_list:
                col = getattr(self.model, col_name, None)
                if col is not None:
                    search_filter_clauses.append(col.ilike(f'%{search_query}%'))
            if search_filter_clauses:
                query = query.filter(db.or_(*search_filter_clauses))

        active_filters = []
        for i in range(5):
            flt_col_key = f'flt{i}_0'
            flt_op_key = f'flt{i}_1'
            flt_val_key = f'flt{i}_2'

            column_name = request.args.get(flt_col_key)
            operation = request.args.get(flt_op_key)
            value = request.args.get(flt_val_key)

            if column_name and operation and value:
                for filter_obj in self.column_filters:
                    if hasattr(filter_obj, 'column') and filter_obj.column.key == column_name and filter_obj.operation == operation:
                        query = filter_obj.apply(query, value)
                        active_filters.append({
                            'column': column_name,
                            'operation': operation,
                            'value': value,
                            'name': filter_obj.name
                        })
                        break
                    # For simple equality filters on Enum/String columns, the column name is sufficient
                    elif hasattr(filter_obj, 'column') and filter_obj.column.key == column_name and operation == 'eq':
                        col = getattr(self.model, column_name, None)
                        if col is not None:
                            query = query.filter(col == value)
                            active_filters.append({
                                'column': column_name,
                                'operation': operation,
                                'value': value,
                                'name': filter_obj.name # You might need a way to get a readable name for this filter
                            })
                            break


        if sort_field:
            sort_column = getattr(self.model, sort_field, None)
            if sort_column is not None:
                if sort_desc:
                    query = query.order_by(sort_column.desc())
                else:
                    query = query.order_by(sort_column.asc())

        total_count = query.count()

        items = query.limit(per_page).offset(page * per_page).all()

        model_list = CustomPagination(
            items,
            page,
            per_page,
            total_count,
            sort_field=sort_field,
            sort_desc=sort_desc,
            search_query=search_query,
            filter_args=active_filters
        )

        template_context = {
            'model_list': model_list,
            'list_columns': self._list_columns,
            'column_filters': self.column_filters,
            'filters': active_filters,
            'admin_view': self,
            'can_create': self.can_create,
            'can_edit': self.can_edit,
            'can_delete': self.can_delete,
            'can_view_details': self.can_view_details,
            'search_supported': True if self.column_searchable_list else False,
            'can_export': self.can_export,
            'actions': self.get_actions_list(),
            'page_size': self.page_size,
            'endpoint': self.endpoint,
            'name': self.name,
            'edit_modal': self.edit_modal,
            'create_modal': self.create_modal,
            'column_display_actions': True,
            **kwargs
        }

        return self.render(self.list_template, **template_context)

    def create_model(self, form):
        try:
            model = self.model()
            form.populate_obj(model)
            model.verification_code = generate_verification_code(model.area_code)

            # Set is_verified based on whether ID card number is provided
            model.is_verified = bool(model.id_card_number)

            self.session.add(model)
            self._on_model_change(form, model, True)
            self.session.commit()
            flash('Community member created successfully!', 'success')

            # NEW: Append to Google Sheet
            gs_client, gs_sheet = get_google_sheet_client()
            if gs_sheet:
                try:
                    # Define headers that match your Google Sheet's first row
                    # Ensure this order matches the order you want data to appear
                    headers = [
                        'ID', 'First Name', 'Last Name', 'Phone Number', 'Gender', 'Email',
                        'Employment Status', 'Profession', 'Employer', 'Parent/Guardian Name',
                        'Parent/Guardian Contact', 'Parent/Guardian Address', 'Date of Birth',
                        'Residence', 'Area Code', 'Is Verified', 'Registration Date',
                        'Verification Code', 'ID Card Number', 'Educational Level'
                    ]

                    # Get current headers from the sheet to ensure they match
                    current_sheet_headers = gs_sheet.row_values(1)
                    if not current_sheet_headers or current_sheet_headers != headers:
                        if not current_sheet_headers:
                            gs_sheet.append_row(headers)
                            app.logger.info("Google Sheet header row added.")
                        else:
                            flash("Google Sheet headers mismatch. Data might be misaligned in the sheet. Please ensure your Google Sheet's first row matches the expected headers.", "warning")
                            app.logger.warning("Google Sheet headers do not match expected structure.")

                    member_data = [
                        model.id,
                        model.first_name,
                        model.last_name,
                        model.phone_number,
                        model.gender,
                        model.email,
                        model.employment_status,
                        model.profession,
                        model.employer,
                        model.parent_guardian_name,
                        model.parent_guardian_contact,
                        model.parent_guardian_address,
                        model.date_of_birth.strftime('%Y-%m-%d') if model.date_of_birth else '',
                        model.residence,
                        model.area_code,
                        'TRUE' if model.is_verified else 'FALSE', # Convert boolean to string for Google Sheet
                        model.registration_date.strftime('%Y-%m-%d %H:%M:%S') if model.registration_date else '',
                        model.verification_code,
                        model.id_card_number,
                        model.educational_level
                    ]
                    gs_sheet.append_row(member_data)
                    flash(f'Member {model.full_name} also added to Google Sheet.', 'info')
                except Exception as gs_ex:
                    flash(f"Error appending to Google Sheet: {gs_ex}. Check server logs.", "error")
                    app.logger.error(f"Error appending to Google Sheet: {gs_ex}")
            else:
                flash("Google Sheets client not available. Member not added to sheet.", "warning")

            if model.phone_number:
                welcome_message = "You are registered. Your verification code is: {verification_code}"
                if send_sms(model.phone_number, welcome_message,
                            verification_code=model.verification_code,
                            full_name=model.full_name):
                    flash(f'Welcome SMS sent to {model.full_name} ({model.phone_number})', 'info')
                else:
                    flash(f'Failed to send welcome SMS to {model.full_name}. Check logs for details.', 'warning')
            else:
                flash(f'No phone number for {model.full_name}. Welcome SMS not sent.', 'warning')

            return True
        except IntegrityError as ex:
            self.session.rollback()
            if 'phone_number' in str(ex) and 'unique constraint' in str(ex).lower():
                flash('A member with this phone number already exists.', 'error')
            elif 'email' in str(ex) and 'unique constraint' in str(ex).lower():
                flash('A member with this email already exists.', 'error')
            elif 'id_card_number' in str(ex) and 'unique constraint' in str(ex).lower():
                flash('A member with this ID Card Number already exists.', 'error')
            else:
                flash(f'Failed to create record: {str(ex)}', 'error')
            app.logger.error(f"IntegrityError creating community member: {ex}")
            return False
        except Exception as ex:
            self.session.rollback()
            flash(f'Failed to create record: {str(ex)}', 'error')
            app.logger.error(f"Error creating community member: {ex}")
            return False

    def update_model(self, form, model):
        try:
            old_area_code = model.area_code
            form.populate_obj(model)
            if old_area_code != model.area_code:
                model.verification_code = generate_verification_code(model.area_code)

            # Update is_verified on update too
            model.is_verified = bool(model.id_card_number)

            self._on_model_change(form, model, False)
            self.session.commit()
            flash('Community member updated successfully!', 'success')
            # NOTE: Updating records in Google Sheets is more complex than appending.
            # It requires finding the row by a unique identifier (like ID) in the sheet,
            # which can be slow and error-prone for large sheets.
            # This example only appends new records. For updates, you'd implement
            # a search and update logic here (e.g., gs_sheet.update_cell(row, col, value))
            # after locating the correct row.
            flash("Google Sheet updates are currently not fully synchronized for existing records. Only new records are appended.", "info")

            return True
        except IntegrityError as ex:
            self.session.rollback()
            if 'phone_number' in str(ex) and 'unique constraint' in str(ex).lower():
                flash('A member with this phone number already exists.', 'error')
            elif 'email' in str(ex) and 'unique constraint' in str(ex).lower():
                flash('A member with this email already exists.', 'error')
            elif 'id_card_number' in str(ex) and 'unique constraint' in str(ex).lower():
                flash('A member with this ID Card Number already exists.', 'error')
            else:
                flash(f'Failed to update record: {str(ex)}', 'error')
            app.logger.error(f"IntegrityError updating community member: {ex}")
            return False
        except Exception as ex:
            self.session.rollback()
            flash(f'Failed to update record: {str(ex)}', 'error')
            app.logger.error(f"Error updating community member: {ex}")
            return False

    def delete_model(self, model):
        try:
            # OPTIONAL: Implement deletion from Google Sheet here if needed
            # This would also require searching for the row and then deleting it.
            # For simplicity, we're only deleting from PostgreSQL for now.
            db.session.delete(model)
            self._on_model_delete(model)
            db.session.commit()
            flash('Community member deleted successfully!', 'success')
            return True
        except Exception as ex:
            self.session.rollback()
            flash(f'Failed to delete record: {str(ex)}', 'error')
            app.logger.error(f"Error deleting community member: {ex}")
            return False

    @expose('/send_sms/<int:member_id>', methods=['GET', 'POST'])
    @login_required
    def send_sms_view(self, member_id):
        member = db.session.get(CommunityMember, member_id)
        if not member:
            flash('Member not found.', 'danger')
            return redirect(url_for('.index_view')) # Corrected: use relative Flask-Admin URL

        # IMPORTANT: This form definition needs to be at the global scope, not inside the route.
        # This is a common Flask-WTF pattern. Let's assume it is or will be.
        class IndividualSMSForm(FlaskForm):
            message = TextAreaField('Message', validators=[DataRequired(), Length(min=10, max=1600)])
            submit = SubmitField('Send SMS')

        form = IndividualSMSForm()
        if form.validate_on_submit():
            message_text = form.message.data
            if member.phone_number:
                if send_sms(member.phone_number, message_text,
                            verification_code=member.verification_code,
                            full_name=member.full_name):
                    flash(f'SMS sent to {member.full_name} successfully!', 'success')
                else:
                    flash(f'Failed to send SMS to {member.full_name}. Check server logs.', 'danger')
            else:
                flash(f'No phone number for {member.full_name}. SMS not sent.', 'warning')
            return redirect(url_for('.index_view')) # Corrected: use relative Flask-Admin URL

        return self.render('admin/send_individual_sms.html', form=form, member=member)


    @expose('/send_all_messages', methods=['GET', 'POST'])
    @login_required
    def send_all_messages_view(self):
        form = SendAllMessagesForm()
        if form.validate_on_submit():
            message_text = form.message.data
            members = db.session.query(CommunityMember).all()

            successful_sends = 0
            failed_sends = 0
            no_contact_count = 0

            for member in members:
                if member.phone_number:
                    if send_sms(member.phone_number, message_text,
                                verification_code=member.verification_code,
                                full_name=member.full_name):
                        successful_sends += 1
                    else:
                        failed_sends += 1
                else:
                    no_contact_count += 1

            flash(f'Bulk SMS operation completed: {successful_sends} sent, {failed_sends} failed, {no_contact_count} members had no phone number.', 'info')
            return redirect(url_for('admin.index'))

        return self.render('admin/send_all_messages_form.html', form=form)


    @action('send_sms_action', 'Send SMS to Selected', 'Are you sure you want to send SMS to selected members?')
    def send_sms_action(self, ids):
        if not ids:
            flash('No members selected for SMS.', 'warning')
            return redirect(request.url)

        members = db.session.query(CommunityMember).filter(CommunityMember.id.in_(ids)).all()

        sent_count = 0
        failed_count = 0

        generic_message = "A general update from Kenyasi N1 Youth Association."

        for member in members:
            if member.phone_number:
                if send_sms(member.phone_number, generic_message,
                            verification_code=member.verification_code,
                            full_name=member.full_name):
                    sent_count += 1
                else:
                    failed_count += 1
            else:
                flash(f'No phone number for {member.full_name}. Skipping SMS.', 'warning')

        if sent_count > 0:
            flash(f'Successfully sent SMS to {sent_count} members.', 'success')
        if failed_count > 0:
            flash(f'Failed to send SMS to {failed_count} members. Check logs.', 'danger')

        return redirect(request.url)

    @action('print_info_action', 'Print Selected Info', 'Are you sure you want to print information for selected members?')
    def print_info_action(self, ids):
        if not ids:
            flash('No members selected for printing.', 'warning')
            return redirect(request.url)

        members = db.session.query(CommunityMember).filter(CommunityMember.id.in_(ids)).all()
        member_names = ", ".join([m.full_name for m in members])
        flash(f'Information for {member_names} marked for printing. (Implementation for batch printing needs to be added)', 'info')
        return redirect(request.url)


# --- GLOBAL VERIFICATION FUNCTION (checks both DB and Google Sheet) ---
def verify_member_details(verification_code: str, first_name: str, last_name: str,
                          area_code: str, residence: str) -> dict:
    """
    Verifies a member's details against both PostgreSQL and Google Sheets.
    Returns a dictionary indicating verification status and member info if successful.
    """
    verification_code = verification_code.strip().upper()
    first_name = first_name.strip().lower()
    last_name = last_name.strip().lower()
    area_code = area_code.strip().lower()
    residence = residence.strip().lower() # Assuming 'residence' encompasses city and street

    # 1. Try to verify against PostgreSQL
    try:
        member_pg = db.session.query(CommunityMember).filter(
            CommunityMember.verification_code == verification_code,
            CommunityMember.is_verified == True # Only verified members
        ).first()

        if member_pg:
            # Check other details for PostgreSQL
            # We are allowing permutation of first and last names for flexibility in input
            if ( (member_pg.first_name.strip().lower() == first_name and
                  member_pg.last_name.strip().lower() == last_name) or
                 (member_pg.first_name.strip().lower() == last_name and
                  member_pg.last_name.strip().lower() == first_name) ) and \
               member_pg.area_code.strip().lower() == area_code and \
               member_pg.residence.strip().lower() == residence:
                app.logger.info(f"Member {member_pg.id} verified from PostgreSQL.")
                return {
                    "verified": True,
                    "source": "PostgreSQL",
                    "first_name": member_pg.first_name,
                    "last_name": member_pg.last_name,
                    "area_code": member_pg.area_code,
                    "residence": member_pg.residence
                }

    except Exception as e:
        app.logger.error(f"Error verifying against PostgreSQL: {e}")

    # 2. If not found in PostgreSQL, try to verify against Google Sheet
    gs_client, gs_sheet = get_google_sheet_client()
    if gs_sheet:
        try:
            headers = gs_sheet.row_values(1)
            try:
                ver_code_col_idx = headers.index('Verification Code') + 1 # gspread is 1-indexed
            except ValueError:
                app.logger.error("Google Sheet does not have a 'Verification Code' column in its header. Cannot verify against Google Sheet.")
                return {"verified": False} # This means GS verification won't work

            # Search by verification code
            cell = gs_sheet.find(verification_code, in_column=ver_code_col_idx)
            if cell:
                row_values = gs_sheet.row_values(cell.row)
                record = dict(zip(headers, row_values))

                gs_code = str(record.get('Verification Code', '')).strip().upper()
                gs_first_name = str(record.get('First Name', '')).strip().lower()
                gs_last_name = str(record.get('Last Name', '')).strip().lower()
                gs_area_code = str(record.get('Area Code', '')).strip().lower()
                gs_residence = str(record.get('Residence', '')).strip().lower()
                gs_is_verified = str(record.get('Is Verified', '')).strip().upper() == 'TRUE'

                if not gs_is_verified:
                    app.logger.info(f"Google Sheet record for code {verification_code} found but not marked as verified.")
                    return {"verified": False}

                if (gs_code == verification_code and
                    ( (gs_first_name == first_name and gs_last_name == last_name) or
                      (gs_first_name == last_name and gs_last_name == first_name) ) and
                    gs_area_code == area_code and
                    gs_residence == residence):
                    app.logger.info(f"Member verified from Google Sheet (ID: {record.get('ID')}).")
                    return {
                        "verified": True,
                        "source": "Google Sheet",
                        "first_name": record.get('First Name'),
                        "last_name": record.get('Last Name'),
                        "area_code": record.get('Area Code'),
                        "residence": record.get('Residence')
                    }
        except Exception as e:
            app.logger.error(f"Error verifying against Google Sheet: {e}")

    app.logger.info(f"Verification failed for code: {verification_code}, name: {first_name} {last_name}.")
    return {"verified": False}


# --- Flask-Admin Initialization (MUST BE AFTER MyAdminIndexView and CommunityMemberView definitions) ---
# Removed 'template_mode' keyword argument
admin = Admin(app, name='Community Portal', index_view=MyAdminIndexView())
admin.add_view(ModelView(User, db.session, name='Admin Users')) # Adding Admin Users view
# Explicitly setting the endpoint name to 'communitymember'
admin.add_view(CommunityMemberView(CommunityMember, db.session, name='Members', endpoint='communitymember'))


# --- Flask Routes ---
@app.route('/')
def index():
    # Redirects to the login page first, then to admin index upon successful login
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.index'))

    # Use the globally defined LoginForm class
    form = LoginForm()
    if form.validate_on_submit():
        username_attempt = form.username.data
        password_attempt = form.password.data

        user = db.session.query(User).filter_by(username=username_attempt).first()

        if user is None or not user.check_password(password_attempt):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('login'))
        login_user(user, remember=form.remember_me.data)
        flash('Logged in successfully!', 'success')
        next_page = request.args.get('next')
        return redirect(next_page or url_for('admin.index'))
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# This route was duplicated. Keeping the one with the correct URL name (print_member_info)
# and removing the one that was previously in CommunityMemberView.
@app.route('/print_member_info/<int:member_id>')
@login_required
def print_member_info(member_id):
    member = db.session.get(CommunityMember, member_id)
    if not member:
        flash('Community member not found.', 'danger')
        # Redirect to the CommunityMember list view within Flask-Admin
        return redirect(url_for('communitymember.index_view'))

    # Ensure this template exists in templates/admin/print_member_info.html
    return render_template('admin/print_member_info.html', member=member, print_on_load=True, datetime=datetime)

# Excel Export Route (consolidated from CommunityMemberView's export_excel_view)
@app.route('/export_members_excel')
@login_required
def export_members_excel():
    members = db.session.query(CommunityMember).all()

    data = []
    for member in members:
        member_dict = member.to_dict()
        # Convert 'is_verified' to 'TRUE'/'FALSE' for Excel
        member_dict['is_verified'] = 'TRUE' if member_dict['is_verified'] else 'FALSE'
        data.append(member_dict)

    df = pd.DataFrame(data)

    # Reorder columns to match the desired display or Google Sheet headers
    ordered_columns = [
        'id', 'first_name', 'last_name', 'phone_number', 'gender', 'email',
        'employment_status', 'profession', 'employer', 'parent_guardian_name',
        'parent_guardian_contact', 'parent_guardian_address', 'date_of_birth',
        'residence', 'area_code', 'is_verified', 'registration_date',
        'verification_code', 'id_card_number', 'educational_level'
    ]

    # Select only the columns that exist in the DataFrame and reorder them
    df = df[[col for col in ordered_columns if col in df.columns]]

    # Optionally rename columns for better readability in Excel
    column_renames = {
        'id': 'ID', 'first_name': 'First Name', 'last_name': 'Last Name',
        'phone_number': 'Phone Number', 'gender': 'Gender', 'email': 'Email',
        'employment_status': 'Employment Status', 'profession': 'Profession',
        'employer': 'Employer', 'parent_guardian_name': 'Parent/Guardian Name',
        'parent_guardian_contact': 'Parent/Guardian Contact',
        'parent_guardian_address': 'Parent/Guardian Address',
        'date_of_birth': 'Date of Birth', 'residence': 'Residence',
        'area_code': 'Area Code', 'is_verified': 'Is Verified',
        'registration_date': 'Registration Date', 'verification_code': 'Verification Code',
        'id_card_number': 'ID Card Number', 'educational_level': 'Educational Level'
    }
    df = df.rename(columns=column_renames)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Community Members')
    output.seek(0)

    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     download_name=f'community_members_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
                     as_attachment=True)


# --- Public Verification API (JSON response) ---
@app.route("/api/verify_member", methods=["GET"])
def api_verify_member():
    """
    API endpoint for programmatic verification of community members.
    Requires: code, fname, lname, area_code, residence as query parameters.
    Returns JSON response.
    """
    code = request.args.get('code')
    fname = request.args.get('fname')
    lname = request.args.get('lname')
    area_code = request.args.get('area_code')
    residence = request.args.get('residence')

    if not all([code, fname, lname, area_code, residence]):
        return jsonify({
            "status": "error",
            "message": "Missing required parameters: code, fname, lname, area_code, residence."
        }), 400

    result = verify_member_details(code, fname, lname, area_code, residence)

    if result["verified"]:
        return jsonify({
            "status": "success",
            "verified": True,
            "message": "Member verified successfully.",
            "member_info": {
                "first_name": result["first_name"],
                "last_name": result["last_name"],
                "area_code": result["area_code"],
                "residence": result["residence"],
                "source": result["source"]
            }
        }), 200
    else:
        return jsonify({
            "status": "failed",
            "verified": False,
            "message": "No matching verified member found with the provided details."
        }), 404

# --- Public Verification Link (HTML page response) ---
@app.route("/verify_member_public", methods=["GET"])
def verify_member_public():
    """
    Public-facing route for companies to verify community members via a link.
    Requires: code, fname, lname, area_code, residence as query parameters.
    Returns an HTML page with verification result.
    """
    code = request.args.get('code')
    fname = request.args.get('fname')
    lname = request.args.get('lname')
    area_code = request.args.get('area_code')
    residence = request.args.get('residence')

    template_data = {
        "status_class": "danger",
        "title": "Verification Failed",
        "message": "Missing one or more required details. Please ensure all fields are provided.",
        "verified_info": None
    }

    if not all([code, fname, lname, area_code, residence]):
        app.logger.warning("Missing parameters for public verification request.")
        return render_template("verify_result.html", **template_data)

    result = verify_member_details(code, fname, lname, area_code, residence)

    if result["verified"]:
        template_data.update({
            "status_class": "success",
            "title": "Verification Successful!",
            "message": f"The community member's details have been successfully verified from {result['source']}.",
            "verified_info": {
                "First Name": result["first_name"],
                "Last Name": result["last_name"],
                "Area Code": result["area_code"],
                "Residence": result["residence"]
            }
        })
    else:
        template_data.update({
            "status_class": "danger",
            "title": "Verification Failed",
            "message": "No matching verified community member found with the provided details. Please check the information and try again."
        })

    return render_template("verify_result.html", **template_data)


# --- Flask CLI Commands for Database Management ---
@app.cli.command("init-db")
def init_db_command():
    """Clear existing data and create new tables, then add/update admin user."""
    print("Attempting to initialize database...")
    with app.app_context():
        db.drop_all()
        db.create_all()

        new_admin_username = 'user'
        new_admin_password = 'executive@2025'

        admin_user = db.session.query(User).filter_by(username=new_admin_username).first()
        if not admin_user:
            admin_user = User(username=new_admin_username)
            admin_user.set_password(new_admin_password)
            db.session.add(admin_user)
            db.session.commit()
            print(f"Database initialized: Tables created and admin user '{new_admin_username}' (password '{new_admin_password}') created.")
        else:
            if not admin_user.check_password(new_admin_password):
                admin_user.set_password(new_admin_password)
                db.session.commit()
                print(f"Admin user '{new_admin_username}' already exists. Password reset to '{new_admin_password}'.")
            else:
                print(f"Database tables created. Admin user '{new_admin_username}' already exists (not created again).")

        old_usernames_to_clean = ['admin', 'k1youthassociation', 'executive']
        for old_user_name in old_usernames_to_clean:
            if old_user_name != new_admin_username:
                old_user = db.session.query(User).filter_by(username=old_user_name).first()
                if old_user:
                    db.session.delete(old_user)
                    db.session.commit()
                    app.logger.info(f"Old '{old_user_name}' user removed for local dev.")

    print("Database initialization complete.")


if __name__ == '__main__':
    with app.app_context():
        # This code runs once when the application starts
        db.create_all() # Create database tables if they don't exist

        # Create a default admin user if one doesn't exist
        admin_username = os.getenv('ADMIN_USERNAME', 'user') # Changed default to 'user'
        admin_password = os.getenv('ADMIN_PASSWORD', 'executive@2025') # Changed default password
        if not User.query.filter_by(username=admin_username).first():
            admin_user = User(
                username=admin_username,
                password_hash=generate_password_hash(admin_password)
            )
            db.session.add(admin_user)
            db.session.commit()
            app.logger.info(f"Initial admin user '{admin_username}' created with password '{admin_password}'")
            print(f"Initial admin user '{admin_username}' created with password '{admin_password}'")
        else:
            if not User.query.filter_by(username=admin_username).first().check_password(admin_password):
                admin_user = User.query.filter_by(username=admin_username).first()
                admin_user.set_password(admin_password)
                db.session.commit()
                app.logger.info(f"Admin user '{admin_username}' already exists. Password reset to '{admin_password}' for local dev.")
                print(f"Admin user '{admin_username}' already exists. Password reset to '{admin_password}' for local dev.")


        # Old usernames to clean up, if they exist from previous runs.
        # This makes sure only the desired admin user (from ADMIN_USERNAME env var or default) exists.
        old_usernames_to_clean = ['admin', 'k1youthassociation', 'executive']
        for old_user_name in old_usernames_to_clean:
            if old_user_name != admin_username: # Don't delete the current admin user
                old_user = db.session.query(User).filter_by(username=old_user_name).first()
                if old_user:
                    db.session.delete(old_user)
                    db.session.commit()
                    app.logger.info(f"Old '{old_user_name}' user removed for local dev.")


        # Attempt to connect to Google Sheet at startup for early error detection
        get_google_sheet_client()

    app.run(debug=os.getenv('FLASK_DEBUG', 'True') == 'True', host='0.0.0.0', port=5000)
