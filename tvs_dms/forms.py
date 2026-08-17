from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"  # text, longtext, integer, date, choice
    required: bool = False
    choices: Tuple[str, ...] = ()
    hint: str = ""


@dataclass(frozen=True)
class Module:
    key: str
    name: str
    role: str
    fields: Tuple[Field, ...]


ROLE_LABELS = {
    "administrator": "Administrator",
    "class_teacher": "Class Teacher",
    "catalyst_member": "Catalyst Member",
    "office": "Office",
    "academic_supervisor": "Academic Supervisor",
}

LEVELS = ("Pre-Primary", "Primary", "Middle", "Secondary", "Senior Secondary", "All")
STANDARDS = ("Nursery", "LKG", "UKG", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "All")
SHIFTS = ("Morning", "Afternoon", "General", "Not applicable")
# One shared scale across every IMPACT hub: the distribution and segment-gap
# analyzers compare ratings across forms, which only works if the labels match.
RATINGS = ("Excellent", "Good", "Satisfactory", "Needs improvement", "Poor")
EXTENT = ("None", "Minimal", "Moderate", "High", "Very high")

DATE = Field("event_date", "Activity date", "date", True, hint="DD-MM-YYYY")
LEVEL = Field("level", "Level", "choice", False, LEVELS)
STANDARD = Field("standard", "Standard / Class", "choice", False, STANDARDS)
SHIFT = Field("shift", "Shift", "choice", False, SHIFTS)


def f(key: str, label: str, kind: str = "text", required: bool = False, choices: Sequence[str] = (), hint: str = "") -> Field:
    return Field(key, label, kind, required, tuple(choices), hint)


def activity_fields(*extra: Field, audience: bool = True) -> Tuple[Field, ...]:
    common = [DATE, LEVEL, STANDARD, SHIFT]
    if audience:
        common.append(f("participants", "Participants", "integer", False))
    common.extend(extra)
    common.extend((
        f("outcome", "Outcome / impact", "longtext", True),
        f("remarks", "Remarks", "longtext"),
    ))
    return tuple(common)


def simple_activity(topic_label: str = "Activity / topic", *, facilitator: bool = True) -> Tuple[Field, ...]:
    extras = [f("topic", topic_label, required=True)]
    if facilitator:
        extras.append(f("facilitator", "Conducted / facilitated by"))
    extras.append(f("venue", "Venue / platform"))
    return activity_fields(*extras)


