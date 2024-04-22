from __future__ import annotations

import copy
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List

import jsonpickle
import pandas as pd
import requests_cache
from requests import auth

_CACHE_DIR_PATH = ".cache"
_CACHE_FILE = "cache.json"
_REQUEST_CACHE_FILE_NAME = "requests_cache"
_REQUEST_CACHE_EXPIRY_SECONDS = 600

LAST_USED_BUDGET_ID="last-used"

def milliunits_to_centiunits(num) -> int:
    if not num:
        return int(0)
    
    centiunit = num / int(10)
    return int(centiunit)

class BearerAuth(auth.AuthBase): # type: ignore
    def __init__(self, token):
        self.token = token
        
    def __call__(self, r):
        r.headers["authorization"] = "Bearer " + self.token
        return r

class Term(Enum):
    short = "Short"
    medium = "Medium"
    long = "Long"

class Account:
    def __init__(self, account_json: Dict):
        #logging.debug(f"account_json: {account_json}")
        
        self.id = account_json["id"]
        self.name = account_json["name"]
        self.set_type(account_json["type"])
        self.on_budget = account_json["on_budget"]
        self.balance = milliunits_to_centiunits(account_json["balance"])
        self.set_term(account_json["note"])
        self.closed = account_json["closed"]

    def get_id(self):
        return self.id
        
    class Type(Enum):
        checking = "Checking"
        savings = "Savings"
        cash = "Cash"
        credit_card = "Credit Card"
        line_of_credit = "Line of Credit"
        other_asset = "Other Asset"
        other_liability = "Other Liability"
        mortgage = "mortgage"
        auto_loan = "Auto Loan"
        student_loan = "Student Loan"
        personal_loan = "Personal Loan"
        medical_debt = "Medical Debt"
        other_debt = "Other Debt"
    
    def set_type(self, type_str: str):
        match type_str:
            case "checking":
                self.type = Account.Type.checking
            case "savings":
                self.type = Account.Type.savings
            case "cash":
                self.type = Account.Type.cash
            case "creditCard":
                self.type = Account.Type.credit_card
            case "lineOfCredit":
                self.type = Account.Type.line_of_credit
            case "otherAsset":
                self.type = Account.Type.other_asset
            case "otherLiability":
                self.type = Account.Type.other_liability
            case "autoLoan":
                self.type = Account.Type.auto_loan
            case "studentLoan":
                self.type = Account.Type.student_loan
            case "personalLoan":
                self.type = Account.Type.personal_loan
            case "medicalDebt":
                self.type = Account.Type.medical_debt
            case "otherDebt":
                self.type = Account.Type.other_debt
            case _:
                logging.error(f"unexpected account type: {type_str}")
                raise Exception()
        
    def set_term(self, note: str):        
        def extract_term_from_note(note: str):
            if not note:
                logging.error(f"account {self.name}: empty note")
                raise Exception()
            
            match = re.search(r'\w+ Term', note)
            if not match:
                logging.error(f"account {self.name}: term not found in note: {note}")
                raise Exception()
            
            term = match.group(0)
            return term.split()[0].lower()

        term_str = extract_term_from_note(note)
        match term_str:
            case "short":
                self.term = Term.short
            case "medium":
                self.term = Term.medium
            case "long":
                self.term = Term.long
            case _:
                logging.error(f"account {self.name}: unexpected term: {term_str}")
                raise Exception()
    
    def as_dict(self) -> Dict:
        return {
            "id": self.id, "name": self.name, "type": self.type, "on budget": self.on_budget,
            "balance": self.balance, "term": self.term, "closed": self.closed,
        }
        
    def to_df(self) -> pd.DataFrame:
        accounts = pd.DataFrame([self.as_dict()])
        accounts["term"] = pd.Categorical(accounts["term"], [term for term in Term], ordered=True)
        accounts["type"] = pd.Categorical(accounts["type"], [type for type in Account.Type], ordered=True)
        return accounts
    
    @classmethod
    def collect_as_df(cls, accounts):
        accounts_df = pd.concat([ account.to_df() for account in accounts ], ignore_index=True)
        return accounts_df.sort_values("name")
    
    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

