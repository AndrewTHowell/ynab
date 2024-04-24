import argparse
import json
import locale
import logging
import os
import random
from enum import Enum

import jsonschema
import numpy as np
import pandas as pd
import requests
from simple_term_menu import TerminalMenu
from tabulate import tabulate

import api

locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')

CONFIG_SCHEMA_FILE_PATH = "config_schema.json"
    
def valid_file_path(file_path: str):
    if not os.path.exists(file_path):
        raise argparse.ArgumentTypeError
    return file_path

class Config():
    def __init__(self, file_path: str):
        with open(file_path) as f:
            config_json = json.load(f)
            
        with open(CONFIG_SCHEMA_FILE_PATH) as f:
            config_schema_json = json.load(f)
            
        jsonschema.validate(instance=config_json, schema=config_schema_json)

        self.auth_token = config_json["auth_token"]
        self.cache_ttl = config_json["cache_ttl"]
        self.num_of_months_lookback = config_json["num_of_months_lookback"]
        
        logging.debug(f"auth_token: {self.auth_token}")
        logging.debug(f"cache_ttl: {self.cache_ttl}")
        logging.debug(f"num_of_months_lookback: {self.num_of_months_lookback}")


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
        "-m", "--cache_mode",
        help="Choose a cache mode",
        action='store',
        type=api.Client.CacheMode.argparse,
        choices=list(api.Client.CacheMode),
        default=api.Client.CacheMode.normal,
        dest="cache_mode",
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
    
    YNAB(config, args.cache_mode)
    