_MODULE_SPECS: Dict[str, List[Tuple[str, str, Tuple[Field, ...]]]] = {
    "class_teacher": [
        ("assembly_console", "Assembly Console", activity_fields(
            f("assembly_type", "Assembly type", "choice", True, ("Class", "House", "School", "Special")),
            f("theme", "Theme / topic", required=True), f("conducted_by", "Conducted by"),
            f("students_expected", "Students on roll", "integer"),
            f("programme_flow", "Flow of the programme", "longtext", True),
            f("flow_rating", "Rating: overall quality / flow", "choice", True, RATINGS),
            f("student_performance", "Rating: student performance", "choice", False, RATINGS),
            f("values_shared", "Values shared", hint="The value or message the assembly carried"),
            f("feedback", "Feedback received", "longtext"),
            f("challenges", "Challenges faced", "longtext"))),
        ("no_bag_day", "No Bag Day", activity_fields(
            f("event", "Event", required=True), f("activities", "Activities completed", "longtext", True),
            f("activity_count", "Number of activities", "integer"))),
        ("online_class", "Online Class", activity_fields(
            f("subject", "Subject", required=True), f("topic", "Topic", required=True),
            f("platform", "Platform"), f("duration", "Duration"))),
        ("open_house", "Open House", activity_fields(
            f("mode", "Mode", "choice", True, ("Physical", "Virtual", "Hybrid")),
            f("session_type", "Session", "choice", True, ("Regular", "Special")),
            f("purpose", "Purpose", "longtext", True), f("parents_attended", "Parents attended", "integer"))),
        ("sanskrit", "Sanskrit", activity_fields(
            f("topic", "Topic", required=True), f("addressed_by", "Addressed by", required=True),
            f("venue", "Venue"), f("duration", "Duration"))),
    ],
    "catalyst_member": [
        ("career_guidance", "Career Guidance", simple_activity("Guidance topic")),
        ("cca_edu_sports", "CCA or Edu Sports", activity_fields(
            f("activity_type", "Activity type", "choice", True, ("CCA", "Edu Sports")), f("activity", "Activity", required=True), f("coach", "Coach / teacher"))),
        ("class_project", "Class Project", simple_activity("Project title")),
        ("dayboarding", "Dayboarding", activity_fields(
            f("session", "Session / activity", required=True), f("staff", "Staff in charge"),
            f("attendance", "Students availed", "integer", True, hint="Count who actually ate"),
            f("expected_attendance", "Students expected", "integer", hint="Drives the utilisation ratio"),
            f("food_wastage", "Food wastage observed", "choice", True, EXTENT),
            f("wastage_notes", "What was left over", "longtext", hint="Which items, so preferences can be read"),
            f("rating_food", "Rating: food served", "choice", True, RATINGS),
            f("rating_student_feedback", "Rating: student feedback", "choice", True, RATINGS),
            f("rating_staff_feedback", "Rating: staff feedback", "choice", False, RATINGS),
            f("rating_waiting_time", "Rating: waiting time", "choice", True, RATINGS),
            f("waiting_minutes", "Longest wait (minutes)", "integer"),
            f("challenges", "Problems observed / challenges faced", "longtext", True))),
        ("enrichment", "Enrichment", simple_activity("Enrichment topic")),
        ("event_details", "Event Details", activity_fields(f("event", "Event name", required=True), f("organiser", "Organiser"), f("venue", "Venue"))),
        ("faca_details", "FACA Details", simple_activity("FACA activity")),
        ("field_trip", "Field Trip", activity_fields(
            f("destination", "Destination", required=True), f("purpose", "Purpose", "longtext", True),
            f("venue_planned", "Venue planned", hint="Record the plan when it differs from where the trip went"),
            f("staff_count", "Accompanying staff", "integer", True),
            f("students_expected", "Students planned", "integer"),
            f("transport_mode", "Transport", "choice", False, ("School bus", "Hired coach", "Public transport", "Walk", "Other")),
            f("budget", "Cost incurred", "integer"),
            f("learning_outcome", "Learning outcome", "longtext"),
            f("student_engagement", "Rating: student engagement", "choice", False, RATINGS),
            f("feedback", "Feedback received", "longtext"),
            f("challenges", "Challenges / concerns faced", "longtext", True))),
        ("quality_circle", "Quality Circle", simple_activity("Improvement area")),
        ("self_learning", "Self Learning", simple_activity("Learning topic", facilitator=False)),
        ("student_empowerment", "Student Empowerment", simple_activity("Empowerment topic")),
        ("value_camp", "Value Camp", simple_activity("Value / theme")),
        ("health_initiative", "Health Initiative", simple_activity("Health initiative")),
        ("subject_group_discussion", "Subject Group Discussion", activity_fields(f("subject", "Subject", required=True), f("agenda", "Agenda", "longtext", True), f("members", "Members present"))),
    ],
    "office": [
        ("circle_time", "Circle Time", simple_activity("Discussion theme")),
        ("counselling_staff", "Counselling Staff", activity_fields(f("staff_reference", "Staff name / ID", required=True), f("concern", "Concern category", required=True), f("action", "Action / follow-up", "longtext", True), audience=False)),
        ("counselling", "Counselling", activity_fields(f("student_reference", "Student name / ID", required=True), f("concern", "Concern category", required=True), f("action", "Action / follow-up", "longtext", True), audience=False)),
        ("first_aid", "First Aid", activity_fields(f("person_reference", "Person name / ID", required=True), f("incident", "Incident / complaint", "longtext", True), f("care_given", "First aid given", "longtext", True), f("referred_to", "Referred to"), audience=False)),
        ("life_skill_classes", "Life Skill Classes", simple_activity("Life skill topic")),
        ("parenting_session", "Parenting Session and Orientation", simple_activity("Session topic")),
        ("special_educator", "Special Educator", activity_fields(f("student_reference", "Student name / ID", required=True), f("support_area", "Support area", required=True), f("intervention", "Intervention / follow-up", "longtext", True), audience=False)),
        # Inventory rather than an activity: one entry per item per month, so
        # stock movement and pending indents are readable per department.
        ("stationary", "Stationary", activity_fields(
            f("item", "Item", required=True),
            f("department", "Department", required=True, hint="Who the stock is issued to"),
            f("category", "Category", "choice", False, ("Paper", "Writing", "Printing", "Housekeeping", "Lab", "Sports", "Other")),
            f("opening_stock", "Opening stock", "integer", True),
            f("received", "Received", "integer", True),
            f("issued", "Issued", "integer", True),
            f("closing_stock", "Closing stock", "integer", hint="Leave blank to derive from opening + received − issued"),
            f("pending_items", "Pending / to be indented", "longtext"),
            f("pending_count", "Pending quantity", "integer"),
            f("unit_cost", "Unit cost", "integer"),
            f("receipt_reference", "Receipt / bill reference"),
            f("supplier", "Supplier"),
            f("stock_status", "Stock status", "choice", True, ("Sufficient", "Reorder soon", "Critically low", "Out of stock")),
            f("challenges", "Issues / challenges", "longtext"),
            audience=False)),
    ],
    "academic_supervisor": [
        ("club_activities", "Club Activities", simple_activity("Club / activity")),
        ("competition_details", "Competition Details", activity_fields(f("competition", "Competition", required=True), f("level_of_event", "Competition level"), f("result", "Result / achievement"))),
        ("curriculum_status", "Curriculum Status", activity_fields(f("subject", "Subject", required=True), f("planned_units", "Planned units", "integer"), f("completed_units", "Completed units", "integer"), f("status_notes", "Status notes", "longtext"), audience=False)),
        ("exam_details", "Exam Details", activity_fields(
            f("exam", "Exam name", required=True), f("subjects", "Subjects", "longtext"),
            f("subject", "Subject examined", hint="One subject per entry keeps the portions report readable"),
            f("students_appeared", "Students appeared", "integer", True),
            f("students_expected", "Students on roll", "integer", True),
            f("absentees", "Absentee roll numbers", "longtext", hint="Withheld from the strategic view"),
            f("od_count", "On-duty (OD) students", "integer"),
            f("od_students", "OD roll numbers and reason", "longtext"),
            f("portion_covered", "Portions covered (%)", "integer", hint="Syllabus completed for this subject and standard"),
            f("qp_status", "Question paper availability", "choice", True, ("Ready", "In preparation", "Delayed", "Not started")),
            f("paper_arrangement", "Paper arrangement", "choice", False, ("Complete", "Partial", "Pending")),
            f("invigilators", "Invigilators deployed", "integer"),
            f("invigilation_notes", "Invigilation / hall arrangement", "longtext"),
            f("challenges", "Issues / challenges faced", "longtext", True))),
        ("finlit", "Finlit", simple_activity("Financial literacy topic")),
        ("function_celebrations", "Function / Celebrations", simple_activity("Function / celebration")),
        ("lab_activities", "Lab Activities", activity_fields(f("subject", "Subject / lab", required=True), f("experiment", "Experiment / activity", required=True), f("teacher", "Teacher in charge"))),
        ("learning_methodology", "Learning Methodology", simple_activity("Methodology / strategy")),
        ("liveworksheet", "Liveworksheet", activity_fields(f("subject", "Subject", required=True), f("worksheet", "Worksheet / topic", required=True), f("completion_rate", "Completion %", "integer"))),
        ("long_absentees", "Long Absentees", activity_fields(f("student_reference", "Student name / ID", required=True), f("absence_from", "Absent from", "date", True), f("reason", "Reason"), f("follow_up", "Follow-up", "longtext", True), audience=False)),
        ("meeting", "Meeting", activity_fields(f("meeting_type", "Meeting type", required=True), f("agenda", "Agenda", "longtext", True), f("attendees", "Attendees"), f("decisions", "Decisions / actions", "longtext"))),
        ("notebook_correction", "Notebook Correction", activity_fields(f("subject", "Subject", required=True), f("notebooks_checked", "Notebooks checked", "integer"), f("observations", "Observations", "longtext", True), audience=False)),
        ("notebook_homework_status", "Notebook / Homework Status", activity_fields(f("subject", "Subject", required=True), f("status", "Status", "choice", True, ("On schedule", "Needs attention", "Delayed")), f("observations", "Observations", "longtext"), audience=False)),
        ("nss", "NSS", simple_activity("NSS activity")),
        ("observation_details", "Observation Details", activity_fields(f("teacher_reference", "Teacher name / ID", required=True), f("subject", "Subject"), f("observation", "Observation", "longtext", True), f("feedback", "Feedback / action", "longtext"), audience=False)),
        ("parents_involvement", "Parents Involvement", simple_activity("Parent involvement activity")),
        ("peer_teaching_student", "Peer Teaching - Student", simple_activity("Topic / lesson")),
        ("peer_teaching_staff", "Peer Teaching - Staff", simple_activity("Topic / practice")),
        ("projects", "Projects", simple_activity("Project title")),
        ("rounds_duty", "Rounds Duty", activity_fields(f("area", "Area / block", required=True), f("time_slot", "Time slot"), f("observations", "Observations", "longtext", True), f("action", "Action taken", "longtext"), audience=False)),
        ("sdg_details", "SDG Details", activity_fields(f("sdg", "SDG goal", required=True), f("activity", "Activity", required=True), f("impact", "Impact", "longtext", True))),
        ("social_project", "Social Project", simple_activity("Project / cause")),
        ("staff_leave_details", "Staff Leave Details", activity_fields(f("staff_reference", "Staff name / ID", required=True), f("leave_type", "Leave type", required=True), f("date_to", "Leave to", "date", True), f("days", "Number of days", "integer"), audience=False)),
        ("staff_training", "Staff Training Program", activity_fields(f("program", "Program / topic", required=True), f("trainer", "Trainer / organisation"), f("venue", "Venue"))),
        ("student_performance", "Student Performance", activity_fields(f("student_reference", "Student name / ID", required=True), f("subject", "Subject / area"), f("performance", "Performance notes", "longtext", True), f("support_plan", "Support / extension plan", "longtext"), audience=False)),
        ("subject_forum", "Subject Forum", activity_fields(f("subject", "Subject", required=True), f("topic", "Forum topic", required=True), f("presenter", "Presenter"))),
        ("supportive_saturday", "Supportive Saturday", simple_activity("Support activity")),
        ("assessment", "Assessment", activity_fields(f("assessment_type", "Assessment type", required=True), f("subject", "Subject"), f("students_assessed", "Students assessed", "integer"), f("analysis", "Analysis", "longtext"))),
        ("formative_assessment", "Formative Assessment", activity_fields(f("subject", "Subject", required=True), f("assessment_tool", "Assessment tool", required=True), f("students_assessed", "Students assessed", "integer"), f("analysis", "Analysis", "longtext"))),
        ("leave_details", "Leave Details", activity_fields(f("student_reference", "Student name / ID", required=True), f("leave_type", "Leave type"), f("date_to", "Leave to", "date", True), f("reason", "Reason", "longtext"), audience=False)),
        ("working_days", "Working Days", activity_fields(f("period", "Month / term", required=True), f("planned_days", "Planned working days", "integer", True), f("actual_days", "Actual working days", "integer", True), audience=False)),
        ("social_awareness", "Social Awareness", simple_activity("Awareness topic / campaign")),
    ],
}


MODULES: Dict[str, Module] = {}
MODULES_BY_ROLE: Dict[str, List[Module]] = {}
for role, specs in _MODULE_SPECS.items():
    modules = [Module(key, name, role, fields) for key, name, fields in specs]
    MODULES_BY_ROLE[role] = modules
    MODULES.update({module.key: module for module in modules})


def modules_for_role(role: str) -> List[Module]:
    if role == "administrator":
        return [module for modules in MODULES_BY_ROLE.values() for module in modules]
    return list(MODULES_BY_ROLE.get(role, ()))


