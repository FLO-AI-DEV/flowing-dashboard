"""What the assistant knows about the dashboard itself: its pages, their filters, and how the screen works.

Everything here describes the dashboard's own features (taken from the frontend and the API); no company facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Page:
    key: str                     # assistant name of the page (app.main maps it to the endpoint function)
    label: str                   # sidebar label
    path: str                    # frontend route
    words: tuple[str, ...]       # how people refer to the page
    about: str                   # one-paragraph description
    filters: dict[str, str] = field(default_factory=dict)   # API filter parameter -> entity type
    order: int = 0               # tie-break: lower wins when two pages show the same figure


PAGES: dict[str, Page] = {p.key: p for p in [
    Page("orders", "Orders", "/orders", ("orders page", "order page", "order sheet", "open orders"),
         "Every open order from the Order Sheet: the client, order date, sales person, channel, the step it is "
         "waiting for (Mona's reply, PO, billing), who must act, days open, on time / late, and the reason when an "
         "order is on hold.",
         {"month": "month", "channel": "channel", "sales_person": "sales_person", "stage": "stage"}, 1),
    Page("home", "Today", "/", ("today", "today page", "home", "home page", "overview", "main page", "summary"),
         "The owner's one screen: orders today, orders this month, open orders and late orders, where orders are "
         "waiting (the pipeline), the daily close by channel, and who needs to act now (orders and PO follow-up).",
         {"month": "month", "channel": "channel", "sales_person": "sales_person"}, 2),
    Page("team", "Team", "/team", ("team page", "team", "sales team", "staff"),
         "One row per sales person (orders, sets, clients, open, late, average days to bill), one row per step owner "
         "(waiting now, late now, oldest, on-time %), and rows in the sheet that someone should fix.",
         {"month": "month", "channel": "channel"}, 3),
    Page("clients", "Clients", "/clients", ("clients page", "client page", "clients", "customers"),
         "One row per client: orders, sets, open orders, sales person, last order and days since the last order, "
         "plus how many clients ordered more than once and how many have been quiet for 30+ days.",
         {"channel": "channel", "sales_person": "sales_person"}, 4),
    Page("payments", "Payments", "/payments", ("payments page", "payment follow up", "payment followup",
                                               "pending payments", "collections"),
         "The CRM payment follow-up sheet: pending payments (₹), orders not followed up, collected and cancelled this "
         "month, one row per CRM member and every pending payment with its client, SO, amount and last follow-up.",
         {"owner": "crm", "sales_person": "sales_person"}, 5),
    Page("po", "PO follow-up", "/payments", ("po follow up", "po followup", "po page", "escalation", "callers"),
         "PO follow-up: open POs, those due in 7 days, overdue and past the limit, the escalation levels, POs whose "
         "PO was not sent, and one row per caller (CRM member) and per sales person.",
         {}, 6),
    Page("enquiries", "Enquiries", "/enquiries", ("enquiries page", "enquiry page", "enquiries", "enquiry",
                                                  "customer enquiries", "customer care"),
         "Customer-care enquiries: enquired today, total open, not picked up yet, older than 30 days, and the open "
         "ones grouped by what they are about and by source.",
         {}, 7),
    Page("returns", "Sales returns", "/returns", ("returns page", "sales returns", "returns", "return", "gr"),
         "Sales returns (GR): pieces returned, QC pass and fail, calls still to be made, returns outside the 90-day "
         "policy, and returns by month, client and reason.",
         {"client": "client"}, 8),
]}

# Option lists in the API -> entity type. Other option lists are not used as names.
OPTION_TYPES = {"month": "month", "channel": "channel", "sales_person": "sales_person", "stage": "stage",
                "owner": "crm", "client": "client"}

# First column of a table -> what each row is.
ROW_TYPES = {"client": "client", "sales person": "sales_person", "crm member": "crm", "month": "month",
             "who": "person", "who should fix": "person", "so": "po"}

DIMENSION_WORDS = {"client": "client", "month": "month", "channel": "channel", "stage": "stage",
                   "salesperson": "sales_person", "crm": "crm", "caller": "crm", "po": "po"}

# Plural words that ask about every row of a kind ("har client ka", "orders of clients").
DIMENSION_PLURALS = {"clients": "client", "customers": "client", "parties": "client", "buyers": "client",
                     "channels": "channel", "stages": "stage", "salespersons": "sales_person",
                     "salespeople": "sales_person", "callers": "crm"}

# "Best" / "worst" with no measure named: what makes a row good (higher is better).
QUALITY = {"crm": "on time %"}

TYPE_NAMES = {"client": "client", "month": "month", "channel": "channel", "stage": "stage",
              "sales_person": "sales person", "crm": "CRM member", "person": "person", "po": "SO"}
PLURALS = {"sales person": "sales people", "CRM member": "CRM members", "SO": "SOs"}

# The page that "owns" a kind of row, used when a ranking names no measure ("top client").
HOME_PAGE = {"client": "clients", "sales_person": "team", "crm": "payments", "month": "orders", "channel": "orders",
             "stage": "orders"}

# Questions about how to use the screen. Each entry: trigger words -> answer.
FEATURES = [
    ({"filter", "filters", "filtr"},
     "Pages have filter buttons at the top (month, channel, sales person, stage and so on). Pick one or more values "
     "and the numbers and tables update straight away. Clear a filter to see everything again."),
    ({"download", "csv", "export", "excel"},
     "Tables have a **CSV** button under them; it saves exactly the rows you see with the current filters."),
    ({"refresh", "reload", "sync", "update", "updated", "live", "latest"},
     "The dashboard reads the Google Sheets again every minute by itself. The ↻ button in the top bar reads them "
     "right now, and the live light next to it shows when the data was last read."),
    ({"dark", "light", "theme", "mode"},
     "Use the moon / sun button in the top bar to switch between dark and light mode. By default it follows your "
     "device."),
    ({"sidebar", "menu", "collapse", "navigation", "nav"},
     "Pages are in the sidebar on the left: Today, Orders, Enquiries, PO follow-up, Sales returns, Team and "
     "Clients. On a phone, open it with the ☰ menu button."),
    ({"whatsapp", "nudge", "nudges", "send", "remind", "reminder"},
     "The **Send** buttons add a WhatsApp reminder for the right people to the nudges sheet, and Iris sends it from "
     "the company number. They appear only when the nudges sheet is set up."),
    ({"login", "passcode", "password", "signin", "sign"},
     "The dashboard asks for the team password when it opens, and again every 24 hours."),
    ({"edit", "change", "add", "delete", "modify", "write"},
     "The dashboard only reads the order, payment, enquiry and returns sheets. To change a number, edit the Google "
     "Sheet; the dashboard shows the change within a minute."),
]

HELP = ("I answer questions about the numbers and pages of this dashboard, in English or Hinglish. Ask about "
        "orders (today, this month, open, late, on hold), who must act, a sales person, client, channel or month, "
        "pending payments and PO follow-up, customer enquiries and sales returns. Add “in one word” for just the "
        "number, or “in detail” for a breakdown.")
