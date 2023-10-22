import urllib.parse
from decimal import Decimal
import re
from typing import Any, Dict, List
from datetime import datetime, timedelta
from requests import exceptions, auth, Session
import requests_cache
import logging
import locale

logging.basicConfig(format="%(levelname)s: %(message)s")
locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

def get_session(caching) -> Session:
    if caching:
        return requests_cache.CachedSession(cache_name="ynab_api_cache", expire_after=60)
    
    return Session()
    
    
        
_base_url = "https://api.ynab.com/v1/"

class BearerAuth(auth.AuthBase): # type: ignore
    def __init__(self, token):
        self.token = token
        
    def __call__(self, r):
        r.headers["authorization"] = "Bearer " + self.token
        return r

_budgets_url = "budgets"

def get_budgets(session: Session, auth: Any) -> List[Any]:
    requests_cache.disabled()
    resp_dict = {}
    try:
        resp = session.get(urllib.parse.urljoin(_base_url, _budgets_url), auth=auth)
        resp.raise_for_status()
        resp_dict = resp.json()

    except exceptions.HTTPError as e:
        print("Bad HTTP status code:", e)
    except exceptions.RequestException as e:
        print("Network error:", e)

    return resp_dict["data"]["budgets"]

def get_budget_by_name(session: Session, auth: Any, name: str) -> Dict[str, Any]:
    budgets = get_budgets(session=session, auth=auth)
    
    for budget in budgets:
        if budget["name"] == name:
            return budget
    
    return None # type: ignore

_budget_url = "budgets/{}"

def get_last_used_budget(session: Session, auth: Any) -> Dict[str, Any]:
    resp_dict = {}
    try:
        resp = session.get(urllib.parse.urljoin(_base_url, _budget_url.format("last-used")), auth=auth)
        resp.raise_for_status()
        resp_dict = resp.json()

    except exceptions.HTTPError as e:
        print("Bad HTTP status code:", e)
    except exceptions.RequestException as e:
        print("Network error:", e)

    return resp_dict["data"]["budget"]

_term_pattern = r'\w+ Term'

def get_term(note: str):
    log.debug(f"note: {note}")
    if not note:
        return ""
    
    match = re.search(_term_pattern, note)
    if not match:
        return ""
    
    term = match.group(0)
    return term.split()[0].lower()

_accounts_url = "budgets/{}/accounts"

class Account:
    def __init__(self, account_json: Dict):
        log.debug(f"account_json: {account_json}")
        
        self.id = account_json["id"]
        self.name = account_json["name"]
        self.type = account_json["type"]
        self.balance = Decimal(account_json["balance"]) / Decimal(1000)
        self.term = get_term(account_json["note"])
        self.closed = account_json["closed"]

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

    
def get_accounts(session: Session, auth: Any, budget_id: str) -> List[Account]:
    resp_dict = {}
    try:
        resp = session.get(urllib.parse.urljoin(_base_url, _accounts_url.format(budget_id)), auth=auth)
        resp.raise_for_status()
        resp_dict = resp.json()

    except exceptions.HTTPError as e:
        print("Bad HTTP status code:", e)
    except exceptions.RequestException as e:
        print("Network error:", e)

    return [ Account(account_json) for account_json in resp_dict["data"]["accounts"]] 

_categories_url = "budgets/{}/categories"

class Category:
    def __init__(self, category_json: Dict):
        log.debug(f"category_json: {category_json}")
        
        self.id = category_json["id"]
        self.name = re.sub(r'[^\w :()]', '', category_json["name"]).lstrip(" ")
        self.balance = Decimal(category_json["balance"]) / Decimal(1000)
        self.category_group_name = category_json["category_group_name"]
        self.hidden = category_json["hidden"]
        self.deleted = category_json["deleted"]
        
        self.__set_term(category_json=category_json)
        
    def __set_term(self, category_json: Dict):
        goal_type = category_json["goal_type"]
        goal_target_month_str = category_json["goal_target_month"]
        goal_target_month = None
        if goal_target_month_str:
            goal_target_month = datetime.strptime(goal_target_month_str, "%Y-%m-%d").date()
        goal_months_to_budget = category_json["goal_months_to_budget"]
        
        if goal_type:
            if goal_type == "TB" or goal_type == "MF":
                self.term = "medium"
                return
            
        if goal_months_to_budget:
            if goal_months_to_budget <= 3:
                self.term = "short"
                return
            if goal_months_to_budget <= 5*12:
                self.term = "medium"
                return
            
        if goal_target_month:
            if goal_target_month <= datetime.today().date() + timedelta(days=3*30):
                self.term = "short"
                return
            if goal_target_month <= datetime.today().date() + timedelta(days=5*365):
                self.term = "medium"
                return
            
        if self.category_group_name:
            if self.category_group_name == "Credit Card Payments":
                self.term = "short"
                return
            
        if self.name == "Amex Membership":
            self.term = "medium"
            
        self.term = "long"

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

    
def get_categories(session: Session, auth: Any, budget_id: str) -> List[Category]:
    resp_dict = {}
    try:
        resp = session.get(urllib.parse.urljoin(_base_url, _categories_url.format(budget_id)), auth=auth)
        resp.raise_for_status()
        resp_dict = resp.json()

    except exceptions.HTTPError as e:
        print("Bad HTTP status code:", e)
    except exceptions.RequestException as e:
        print("Network error:", e)
        
    log.debug(f"list categories json: {resp_dict}")

    return [
        Category(category_json)
        for category_group in resp_dict["data"]["category_groups"]
        for category_json in category_group["categories"]
    ] 
    