import argparse
import json
import locale
import logging
import os
from datetime import datetime

import jsonschema
from dateutil.relativedelta import relativedelta

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
        
        logging.debug(f"auth_token: {self.auth_token}")
        logging.debug(f"cache_ttl: {self.cache_ttl}")


def main():
    parser = argparse.ArgumentParser(
        prog="api_ping.py",
        description="Ping the YNAB API.",
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
    
    test_budget_id = "e0ceb515-98ed-4523-a59b-70effa49485e"
    with api.Client(auth_token=config.auth_token, cache_ttl=config.cache_ttl, flush_cache=args.flush_cache) as client:
        
        print("Delta-cacheable - categories")
        categories = client.get_categories(budget_id=test_budget_id)
        print(categories)
        
        print()
        
        print("Non-cacheable - current month")
        start_date_of_current_month = datetime.today().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month = datetime.strftime(start_date_of_current_month, api.Month.str_format())
        category_this_month = client.get_category_by_month(current_month, categories[0].get_id(), budget_id=test_budget_id)
        print(category_this_month)
        
        print()
        
        print("Cacheable - previous month")
        start_date_of_last_month = start_date_of_current_month - relativedelta(months=1)
        last_month = datetime.strftime(start_date_of_last_month, api.Month.str_format())
        category_last_month = client.get_category_by_month(last_month, categories[0].get_id(), budget_id=test_budget_id)
        print(category_last_month)

if __name__ == "__main__":
    main()