class Budget:
    def __init__(self, budget_json: Dict):
        #logging.debug(f"budget_json: {budget_json}")
        
        self.id = budget_json["id"]
        self.name = budget_json["name"]

    def get_id(self):
        return self.id
    
    def as_dict(self):
        return {"id": self.id, "name": self.name}

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()
                
class Category:
    def __init__(self, category_json: Dict):
        #logging.debug(f"category_json: {category_json}")
        
        self.id = category_json["id"]
        self.name = re.sub(r'[^\w :()]', '', category_json["name"]).lstrip(" ")
        self.activity = milliunits_to_centiunits(category_json["activity"])
        self.balance = milliunits_to_centiunits(category_json["balance"])
        self.budgeted = milliunits_to_centiunits(category_json["budgeted"])
        self.category_group_name = category_json["category_group_name"]
        self.hidden = category_json["hidden"]
        self.deleted = category_json["deleted"]
        
        self.set_cadence(category_json["goal_cadence"])
        self.goal_cadence_frequency = category_json["goal_cadence_frequency"]
        
        self.goal_months_to_budget = category_json["goal_months_to_budget"]
        self.set_goal_type(category_json["goal_type"])
        self.set_goal_target_month(category_json["goal_target_month"])
        self.set_term()

    def get_id(self):
        return self.id
        
    class GoalType(Enum):
        none = "None"
        needed_for_spending = "Needed For Spending"
        target_balance = "Target Balance"
        target_balance_date = "Target Balance by Date"
        monthly_funding = "Monthly Funding"
        
    def set_goal_type(self, goal_type_str: str):
        match goal_type_str:
            case "":
                self.goal_type = Category.GoalType.none
            case "NEED":
                self.goal_type = Category.GoalType.needed_for_spending
            case "TB":
                self.goal_type = Category.GoalType.target_balance
            case "TBD":
                self.goal_type = Category.GoalType.target_balance_date
            case "MF":
                self.goal_type = Category.GoalType.monthly_funding
            case _:
                if goal_type_str is None:
                    self.goal_type = Category.GoalType.none
                else:
                    logging.error(f"unexpected category goal type: {goal_type_str}")
                    raise Exception()

    class GoalCadence(Enum):
        none = ""
        monthly = "Monthly"
        weekly = "Weekly"
        yearly = "Yearly"   
        
    def set_cadence(self, cadence: int):
        match cadence:
            case 0:
                self.goal_cadence = Category.GoalCadence.none
            case 1:
                self.goal_cadence = Category.GoalCadence.monthly
            case 2:
                self.goal_cadence = Category.GoalCadence.weekly
            case 13:
                self.goal_cadence = Category.GoalCadence.yearly
            case _:
                if cadence is None:
                    self.goal_cadence = Category.GoalCadence.none
                else:
                    # See https://api.ynab.com/v1#/Categories/getCategories schema for definition of goal_cadence
                    logging.error(f"unexpected category goal type: {cadence}, want 0,1,2, or 13. 3-12 are legacy")
                    raise Exception()
        
    def set_goal_target_month(self, goal_target_month_str: str):
        self.goal_target_month = None
        if goal_target_month_str:
            self.goal_target_month = datetime.strptime(goal_target_month_str, "%Y-%m-%d").date()
        
    def set_term(self):
        if self.goal_type != Category.GoalType.none:
            if self.goal_type == Category.GoalType.target_balance or self.goal_type == Category.GoalType.monthly_funding:
                self.term = Term.medium
                return
            
        if self.goal_months_to_budget:
            if self.goal_months_to_budget <= 3:
                self.term = Term.short
                return
            if self.goal_months_to_budget <= 5*12:
                self.term = Term.medium
                return
            
        if self.goal_target_month:
            if self.goal_target_month <= datetime.today().date() + timedelta(days=3*30):
                self.term = Term.short
                return
            if self.goal_target_month <= datetime.today().date() + timedelta(days=5*365):
                self.term = Term.medium
                return
            
        if self.category_group_name:
            if self.category_group_name == "Credit Card Payments":
                self.term = Term.short
                return
            
        if self.name == "Amex Membership":
            self.term = Term.medium
            
        self.term = Term.long
        
    def copy(self) -> Category:
        category = copy.deepcopy(self)
        category.activity, self.balance, self.budgeted = 0, 0, 0
        self.goal_type = Category.GoalType.none
        self.goal_target_month = None
        self.goal_cadence = Category.GoalCadence.none
        self.goal_cadence_frequency, self.goal_months_to_budget = "", 0
        return category
    
    def as_dict(self):
        return {
            "id": self.id, "name": self.name, "activity": self.activity, "balance": self.balance, "budgeted": self.budgeted,
            "term": self.term, "category group name": self.category_group_name, "goal type": self.goal_type,
            "goal target month": self.goal_target_month,"goal cadence": self.goal_cadence,
            "goal cadence frequency": self.goal_cadence_frequency, "goal months to budget": self.goal_months_to_budget,
            "hidden": self.hidden, "deleted": self.deleted,
        }
        
    def to_df(self) -> pd.DataFrame:
        categories = pd.DataFrame([self.as_dict()])
        categories["goal cadence"] = pd.Categorical(categories["goal cadence"], [cadence for cadence in Category.GoalCadence], ordered=True)
        categories["goal type"] = pd.Categorical(categories["goal type"], [type for type in Category.GoalType], ordered=True)
        categories["term"] = pd.Categorical(categories["term"], [term for term in Term], ordered=True)
        return categories
    
    @classmethod
    def collect_as_df(cls, categories):
        categories_df = pd.concat([ category.to_df() for category in categories ], ignore_index=True)
        return categories_df.sort_values(
            by=["term", "balance", "name"],
            ascending=[False, True, True],
        )

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

