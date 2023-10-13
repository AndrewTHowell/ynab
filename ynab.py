import argparse
from decimal import Decimal
import json
import os
import urllib.parse
import requests
from typing import Any, Dict, List
import locale

locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')

base_url = "https://api.ynab.com/v1/"

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
    args = parser.parse_args()
    
    config_file_path = args.config_file_path
    
    with open(config_file_path) as f:
        config = json.load(f)

    auth_token = config["auth_token"]
    auth = BearerAuth(auth_token)
    budget_name =config["budget_name"]
    fund_distribution =config["fund_distribution"]
    
    
    budget = get_budget_by_name(base_url=base_url, auth=auth, name=budget_name)
    
    accounts = get_accounts(base_url=base_url, auth=auth, budget_id=budget["id"])
    
    open_accounts = [ account for account in accounts if not account.closed ]
    
    accounts_by_term = fund_distribution["accounts_by_term"]
    terms = list(accounts_by_term.keys())
    term_totals = {term: Decimal(0) for term in terms}
    for open_account in open_accounts:
        for term in terms:
            if open_account.name in accounts_by_term[term]:
                term_totals[term] += open_account.balance
    
    total = 0
    for term_total in term_totals.values():
        total += term_total
        
    print(f"Net Worth: {locale.currency(total, grouping=True)}")
    
    target_term_distribution = fund_distribution["target_term_distribution"]
    real_term_distribution = {
        term: float(term_total)/float(total)
        for term, term_total in term_totals.items()
    }
    
    term_distribution_diff = {
        term: f"{real_term_distribution[term] - target_term_distribution[term]:.2f}" # Needs division by 100 to make %
        for term in terms
    }
    
    print(term_totals)
    print(target_term_distribution)
    print(real_term_distribution)
    print(term_distribution_diff)
        

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

_accounts_url = "budgets/{}/accounts"

class Account:
    def __init__(self, account_json: Dict):
        self.id = account_json["id"]
        self.name = account_json["name"]
        self.balance = Decimal(account_json["balance"]) / Decimal(1000)
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
    

if __name__ == "__main__":
    main()