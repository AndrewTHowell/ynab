import argparse
from decimal import Decimal
import json
import logging
import os
import urllib.parse
import requests
import re
from typing import Any, Dict, List
import locale
from prettytable import PrettyTable
from datetime import datetime, timedelta

logging.basicConfig(format="%(levelname)s: %(message)s")
locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

_base_url = "https://api.ynab.com/v1/"

""" 
_terms defines what terms accounts/categories can be classed as.

Short: 0-3 months
Medium: 3 months - 5 years
Long: 5+ years
"""
_terms = ["short", "medium", "long"]

class BearerAuth(requests.auth.AuthBase): # type: ignore
    def __init__(self, token):
        self.token = token
        
    def __call__(self, r):
        r.headers["authorization"] = "Bearer " + self.token
        return r
    
def valid_file_path(file_path: str):
    if not os.path.exists(file_path):
        raise argparse.ArgumentTypeError
    return file_path

def main():
    parser = argparse.ArgumentParser(
        prog="YNAB",
        description="Script for consuming and processing YNAB data.",
    )
    parser.add_argument(
        "-c", "--config_file_path",
        help="The path to the configuration for this script.",
        type=valid_file_path,
        required=True,
        dest="config_file_path",
    )
    parser.add_argument(
        "-d", "--debug",
        help="Turn on debug logging.",
        action='store_true',
        dest="debug"
    )
    args = parser.parse_args()
    
    if args.debug:
        log.setLevel(logging.DEBUG)
    
    config_file_path = args.config_file_path
    
    with open(config_file_path) as f:
        config = json.load(f)

    auth_token = config["auth_token"]
    log.debug(f"auth_token: {auth_token}")
    auth = BearerAuth(auth_token)
    
    budget_name = ""
    if "budget_name" in config:
        budget_name = config["budget_name"]
    log.debug(f"budget_name: {budget_name}")
        
    if budget_name:
        budget = get_budget_by_name(base_url=_base_url, auth=auth, name=budget_name)
    else:
        budget = get_last_used_budget(base_url=_base_url, auth=auth)
            
    accounts = get_accounts(base_url=_base_url, auth=auth, budget_id=budget["id"])
    
    open_accounts = [
        account for account in accounts
        #if not account.closed and account.name not in ["Pension", "Student Loan"]
        if account.name not in ["Pension", "Student Loan"]
    ]
    
    term_totals = {term: Decimal(0) for term in _terms}
    account_names_by_term = {term: [] for term in _terms}
    for open_account in open_accounts:
        term_totals[open_account.term] += open_account.balance
        account_names_by_term[open_account.term].append(open_account.name)
    
    category_total = Decimal(0)
    for term_total in term_totals.values():
        category_total += term_total
        
    net_worth = PrettyTable(["Net Worth"])
    net_worth.add_row([locale.currency(category_total, grouping=True)])
    print(net_worth)
        
    categories = get_categories(base_url=_base_url, auth=auth, budget_id=budget["id"])
    
    active_categories = [
        category for category in categories
        #if not category.hidden and not category.deleted and
        if not category.name == "Inflow: Ready to Assign"
    ]
    
    active_categories.sort(key = lambda x: (x.name))
    active_categories.sort(key = lambda x: (x.balance))
    active_categories.sort(key = lambda x: (x.term), reverse=True)
    
    category_total = Decimal(0)
    categories_table = PrettyTable(["Name", "Balance", "Term"])
    for category in active_categories:
        categories_table.add_row([
            category.name,
            locale.currency(category.balance, grouping=True),
            category.term,
        ])
        category_total += category.balance
    print(categories_table)
    print(f"category_total: {category_total}")
    
    categories_by_term = {}
    for category in active_categories:
        if category.term not in categories_by_term:
            categories_by_term[category.term] = []
        categories_by_term[category.term].append(category)
        
    term_balances = { term: Decimal(0) for term in categories_by_term.keys() }
    for term, categories in categories_by_term.items():
        for category in categories:
            term_balances[term] += category.balance
            
    # Manually fake a category for student loan
    ## It means we don't have to ignore it from balances and final net worth
    
    account_total = Decimal(0)
    accounts_table = PrettyTable(["Name", "Balance", "Term"])
    for account in open_accounts:
        accounts_table.add_row([
            account.name,
            locale.currency(account.balance, grouping=True),
            account.term,
        ])
        account_total += account.balance
    print(accounts_table)
    print(f"account_total: {account_total}")
    
    checksum = account_total - category_total
    print(f"checksum: {checksum}")
    assert checksum == 0
    
    term_total_diff = {
        term: {
            "diff": term_totals[term],# - target_term_totals[term],
            #"target": target_term_totals[term],
            "actual": term_totals[term]
        }
        for term in _terms# if term_totals[term] - target_term_totals[term] != 0
    }
    
    breakdown_by_terms = PrettyTable(["Term", "Target Total", "Actual Total", "Action"])
    for term, term_total in term_total_diff.items():
        diff = term_total["diff"] 
        target_total = term_total["target"]
        actual_total = term_total["actual"]
        
        operand = "more"
        if diff > 0:
            operand = "less"
        diff = abs(diff)
        diff = round(diff, -2) # Round to nearest 100
        
        breakdown_by_terms.add_row([
            term.capitalize(),
            locale.currency(target_total, grouping=True),
            locale.currency(actual_total, grouping=True),
            f"Needs ~{locale.currency(diff, grouping=True)} {operand}"
        ])
        
    print(breakdown_by_terms)
        