class Month:
    def __init__(self, month_json: Dict):
        logging.debug(f"month_json: {month_json}")
        
        self.month = month_json["month"]

    def get_id(self):
        return self.month
    
    @classmethod
    def str_format(cls):
        return "%Y-%m-%d"
    
    @classmethod
    def str_to_date(cls, month:str):
        return  datetime.strptime(month, cls.str_format())
    
    def as_dict(self):
        return {"month": self.month}
        
    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame([self.as_dict()])
    
    @classmethod
    def collect_as_df(cls, months):
        months_df = pd.concat([ month.to_df() for month in months ], ignore_index=True)
        return months_df.sort_values(
            by=["month"],
            ascending=True,
        )

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

class Payee:
    def __init__(self, payee_json: Dict):
        #logging.debug(f"payee_json: {payee_json}")
        
        self.id = payee_json["id"]
        self.name = payee_json["name"]
        self.transfer_account_id = payee_json["transfer_account_id"]
        self.deleted = payee_json["deleted"]

    def get_id(self):
        return self.id
    
    def as_dict(self):
        return {"id": self.id, "name": self.name, "transfer account id": self.transfer_account_id, "deleted": self.deleted}
        
    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame([self.as_dict()])
    
    @classmethod
    def collect_as_df(cls, payees):
        payees_df = pd.concat([ payee.to_df() for payee in payees ], ignore_index=True)
        return payees_df.sort_values(
            by=["name", "id"],
            ascending=True,
        )

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return self.__str__()

class Transaction:
    def __init__(self, transaction_json: Dict):
        #logging.debug(f"transaction_json: {transaction_json}")
        
        self.id = transaction_json["id"]
        self.date = transaction_json["date"]
        self.amount = transaction_json["amount"]
        self.account_name = transaction_json["account_name"]
        self.payee_name = transaction_json["payee_name"]
        self.payee_id = transaction_json["payee_id"]
        self.deleted = transaction_json["deleted"]

    def get_id(self):
        return self.id
    
    def as_dict(self):
        return {
            "id": self.id, "date": self.date, "amount": self.amount,
            "account name": self.account_name, "payee name": self.payee_name,
            "payee id": self.payee_id, "deleted": self.deleted
        }
        
    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame([self.as_dict()])
    
    @classmethod
    def collect_as_df(cls, transactions):
        transactions_df = pd.concat([ transaction.to_df() for transaction in transactions ], ignore_index=True)
        return transactions_df.sort_values(
            by=["date", "account name"],
            ascending=[False, True],
        )

    def __str__(self):
        return self.id
    
    def __repr__(self):
        return self.__str__()
    
