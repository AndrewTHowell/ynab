import argparse
import json
import logging
import os
import locale
import api
import pandas as pd
from tabulate import tabulate
from simple_term_menu import TerminalMenu
import random

locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')
logging.basicConfig(format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
    
def valid_file_path(file_path: str):
    if not os.path.exists(file_path):
        raise argparse.ArgumentTypeError
    return file_path

class Config():
    def __init__(self, file_path: str):        
        with open(file_path) as f:
            config_json = json.load(f)

            self.auth_token = config_json["auth_token"]
            self.cache_ttl = config_json["cache_ttl"]
            
            log.debug(f"auth_token: {self.auth_token}")
            log.debug(f"cache_ttl: {self.cache_ttl}")
        

def main():
    parser = argparse.ArgumentParser(
        prog="YNAB",
        description="Script for consuming and processing YNAB data.",
    )
    parser.add_argument(
        "-c", "--config_file_path",
        help="The path to the configuration for this script.",
        type=valid_file_path,
        dest="config_file_path",
        default="config.json"
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
    
    config = Config(args.config_file_path)
    
    YNAB(config, args.flush_cache)
    
class YNAB:
    def __init__(self, config, flush_cache):
        self.auth_token = config.auth_token
        self.cache_ttl = config.cache_ttl        
        self.load_data(flush_cache)
        
        self.main_menu()
    
    def main_menu(self):
        while True:
            options = [
                "[n] Net Worth",
                "[t] Term Distribution",
                "[r] Rollover Balance",
                "[d] Data",
                "[e] Exit"
            ]
            terminal_menu = TerminalMenu(options, title="Main Menu")
            choice = terminal_menu.show()
            
            match choice:
                case 0:
                    print(self.report_net_worth())
                case 1:
                    print(self.report_term_distribution())
                case 2:
                    print(self.report_rollover())
                case 3:
                    self.data_menu()
                case _:
                    number_of_e = random.randrange(2, 10)
                    print(f"Y{'e'*number_of_e}t")
                    break
    
    def data_menu(self):
        while True:
            options = [
                "[a] Accounts",
                "[c] Categories",
                "[r] Refresh Data",
                "[b] Back"
            ]
            terminal_menu = TerminalMenu(options, title="Data Menu")
            choice = terminal_menu.show()
            
            match choice:
                case 0:
                    print(self.report_accounts())
                case 1:
                    print(self.report_categories())
                case 2:
                    self.load_data(True)
                case _:
                    break
                
    
    def load_data(self, flush_cache):
        with api.Client(auth_token=self.auth_token, cache_ttl=self.cache_ttl, flush_cache=flush_cache) as client:
            budget = client.get_last_used_budget()         
            accounts = client.get_accounts(budget_id=budget.id)
            categories = client.get_categories(budget_id=budget.id)
            
        accounts = pd.DataFrame([ account.as_dict() for account in accounts ])
        self.accounts = accounts.sort_values("name")
        
        categories = pd.DataFrame([ category.as_dict() for category in categories ])
        self.categories = categories.sort_values(
            by=["term", "balance", "name"],
            ascending=[False, True, True]
        )

    def report_accounts(self):
        accounts = self.accounts.copy(deep=True)
        return format_panda(accounts)

    def report_categories(self):
        categories = self.categories.copy(deep=True)
        return format_panda(categories)

    def report_net_worth(self):
        accounts = self.accounts.copy(deep=True)
        
        open_accounts = accounts[accounts["closed"] == False]
        
        net_worth_total = open_accounts["balance"].sum()
        net_worth = pd.DataFrame({"Net Worth": net_worth_total}, index=[0])
        
        return format_panda(net_worth)

    def report_term_distribution(self):
        accounts = self.accounts.copy(deep=True)
        categories = self.categories.copy(deep=True)
        
        open_accounts = accounts[
            (accounts["closed"] == False) &
            (accounts["on budget"] == True)
        ]
        accounts_by_term = open_accounts[["balance", "term"]]
        accounts_by_term = accounts_by_term.groupby("term").sum()
        accounts_by_term = accounts_by_term.rename(columns={"balance": "account balance"})
        
        active_categories = categories[
            (categories["hidden"] == False) &
            (~categories["category group name"].isin(["Internal Master Category", "Credit Card Payments"]))
        ]
        categories_by_term = active_categories[["balance", "term"]]
        categories_by_term = categories_by_term.groupby("term").sum()
        categories_by_term = categories_by_term.rename(columns={"balance": "category balance"})
        
        term_distribution = accounts_by_term.join(categories_by_term)
        term_distribution = term_distribution.reset_index()
        term_distribution = term_distribution.sort_values("term", ascending=False)
        term_distribution["redistribute"] = term_distribution.apply(lambda row: row["category balance"] - row["account balance"], axis=1)
        
        return format_panda(term_distribution, total_row="term")

    def report_rollover(self):
        categories = self.categories.copy(deep=True)
        
        categories_that_rollover = categories[
            (categories["hidden"] == False) &
            (categories["goal type"] == api.CategoryGoalType.needed_for_spending.value) &
            (
                (categories["goal cadence"] == api.CategoryGoalCadence.weekly.value) |
                (categories["goal cadence"] == api.CategoryGoalCadence.monthly.value)
            )
        ]
        
        rollover_total = categories_that_rollover["balance"].sum()
        rollover = pd.DataFrame({"Rollover Balance": rollover_total}, index=[0])
        
        return format_panda(rollover)

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

if __name__ == "__main__":
    main()
