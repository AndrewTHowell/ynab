import argparse
from decimal import Decimal
import json
import logging
import os
import locale
from prettytable import PrettyTable
import api

logging.basicConfig(format="%(levelname)s: %(message)s")
locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')

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
    caching = parser.add_mutually_exclusive_group()
    caching.add_argument(
        "-nc", "--naive-cache",
        help="Turn on naive API caching.",
        action='store_true',
        dest="naive_caching"
    )
    caching.add_argument(
        "-dc", "--delta-cache",
        help="Turn on API delta caching.",
        action='store_true',
        dest="delta_caching"
    )
    args = parser.parse_args()
    
    if args.debug:
        log.setLevel(logging.DEBUG)
    
    config_file_path = args.config_file_path
    
    with open(config_file_path) as f:
        config = json.load(f)

    auth_token = config["auth_token"]
    log.debug(f"auth_token: {auth_token}")
    auth = api.BearerAuth(auth_token)
    
    session = api.get_session(caching=args.naive_caching)
    
    budget_name = ""
    if "budget_name" in config:
        budget_name = config["budget_name"]
    log.debug(f"budget_name: {budget_name}")
        
    if budget_name:
        budget = api.get_budget_by_name(session=session, auth=auth, name=budget_name)
    else:
        budget = api.get_last_used_budget(session=session, auth=auth)
            
    accounts = api.get_accounts(session=session, auth=auth, budget_id=budget["id"])
    
    categories = api.get_categories(session=session, auth=auth, budget_id=budget["id"])
    
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
        
    
    active_categories = [
        category for category in categories
        #if not category.hidden and not category.deleted and
        if not category.category_group_name in ["Internal Master Category", "Credit Card Payments"]
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
    log.debug(f"category_total: {category_total}")
    
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
    log.debug(f"account_total: {account_total}")
    
    checksum = account_total - category_total
    assert checksum == 0
    
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
        


if __name__ == "__main__":
    main()