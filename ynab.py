import argparse
from decimal import Decimal
import json
import logging
import os
import locale
import api
import pandas as pd
from tabulate import tabulate, SEPARATING_LINE

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
        "-c", "--config_file_path",
        help="The path to the configuration for this script.",
        type=valid_file_path,
        required=True,
        dest="config_file_path",
    )
    parser.add_argument(
        "-f", "--flush_cache",
        help="Flush the cache.",
        action='store_true',
        dest="flush_cache",
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
    
    cache_ttl = config["cache_ttl"]
    log.debug(f"cache_ttl: {cache_ttl}")
    
    budget_name = ""
    if "budget_name" in config:
        budget_name = config["budget_name"]
    log.debug(f"budget_name: {budget_name}")
    
    with api.Client(auth_token=auth_token, flush_cache=args.flush_cache, cache_ttl=cache_ttl) as client:       
        budget = client.get_last_used_budget()         
        accounts = client.get_accounts(budget_id=budget.id)
        categories = client.get_categories(budget_id=budget.id)
        
    accounts = pd.DataFrame([ account.as_dict() for account in accounts ])
    accounts = accounts.sort_values("name")
    
    categories = pd.DataFrame([ category.as_dict() for category in categories ])
    categories = categories.sort_values(
        by=["term", "balance", "name"],
        ascending=[False, True, True]
    )
    
    print(report_net_worth(accounts))
    print(report_term_distribution(accounts, categories))

def format_currency(centiunit):
    unit = centiunit / 100
    return locale.currency(unit, grouping=True)

def format_currencies(df: pd.DataFrame):
    """Replaces all int columns with formatted string columns"""
    def format_column(col):
        if col.dtype != int:
            return col
        return col.apply(format_currency)

    return df.apply(format_column)

def format_panda(df: pd.DataFrame, total_row: str=""):
    if total_row:
        totals = pd.DataFrame([df.apply(pd.to_numeric, errors="coerce").fillna("").sum()])
        totals[total_row] = "Total"
        df = pd.concat([df, totals], ignore_index=True)
        
    df.columns = map(str.title, df.columns) # type: ignore
    df = format_currencies(df)
    
    return tabulate(df, headers="keys", tablefmt="rounded_outline", showindex=False) # type: ignore

def report_net_worth(accounts: pd.DataFrame):
    open_accounts = accounts[accounts["closed"] == False]
    
    net_worth_total = open_accounts["balance"].sum()
    net_worth = pd.DataFrame({"Net Worth": net_worth_total}, index=[0])
    
    return format_panda(net_worth)

def report_term_distribution(accounts: pd.DataFrame, categories: pd.DataFrame):
    open_accounts = accounts[
        (accounts["closed"] == False) &
        (accounts["on budget"] == True)
    ]
    accounts_by_term = open_accounts.groupby("term").sum()
    accounts_by_term = accounts_by_term[["balance"]]
    accounts_by_term = accounts_by_term.rename(columns={"balance": "account balance"})
    
    active_categories = categories[
        (categories["hidden"] == False) &
        (~categories["category group name"].isin(["Internal Master Category", "Credit Card Payments"]))
    ]
    categories_by_term = active_categories.groupby("term").sum()
    categories_by_term = categories_by_term[["balance"]]
    categories_by_term = categories_by_term.rename(columns={"balance": "category balance"})
    
    term_distribution = accounts_by_term.join(categories_by_term)
    term_distribution = term_distribution.reset_index()
    term_distribution = term_distribution.sort_values("term", ascending=False)
    term_distribution["redistribute"] = term_distribution.apply(lambda row: row["category balance"] - row["account balance"], axis=1)
    term_distribution["term"] = term_distribution["term"].apply(str.title)
    
    return format_panda(term_distribution, total_row="term")

if __name__ == "__main__":
    main()