class CacheItem():
    def __init__(self, data: Any):
        self.data = data
    
class DeltaCacheData(ABC):
    @abstractmethod
    def get_id(self) -> str:
        pass
    
class DeltaCacheItem():
    def __init__(self, server_knowledge: int, data: DeltaCacheData | List[DeltaCacheData]):
        self.server_knowledge = server_knowledge
        self.data = data
        
class Cache(dict):
    def __init__(self, file_path: str, mode: str):
        super(Cache, self).__init__()
        self._file_path = file_path
        
        self.frozen = False
        match mode:
            case Client.CacheMode.freeze:
                self.frozen = True
            case Client.CacheMode.flush:
                self.load_from_file()
        
        logging.debug(f"DeltaCache.frozen: {self.frozen}")
                
                
    def load_from_file(self):
        if os.path.exists(self._file_path):
            with open(self._file_path) as f:
                encoded_cache = json.load(f)
                logging.debug(f"encoded_cache: {encoded_cache}")
                cache: Dict = jsonpickle.decode(str(encoded_cache)) # type: ignore
                
                self.clear()
                self.update(cache)
                
    def save_to_file(self):
        file_path = self._file_path
        del self._file_path
        
        encoded_cache = jsonpickle.encode(self)
        logging.debug(f"encoded_cache: {encoded_cache}")
        with open(file_path, mode="w") as f:
            json.dump(encoded_cache, f)
            
    def update_delta_data(self, key: str, data: List[DeltaCacheData], server_knowledge: int) -> List[DeltaCacheData]:            
        cached_data: List[DeltaCacheData] = []
        if key in self:
            cached_data = self[key].data
        
        data_to_cache = data
        for cached_datum in cached_data:
            found = False
            for datum_to_cache in data_to_cache:
                if cached_datum.get_id() == datum_to_cache.get_id():
                    # Cached datum was also in the delta response
                    found = True
            
            if not found:
                # Cached datum wasn't in delta response, so it's not stale and should be kept
                data_to_cache.append(cached_datum)
        
        self[key] = DeltaCacheItem(server_knowledge, data_to_cache)
        
        return data_to_cache
        
    def update_data(self, key: str, data: Any) -> None:
        self[key] = CacheItem(data)

