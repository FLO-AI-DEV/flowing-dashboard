"""What the assistant knows about the dashboard itself: its pages, their filters, and how the screen works.

Everything here describes the dashboard's own features (taken from the frontend and the API); no company facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Page:
    key: str                     # API name, e.g. "orders" -> GET /api/orders
    label: str                   # sidebar label
    path: str                    # frontend route
    words: tuple[str, ...]       # how people refer to the page
    about: str                   # one-paragraph description
    filters: dict[str, str] = field(default_factory=dict)   # API filter parameter -> entity type
    order: int = 0               # tie-break: lower wins when two pages show the same figure


PAGES: dict[str, Page] = {p.key: p for p in [
    Page("orders", "Orders", "/orders", ("orders page", "order page", "order status", "po master"),
         "Every PO line from the Order Status sheet (PO Master tab): ordered, received and pending value and pcs, "
         "overdue lines (delivery date passed, pieces still pending), on-time delivery and delays, by month, vendor, "
         "category, department, city and fabric (cotton, silk, viscose ...). Every PO line is listed with its order "
         "date, delivery date and received date. The filters can use the order date or the delivery date ('Date by').",
         {"month": "month", "vendor": "vendor", "department": "department", "category": "category", "city": "city",
          "fabric": "fabric"}, 1),
    Page("dues", "Supplier dues", "/dues", ("dues page", "dues", "payment page", "supplier dues", "payables"),
         "Supplier bills from the DUES PAYMENT SUPPLIERS sheet: total net payable, overdue amount, what falls due in "
         "the next 7 days, ageing, and dues per supplier with credit days, discount and agency. Pick the dues list "
         "(tab) at the top of the page.",
         {"supplier": "vendor", "agency": "agency"}, 2),
    Page("vendors", "Vendors", "/vendors", ("vendors page", "vendor page", "scorecard", "vendor scorecard"),
         "A scorecard per vendor from the PO Master: lines, ordered, received, pending and overdue value, received %, "
         "on-time % and average delay.",
         {"month": "month", "department": "department", "category": "category", "city": "city"}, 3),
    Page("order-to-vendors", "Order to vendors", "/order-to-vendors",
         ("order to vendors", "order to vendor", "vendor orders", "otv"),
         "Rows of the Order to vendors sheet with totals and a breakdown by status and vendor (columns are found by "
         "name).",
         {"vendor": "vendor"}, 4),
    Page("enquiries", "Supplier enquiries", "/enquiries",
         ("supplier enquiry", "supplier enquiries", "enquiry", "enquiries", "inquiry", "complaints", "follow up",
          "terms approval", "inactive suppliers", "pending po by city"),
         "The Supplier's Enquiry Sheet: supplier enquiries and their status (solved / unsolved / in process), who is "
         "handling each, how long open ones have waited, pending POs city by city, payment-terms approvals and "
         "inactive suppliers.",
         {"month": "month", "party": "party", "city": "city", "handler": "handler"}, 5),
    Page("overview", "Overview", "/", ("overview", "home page", "summary page", "main page"),
         "A summary of the four sheets: overdue PO lines, pending orders, supplier dues, vendor orders and open supplier enquiries, plus the "
         "alerts that need attention.",
         {"month": "month"}, 8),
]}

# Option lists in the API -> entity type. Other option lists (timing, status...) are not used as names.
OPTION_TYPES = {"vendor": "vendor", "supplier": "vendor", "category": "category", "department": "department",
                "city": "city", "agency": "agency", "month": "month", "fabric": "fabric",
                "party": "party", "handler": "handler"}

# First column of a table -> what each row is.
ROW_TYPES = {"vendor": "vendor", "supplier": "vendor", "month": "month", "category": "category",
             "department": "department", "city": "city", "agency": "agency", "po no.": "po", "po no": "po",
             "handled by": "handler", "fabric": "fabric"}

DIMENSION_WORDS = {"vendor": "vendor", "month": "month", "category": "category", "department": "department",
                   "city": "city", "agency": "agency", "po": "po",
                   "handler": "handler", "fabric": "fabric"}

# Plural words that ask about every row of a kind ("on-time rate of vendors", "har vendor ka pending").
DIMENSION_PLURALS = {"vendors": "vendor", "suppliers": "vendor", "parties": "vendor", "venders": "vendor",
                     "categories": "category", "items": "category", "products": "category",
                     "departments": "department", "cities": "city", "agencies": "agency",
                     "handlers": "handler"}

# "Best" / "worst" with no measure named: what makes a vendor good (higher is better).
QUALITY = {"vendor": "on-time rate"}

TYPE_NAMES = {"vendor": "vendor", "category": "category", "department": "department", "city": "city",
              "agency": "agency", "month": "month", "po": "PO",
              "handler": "person", "party": "supplier", "fabric": "fabric"}
PLURALS = {"category": "categories", "city": "cities", "agency": "agencies", "PO": "POs"}

# The page that "owns" a kind of row, used when a ranking names no measure ("top vendor").
HOME_PAGE = {"vendor": "vendors", "category": "orders", "department": "orders", "city": "orders", "month": "orders",
             "agency": "dues", "fabric": "orders"}

# Questions about how to use the screen. Each entry: trigger words -> answer.
FEATURES = [
    ({"filter", "filters", "filtr"},
     "Every page has filter buttons at the top (month, vendor, department, fabric and so on). Pick one or more values and "
     "the numbers, charts and tables update straight away. Clear a filter to see everything again."),
    ({"download", "csv", "export", "excel"},
     "Tables have a **CSV** button under them; it saves exactly the rows you see with the current filters."),
    ({"refresh", "reload", "sync", "update", "updated", "live", "latest"},
     "The dashboard reads the Google Sheets again every minute by itself. The ↻ button in the top bar reads them "
     "right now, and the live light next to it shows when the data was last read."),
    ({"dark", "light", "theme", "mode"},
     "Use the moon / sun button in the top bar to switch between dark and light mode. By default it follows your "
     "device."),
    ({"sidebar", "menu", "collapse", "navigation", "nav"},
     "Pages are in the sidebar on the left. On a PC the sidebar folds into an icon rail with the button in the top "
     "bar (or press **[**). On a phone, open it with the ☰ menu button."),
    ({"tab", "tabs", "sheet", "sheets"},
     "The **Sheets** page shows any tab of the four sheets live, with search. On **Supplier dues** pick the dues "
     "list (tab) at the top; on **Order to vendors** pick the tab the same way."),
    ({"login", "passcode", "password", "signin", "sign"},
     "When sign-in is switched on, the dashboard asks for the team passcode once per device."),
    ({"edit", "change", "add", "delete", "modify", "write"},
     "The dashboard is read-only. To change a number, edit the Google Sheet; the dashboard shows the change within "
     "a minute. I can only read the dashboard too."),
]

HELP = ("I answer questions about the numbers and pages of this dashboard, in English or Hinglish. Ask about "
        "ordered, received, pending or overdue value and pcs, on-time delivery, supplier dues and payments, a vendor, "
        "category, department, city or month. Add “in one word” for just the number, or “in detail” for a breakdown.")