_budgets_url = "budgets"

def get_budgets(base_url: str, auth: Any) -> List[Any]:
    resp_dict = {}
    try:
        resp = requests.get(urllib.parse.urljoin(base_url, _budgets_url), auth=auth)
        resp.raise_for_status()
        resp_dict = resp.json()

    except requests.exceptions.HTTPError as e:
        print("Bad HTTP status code:", e)
    except requests.exceptions.RequestException as e:
        print("Network error:", e)

    return resp_dict["data"]["budgets"]

def get_budget_by_name(base_url: str, auth: Any, name: str) -> Dict[str, Any]:
    budgets = get_budgets(base_url=base_url, auth=auth)
    
    for budget in budgets:
        if budget["name"] == name:
            return budget
    
    return None # type: ignore

_budget_url = "budgets/{}"

def get_last_used_budget(base_url: str, auth: Any) -> Dict[str, Any]:
    resp_dict = {}
    try:
        resp = requests.get(urllib.parse.urljoin(base_url, _budget_url.format("last-used")), auth=auth)
        resp.raise_for_status()
        resp_dict = resp.json()

    except requests.exceptions.HTTPError as e:
        print("Bad HTTP status code:", e)
    except requests.exceptions.RequestException as e:
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

    
def get_accounts(base_url: str, auth: Any, budget_id: str) -> List[Account]:
    resp_dict = {}
    try:
        resp = requests.get(urllib.parse.urljoin(base_url, _accounts_url.format(budget_id)), auth=auth)
        resp.raise_for_status()
        resp_dict = resp.json()

    except requests.exceptions.HTTPError as e:
        print("Bad HTTP status code:", e)
    except requests.exceptions.RequestException as e:
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

    
def get_categories(base_url: str, auth: Any, budget_id: str) -> List[Category]:
    resp_dict = {}
    try:
        resp = requests.get(urllib.parse.urljoin(base_url, _categories_url.format(budget_id)), auth=auth)
        resp.raise_for_status()
        resp_dict = resp.json()

    except requests.exceptions.HTTPError as e:
        print("Bad HTTP status code:", e)
    except requests.exceptions.RequestException as e:
        print("Network error:", e)
        
    log.debug(f"list categories json: {resp_dict}")

    return [
        Category(category_json)
        for category_group in resp_dict["data"]["category_groups"]
        for category_json in category_group["categories"]
    ] 
    

if __name__ == "__main__":
    main()