import urllib.parse
from decimal import Decimal
import re
import os
import json
from typing import Any, Dict, List
from datetime import datetime, timedelta
import jsonpickle
from requests import exceptions, auth, Session
import requests_cache
import logging
import locale

logging.basicConfig(format="%(levelname)s: %(message)s")
locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

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
        self.type = account_json["type"]
        self.balance = Decimal(account_json["balance"]) / Decimal(1000)
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
        return term.split()[0].lower()

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()
    
class Budget:
    def __init__(self, budget_json: Dict):
        log.debug(f"budget_json: {budget_json}")
        
        self.id = budget_json["id"]
        self.name = budget_json["name"]

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

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


class Client():
    _base_url = "https://api.ynab.com/v1/"
    _accounts_url = "budgets/{}/accounts"
    _budget_url = "budgets/{}"
    _budgets_url = "budgets"
    _categories_url = "budgets/{}/categories"
    _cache_file_path = "delta_cache.json"
    
    def __init__(self, auth_token: str, caching: str):
        self.auth = BearerAuth(auth_token)
        self.session = Session()
        self.cache = None
        
        match caching:
            case "none":
                pass
            case "naive":
                self.session = requests_cache.CachedSession(cache_name="naive_cache", expire_after=60)
            case "delta":
                if not os.path.exists(self._cache_file_path):
                    self.cache = {}
                else:
                    with open(self._cache_file_path) as f:
                        encoded_cache = json.load(f)
                        self.cache = jsonpickle.decode(str(encoded_cache))
     
    def __enter__(self):
        return self
 
    def __exit__(self, *args):
        if not self.cache is None:
            encoded_cache = jsonpickle.encode(self.cache)
            with open(self._cache_file_path, mode="w") as f:
                json.dump(encoded_cache, f)  
    
    def get(self, url: str, server_knowledge=None):
        # Check cache
        params={}
        if not server_knowledge is None:
            params["last_knowledge_of_server"] = server_knowledge
        
        resp_dict = {}
        try:
            resp = self.session.get(
                urllib.parse.urljoin(self._base_url, url),
                params=params,
                auth=self.auth
            )
            resp.raise_for_status()
            resp_dict = resp.json()

        except exceptions.HTTPError as e:
            log.error(f"Bad HTTP status code: {e}")
        except exceptions.RequestException as e:
            log.error(f"Network error: {e}")
            
        return resp_dict["data"]

    def get_last_used_budget(self) -> Budget:
        cache_key = "budget"
        
        if not self.cache is None and cache_key in self.cache:
            return self.cache[cache_key][cache_key]
            
        resp_data = self.get(self._budget_url.format("last-used"))
        budget = Budget(resp_data["budget"])
        
        if not self.cache is None:
            self.cache[cache_key] = {
                "server_knowledge": resp_data["server_knowledge"],
                cache_key: budget
            }
            
        return budget       
        
    
    def get_accounts(self, budget_id: str) -> List[Account]:     
        cache_key = "accounts"
        
        server_knowledge = None
        if not self.cache is None and cache_key in self.cache:
            server_knowledge = self.cache[cache_key]["server_knowledge"]
                   
        resp_data = self.get(self._accounts_url.format(budget_id), server_knowledge)
        accounts = [
            Account(account_json)
            for account_json in resp_data["accounts"]
        ]
        
        if not self.cache is None:
            self.cache[cache_key] = {
                "server_knowledge": resp_data["server_knowledge"],
                cache_key: accounts
            }
            
        return accounts  
       
    def get_categories(self, budget_id: str) -> List[Category]:    
        resp_data = self.get(self._categories_url.format(budget_id))
        return [
            Category(category_json)
            for category_group in resp_data["category_groups"]
            for category_json in category_group["categories"]
        ] 
