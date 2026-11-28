"""Question text handling: normalising English / Hinglish, tokens, months, fuzzy name matching."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Intent markers. They are kept as tokens so labels such as "Top performer" can still match them.
TOP, BOTTOM, HOWMANY, TREND = "qqtop", "qqbottom", "qqhowmany", "qqtrend"
MARKERS = {TOP, BOTTOM, HOWMANY, TREND}

# Multi-word phrases first (longest first). Hinglish is mapped onto the same English words.
PHRASES = [
    ("sales persons", "salespersons"), ("sales people", "salespeople"), ("sales person", "salesperson"),
    ("salesman", "salesperson"), ("crm members", "callers"), ("crm member", "crm"), ("not picked up", "notpicked"),
    ("on hold", "hold"), ("this month", "thismonth"), ("is mahine", "thismonth"), ("current month", "thismonth"),
    ("late orders", "late"), ("late order", "late"), ("qc pass", "qcpass"), ("qc fail", "qcfail"),
    ("purchase orders", "po"), ("purchase order", "po"), ("fabric po", "fabric po"),
    ("on time", "ontime"), ("on-time", "ontime"), ("job worker", "fabricator"), ("job workers", "fabricator"),
    ("sabse zyada", TOP), ("sabse jyada", TOP), ("sabse adhik", TOP), ("sab se zyada", TOP), ("sabse jada", TOP),
    ("sabse kam", BOTTOM), ("sab se kam", BOTTOM), ("sabse neeche", BOTTOM),
    ("how many", HOWMANY), ("how much", "howmuch"), ("number of", HOWMANY), ("count of", HOWMANY),
    ("month wise", TREND), ("monthwise", TREND), ("month-wise", TREND), ("by month", TREND), ("per month", TREND),
    ("har mahine", TREND), ("mahine wise", TREND), ("every month", TREND), ("each month", TREND),
    ("month by month", TREND),
    ("total orders", "order qty"), ("total order", "order qty"), ("order quantity", "order qty"),
    ("kitne order", "order qty"), ("kitna order", "order qty"),
    ("kitne ka", "inr"), ("kitne ki", "inr"), ("kitne rupaye", "inr"), ("in rupees", "inr"), ("in value", "inr"),
    ("value me", "inr"), ("value mein", "inr"), ("paise me", "inr"), ("paise mein", "inr"), ("rupees me", "inr"),
    ("pcs me", "qty"), ("pcs mein", "qty"), ("pieces me", "qty"), ("in pcs", "qty"), ("in pieces", "qty"),
    ("aana baki", "pending"), ("aana hai", "pending"), ("nahi aaya", "pending"), ("nahi aya", "pending"),
    ("der se", "delay"), ("time pe", "ontime"), ("time par", "ontime"), ("samay par", "ontime"),
    ("dena hai", "payable"), ("dene hai", "payable"), ("payment karna", "payable"), ("kitna dena", "payable"),
    ("this week", "next 7 days"), ("next week", "next 7 days"), ("is hafte", "next 7 days"),
    ("is week", "next 7 days"), ("7 din", "next 7 days"), ("sabse purana", "oldest"), ("most late", "oldest"),
]

# Single words -> canonical word.
WORDS = {
    # intent
    "top": TOP, "highest": TOP, "maximum": TOP, "max": TOP, "most": TOP, "best": TOP, "biggest": TOP,
    "largest": TOP, "leading": TOP, "zyada": TOP, "jyada": TOP,
    "lowest": BOTTOM, "minimum": BOTTOM, "min": BOTTOM, "least": BOTTOM, "worst": BOTTOM, "bottom": BOTTOM,
    "smallest": BOTTOM, "fewest": BOTTOM,
    "kitna": HOWMANY, "kitne": HOWMANY, "kitni": HOWMANY, "count": HOWMANY,
    "trend": TREND, "monthly": TREND,
    # metrics
    "pos": "po", "po's": "po", "fpo": "po",
    "pcs": "qty", "pc": "qty", "piece": "qty", "pieces": "qty", "qty": "qty", "quantity": "qty", "volume": "qty",
    "quantities": "qty",
    "rcvd": "received", "recieved": "received", "receive": "received", "receipt": "received", "aaya": "received",
    "aya": "received", "aaye": "received", "mila": "received",
    "baki": "pending", "baaki": "pending", "bacha": "pending", "outstanding": "pending",
    "mtr": "mtr", "meter": "mtr", "meters": "mtr", "metre": "mtr", "metres": "mtr", "mtrs": "mtr",
    "sales": "revenue", "sale": "revenue", "turnover": "revenue", "kamai": "revenue", "income": "revenue",
    "business": "revenue",
    # Flo-Wing Hinglish: money vs pieces, delivery, dues
    "paise": "inr", "paisa": "inr", "paison": "inr", "rupaye": "inr", "rupaya": "inr", "rupees": "inr",
    "rupee": "inr", "rs": "inr", "inr": "inr", "₹": "inr", "worth": "inr", "lakh": "inr", "crore": "inr",
    "maal": "qty", "nag": "qty",
    "bakaya": "payable", "lena": "pending", "aana": "pending", "aane": "pending", "ana": "pending",
    "deri": "delay", "lapse": "overdue", "expired": "overdue", "khatam": "overdue",
    "bheja": "order", "diya": "order", "kharida": "order", "purchase": "order",
    "dues": "payable", "payment": "payable", "payments": "payable", "pay": "payable", "dena": "payable",
    "dene": "payable", "bhugtan": "payable", "payables": "payable", "udhaar": "payable", "udhar": "payable",
    "vender": "vendor", "venders": "vendor", "dept": "department", "departments": "department", "cities": "city",
    "agencies": "agency", "bills": "bill",
    "late": "delay", "delayed": "delay", "delays": "delay", "der": "delay", "lateness": "delay",
    "overdue": "overdue",
    "percent": "rate", "percentage": "rate", "%": "rate", "ratio": "rate", "pct": "rate",
    "approved": "approv", "approval": "approv", "approve": "approv", "approvals": "approv", "pass": "approv",
    "rejected": "reject", "rejection": "reject", "rejects": "reject", "fail": "reject",
    "kapda": "fabric", "cloth": "fabric", "fabrics": "fabric",
    "purana": "oldest", "old": "oldest", "longest": "oldest",
    "goal": "target", "lakshya": "target",
    "achievement": "achieved", "achieve": "achieved",
    "left": "remaining",
    "issue": "issued",
    "supplier": "vendor", "suppliers": "vendor", "mill": "vendor", "mills": "vendor", "vendors": "vendor",
    "customer": "client", "customers": "client", "party": "client", "parties": "client", "buyer": "client",
    "buyers": "client", "clients": "client",
    "karigar": "fabricator", "fabricators": "fabricator", "stitcher": "fabricator",
    "item": "category", "items": "category", "product": "category", "products": "category", "categories": "category",
    "style": "category", "styles": "category",
    "designers": "designer",
    "mahina": "month", "mahine": "month", "months": "month",
    "samples": "sample", "sampling": "sample",
    "orders": "order", "designs": "design",
    "average": "avg", "avg": "avg", "mean": "avg",
    "required": "require", "needed": "require", "need": "require", "zaroorat": "require",
}

# Words that mostly say which page a question is about. When a question also has a more specific word
# ("rejected samples"), these count less, so "Rejected" beats "Total samples".
CONTEXT_WORDS = {"sample", "po", "fabric", "target", "production", "order", "design"}

# Words that never carry meaning for matching (English + Hinglish fillers).
STOP = set("""
a an the of is are was were be been am what whats what's tell me show give please pls plz total overall all in for
on at to howmuch much many kya hai hain ka ki ke ko se mein me main batao bataiye bata dikhao do current currently
our we us number value figure this that so far till now abhi tak ab and or with did does has have get got which who
whose kaun konsa kaunsa kon sa wala wali wale ye yeh woh wo uska iska there any about i you can could would should
it its it's by from as us my your hamara hamare humara mujhe hume our pe par bhi just only sirf bas aur ji sir mam
madam hello hi hey thanks thank ok okay right now today data number list names name see
find check know dikhata dikhati dikhate dikha hota hoti hote hue hua hui raha rahe rahi gaya gaye gayi paas
kis kisne kisi liye wala tha thi the wise
""".split())

GENERIC_NAME_WORDS = set("""
tex textile textiles mills mill exports export house studio label retail co and & fabrics fabric silks silk weaves
weave garments garment fab works work lab trends trend lane sampling kendra the pvt ltd private limited company
""".split())

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MONTH_ALIASES = {m: i + 1 for i, m in enumerate(MONTHS)}
MONTH_ALIASES.update({m[:3]: i + 1 for i, m in enumerate(MONTHS)})
MONTH_ALIASES.update({"sept": 9, "jany": 1, "febuary": 2, "agust": 8, "octuber": 10, "novmber": 11})

_TOKEN = re.compile(r"[a-z0-9%]+(?:[/'.-][a-z0-9]+)*|₹")


def norm(text: str) -> str:
    """Lower case, unify quotes and spaces."""
    t = (text or "").lower().replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", t).strip()


def apply_phrases(text: str) -> str:
    t = f" {norm(text)} "
    for src, dst in sorted(PHRASES, key=lambda p: -len(p[0])):
        t = re.sub(rf"(?<![a-z0-9]){re.escape(src)}(?![a-z0-9])", f" {dst} ", t)
    return re.sub(r"\s+", " ", t).strip()


def raw_tokens(text: str) -> list[str]:
    return _TOKEN.findall(norm(text))


def stem(w: str) -> str:
    if w in MARKERS or len(w) <= 3 or not w.isalpha():
        return w
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            if suf == "es" and not re.search(r"(ss|x|ch|sh)es$", w):
                continue
            return w[: len(w) - len(suf)] + rep
    return w


def canon(word: str) -> str:
    w = WORDS.get(word, word)
    return stem(w) if w not in MARKERS else w


def tokens(text: str, keep_stop: bool = False) -> list[str]:
    """Canonical tokens of a question or label."""
    out = []
    for w in raw_tokens(apply_phrases(text)):
        c = canon(w)
        if not keep_stop and c not in MARKERS and (c in STOP or w in STOP):
            continue
        out.append(c)
    return out


def label_tokens(label: str) -> set[str]:
    """Tokens of a dashboard label; '(Pcs)' style units count too, '%' becomes 'rate'."""
    t = label.replace("%", " percent ").replace("₹/pc", " rate ").replace("/", " ")
    return {w for w in tokens(t) if w not in {"total"}}


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def name_key(s: str) -> str:
    """Comparable form of a name: lower case, letters and digits only, single spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/& ]+", " ", norm(s))).strip()