class Client():
    _base_url = "https://api.ynab.com/v1/"
    _accounts_url = "budgets/{}/accounts"
    #_budget_url = "budgets/{}"
    #_budgets_url = "budgets"
    _categories_url = "budgets/{}/categories"
    _category_by_month_url = "budgets/{}/months/{}/categories/{}"
    _months_url = "budgets/{}/months"
    _payees_url = "budgets/{}/payees"
    _transactions_url = "budgets/{}/transactions"
    
    _delta_cacheable_urls = {
        _accounts_url,
        _categories_url,
        _months_url,
        _payees_url,
        _transactions_url,
    }
    
    _rate_warn_threshold = 0.95
    
    class CacheMode(Enum): 
        normal = 1
        freeze = 2
        flush = 3
        
        def __str__(self):
            return self.name

        def __repr__(self):
            return str(self)

        @staticmethod
        def argparse(s):
            try:
                return Client.CacheMode[s]
            except KeyError:
                return s
    
    def __init__(self, auth_token: str, cache_mode: CacheMode, cache_ttl=_REQUEST_CACHE_EXPIRY_SECONDS):
        logging.debug(f"Operating in cache mode: {cache_mode}")
        
        self.auth = BearerAuth(auth_token)
        
        if not os.path.exists(_CACHE_DIR_PATH):
            os.makedirs(_CACHE_DIR_PATH)
        
        self.session = requests_cache.CachedSession(
            cache_name=os.path.join(_CACHE_DIR_PATH, _REQUEST_CACHE_FILE_NAME),
            expire_after=cache_ttl,
        )
        if cache_mode == Client.CacheMode.flush:
            input_str = input(f"You've passed in the `{Client.CacheMode.flush}` cache mode, are you sure you want to flush the cache? (Y|N): ")
            if input_str.upper() != "Y":
                logging.fatal("Cache mode `flush` accidentally given. Rerun without this mode")
                exit(0)
            else:
                self.session.cache.clear()
            
        self.cache = Cache(file_path=os.path.join(_CACHE_DIR_PATH, _CACHE_FILE), mode=cache_mode)
        
    def __enter__(self):
        return self
 
    def __exit__(self, *args):
        if not self.cache is None:
            self.cache.save_to_file()
            
    def record_rate_limit(self, rate_limit: str):
        current, max = rate_limit.split("/")
        current, max = int(current), int(max)
        
        self.current_rate = current
        
        logging.debug(f"Request limit used: {current}/{max}")
        if current/max > self._rate_warn_threshold :
            logging.warn(f"{self._rate_warn_threshold} breached, you only have {max-current} requests remaining this hour")
    
    def get_cached_resource(self, url_template: str, url_args: List[str], resource_extractor: Callable):
        url = url_template.format(*url_args)
        
        params={}
        if url in self.cache:
            match (item := self.cache[url]):
                case CacheItem():
                    return item.data
                case DeltaCacheItem():
                    # When the cache is frozen, don't call to update the delta, just reuse what is already stored locally
                    if self.cache.frozen:
                        logging.debug(f"Delta frozen, returning existing data for URL '{url}'")
                        return self.cache[url].data
                    params["last_knowledge_of_server"] = item.server_knowledge
                case _:
                    raise TypeError("Client cache contained unexpected item type")
        
        data = self.get(url, params)
        resource = resource_extractor(data)
        
        if url_template in self._delta_cacheable_urls:
            resource = self.cache.update_delta_data(url, resource, server_knowledge=data["server_knowledge"])
        else:
            self.cache.update_data(url, resource)
            
        return resource
    
    def get_resource(self, url_template: str, url_args: List[str], resource_extractor: Callable):
        url = url_template.format(*url_args)
        data = self.get(url)
        resource = resource_extractor(data)
        return resource
    
    def get(self, url: str, params:Dict={}):
        resp = self.session.get(
            urllib.parse.urljoin(self._base_url, url),
            params=params,
            auth=self.auth
        )
        resp.raise_for_status()
        
        self.record_rate_limit(resp.headers['X-Rate-Limit'])

        return resp.json()["data"]
        
    """
    def get_last_used_budget(self) -> Budget:
        return self.get(self._budget_url, [LAST_USED_BUDGET_ID], lambda data: Budget(data["budget"]))
    """

    def get_accounts(self, budget_id=LAST_USED_BUDGET_ID) -> List[Account]:  
        return self.get_cached_resource(self._accounts_url, [budget_id], lambda data: [
            Account(account_json)
            for account_json in data["accounts"]
        ])
       
    def get_categories(self, budget_id=LAST_USED_BUDGET_ID) -> List[Category]:
        return self.get_cached_resource(self._categories_url, [budget_id], lambda data: [
            Category(category_json)
            for category_group in data["category_groups"]
            for category_json in category_group["categories"]
        ])
       
    def get_category_by_month(self, month: str, category_id: str, budget_id=LAST_USED_BUDGET_ID) -> Category:
        start_date_of_target_month = Month.str_to_date(month)
        start_date_of_current_month = datetime.today().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start_date_of_target_month < start_date_of_current_month:
            # Previous months are static and therefore cacheable
            return self.get_cached_resource(self._category_by_month_url, [budget_id, month, category_id], lambda data: Category(data["category"]))
        
        return self.get_resource(self._category_by_month_url, [budget_id, month, category_id], lambda data: Category(data["category"]))
        
    def get_months(self, budget_id=LAST_USED_BUDGET_ID) -> List[Month]:
        return self.get_cached_resource(self._months_url, [budget_id], lambda data: [
            Month(month_json)
            for month_json in data["months"]
        ])
       
    def get_payees(self, budget_id=LAST_USED_BUDGET_ID) -> List[Payee]:
        return self.get_cached_resource(self._payees_url, [budget_id], lambda data: [
            Payee(payee_json)
            for payee_json in data["payees"]
        ])
       
    def get_transactions(self, budget_id=LAST_USED_BUDGET_ID) -> List[Transaction]:
        return self.get_cached_resource(self._transactions_url, [budget_id], lambda data: [
            Transaction(transaction_json)
            for transaction_json in data["transactions"]
        ])
