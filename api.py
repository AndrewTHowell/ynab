import urllib.parse
from decimal import Decimal
import re
import os
import json
from typing import Any, Dict, List, Protocol
from datetime import datetime, timedelta
import jsonpickle
from requests import auth, Session
import requests_cache
import logging
import locale
from enum import Enum

locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')
logging.basicConfig(format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

_CACHE_DIR_PATH = ".cache"
_REQUEST_CACHE_FILE_NAME = "requests"
_DELTA_CACHE_FILE = "delta.json"
_REQUEST_CACHE_EXPIRY_SECONDS = 600

def milliunits_to_centiunits(num) -> int:
    centiunit = num / int(10)
    return int(centiunit)

class BearerAuth(auth.AuthBase): # type: ignore
    def __init__(self, token):
        self.token = token
        
    def __call__(self, r):
        r.headers["authorization"] = "Bearer " + self.token
        return r

class Account:
    def __init__(self, account_json: Dict):
        log.debug(f"account_json: {account_json}")
        
        self.id = account_json["id"]
        self.name = account_json["name"]
        # TODO: use an enum for this
        self.type = account_json["type"]
        self.on_budget = account_json["on_budget"]
        self.balance = milliunits_to_centiunits(account_json["balance"])
        # TODO: use an enum for this
        self.term = self.get_term(account_json["note"])
        self.closed = account_json["closed"]

    def get_term(self, note: str):
        log.debug(f"note: {note}")
        if not note:
            return ""
        
        match = re.search(r'\w+ Term', note)
        if not match:
            return ""
        
        term = match.group(0)
        return term.split()[0].title()
    
    def as_dict(self):
        return {
            "id": self.id, "name": self.name, "type": self.type, "on budget": self.on_budget,
            "balance": self.balance, "term": self.term, "closed": self.closed,
        }

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()
    
class Budget:
    def __init__(self, budget_json: Dict):
        log.debug(f"budget_json: {budget_json}")
        
        self.id = budget_json["id"]
        self.name = budget_json["name"]
    
    def as_dict(self):
        return {"id": self.id, "name": self.name}

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

class CategoryGoalType(Enum):
    none = "None"
    needed_for_spending = "Needed For Spending"
    target_balance = "Target Balance"
    target_balance_date = "Target Balance by Date"
    monthly_funding = "Monthly Funding"

class CategoryGoalCadence(Enum):
    none = ""
    monthly = "Monthly"
    weekly = "Weekly"
    yearly = "Yearly"
                
class Category:        
    def __init__(self, category_json: Dict):
        log.debug(f"category_json: {category_json}")
        
        self.id = category_json["id"]
        self.name = re.sub(r'[^\w :()]', '', category_json["name"]).lstrip(" ")
        self.balance = milliunits_to_centiunits(category_json["balance"])
        self.category_group_name = category_json["category_group_name"]
        self.hidden = category_json["hidden"]
        self.deleted = category_json["deleted"]
        
        self.set_cadence(category_json["goal_cadence"])
        self.goal_cadence_frequency = category_json["goal_cadence_frequency"]
        
        self.goal_months_to_budget = category_json["goal_months_to_budget"]
        self.set_goal_type(category_json["goal_type"])
        self.set_goal_target_month(category_json["goal_target_month"])
        self.set_term()
        
    def set_cadence(self, cadence: int):
        match cadence:
            case 0:
                self.goal_cadence = CategoryGoalCadence.none
            case 1:
                self.goal_cadence = CategoryGoalCadence.monthly
            case 2:
                self.goal_cadence = CategoryGoalCadence.weekly
            case 13:
                self.goal_cadence = CategoryGoalCadence.yearly
            case _:
                if cadence is None:
                    self.goal_cadence = CategoryGoalCadence.none
                else:
                    # See https://api.ynab.com/v1#/Categories/getCategories schema for definition of goal_cadence
                    log.error(f"unexpected category goal type: {cadence}, want 0,1,2, or 13. 3-12 are legacy")
                    raise Exception()
        
    def set_goal_type(self, goal_type_str: str):
        match goal_type_str:
            case "":
                self.goal_type = CategoryGoalType.none
            case "NEED":
                self.goal_type = CategoryGoalType.needed_for_spending
            case "TB":
                self.goal_type = CategoryGoalType.target_balance
            case "TBD":
                self.goal_type = CategoryGoalType.target_balance_date
            case "MF":
                self.goal_type = CategoryGoalType.monthly_funding
            case _:
                if goal_type_str is None:
                    self.goal_type = CategoryGoalType.none
                else:
                    log.error(f"unexpected category goal type: {goal_type_str}")
                    raise Exception()
        
    def set_goal_target_month(self, goal_target_month_str: str):
        self.goal_target_month = None
        if goal_target_month_str:
            self.goal_target_month = datetime.strptime(goal_target_month_str, "%Y-%m-%d").date()
        
    def set_term(self):
        # TODO: use an enum for this
        if self.goal_type != CategoryGoalType.none:
            if self.goal_type == CategoryGoalType.target_balance or self.goal_type == CategoryGoalType.monthly_funding:
                self.term = "Medium"
                return
            
        if self.goal_months_to_budget:
            if self.goal_months_to_budget <= 3:
                self.term = "Short"
                return
            if self.goal_months_to_budget <= 5*12:
                self.term = "Medium"
                return
            
        if self.goal_target_month:
            if self.goal_target_month <= datetime.today().date() + timedelta(days=3*30):
                self.term = "Short"
                return
            if self.goal_target_month <= datetime.today().date() + timedelta(days=5*365):
                self.term = "Medium"
                return
            
        if self.category_group_name:
            if self.category_group_name == "Credit Card Payments":
                self.term = "Short"
                return
            
        if self.name == "Amex Membership":
            self.term = "Medium"
            
        self.term = "Long"
    
    def as_dict(self):
        # TODO: use direct enums in dict repr. Could add __repr__ to enum classes? That would mean they'd still be enum typed but show just the value
        return {
            "id": self.id, "name": self.name, "balance": self.balance, "term": self.term,
            "category group name": self.category_group_name, "goal type": self.goal_type.value,
            "goal target month": self.goal_target_month,"goal cadence": self.goal_cadence.value,
            "goal cadence frequency": self.goal_cadence_frequency, "hidden": self.hidden, "deleted": self.deleted,
        }

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

class DeltaCacheData(Protocol):
    id: str
    
class DeltaCacheItem():
    def __init__(self, server_knowledge: int, data: DeltaCacheData | List[DeltaCacheData]):
        self.server_knowledge = server_knowledge
        self.data = data
        
class DeltaCache(dict):
    def __init__(self, file_path: str, flush_cache: bool):
        super(DeltaCache, self).__init__()
        self._file_path = file_path
        
        if not flush_cache:
            self.load_from_file()
                
    def load_from_file(self):
        if os.path.exists(self._file_path):
            with open(self._file_path) as f:
                encoded_cache = json.load(f)
                log.debug(f"encoded_cache: {encoded_cache}")
                cache: Dict = jsonpickle.decode(str(encoded_cache)) # type: ignore
                
                self.clear()
                self.update(cache)
                
    def save_to_file(self):
        file_path = self._file_path
        del self._file_path
        
        encoded_cache = jsonpickle.encode(self)
        log.debug(f"encoded_cache: {encoded_cache}")
        with open(file_path, mode="w") as f:
            json.dump(encoded_cache, f)
            
    def update_data(self, key: str, server_knowledge:int, data: List[Any]):
        cached_data = []
        if key in self:
            cached_data = self[key].data
        
        data_to_cache = data
        for cached_datum in cached_data:
            found = False
            for datum_to_cache in data_to_cache:
                if cached_datum.id == datum_to_cache.id:
                    # Cached datum was also in the delta response
                    found = True
            
            if not found:
                # Cached datum wasn't in delta response, so it's not stale and should be kept
                data_to_cache.append(cached_datum)
        
        self[key] = DeltaCacheItem(server_knowledge, data_to_cache)

class Client():
    _base_url = "https://api.ynab.com/v1/"
    _accounts_url = "budgets/{}/accounts"
    _budget_url = "budgets/{}"
    _budgets_url = "budgets"
    _categories_url = "budgets/{}/categories"
    
    def __init__(self, auth_token: str, flush_cache: bool, cache_ttl=_REQUEST_CACHE_EXPIRY_SECONDS):
        self.auth = BearerAuth(auth_token)
        
        if not os.path.exists(_CACHE_DIR_PATH):
            os.makedirs(_CACHE_DIR_PATH)
        
        self.session = requests_cache.CachedSession(
            cache_name=os.path.join(_CACHE_DIR_PATH, _REQUEST_CACHE_FILE_NAME),
            expire_after=cache_ttl,
        )
        if flush_cache:
            self.session.cache.clear()
            
        self.cache = DeltaCache(file_path=os.path.join(_CACHE_DIR_PATH, _DELTA_CACHE_FILE), flush_cache=flush_cache)
        
    def __enter__(self):
        return self
 
    def __exit__(self, *args):
        if not self.cache is None:
            self.cache.save_to_file()
    
    def get(self, url: str, server_knowledge=None):
        params={}
        if not server_knowledge is None:
            params["last_knowledge_of_server"] = server_knowledge
        
        resp_dict = {}
        resp = self.session.get(
            urllib.parse.urljoin(self._base_url, url),
            params=params,
            auth=self.auth
        )
        resp.raise_for_status()
        log.debug(f"Request limit used: {resp.headers['X-Rate-Limit']}")
            
        resp_dict = resp.json()
        return resp_dict["data"]
        
    def get_last_used_budget(self) -> Budget:        
        if not self.cache is None and "budget" in self.cache:
            return self.cache["budget"].data
            
        resp_data = self.get(self._budget_url.format("last-used"))
        budget = Budget(resp_data["budget"])
        
        if not self.cache is None:
            self.cache["budget"] = DeltaCacheItem(resp_data["server_knowledge"], budget)
            
        return budget

    def get_accounts(self, budget_id: str) -> List[Account]:
        server_knowledge = None
        if not self.cache is None and "accounts" in self.cache:
            server_knowledge = self.cache["accounts"].server_knowledge
                   
        resp_data = self.get(self._accounts_url.format(budget_id), server_knowledge)
        accounts = [
            Account(account_json)
            for account_json in resp_data["accounts"]
        ]
        
        if not self.cache is None:
            self.cache.update_data("accounts", resp_data["server_knowledge"], accounts)
            
        return accounts
       
    def get_categories(self, budget_id: str) -> List[Category]:  
        server_knowledge = None
        if not self.cache is None and "categories" in self.cache:
            server_knowledge = self.cache["categories"].server_knowledge
              
        resp_data = self.get(self._categories_url.format(budget_id), server_knowledge)
        categories = [
            Category(category_json)
            for category_group in resp_data["category_groups"]
            for category_json in category_group["categories"]
        ] 
        
        if not self.cache is None:
            self.cache.update_data("categories", resp_data["server_knowledge"], categories)
            
        return categories