class YNAB:
    def __init__(self, config: Config, cache_mode: api.Client.CacheMode):        
        with api.Client(auth_token=config.auth_token, cache_mode=cache_mode, cache_ttl=config.cache_ttl) as client:
            self.client = client
        
            self.main_menu(config.num_of_months_lookback)
    
    def main_menu(self, num_of_months_lookback: int):
        while True:
            options = [
                "[n] Net Worth",
                "[t] Term Distribution",
                "[r] Rollover Balance",
                "[c] Category Normalisation",
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
                    print(self.report_category_stats(num_of_months_lookback))
                case 4:
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
                "[p] Redundant Payees",
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
                    print(self.report_redundant_payees())
                case _:
                    break

    def get_accounts(self):
        return api.Account.collect_as_df(self.client.get_accounts())

    def get_categories(self):
        return api.Category.collect_as_df(self.client.get_categories())

    def get_months(self):
        return api.Month.collect_as_df(self.client.get_months())

    def get_payees(self):
        return api.Payee.collect_as_df(self.client.get_payees())

    def get_transactions(self):
        return api.Transaction.collect_as_df(self.client.get_transactions())

    def report_accounts(self):
        return format_panda(self.get_accounts())

    def report_categories(self):
        return format_panda(self.get_categories())

    def report_net_worth(self):
        accounts = self.get_accounts()
        
        open_accounts = accounts[accounts["closed"] == False]
        
        net_worth_total = open_accounts["balance"].sum()
        net_worth = pd.DataFrame({"Net Worth": net_worth_total}, index=[0])
        
        return format_panda(net_worth)

    def report_term_distribution(self):
        accounts = self.get_accounts()
        categories = self.get_categories()
        
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
        categories = self.get_categories()
        
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

    def report_category_stats(self, num_of_months_lookback: int):
        months = self.get_months()
        categories = self.get_categories()
        
        # Check the last N months (ignoring the last, which is next month)
        months_to_check = months.drop(months.tail(1).index).tail(num_of_months_lookback)["month"]
        current_month = months_to_check.iloc[-1]

        categories = categories.set_index("id")
        categories_to_check = categories[
            (categories["goal type"].isin((api.Category.GoalType.needed_for_spending, api.Category.GoalType.target_balance_date))) &
            (categories["hidden"] == False) &
            (categories["deleted"] == False)
        ]
        
        # Circuit breaker is activated when the request limit is reached. It ensures that no more calls are sent.
        circuit_breaker = False
        base_month = self.client.get_category_by_month(current_month, categories_to_check.index[0]).copy()
        def get_category_by_month(month: str, category_id: str):
            nonlocal circuit_breaker
            # Can't retrieve more months, return a base category to allow partial reporting
            if circuit_breaker:
                return base_month
            
            try:
                return self.client.get_category_by_month(month, category_id)
            except requests.HTTPError as e:
                match e.response.status_code:
                    case 404:
                        # Category not found in given month, it did not exist yet. Use copy of current month
                        current = self.client.get_category_by_month(current_month, category_id)
                        return current.copy()
                    case 429:
                        logging.error(f"Rate limit reached. Stopped at month {month} and category id {category_id}. Retrieved")
                        # Can't retrieve more months, ensure no other calls are sent and return a base category to allow partial reporting
                        circuit_breaker = True
                        return base_month
                    case _:
                        raise e
        
        categories_by_month_data = pd.DataFrame(index=categories_to_check.index, columns=months_to_check)
        def get_categories_by_month(row: pd.Series):
            category_id = row.name
            return pd.Series([
                get_category_by_month(month, category_id)
                for month in row.index
            ], index=row.index)

        categories_by_month_data = categories_by_month_data.apply(get_categories_by_month, axis=1)

        categories_by_month_spending_data = categories_by_month_data.copy(deep=True)
        categories_by_month_spending_data =  categories_by_month_spending_data.apply(lambda col: col.apply(lambda category: -category.activity))
        
        category_spending_by_month = pd.DataFrame(index=categories_by_month_spending_data.index)
        category_spending_by_month["category"] = categories_to_check["name"]
        category_spending_by_month[f"ewm({num_of_months_lookback})"] = categories_by_month_spending_data.apply(lambda r: round(r.ewm(span=num_of_months_lookback).mean().tail(1)), axis=1).astype(np.int64)
        category_spending_by_month["95%"] = categories_by_month_spending_data.apply(lambda r: round(r.quantile(q=0.95)), axis=1).astype(np.int64)
        
        logging.debug(f"Raw data from category normalisation: \n{pd.concat([categories_by_month_spending_data, categories_to_check['name'].rename('category')], axis=1)}")

        # TODO: Derive this from the goal instead 
        categories_by_month_budgeted_data = categories_by_month_data.copy(deep=True)
        categories_by_month_budgeted_data =  categories_by_month_budgeted_data.apply(lambda col: col.apply(lambda category: category.budgeted))
        current_category_budgeted_data = categories_by_month_budgeted_data[current_month]
        category_spending_by_month = pd.concat([category_spending_by_month, current_category_budgeted_data.rename("budgeted")], axis=1)
        
        category_spending_by_month = category_spending_by_month.sort_values("category", ascending=True, key=lambda col: col.str.lower())
        
        return format_panda(category_spending_by_month)

    def report_redundant_payees(self):
        payees = self.get_payees()
        transactions = self.get_transactions()
        
        payees = payees[
            (payees["deleted"] == False) &
            (payees["transfer account id"].isnull())
        ]
               
        def get_num_of_transactions(payee: pd.Series):
            nonlocal transactions
            payee_transactions = transactions[transactions["payee id"] == payee["id"]]
            return len(payee_transactions)
            
        payees["num of transactions"] = payees.apply(get_num_of_transactions, axis=1)
        
        payees = payees[payees["num of transactions"] == 0]
        payees = payees[["id", "name"]]
        
        return format_panda(payees)
        
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

def format_panda(df: pd.DataFrame, total_row: str="", show_index: bool=False):
    if total_row:
        totals = pd.DataFrame([df.apply(pd.to_numeric, errors="coerce").fillna("").sum()])
        totals[total_row] = "Total"
        df = pd.concat([df, totals], ignore_index=True)
        
    df.columns = map(str.title, df.columns) # type: ignore
    if df.index.name:
        df.index.name = df.index.name.title()
    df = format_currencies(df)
    df = format_enums(df)
    
    return tabulate(df, headers="keys", tablefmt="rounded_outline", showindex=show_index) # type: ignore

if __name__ == "__main__":
    main()
