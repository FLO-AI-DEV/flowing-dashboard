"""Keep tests on demo data even when a real backend/.env (sheet key, passcode) sits next to them."""
import os

os.environ["FLO_SKIP_DOTENV"] = "1"     # config._load_dotenv reads nothing while this is set
os.environ.setdefault("DATA_SOURCE", "demo")
