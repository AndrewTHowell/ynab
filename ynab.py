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
from enum import Enum

locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')
    
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
            
            logging.debug(f"auth_token: {self.auth_token}")
            logging.debug(f"cache_ttl: {self.cache_ttl}")


def main():
    parser = argparse.ArgumentParser(
        prog="ynab.py",
        description="Script for consuming and processing YNAB data.",
    )
    parser.add_argument(
        "-c", "--config_file_path",
        help="The path to the configuration for this script. See schema at `config_schema.json`",
        type=valid_file_path,
        dest="config_file_path",
        default="config.json"
    )
    parser.add_argument(
        "-f", "--flush_cache",
        help="Flush the cache",
        action='store_true',
        dest="flush_cache",
    )
    parser.add_argument(
        "-d", "--debug",
        help="Turn on debug logging",
        action='store_true',
        dest="debug"
    )
    args = parser.parse_args()
    
    log_level = logging.INFO
    if args.debug:
        log_level = logging.DEBUG
        
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(module)s:L%(lineno)d > %(message)s",
        level=log_level,
    )
    
    config = Config(args.config_file_path)
    
    YNAB(config, args.flush_cache)
    
class YNAB:
    def __init__(self, config, flush_cache):        
        with api.Client(auth_token=config.auth_token, cache_ttl=config.cache_ttl, flush_cache=flush_cache) as client:
            self.client = client
            
            self.load_data()
        
            self.main_menu()
    
    def main_menu(self):
        while True:
            options = [
                "[n] Net Worth",
                "[t] Term Distribution",
                "[r] Rollover Balance",
                "[p] Delete Redundant Payees",
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
                    self.redundant_payee_menu()
                case 4:
                    self.data_menu()
                case _:
                    number_of_e = random.randrange(2, 10)
                    print(f"Y{'e'*number_of_e}t")
                    break
    
    def redundant_payee_menu(self):
        while True:
            redundant_payees = self.report_redundant_payees()
            print(redundant_payees)
            options = [
                "[d] Delete All",
                "[b] Back"
            ]
            terminal_menu = TerminalMenu(options, title="Redundant Payee Menu")
            choice = terminal_menu.show()
            
            match choice:
                case 0:
                    self.delete_payees(redundant_payees)
                case _:
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
                    self.load_data()
                case _:
                    break
                
    
    def load_data(self):    
        accounts = self.client.get_accounts()
        categories = self.client.get_categories()
        payees = self.client.get_payees()
        transactions = self.client.get_transactions()
        
        self.accounts = api.Account.collect_as_df(accounts)
        self.categories = api.Category.collect_as_df(categories)
        self.payees = api.Payee.collect_as_df(payees)
        self.transactions = api.Transaction.collect_as_df(transactions)

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
        accounts_by_term = accounts_by_term.groupby("term", observed=True).sum()
        accounts_by_term = accounts_by_term.rename(columns={"balance": "account balance"})
        
        active_categories = categories[
            (categories["hidden"] == False) &
            (~categories["category group name"].isin(["Internal Master Category", "Credit Card Payments"]))
        ]
        categories_by_term = active_categories[["balance", "term"]]
        categories_by_term = categories_by_term.groupby("term", observed=True).sum()
        categories_by_term = categories_by_term.rename(columns={"balance": "category balance"})
        
        term_distribution = accounts_by_term.join(categories_by_term)
        term_distribution = term_distribution.reset_index()
        term_distribution = term_distribution.sort_values("term", ascending=True)
        
        term_distribution["redistribute"] = term_distribution.apply(lambda row: row["category balance"] - row["account balance"], axis=1)
        
        return format_panda(term_distribution, total_row="term")

    def report_rollover(self):
        categories = self.categories.copy(deep=True)
        
        categories_that_rollover = categories[
            (categories["hidden"] == False) &
            (categories["goal type"] == api.Category.GoalType.needed_for_spending) &
            (
                (categories["goal cadence"] == api.Category.GoalCadence.weekly) |
                (categories["goal cadence"] == api.Category.GoalCadence.monthly)
            )
        ]
        
        rollover_total = categories_that_rollover["balance"].sum()
        rollover = pd.DataFrame({"Rollover Balance": rollover_total}, index=[0])
        
        return format_panda(rollover)

    def report_redundant_payees(self):
        payees = self.payees.copy(deep=True)
        transactions = self.transactions.copy(deep=True)
        
        payees = payees[payees["deleted"] == False]
               
        def get_num_of_transactions(payee: pd.Series):
            nonlocal transactions
            transactions = transactions[transactions["payee_id"] == payee["id"]]
            return len(transactions)
            
        payees["num_of_transactions"] = payees.apply(get_num_of_transactions, axis=1)
        
        return format_panda(payees)

    def delete_payees(self, payees):
        print("Unimplemented")

def format_currency(centiunit):
    unit = centiunit / 100
    return locale.currency(unit, grouping=True)

def format_currencies(df: pd.DataFrame):
    """Replaces all int columns with formatted string columns"""
    def format_column(col: pd.Series):
        if col.dtype != int:
            return col
        return col.apply(format_currency)

    return df.apply(format_column)
        
def format_enums(df: pd.DataFrame):
    """Replaces all enums with their values"""
    def format_enum_col(col: pd.Series):
        def format_enum(val):
            if hasattr(val, 'value'):
                return val.value
            return val
        
        if isinstance(col.iloc[0], Enum):
            return col.apply(format_enum)
        return col

    return df.apply(format_enum_col)

def format_panda(df: pd.DataFrame, total_row: str=""):
    if total_row:
        totals = pd.DataFrame([df.apply(pd.to_numeric, errors="coerce").fillna("").sum()])
        totals[total_row] = "Total"
        df = pd.concat([df, totals], ignore_index=True)
        
    df.columns = map(str.title, df.columns) # type: ignore
    df = format_currencies(df)
    df = format_enums(df)
    
    return tabulate(df, headers="keys", tablefmt="rounded_outline", showindex=False) # type: ignore

if __name__ == "__main__":
    main()
