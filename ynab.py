import argparse
from decimal import Decimal
import json
import logging
import os
import locale
from prettytable import PrettyTable
import api
import pandas as pd
from tabulate import tabulate

locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')
logging.basicConfig(format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

""" 
_terms defines what terms accounts/categories can be classed as.

Short: 0-3 months
Medium: 3 months - 5 years
Long: 5+ years
"""
_terms = ["short", "medium", "long"]
    
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
        "-cf", "--config_file_path",
        help="The path to the configuration for this script.",
        type=valid_file_path,
        required=True,
        dest="config_file_path",
    )
    parser.add_argument(
        "-ca", "--cache",
        help="Turn on API caching.",
        action='store_true',
        dest="cache"
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
    
    budget_name = ""
    if "budget_name" in config:
        budget_name = config["budget_name"]
    log.debug(f"budget_name: {budget_name}")
    
    with api.Client(auth_token=auth_token, cache=args.cache) as client:       
        budget = client.get_last_used_budget()         
        accounts = client.get_accounts(budget_id=budget.id)
        categories = client.get_categories(budget_id=budget.id)
        
    accounts = pd.DataFrame([ account.as_dict() for account in accounts ])
    accounts.sort_values("name")
    
    categories = pd.DataFrame([ category.as_dict() for category in categories ])
    categories.sort_values(
        by=["name", "balance", "term"],
        ascending=[True, True, False]
    )
    
    print(generate_net_worth_report(accounts))
    
    account_total, accounts_table = generate_accounts_report(accounts)
    print(accounts_table)
    
    category_total, categories_table = generate_categories_report(categories)
    print(categories_table)
    
    log.debug(f"account_total: {account_total}")
    log.debug(f"category_total: {category_total}")
    log.debug(f"account_total - category_total: {account_total - category_total}")
    
    #generate_term_report(active_categories)

def generate_term_report(active_categories):
    categories_by_term = {}
    for category in active_categories:
        if category.term not in categories_by_term:
            categories_by_term[category.term] = []
        categories_by_term[category.term].append(category)
        
    term_balances = { term: Decimal(0) for term in categories_by_term.keys() }
    for term, categories in categories_by_term.items():
        for category in categories:
            term_balances[term] += category.balance
    
    """ term_total_diff = {
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
    print(breakdown_by_terms) """

def generate_accounts_report(accounts):
    open_accounts = accounts[accounts["closed"] == False]
    
    account_total = open_accounts["balance"].sum()
    
    accounts_table = PrettyTable(["Name", "Balance", "Term"])
    """ for account in accounts:
        accounts_table.add_row([
            account["name"],
            locale.currency(account.balance, grouping=True),
            account["term"],
        ]) """
        
    return account_total, accounts_table

def generate_categories_report(categories):
    active_categories = categories[
        ~categories["name"].isin(["Internal Master Category", "Credit Card Payments"])
    ]
    
    category_total = Decimal(0)
    categories_table = PrettyTable(["Name", "Balance", "Term"])
    for category in active_categories:
        categories_table.add_row([
            category["name"],
            locale.currency(category["balance"], grouping=True),
            category["term"],
        ])
        category_total += category["balance"]
        
    return category_total,categories_table

def format_currency(float):
    return locale.currency(float, grouping=True)

def format_floats(df):
    """Replaces all float columns with string columns formatted to 6 decimal places"""
    def format_column(col):
        if col.dtype != float:
            return col
        return col.apply(format_currency)

    return df.apply(format_column)

def format_panda(df):
    return tabulate(format_floats(df), headers='keys', tablefmt="rounded_outline", showindex=False)

def generate_net_worth_report(accounts):
    open_accounts = accounts[accounts["closed"] == False]
    net_worth = open_accounts["balance"].sum()
    
    return format_panda(pd.DataFrame({"Net Worth": net_worth}, index=[0], dtype=float))

if __name__ == "__main__":
    main()